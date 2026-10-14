"""Endpoint detail resource: `GET /api/v1/<industry>/<resource>/<id>/` (Kontrak §3).

Mengirim data **mentah** instance (bukan metadata schema) — dipakai frontend
untuk refetch setelah aksi/konflik. `version` diambil dari builder Sprint 3.1
supaya nilainya identik dengan yang dikirim schema & dipakai conflict detection.
"""

from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps_industry.garment.api.industries import require_industry
from apps_industry.garment.api.schema.registry import get_builder

logger = logging.getLogger(__name__)


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def serialize_bundle_detail(instance) -> dict:
    """Detail bundle (field yang dipakai UI operator)."""
    return {
        "id": instance.pk,
        "code": instance.code,
        "state": instance.state,
        "size": instance.size,
        "sku_variant": instance.sku_variant,
        "qty": instance.qty,
        "qty_done": instance.qty_done,
        "work_order_id": instance.work_order_id,
        "current_work_center_code": (
            instance.current_work_center.code
            if instance.current_work_center_id
            else None
        ),
        "production_line_code": (
            instance.production_line.code if instance.production_line_id else None
        ),
        "updated_at": _iso(instance.updated_at),
    }


def serialize_work_order_detail(instance) -> dict:
    """Detail work order."""
    return {
        "id": instance.pk,
        "code": instance.code,
        "state": instance.state,
        "order_line_id": instance.order_line_id,
        "order_code": instance.order_line.order.code,
        "product_code": instance.order_line.product.code,
        "qty_planned": instance.qty_planned,
        "qty_done": instance.qty_done,
        "updated_at": _iso(instance.updated_at),
    }


def serialize_qc_detail(instance) -> dict:
    """Detail catatan QC."""
    return {
        "id": instance.pk,
        "work_center_code": (
            instance.work_center.code if instance.work_center_id else None
        ),
        "bundle_id": instance.bundle_id,
        "bundle_code": instance.bundle.code if instance.bundle_id else None,
        "qty": instance.qty,
        "rework_qty": instance.rework_qty,
        "end_loss_qty": instance.end_loss_qty,
        "reason": instance.reason,
        "notes": instance.notes,
        "updated_at": _iso(instance.updated_at),
    }


def serialize_order_line_detail(instance) -> dict:
    """Detail order line (jalur "order baru" FASE 3.4 P1).

    ``work_order_ids`` supaya pemanggil tahu apakah order line ini sudah punya
    WorkOrder — endpoint create bundle menolak WO yang bukan WO **pertama** order
    line, jadi order line yang sudah punya WO tidak bisa dipakai lagi.
    """

    return {
        "id": instance.pk,
        "order_id": instance.order_id,
        "order_code": instance.order.code if instance.order_id else None,
        "product_code": instance.product.code if instance.product_id else None,
        "qty": instance.qty,
        "tag": instance.tag,
        "ticket_code": instance.ticket_code,
        "work_order_ids": list(instance.work_orders.values_list("id", flat=True)),
        "updated_at": _iso(instance.updated_at),
    }


#: resource -> serializer detail.
RESOURCE_DETAIL = {
    "bundles": serialize_bundle_detail,
    "work-orders": serialize_work_order_detail,
    "qc": serialize_qc_detail,
    "order-lines": serialize_order_line_detail,
}


class ResourceDetailView(APIView):
    """Data mentah satu instance resource (+ `version` untuk conflict detection)."""

    permission_classes = [AllowAny]  # auth menyusul Fase 6

    def get(self, request, industry: str, resource: str, id: int):
        """Kembalikan detail instance; 404 kalau resource/id tidak ada."""
        # Fase A: industri divalidasi dulu (404 eksplisit) sebelum menyentuh data.
        industry_code = require_industry(industry)

        resource_key = str(resource).strip().lower()
        serializer = RESOURCE_DETAIL.get(resource_key)
        builder_class = get_builder(resource_key)
        if serializer is None or builder_class is None:
            return Response(
                {"detail": f"Resource '{resource}' tidak dikenal."},
                status=status.HTTP_404_NOT_FOUND,
            )

        queryset = builder_class.MODEL.objects.all()
        if builder_class.SELECT_RELATED:
            queryset = queryset.select_related(*builder_class.SELECT_RELATED)

        instance = queryset.filter(pk=id).first()
        if instance is None:
            return Response(
                {"detail": f"Resource '{resource}' dengan id {id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        builder = builder_class(
            instance=instance, request=request, industry=industry_code
        )
        payload = serializer(instance)
        payload["version"] = builder.get_version()
        # Fase 0.5: aksi yang diizinkan ikut di detail, memakai helper state
        # machine yang SAMA dengan endpoint schema (`builder.get_state_machine()`).
        payload["allowed_actions"] = builder.get_state_machine()["allowed_actions"]
        return Response(payload, status=status.HTTP_200_OK)
