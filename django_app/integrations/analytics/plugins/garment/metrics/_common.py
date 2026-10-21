"""Helper bersama metrik garment (set-based, tanpa loop query per baris)."""

from __future__ import annotations

from typing import Any

from django.db.models import IntegerField, Value
from django.db.models.functions import Cast, Coalesce, TruncDate, TruncHour

BUCKETS = {"day": TruncDate, "hour": TruncHour}


def bucket_fn(granularity: str):
    """Fungsi truncasi waktu untuk granularity `day`/`hour`."""
    try:
        return BUCKETS[granularity]
    except KeyError:
        raise ValueError(f"granularity tidak dikenal: {granularity!r}") from None


def range_kwargs(filters: dict[str, Any], field: str) -> dict[str, Any]:
    """Filter rentang `field` dari `date_from`/`date_to` (opsional)."""
    kwargs: dict[str, Any] = {}
    if filters.get("date_from") is not None:
        kwargs[f"{field}__gte"] = filters["date_from"]
    if filters.get("date_to") is not None:
        kwargs[f"{field}__lte"] = filters["date_to"]
    return kwargs


def rework_qty_expr():
    """`payload.qty` (integer) bila ada, fallback 1 per event REWORK."""
    return Coalesce(Cast("payload__qty", IntegerField()), Value(1))


def merge_ratio(numerator: dict, denominator: dict) -> list[dict]:
    """Gabungkan dua peta `key -> qty` menjadi rows rasio (%) — null bila denom 0."""
    rows = []
    for key in sorted(set(numerator) | set(denominator), key=str):
        denom = denominator.get(key, 0) or 0
        num = numerator.get(key, 0) or 0
        rows.append(
            {
                "key": str(key) if key is not None else "",
                "label": str(key) if key is not None else "Total",
                "value": round(num / denom * 100, 6) if denom else None,
                "numerator": num,
                "denominator": denom,
            }
        )
    return rows


def dimension_field(filters: dict[str, Any], prefix: str) -> tuple[str, dict]:
    """Tentukan field grouping + filter untuk dimensi work_center/line."""
    group_by = filters.get("group_by") or "period"
    if group_by == "work_center":
        return f"{prefix}work_center_id", {
            "work_center_id": filters.get("work_center_id")
        }
    if group_by == "line":
        return f"{prefix}production_line_id", {
            "production_line_id": filters.get("line_id")
        }
    return "", {}


def apply_optional(qs, filters: dict[str, Any]):
    """Terapkan filter dimensi opsional (work_center_id / line_id)."""
    if filters.get("work_center_id"):
        qs = qs.filter(work_center_id=filters["work_center_id"])
    if filters.get("line_id"):
        qs = qs.filter(production_line_id=filters["line_id"])
    return qs
