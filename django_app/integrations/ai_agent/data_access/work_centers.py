"""Repository work center."""

from __future__ import annotations

from apps_industry.garment.models import WorkCenter

from .base import BaseRepository


class WorkCenterRepository(BaseRepository):
    model = WorkCenter
    order_by = ["name"]
    serialize_fields = [
        "id",
        "code",
        "name",
        "wc_type",
        "capacity_per_hour",
    ]


__all__ = ("WorkCenterRepository",)
