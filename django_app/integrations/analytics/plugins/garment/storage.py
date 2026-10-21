"""Pemilihan storage backend per metrik garment (B.5).

Semua metrik garment memakai DjangoORMStorage. Fase G bisa menambah
TimescaleBackend per metrik tanpa mengubah pemanggil (`get_storage_for_metric`).
"""

from __future__ import annotations

from ...core.storage import StorageBackend
from ...storage_backends.django_orm import DjangoORMStorage

_DEFAULT = DjangoORMStorage()


def get_storage_for_metric(metric_id: str) -> StorageBackend:
    """Storage backend untuk `metric_id` (saat ini: selalu Django ORM)."""
    del metric_id  # belum ada routing per-metrik
    return _DEFAULT


__all__ = ("get_storage_for_metric",)

