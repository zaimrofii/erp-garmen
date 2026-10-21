"""Metrik `garment.lead_time` (CONTRACT §8.3) — jam, p50/p90 per hari."""

from __future__ import annotations

import math
from typing import Any

from django.db.models import OuterRef, Subquery
from django.db.models.functions import TruncDate

from ....core.metric import MetricDefinition
from ....core.stream_engine import evaluate as stream_evaluate
from ._common import range_kwargs

METRIC_ID = "garment.lead_time"


def _percentile(values: list[float], p: float) -> float | None:
    """Percentile nearest-rank (p50/p90 deterministik, tanpa interpolasi)."""
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(p * len(ordered)) - 1)
    return round(ordered[index], 6)


def count_incomplete_pairs(filters: dict[str, Any]) -> int:
    """Bundle yang hanya punya START atau hanya FINISH (dalam rentang filter)."""
    from apps_industry.garment.models import Bundle, BundleEvent

    start_sq = (
        BundleEvent.objects.filter(bundle=OuterRef("pk"), event_type="BUNDLE_START")
        .order_by("ts")
        .values("ts")[:1]
    )
    finish_sq = (
        BundleEvent.objects.filter(bundle=OuterRef("pk"), event_type="BUNDLE_FINISH")
        .order_by("-ts")
        .values("ts")[:1]
    )

    bundles = Bundle.objects.annotate(
        start_ts=Subquery(start_sq), finish_ts=Subquery(finish_sq)
    )
    if filters.get("line_id"):
        bundles = bundles.filter(production_line_id=filters["line_id"])
    if filters.get("date_from") is not None:
        bundles = bundles.filter(finish_ts__gte=filters["date_from"])
    if filters.get("date_to") is not None:
        bundles = bundles.filter(finish_ts__lte=filters["date_to"])

    incomplete = bundles.filter(start_ts__isnull=True, finish_ts__isnull=False).count()
    incomplete += bundles.filter(start_ts__isnull=False, finish_ts__isnull=True).count()
    return incomplete


def _compute_lead_time(filters: dict[str, Any]) -> list[dict]:
    """Per bundle: ts(FINISH) − ts(START) dalam jam; agregasi per hari."""
    from apps_industry.garment.models import Bundle, BundleEvent

    start_sq = (
        BundleEvent.objects.filter(bundle=OuterRef("pk"), event_type="BUNDLE_START")
        .order_by("ts")
        .values("ts")[:1]
    )
    finish_sq = (
        BundleEvent.objects.filter(bundle=OuterRef("pk"), event_type="BUNDLE_FINISH")
        .order_by("-ts")
        .values("ts")[:1]
    )

    bundles = Bundle.objects.annotate(
        start_ts=Subquery(start_sq), finish_ts=Subquery(finish_sq)
    )
    if filters.get("line_id"):
        bundles = bundles.filter(production_line_id=filters["line_id"])
    if filters.get("date_from") is not None:
        bundles = bundles.filter(finish_ts__gte=filters["date_from"])
    if filters.get("date_to") is not None:
        bundles = bundles.filter(finish_ts__lte=filters["date_to"])

    incomplete = bundles.filter(start_ts__isnull=True, finish_ts__isnull=False).count()
    incomplete += bundles.filter(start_ts__isnull=False, finish_ts__isnull=True).count()

    pairs = list(
        bundles.filter(start_ts__isnull=False, finish_ts__isnull=False)
        .annotate(bucket=TruncDate("finish_ts"))
        .values_list("bucket", "start_ts", "finish_ts")
    )

    buckets: dict[Any, list[float]] = {}
    for bucket, start_ts, finish_ts in pairs:
        hours = (finish_ts - start_ts).total_seconds() / 3600
        buckets.setdefault(bucket, []).append(hours)

    rows = []
    for bucket in sorted(buckets, key=str):
        durations = buckets[bucket]
        rows.append(
            {
                "key": str(bucket),
                "label": str(bucket),
                "value": round(sum(durations) / len(durations), 6),
                "p50": _percentile(durations, 0.5),
                "p90": _percentile(durations, 0.9),
                "n_bundles": len(durations),
                "incomplete_pairs": incomplete,
            }
        )
    return rows


def _stream_lead_time(event: dict, rule: dict) -> dict | None:
    return stream_evaluate(event, rule)


METRIC = MetricDefinition(
    metric_id=METRIC_ID,
    domain="garment",
    label="Lead Time",
    unit="jam",
    granularities=["day"],
    dimensions=["period", "line"],
    source_models=["garment.BundleEvent", "garment.Bundle"],
    formula_version="1.0",
    compute=_compute_lead_time,
    stream_check=_stream_lead_time,
)
