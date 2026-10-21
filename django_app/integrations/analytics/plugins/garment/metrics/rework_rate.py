"""Metrik `garment.rework_rate` (CONTRACT §8.2)."""

from __future__ import annotations

from typing import Any

from django.db.models import Sum

from ....core.metric import MetricDefinition
from ....core.stream_engine import evaluate as stream_evaluate
from ._common import bucket_fn, merge_ratio, range_kwargs, rework_qty_expr

METRIC_ID = "garment.rework_rate"


def _compute_rework_rate(filters: dict[str, Any]) -> list[dict]:
    """Numerator = Σ BundleEvent(REWORK).payload.qty (fallback 1/event).

    `ScrapAccumulator.rework_qty` TIDAK dipakai (hindari dobel hitung);
    hanya cross-check di `health`.
    """
    from apps_industry.garment.models import BundleEvent

    granularity = filters.get("granularity") or "day"
    group_by = filters.get("group_by") or "period"
    trunc = bucket_fn(granularity)

    rework = BundleEvent.objects.filter(
        event_type="REWORK", **range_kwargs(filters, "ts")
    )
    finished = BundleEvent.objects.filter(
        event_type="BUNDLE_FINISH", **range_kwargs(filters, "ts")
    )

    if filters.get("line_id"):
        rework = rework.filter(bundle__production_line_id=filters["line_id"])
        finished = finished.filter(bundle__production_line_id=filters["line_id"])
    if filters.get("work_center_id"):
        rework = rework.filter(payload__work_center_id=filters["work_center_id"])

    if group_by == "work_center":
        num_rows = (
            rework.values("payload__work_center_id")
            .annotate(qty=Sum(rework_qty_expr()))
            .values_list("payload__work_center_id", "qty")
        )
        den_rows = (
            finished.values("bundle__current_work_center_id")
            .annotate(qty=Sum("bundle__qty"))
            .values_list("bundle__current_work_center_id", "qty")
        )
    elif group_by == "line":
        num_rows = (
            rework.values("bundle__production_line_id")
            .annotate(qty=Sum(rework_qty_expr()))
            .values_list("bundle__production_line_id", "qty")
        )
        den_rows = (
            finished.values("bundle__production_line_id")
            .annotate(qty=Sum("bundle__qty"))
            .values_list("bundle__production_line_id", "qty")
        )
    else:
        num_rows = (
            rework.annotate(bucket=trunc("ts"))
            .values("bucket")
            .annotate(qty=Sum(rework_qty_expr()))
            .values_list("bucket", "qty")
        )
        den_rows = (
            finished.annotate(bucket=trunc("ts"))
            .values("bucket")
            .annotate(qty=Sum("bundle__qty"))
            .values_list("bucket", "qty")
        )

    return merge_ratio(dict(num_rows), dict(den_rows))


def _stream_rework_spike(event: dict, rule: dict) -> dict | None:
    return stream_evaluate(event, rule)


METRIC = MetricDefinition(
    metric_id=METRIC_ID,
    domain="garment",
    label="Rework Rate",
    unit="%",
    granularities=["hour", "day"],
    dimensions=["period", "work_center", "line"],
    source_models=["garment.BundleEvent", "garment.Bundle"],
    formula_version="1.0",
    compute=_compute_rework_rate,
    stream_check=_stream_rework_spike,
)
