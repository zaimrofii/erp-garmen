"""Base repository AI data access — template query + serialisasi.

Semua repository entity mewarisi kelas ini. JOIN/prefetch dan serialisasi
dideklarasikan di subclass; context builder tidak menulis JOIN sendiri.
"""

from __future__ import annotations

from abc import ABC
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any


class BaseRepository(ABC):
    model: type | None = None
    join_spec: list[str] = []
    prefetch_spec: list[str] = []
    order_by: list[str] = ["-id"]
    serialize_fields: list[str] = []
    serialize_joins: dict[str, str] = {}

    def _base_queryset(self):
        qs = self.model.objects.all()
        if self.join_spec:
            qs = qs.select_related(*self.join_spec)
        if self.prefetch_spec:
            qs = qs.prefetch_related(*self.prefetch_spec)
        return qs

    def get_list(self, filters: dict | None = None, limit: int = 20) -> list[dict]:
        qs = self._base_queryset()
        if filters:
            qs = qs.filter(**filters)
        rows = qs.order_by(*self.order_by)[:limit]
        return [self._serialize(obj) for obj in rows]

    def get_by_id(self, obj_id: int) -> dict | None:
        obj = self._base_queryset().filter(id=obj_id).first()
        return self._serialize(obj) if obj else None

    def _serialize(self, obj) -> dict:
        data: dict[str, Any] = {}
        for field in self.serialize_fields:
            data[field] = self._cast(getattr(obj, field, None))
        for out_key, path in self.serialize_joins.items():
            data[out_key] = self._cast(self._resolve(obj, path))
        return data

    def _resolve(self, obj, path: str):
        for attr in path.split("."):
            if obj is None:
                return None
            obj = getattr(obj, attr, None)
        return obj

    def _cast(self, value):
        if value is None or isinstance(value, (int, float, str, bool)):
            return value
        if isinstance(value, (date, datetime, time)):
            return value.isoformat()
        if isinstance(value, Decimal):
            return str(value)
        return str(value)


__all__ = ("BaseRepository",)
