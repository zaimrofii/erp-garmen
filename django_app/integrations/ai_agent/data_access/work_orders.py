"""Repository work order (JOIN order + produk)."""

from __future__ import annotations

from apps_industry.garment.models import WorkOrder

from .base import BaseRepository


class WorkOrderRepository(BaseRepository):
    model = WorkOrder
    join_spec = ["order_line__product", "order_line__order"]
    order_by = ["-created_at"]
    serialize_fields = [
        "id",
        "code",
        "order_line_id",
        "state",
        "qty_planned",
        "qty_done",
        "created_at",
    ]
    serialize_joins = {
        "order_code": "order_line.order.code",
        "product_name": "order_line.product.name",
        "product_code": "order_line.product.code",
    }


__all__ = ("WorkOrderRepository",)
