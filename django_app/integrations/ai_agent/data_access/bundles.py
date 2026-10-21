"""Repository bundle (JOIN WO, order, produk, line, work center)."""

from __future__ import annotations

from apps_industry.garment.models import Bundle

from .base import BaseRepository


class BundleRepository(BaseRepository):
    model = Bundle
    join_spec = [
        "work_order__order_line__product",
        "work_order__order_line__order",
        "work_order__order_line__order__customer",
        "production_line",
        "current_work_center",
    ]
    order_by = ["-created_at"]
    serialize_fields = [
        "id",
        "code",
        "work_order_id",
        "qty",
        "qty_done",
        "state",
        "size",
        "created_at",
    ]
    serialize_joins = {
        "work_order_code": "work_order.code",
        "order_code": "work_order.order_line.order.code",
        "customer_name": "work_order.order_line.order.customer.name",
        "product_name": "work_order.order_line.product.name",
        "product_code": "work_order.order_line.product.code",
        "line_name": "production_line.name",
        "work_center_name": "current_work_center.name",
    }


__all__ = ("BundleRepository",)
