"""Metrik `garment.scrap_rate` (CONTRACT §8.1, formula v2 — kohort DONE)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from django.db.models import Sum

from ....core.metric import MetricDefinition
from ....core.stream_engine import evaluate as stream_evaluate
from ..models import (  # noqa: F401 - memastikan app model siap
    MetricSnapshot,
)
from ._common import range_kwargs

METRIC_ID = "garment.scrap_rate"


def _bucket(ts: datetime | None, granularity: str) -> Any:
    """Bucket waktu: per jam atau per tanggal."""
    if ts is None:
        return "Total"
    if granularity == "hour":
        return ts.replace(minute=0, second=0, microsecond=0).isoformat()
    return ts.date().isoformat()


def _compute_scrap_rate(filters: dict[str, Any]) -> list[dict]:
    """Scrap rate kohort SAMA: bundle DONE saja.

    numerator   = SUM(ScrapAccumulator.qty) untuk bundle berstatus DONE
    denominator = SUM(Bundle.qty_done) untuk bundle yang SAMA (DONE)
    denominator 0 → value 0 (bukan error/None). Nilai di-clamp ≤ 100.
    """
    from apps_industry.garment.models import Bundle, BundleEvent, ScrapAccumulator

    granularity = filters.get("granularity") or "day"
    group_by = filters.get("group_by") or "period"

    done = Bundle.objects.filter(state="DONE")
    if filters.get("work_center_id"):
        done = done.filter(current_work_center_id=filters["work_center_id"])
    if filters.get("line_id"):
        done = done.filter(production_line_id=filters["line_id"])

    # Kohort berbasis waktu = bundle yang FINISH di rentang tersebut.
    if filters.get("date_from") is not None or filters.get("date_to") is not None:
        finished = BundleEvent.objects.filter(
            event_type="BUNDLE_FINISH", bundle__in=done, **range_kwargs(filters, "ts")
        )
        done = done.filter(pk__in=finished.values("bundle_id"))

    bundles = list(
        done.values("id", "qty_done", "current_work_center_id", "production_line_id")
    )
    if not bundles:
        return []

    ids = [row["id"] for row in bundles]
    finish_map: dict[int, datetime] = {}
    for bundle_id, ts in BundleEvent.objects.filter(
        event_type="BUNDLE_FINISH", bundle_id__in=ids
    ).values_list("bundle_id", "ts"):
        if bundle_id not in finish_map or ts > finish_map[bundle_id]:
            finish_map[bundle_id] = ts

    scrap = dict(
        ScrapAccumulator.objects.filter(bundle_id__in=ids)
        .values("bundle_id")
        .annotate(qty=Sum("qty"))
        .values_list("bundle_id", "qty")
    )

    numerator: dict[Any, int] = {}
    denominator: dict[Any, int] = {}
    for row in bundles:
        if group_by == "work_center":
            key: Any = str(row["current_work_center_id"])
        elif group_by == "line":
            key = str(row["production_line_id"])
        else:
            key = _bucket(finish_map.get(row["id"]), granularity)
        numerator[key] = numerator.get(key, 0) + int(scrap.get(row["id"], 0) or 0)
        denominator[key] = denominator.get(key, 0) + int(row["qty_done"] or 0)

    rows: list[dict] = []
    for key in sorted(set(numerator) | set(denominator), key=str):
        num = numerator.get(key, 0)
        den = denominator.get(key, 0)
        rate = min(100.0, num / den * 100) if den else 0.0
        rows.append(
            {
                "key": str(key),
                "label": str(key),
                "value": round(rate, 6),
                "numerator": num,
                "denominator": den,
            }
        )
    return rows


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
    source_models=["garment.ScrapAccumulator", "garment.Bundle"],
    formula_version="2.0",
    compute=_compute_scrap_rate,
    stream_check=_stream_scrap_spike,
)

