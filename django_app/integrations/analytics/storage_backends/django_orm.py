"""Storage backend Django ORM (B.5) — append-only `MetricSnapshot`.

Implementasi `core.storage.StorageBackend`. Upsert memakai
`bulk_create(ignore_conflicts=True)`: `unique_together` di model yang menangani
duplikat, jadi pemanggilan ulang (retry task) idempoten tanpa UPDATE baris lama
(append-only: baris lama tidak diubah).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..core.storage import StorageBackend
from ..plugins.garment.models import MetricSnapshot


class DjangoORMStorage(StorageBackend):
    """Storage snapshot metrik di PostgreSQL via Django ORM."""

    def save(self, metric_id: str, granularity: str, rows: list[dict]) -> int:
        """Bulk insert; baris dengan kunci unik sama diabaikan (idempoten)."""
        objects = [
            MetricSnapshot(
                metric_id=metric_id,
                granularity=granularity,
                dimension_key=str(row.get("dimension_key") or ""),
                period_start=row["period_start"],
                period_end=row["period_end"],
                value=row.get("value"),
                extra=row.get("extra") or {},
                formula_version=str(row.get("formula_version") or "1.0"),
            )
            for row in rows
        ]
        if not objects:
            return 0

        MetricSnapshot.objects.bulk_create(objects, ignore_conflicts=True)
        return len(objects)

    def query(
        self,
        metric_id: str,
        dimension: str | None,
        granularity: str,
        period_from: datetime | None = None,
        period_to: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Query snapshot historis (urut `-period_start`)."""
        qs = MetricSnapshot.objects.filter(
            metric_id=metric_id, granularity=granularity
        )
        if dimension:
            qs = qs.filter(dimension_key=dimension)
        if period_from is not None:
            qs = qs.filter(period_start__gte=period_from)
        if period_to is not None:
            qs = qs.filter(period_start__lte=period_to)

        return [
            {
                "metric_id": row.metric_id,
                "granularity": row.granularity,
                "dimension_key": row.dimension_key,
                "period_start": row.period_start,
                "period_end": row.period_end,
                "value": float(row.value) if row.value is not None else None,
                "extra": row.extra or {},
                "formula_version": row.formula_version,
            }
            for row in qs
        ]


__all__ = ("DjangoORMStorage",)

