"""Repository produk master."""

from __future__ import annotations

from master.models import Product

from .base import BaseRepository


class ProductRepository(BaseRepository):
    model = Product
    order_by = ["name"]
    serialize_fields = [
        "id",
        "code",
        "name",
        "category",
        "sale_price",
        "cost_price",
        "is_active",
    ]


__all__ = ("ProductRepository",)
