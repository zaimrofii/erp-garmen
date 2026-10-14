"""Endpoint **create** resource — jalur non-state-machine (FASE 3.4, D1).

``POST /api/v1/<industry>/work-orders/``  -> buat ``WorkOrder`` dari ``OrderLine``
``POST /api/v1/<industry>/bundles/``      -> buat ``Bundle`` dari ``WorkOrder``
    lewat :class:`~apps_industry.garment.services.bundle_engine.BundleEngine`
    (service yang SUDAH ada — tidak ada logika model/state machine baru).

Kenapa perlu: sebelumnya **tidak ada** jalur HTTP untuk membuat WorkOrder/Bundle
(``BundleEngine.create_bundles`` bahkan tak punya pemanggil), sehingga jalur
"order baru -> WO -> bundle -> lini produksi" (FASE 3.4) mustahil dari simulator;
data demo dulu dibuat manual lewat Django shell.

Desain:

* **Satu resource, dua method.** Kedua view mewarisi
  :class:`~apps_industry.garment.api.resources.list_view.ResourceListView` supaya
  ``GET .../work-orders/`` & ``GET .../bundles/`` tetap persis kontrak §3 (list) —
  tidak ada regresi pada endpoint list yang dipakai bootstrap simulator.
* **Permission per method** (:meth:`_CreateViewMixin.get_permissions`): ``POST`` =
  ``IsAuthenticated`` (konsisten dengan endpoint tulis lain, mis. ``/sync/...``),
  sedangkan ``GET`` tetap ``AllowAny`` bawaan ``ResourceListView``. Kalau
  ``IsAuthenticated`` dipasang untuk SEMUA method, bootstrap simulator yang
  anonim akan ikut rusak.
* Validasi *fail-closed*: 404 resource tidak ada; 400 untuk body/qty/state/
  idempotensi.
"""

from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps_industry.garment.api.industries import require_industry
from apps_industry.garment.api.resources.detail_view import (
    serialize_bundle_detail,
    serialize_work_order_detail,
)
from apps_industry.garment.api.resources.list_view import ResourceListView
from apps_industry.garment.models import Bundle, OrderLine, WorkOrder
from apps_industry.garment.services.bundle_engine import BundleEngine
from apps_industry.garment.services.exceptions import BundleEngineError

logger = logging.getLogger(__name__)

__all__ = ("BundleCreateView", "WorkOrderCreateView")

#: State WorkOrder yang boleh melahirkan bundle.
BUNDLE_SOURCE_STATES: tuple[str, ...] = ("DRAFT",)


def _next_work_order_code(order_line: OrderLine) -> str:
    """Kode WorkOrder unik & deterministik: ``WO-<order_line_id>-<seq 3 digit>``.

    Repo **tidak** punya helper ``wo_no`` (field-nya bernama ``code``, bukan
    ``wo_no``) -> dibuat sederhana di sini. Kalau kode sudah terpakai, ``seq``
    dinaikkan sampai bebas (anti tabrakan, unik per order line).
    """

    seq = order_line.work_orders.count() + 1
    while True:
        code = f"WO-{order_line.id}-{seq:03d}"
        if not WorkOrder.objects.filter(code=code).exists():
            return code
        seq += 1


class _CreateViewMixin(ResourceListView):
    """``POST`` membuat resource; ``GET`` tetap list (kontrak §3).

    ``RESOURCE`` wajib diisi subclass — dipakai untuk meneruskan ``GET`` ke
    :class:`ResourceListView` supaya logika list tidak diduplikasi.
    """

    #: Nama resource (kunci ``ResourceListView.RESOURCE_LIST``).
    RESOURCE = ""

    def get_permissions(self):
        """``POST`` butuh auth; ``GET`` tetap ``AllowAny`` (perilaku list lama)."""
        if self.request.method == "POST":
            return [IsAuthenticated()]
        return super().get_permissions()

    def get(self, request, industry: str):
        """Delegasi ke endpoint list kontrak §3 (tanpa duplikasi logika)."""
        return super().get(request, industry=industry, resource=self.RESOURCE)

    @staticmethod
    def _int_field(data, name: str):
        """Baca field angka dari body -> ``(value, error)``."""
        raw = (data or {}).get(name)
        if raw in (None, ""):
            return None, f"Field '{name}' wajib diisi."
        try:
            return int(raw), None
        except (TypeError, ValueError):
            return None, f"Field '{name}' harus berupa angka."


