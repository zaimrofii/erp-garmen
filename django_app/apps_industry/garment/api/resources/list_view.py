"""Endpoint list resource: `GET /api/v1/<industry>/<resource>/` (Kontrak §3).

Paginasi sederhana `limit`/`offset` supaya frontend bisa memuat tabel tanpa
menarik seluruh data. Kolom yang dikirim sengaja ramping (hanya untuk tabel);
data lengkap ada di endpoint detail.

Resource yang didukung: `work-orders`, `bundles`, `qc` (ScrapAccumulator),
`order-lines` (FASE 3.4 P1 — jalur "order baru → WO → bundle").
Resource lain -> 404.
"""

from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps_industry.garment.api.industries import require_industry
from apps_industry.garment.api.resources.bundle import BundleSchemaBuilder
from apps_industry.garment.models import Bundle, OrderLine, ScrapAccumulator, WorkOrder

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
DEFAULT_OFFSET = 0
MAX_OFFSET = 100000


def serialize_work_order(instance) -> dict:
    """Baris tabel work order."""
    return {
        "id": instance.pk,
        "code": instance.code,
        "state": instance.state,
        "qty_planned": instance.qty_planned,
        "qty_done": instance.qty_done,
    }


def serialize_bundle(instance) -> dict:
    """Baris tabel bundle (+ version & allowed_actions untuk optimistic UI)."""
    # Fase 0.5: `allowed_actions` diambil dari helper state machine yang SAMA
    # dengan endpoint schema (`BundleSchemaBuilder.get_state_machine()`), supaya
    # bentuk `{id, label, endpoint, mode}` + path aksi relatif
    # (`ACTION_ENDPOINT_ROOT`, tanpa `/api/v1`) tidak mungkin berbeda jalur.
    # Builder-nya instance-level, jadi tiap baris memuat prefix `/…/bundles/<id>/`.
    builder = BundleSchemaBuilder(instance=instance, request=None)
    return {
        "id": instance.pk,
        "code": instance.code,
        "state": instance.state,
        "size": instance.size,
        "qty": instance.qty,
        "qty_done": instance.qty_done,
        "version": instance.version,
        "current_work_center_code": (
            instance.current_work_center.code
            if instance.current_work_center_id
            else None
        ),
        "allowed_actions": builder.get_state_machine()["allowed_actions"],
    }


def serialize_qc(instance) -> dict:
    """Baris tabel catatan QC (scrap/rework/end-loss)."""
    return {
        "id": instance.pk,
        "work_center_code": (
            instance.work_center.code if instance.work_center_id else None
        ),
        "bundle_code": instance.bundle.code if instance.bundle_id else None,
        "qty": instance.qty,
        "rework_qty": instance.rework_qty,
        "end_loss_qty": instance.end_loss_qty,
        "reason": instance.reason,
    }


def serialize_order_line(instance) -> dict:
    """Baris tabel order line (jalur "order baru" FASE 3.4 P1).

    Rampling, tapi memuat yang dibutuhkan agent `cutting`: ``id`` (untuk
    ``POST /garmen/work-orders/``) + ``qty`` (untuk ``size_matrix``).
    """

    return {
        "id": instance.pk,
        "order_code": instance.order.code if instance.order_id else None,
        "product_code": instance.product.code if instance.product_id else None,
        "qty": instance.qty,
        "tag": instance.tag,
    }


#: resource -> queryset + serializer baris.
RESOURCE_LIST: dict[str, dict] = {
    "order-lines": {
        "queryset": lambda: OrderLine.objects.select_related("order", "product"),
        "serializer": serialize_order_line,
    },
    "work-orders": {
        "queryset": lambda: WorkOrder.objects.all(),
        "serializer": serialize_work_order,
    },
    "bundles": {
        "queryset": lambda: Bundle.objects.select_related("current_work_center"),
        "serializer": serialize_bundle,
    },
    "qc": {
        "queryset": lambda: ScrapAccumulator.objects.select_related(
            "work_center", "bundle"
        ),
        "serializer": serialize_qc,
    },
}


class ResourceListView(APIView):
    """Daftar resource dengan paginasi limit/offset."""

    permission_classes = [AllowAny]  # auth menyusul Fase 6

    def get(self, request, industry: str, resource: str):
        """Kembalikan `ListPage` §3: `{rows, total_count, has_more, next_cursor}`."""
        # Fase A: industri divalidasi dulu (404 eksplisit) sebelum menyentuh data.
        industry_code = require_industry(industry)

        config = RESOURCE_LIST.get(str(resource).strip().lower())
        if config is None:
            return Response(
                {"detail": f"Resource '{resource}' tidak dikenal."},
                status=status.HTTP_404_NOT_FOUND,
            )

        limit, error = self._int_param(request, "limit", DEFAULT_LIMIT, 1, MAX_LIMIT)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        offset, error = self._int_param(request, "offset", DEFAULT_OFFSET, 0, MAX_OFFSET)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        queryset = config["queryset"]()
        total = queryset.count()
        rows = [
            config["serializer"](instance)
            for instance in queryset[offset : offset + limit]
        ]
        return Response(
            {
                # Kontrak `ListPage` frontend (Fase B.2): 4 key berikut WAJIB ada.
                "rows": rows,
                "total_count": total,
                "has_more": offset + len(rows) < total,
                # Paginasi list masih offset-based (`limit`/`offset`), jadi belum
                # ada cursor keyset; key tetap dikirim (`null`) sesuai kontrak.
                "next_cursor": None,
                # --- key tambahan (di luar kontrak; Zod men-strip key asing)
                "resource": str(resource).strip().lower(),
                "industry": industry_code,
            },
            status=status.HTTP_200_OK,
        )

    @staticmethod
    def _int_param(request, name: str, default: int, minimum: int, maximum: int):
        """Baca query param angka; return `(value, error_message)`."""
        raw = request.query_params.get(name)
        if raw in (None, ""):
            return default, None
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return None, f"Parameter '{name}' harus berupa angka."
        if value < minimum or value > maximum:
            return None, f"Parameter '{name}' harus antara {minimum} dan {maximum}."
        return value, None
