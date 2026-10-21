"""Metrik `garment.bottleneck` (R.4) — WC paling menumpuk.

Formula: ``buffer_length × avg_wait_hours`` per work center.
- `buffer_length` = jumlah bundle aktif (state bukan DONE/CANCELLED) di WC.
- `avg_wait_hours` = rata-rata ``now - updated_at`` bundle tersebut.

Set-based: SATU query (COUNT + AVG `updated_at` per WC) — tanpa loop per bundle.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Avg, Count, FloatField, Func
from django.utils import timezone

from ....core.metric import MetricDefinition

METRIC_ID = "garment.bottleneck"

#: State terminal — bukan bagian dari buffer.
TERMINAL_STATES = ("DONE", "CANCELLED")


class _EpochSeconds(Func):
    """`EXTRACT(EPOCH FROM ts)` → detik (Postgres tidak punya AVG(timestamptz))."""

    template = "EXTRACT(EPOCH FROM %(expressions)s)"
    output_field = FloatField()


def _compute_bottleneck(filters: dict[str, Any]) -> list[dict]:
    """Skor bottleneck per work center (buffer × rata-rata waktu tunggu)."""
    from apps_industry.garment.models import Bundle

    qs = Bundle.objects.exclude(state__in=TERMINAL_STATES).filter(
        current_work_center__isnull=False
    )
    if filters.get("work_center_id"):
        qs = qs.filter(current_work_center_id=filters["work_center_id"])
    if filters.get("line_id"):
        qs = qs.filter(production_line_id=filters["line_id"])

    rows = qs.values(
        "current_work_center__code",
        "current_work_center__name",
    ).annotate(
        buffer_length=Count("id"),
        avg_epoch=Avg(_EpochSeconds("updated_at")),
    )

    now_epoch = timezone.now().timestamp()
    result = []
    for row in rows:
        buffer_length = int(row["buffer_length"] or 0)
        avg_epoch = row["avg_epoch"]
        avg_wait = 0.0
        if avg_epoch is not None:
            avg_wait = max(0.0, (now_epoch - float(avg_epoch)) / 3600)
        result.append(
            {
                "key": str(row["current_work_center__code"]),
                "label": row["current_work_center__name"]
                or str(row["current_work_center__code"]),
                "value": round(buffer_length * avg_wait, 2),
                "buffer_length": buffer_length,
                "avg_wait_hours": round(avg_wait, 2),
            }
        )

    return sorted(result, key=lambda item: -item["value"])


METRIC = MetricDefinition(
    metric_id=METRIC_ID,
    domain="garment",
    label="Bottleneck",
    unit="score",
    granularities=["hour", "day"],
    dimensions=["period", "work_center"],
    source_models=["garment.Bundle", "garment.WorkCenter"],
    formula_version="1.0",
    compute=_compute_bottleneck,
    null_policy="no_active_returns_empty",
)


__all__ = ("METRIC", "METRIC_ID", "TERMINAL_STATES")
