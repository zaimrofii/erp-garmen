"""Endpoint **Work Order** MES tambahan (H2.3) — `/api/v1/garmen/work-orders/…`.

Melengkapi resource `work-orders` yang SUDAH ADA (F2/F3) **tanpa mengubah kontrak
yang sudah di-pin**:

  * **sudah ada (tidak disentuh)**: `GET /work-orders/` (list 5 key, AllowAny),
    `POST /work-orders/` (create F2, IsAuthenticated), `GET /work-orders/<id>/`
    (detail + `version` + `allowed_actions`), `GET …/schema/`,
    `POST …/<id>/<action>/` (ActionView: `WO_START`/`WO_CLOSE`/`WO_CANCEL`);
  * **baru H2.3**: `PUT`/`DELETE /work-orders/<id>/` (ubah & hapus hibrida) dan
    `POST /work-orders/<id>/split/` (pecah WO) + `POST /orders/<id>/generate-wo/`
    (batch generate, ada di `orders.py`).

Izin: **tulis = `IsAuthenticated` TANPA role** (keputusan pemilik proyek H2.3) supaya
jalur F2/simulator (user tanpa role) tidak pecah; frontend tetap memakai guard
`PRODUCTION_ROLES`.
"""

from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps_industry.garment.api.resources.create_view import _CreateViewMixin
from apps_industry.garment.api.resources.detail_view import serialize_work_order_detail
from apps_industry.garment.api.resources.list_view import ResourceListView
from apps_industry.garment.api.resources.work_order import WorkOrderSchemaBuilder
from apps_industry.garment.models import WorkOrder
from apps_industry.garment.services import work_order_services

logger = logging.getLogger(__name__)

__all__ = (
    "WorkOrderCreateCrudView",
    "WorkOrderDetailCrudView",
    "WorkOrderSplitView",
    "serialize_work_order_extra",
)

#: Industry MES (path endpoint ini literal `garmen`).
INDUSTRY = "garmen"


def serialize_work_order_extra(wo: WorkOrder, request=None) -> dict:
    """Detail WO versi H2.3 (``wo_detail_row``) + ``version``/``allowed_actions``.

    ``version`` diambil dari schema builder yang SAMA dengan F3 supaya klien bisa
    memakai mekanisme konflik (`X-Base-Version`) yang sama.
    """
    builder = WorkOrderSchemaBuilder(instance=wo, request=request, industry=INDUSTRY)
    payload = work_order_services.wo_detail_row(wo)
    payload["version"] = builder.get_version()
    payload["allowed_actions"] = builder.get_state_machine()["allowed_actions"]

    return payload


def _write_body(result, request, *, status_code: int = status.HTTP_200_OK) -> Response:
    """Respons baris WO + ringkasan operasi (``ledger_id``/``summary``)."""
    body: dict = {"deleted": result.deleted}
    if result.work_order is not None:
        body = serialize_work_order_extra(result.work_order, request=request)
        body["deleted"] = result.deleted

    body["ledger_id"] = result.sync_record_id
    body["cancelled"] = result.cancelled
    if result.work_orders:
        body["work_orders"] = [work_order_services.wo_row(wo) for wo in result.work_orders]
    if result.summary:
        body["summary"] = result.summary

    return Response(body, status=status_code)


def _error_response(result) -> Response:
    """Peta error service → status (404 tidak ada / 409 konflik / 400 validasi)."""
    if result.not_found:
        code = status.HTTP_404_NOT_FOUND
    elif result.conflict:
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_400_BAD_REQUEST

    return Response({"detail": result.error}, status=code)


