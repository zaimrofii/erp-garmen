"""Repository production line."""

from __future__ import annotations

from apps_industry.garment.models import ProductionLine

from .base import BaseRepository


class ProductionLineRepository(BaseRepository):
    model = ProductionLine
    order_by = ["name"]
    serialize_fields = ["id", "code", "name"]


__all__ = ("ProductionLineRepository",)
