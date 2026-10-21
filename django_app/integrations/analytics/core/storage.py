"""Interface storage backend (core tidak peduli implementasi).

Implementasi Django ORM dibuat di B.5 (`storage_backends/django_orm.py`).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime


class StorageBackend(ABC):
    """Interface storage snapshot metrik (append-only)."""

    @abstractmethod
    def save(self, metric_id: str, granularity: str, rows: list[dict]) -> int:
        """Bulk upsert. Return jumlah baris tersimpan."""
        raise NotImplementedError

    @abstractmethod
    def query(
        self,
        metric_id: str,
        dimension: str,
        granularity: str,
        period_from: datetime | None = None,
        period_to: datetime | None = None,
    ) -> list[dict]:
        """Query snapshot historis."""
        raise NotImplementedError


__all__ = ("StorageBackend",)
