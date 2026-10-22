"""Repository order + baris order (nama customer/produk ter-JOIN)."""

from __future__ import annotations

from apps_industry.garment.models import Order

from .base import BaseRepository


class OrderRepository(BaseRepository):
    model = Order
    join_spec = ["customer"]
    order_by = ["-created_at", "-id"]
    serialize_fields = ["id", "code", "customer_id", "state", "created_at", "deadline", "completed_at"]
    serialize_joins = {
        "customer_name": "customer.name",
        "customer_code": "customer.code",
    }

    def get_list(self, filters: dict | None = None, limit: int = 20) -> list[dict]:
        rows = super().get_list(filters, limit)
        ids = [row["id"] for row in rows]
        if not ids:
            return rows

        orders = {
            obj.id: obj
            for obj in Order.objects.filter(id__in=ids).prefetch_related(
                "lines__product"
            )
        }
        for row in rows:
            order = orders.get(row["id"])
            row["lines"] = [
                {
                    "id": line.id,
                    "order_id": line.order_id,
                    "product_id": line.product_id,
                    "product_name": line.product.name if line.product else None,
                    "product_code": line.product.code if line.product else None,
                    "qty": line.qty,
                    "price_unit": str(line.price_unit),
                    "tag": line.tag,
                }
                for line in (order.lines.all() if order else [])
            ]
        return rows


__all__ = ("OrderRepository",)
