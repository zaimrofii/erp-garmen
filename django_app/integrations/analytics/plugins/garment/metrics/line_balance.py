"""Metrik `garment.line_balance` (R.4) — keseimbangan output antar work center.

Formula: per line ``1 - (max_wc - avg_wc) / avg_wc`` dari `Bundle.qty_done`
per work center. Nilai 1.0 = sempurna seimbang, 0.0 = sangat tidak seimbang.

Set-based: SATU query agregat (GROUP BY line + work center); pengelompokan akhir
di memori — tanpa query per baris (bukan N+1).
"""

from __future__ import annotations

from typing import Any

from django.db.models import Sum

from ....core.metric import MetricDefinition
from ._common import bucket_fn, range_kwargs

METRIC_ID = "garment.line_balance"


def _balance(values: list[float]) -> float:
    """Balance score 0..1 dari daftar qty per work center."""
    if not values:
        return 0.0
    average = sum(values) / len(values)
    if average <= 0:
        return 0.0
    return max(0.0, min(1.0, 1.0 - (max(values) - average) / average))


def _compute_line_balance(filters: dict[str, Any]) -> list[dict]:
    """Balance score per line (default) atau per bucket periode."""
    from apps_industry.garment.models import Bundle

    group_by = filters.get("group_by") or "line"
    granularity = filters.get("granularity") or "day"

    qs = Bundle.objects.filter(
        state="DONE",
        current_work_center__isnull=False,
        **range_kwargs(filters, "updated_at"),
    )
    if filters.get("work_center_id"):
        qs = qs.filter(current_work_center_id=filters["work_center_id"])

    grouped: dict[str, dict[str, Any]] = {}

    if group_by == "period":
        trunc = bucket_fn(granularity)
        rows = (
            qs.annotate(bucket=trunc("updated_at"))
            .values("bucket", "current_work_center_id")
            .annotate(qty_done=Sum("qty_done"))
        )
        for row in rows:
            key = str(row["bucket"])
            entry = grouped.setdefault(key, {"label": key, "qty": {}})
            entry["qty"][row["current_work_center_id"]] = float(
                row["qty_done"] or 0
            )
    else:
        qs = qs.filter(production_line__isnull=False)
        if filters.get("line_id"):
            qs = qs.filter(production_line_id=filters["line_id"])
        rows = (
            qs.values(
                "production_line__code",
                "production_line__name",
                "current_work_center_id",
            ).annotate(qty_done=Sum("qty_done"))
        )
        for row in rows:
            key = str(row["production_line__code"])
            entry = grouped.setdefault(
                key, {"label": row["production_line__name"] or key, "qty": {}}
            )
            entry["qty"][row["current_work_center_id"]] = float(
                row["qty_done"] or 0
            )

    result = []
    for key, entry in grouped.items():
        quantities = list(entry["qty"].values())
        if not quantities or sum(quantities) <= 0:
            continue
        result.append(
            {
                "key": key,
                "label": entry["label"],
                "value": round(_balance(quantities), 2),
                "total_done": round(sum(quantities), 2),
                "work_center_count": len(quantities),
            }
        )

    return sorted(result, key=lambda item: item["value"])


METRIC = MetricDefinition(
    metric_id=METRIC_ID,
    domain="garment",
    label="Line Balance",
    unit="ratio",
    granularities=["day"],
    dimensions=["period", "line"],
    source_models=["garment.Bundle", "garment.ProductionLine", "garment.WorkCenter"],
    formula_version="1.0",
    compute=_compute_line_balance,
    null_policy="no_line_returns_empty",
)


__all__ = ("METRIC", "METRIC_ID")