class WorkOrderCreateCrudView(_CreateViewMixin):
    """``POST /api/v1/garmen/work-orders/`` (H2.3) + ``GET`` list F2/F3.

    **Satu jalur create** untuk simulator & UI: ``order_line_id`` wajib (404 kalau
    tidak ada — kontrak F2), ``code`` opsional (kosong ⇒ ``next_number("WO")`` →
    ``WO-<TAHUN>-<SEQ>``), ``qty_planned`` opsional (kosong ⇒ ``OrderLine.qty``),
    ``state`` selalu `DRAFT`, plus ledger `SKIPPED` (MES-only) & audit. ``GET`` tetap
    didelegasikan ke `ResourceListView` (list 5 key, AllowAny) lewat `_CreateViewMixin`.
    """

    RESOURCE = "work-orders"
    #: Path endpoint ini literal `garmen` (tidak ada segment industri di URL).
    INDUSTRY = "garmen"

    def get(self, request):
        """``GET`` = daftar work-orders (kontrak F3) — didelegasikan ke `ResourceListView`."""
        return ResourceListView.get(self, request, self.INDUSTRY, self.RESOURCE)

    def post(self, request):
        """Buat WO lewat service H2.3 (lihat docstring kelas)."""
        result = work_order_services.create_work_order(request.data or {}, request=request)
        if result.error:
            return _error_response(result)

        payload = serialize_work_order_detail(result.work_order)
        payload.update(serialize_work_order_extra(result.work_order, request=request))
        payload["industry"] = self.INDUSTRY
        payload["ledger_id"] = result.sync_record_id

        return Response(payload, status=status.HTTP_201_CREATED)


class WorkOrderDetailCrudView(APIView):
    """``GET|PUT|DELETE /api/v1/garmen/work-orders/<id>/`` (GET = kontrak F3)."""

    def get_permissions(self):
        """``GET`` tetap AllowAny (perilaku F3); ``PUT``/``DELETE`` wajib login."""
        if self.request.method in ("PUT", "DELETE"):
            return [IsAuthenticated()]
        return []

    @staticmethod
    def _get_wo(wo_id: int):
        """WO atau ``None`` (→ 404)."""
        return (
            WorkOrder.objects.select_related(
                "order_line", "order_line__order", "order_line__product"
            )
            .filter(pk=wo_id)
            .first()
        )

    def get(self, request, work_order_id: int):
        """Detail WO (payload H2.3 superset; anonim tetap 200 seperti F3)."""
        wo = self._get_wo(work_order_id)
        if wo is None:
            return Response(
                {"detail": f"WorkOrder {work_order_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(serialize_work_order_extra(wo, request=request))

    def put(self, request, work_order_id: int):
        """Ubah WO (DRAFT-only; ``qty_planned``/``code``)."""
        wo = self._get_wo(work_order_id)
        if wo is None:
            return Response(
                {"detail": f"WorkOrder {work_order_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        result = work_order_services.update_work_order(wo, request.data or {}, request=request)
        if result.error:
            return _error_response(result)

        return _write_body(result, request)

    def delete(self, request, work_order_id: int):
        """Hapus WO (hibrida: hard delete DRAFT tanpa bundle / soft delete CANCELLED)."""
        wo = self._get_wo(work_order_id)
        if wo is None:
            return Response(
                {"detail": f"WorkOrder {work_order_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        result = work_order_services.delete_work_order(wo, request=request)
        if result.error:
            return _error_response(result)

        return _write_body(result, request)


class WorkOrderSplitView(APIView):
    """``POST /api/v1/garmen/work-orders/<id>/split/`` — pecah WO (DRAFT, tanpa bundle)."""

    permission_classes = [IsAuthenticated]

    def post(self, request, work_order_id: int):
        """Jalankan split; body = ``{"splits": [qty, qty, ...]}`` (sum = qty sumber)."""
        wo = WorkOrderDetailCrudView._get_wo(work_order_id)
        if wo is None:
            return Response(
                {"detail": f"WorkOrder {work_order_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        result = work_order_services.split_work_order(wo, request.data or {}, request=request)
        if result.error:
            return _error_response(result)

        return _write_body(result, request, status_code=status.HTTP_201_CREATED)