class WorkOrderCreateView(_CreateViewMixin):
    """``POST`` buat ``WorkOrder`` dari ``OrderLine``; ``GET`` = list work-orders."""

    RESOURCE = "work-orders"

    def post(self, request, industry: str):
        """Buat WorkOrder (``state="DRAFT"``, ``qty_planned = order_line.qty``)."""
        industry_code = require_industry(industry)
        order_line_id, error = self._int_field(request.data, "order_line_id")
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        order_line = OrderLine.objects.filter(pk=order_line_id).first()
        if order_line is None:
            return Response(
                {"detail": f"OrderLine {order_line_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if int(order_line.qty or 0) <= 0:
            return Response(
                {
                    "detail": (
                        f"OrderLine {order_line_id} qty={order_line.qty}; "
                        "WorkOrder butuh qty > 0."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        work_order = WorkOrder.objects.create(
            code=_next_work_order_code(order_line),
            order_line=order_line,
            state="DRAFT",
            qty_planned=order_line.qty,
        )
        logger.info(
            "create: WorkOrder %s dibuat untuk order line %s.",
            work_order.code,
            order_line.pk,
        )
        payload = serialize_work_order_detail(work_order)
        payload["industry"] = industry_code
        return Response(payload, status=status.HTTP_201_CREATED)


class BundleCreateView(_CreateViewMixin):
    """``POST`` buat ``Bundle`` dari ``WorkOrder``; ``GET`` = list bundles."""

    RESOURCE = "bundles"

    def post(self, request, industry: str):
        """Buat bundle lewat ``BundleEngine.create_bundles`` (service yang ada)."""
        industry_code = require_industry(industry)
        data = request.data or {}

        work_order_id, error = self._int_field(data, "work_order_id")
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        work_order = WorkOrder.objects.filter(pk=work_order_id).first()
        if work_order is None:
            return Response(
                {"detail": f"WorkOrder {work_order_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if work_order.state not in BUNDLE_SOURCE_STATES:
            return Response(
                {
                    "detail": (
                        f"WorkOrder {work_order.code} state={work_order.state}; bundle "
                        f"hanya bisa dibuat dari {', '.join(BUNDLE_SOURCE_STATES)}."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        if Bundle.objects.filter(work_order=work_order).exists():
            return Response(
                {
                    "detail": (
                        f"WorkOrder {work_order.code} sudah punya bundle (idempoten)."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        order_line = work_order.order_line
        # `BundleEngine` menempelkan bundle ke WorkOrder PERTAMA (id terkecil) milik
        # order line. Tolak WO lain supaya bundle tidak "nyasar" ke WO berbeda.
        primary = order_line.work_orders.order_by("id").first()
        if primary is None or primary.pk != work_order.pk:
            return Response(
                {
                    "detail": (
                        f"WorkOrder {work_order.code} bukan WorkOrder pertama order "
                        f"line {order_line.pk}; BundleEngine menempelkan bundle ke WO "
                        "pertama order line tersebut."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        size_matrix = data.get("size_matrix")
        if not isinstance(size_matrix, dict) or not size_matrix:
            return Response(
                {"detail": "Field 'size_matrix' wajib objek {size: qty} tidak kosong."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            bundles = BundleEngine.create_bundles(
                order_line, size_matrix, data.get("bundle_size")
            )
        except BundleEngineError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        logger.info(
            "create: %d bundle dibuat untuk WorkOrder %s.",
            len(bundles),
            work_order.code,
        )
        return Response(
            {
                "created": len(bundles),
                "work_order_id": work_order.pk,
                "bundles": [serialize_bundle_detail(bundle) for bundle in bundles],
                "industry": industry_code,
            },
            status=status.HTTP_201_CREATED,
        )
