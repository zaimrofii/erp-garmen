"""Metrik `garment.scrap_rate` (CONTRACT §8.1)."""

from __future__ import annotations

from typing import Any

from django.db.models import Sum

from ....core.metric import MetricDefinition
from ....core.stream_engine import evaluate as stream_evaluate
from ..models import (  # noqa: F401 - memastikan app model siap
    MetricSnapshot,
)
from ._common import bucket_fn, merge_ratio, range_kwargs

METRIC_ID = "garment.scrap_rate"


def _compute_scrap_rate(filters: dict[str, Any]) -> list[dict]:
    """Numerator scrap ÷ denominator qty bundle FINISH (BUKAN WO.qty_planned)."""
    from apps_industry.garment.models import BundleEvent, ScrapAccumulator

    granularity = filters.get("granularity") or "day"
    group_by = filters.get("group_by") or "period"
    trunc = bucket_fn(granularity)

    scrap = ScrapAccumulator.objects.filter(
        **range_kwargs(filters, "created_at")
    )
    finished = BundleEvent.objects.filter(
        event_type="BUNDLE_FINISH", **range_kwargs(filters, "ts")
    )

    if filters.get("work_center_id"):
        scrap = scrap.filter(work_center_id=filters["work_center_id"])
        finished = finished.filter(
            bundle__current_work_center_id=filters["work_center_id"]
        )
    if filters.get("line_id"):
        scrap = scrap.filter(bundle__production_line_id=filters["line_id"])
        finished = finished.filter(bundle__production_line_id=filters["line_id"])

    if group_by == "work_center":
        num_rows = (
            scrap.values("work_center_id")
            .annotate(qty=Sum("qty"))
            .values_list("work_center_id", "qty")
        )
        den_rows = (
            finished.values("bundle__current_work_center_id")
            .annotate(qty=Sum("bundle__qty"))
            .values_list("bundle__current_work_center_id", "qty")
        )
    elif group_by == "line":
        num_rows = (
            scrap.values("bundle__production_line_id")
            .annotate(qty=Sum("qty"))
            .values_list("bundle__production_line_id", "qty")
        )
        den_rows = (
            finished.values("bundle__production_line_id")
            .annotate(qty=Sum("bundle__qty"))
            .values_list("bundle__production_line_id", "qty")
        )
    else:
        num_rows = (
            scrap.annotate(bucket=trunc("created_at"))
            .values("bucket")
            .annotate(qty=Sum("qty"))
            .values_list("bucket", "qty")
        )
        den_rows = (
            finished.annotate(bucket=trunc("ts"))
            .values("bucket")
            .annotate(qty=Sum("bundle__qty"))
            .values_list("bucket", "qty")
        )

    return merge_ratio(dict(num_rows), dict(den_rows))


def _stream_scrap_spike(event: dict, rule: dict) -> dict | None:
    """Delegate ke stream engine (B.4)."""
    return stream_evaluate(event, rule)


METRIC = MetricDefinition(
    metric_id=METRIC_ID,
    domain="garment",
    label="Scrap Rate",
    unit="%",
    granularities=["hour", "day"],
    dimensions=["period", "work_center", "line"],
    source_models=["garment.ScrapAccumulator", "garment.BundleEvent"],
    formula_version="1.0",
    compute=_compute_scrap_rate,
    stream_check=_stream_scrap_spike,
)
