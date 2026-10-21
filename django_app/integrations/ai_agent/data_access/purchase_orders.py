"""Repository purchase order (JOIN vendor)."""

from __future__ import annotations

from apps_industry.garment.models import PurchaseOrder

from .base import BaseRepository


class PurchaseOrderRepository(BaseRepository):
    model = PurchaseOrder
    join_spec = ["vendor"]
    order_by = ["-created_at"]
    serialize_fields = ["id", "code", "state", "created_at", "partner_ref"]
    serialize_joins = {
        "vendor_id": "vendor.id",
        "vendor_name": "vendor.name",
        "vendor_code": "vendor.code",
    }


__all__ = ("PurchaseOrderRepository",)
