"""MCP `comparator` (H T3.1) — banding metrik antar periode/dimensi READ-ONLY."""

from __future__ import annotations

from typing import Any

from django.utils.dateparse import parse_datetime

from integrations.analytics.core import registry

ALLOWED_ROLES = {"SUPERVISOR", "OWNER", "ADMIN"}
VALID_METRICS = {"garment.scrap_rate", "garment.rework_rate", "garment.lead_time"}
VALID_DIMENSIONS = {"line", "work_center"}
SCHEMA = {
    "compare_periods": {
        "metric_id": "str",
        "period_a": "dict",
        "period_b": "dict",
        "group_by": "str?",
    },
    "compare_dimensions": {
        "metric_id": "str",
        "dimension_a": "dict",
        "dimension_b": "dict",
        "period_from": "str",
        "period_to": "str",
    },
}


def _role_code(user) -> str:
    role = getattr(user, "role", None)
    return str(getattr(role, "code", "") or "").strip().upper()


def _error(error: str, detail: str = "") -> dict[str, Any]:
    return {"ok": False, "error": error, "detail": detail}


def _metric(metric_id: str):
    if metric_id not in VALID_METRICS:
        return None
    try:
        return registry.get_metric(metric_id)
    except KeyError:
        return None


def _period(value: Any):
    if not isinstance(value, dict):
        return None, None
    start = parse_datetime(str(value.get("from") or ""))
    end = parse_datetime(str(value.get("to") or ""))
    if start is None or end is None or start > end:
        return None, None
    return start, end


def _average_value(rows: list[dict]) -> tuple[float | None, int]:
    values = [
        float(row.get("value"))
        for row in rows or []
        if isinstance(row, dict) and row.get("value") is not None
    ]
    if not values:
        return None, 0
    return sum(values) / len(values), len(values)


def _dimension_value(rows: list[dict], dimension_id: Any) -> float | None:
    wanted = str(dimension_id)
    for row in rows or []:
        if str(row.get("key")) == wanted:
            return float(row.get("value")) if row.get("value") is not None else None
    return None


def _compare(label: str, a: float, b: float, unit: str) -> tuple[dict, dict]:
    delta = a - b
    delta_pct = (delta / b * 100) if b else 0.0
    if abs(delta) < 1e-9:
        trend = "same"
        winner = "tie"
    else:
        trend = "better" if a < b else "worse"
        winner = "A" if a < b else "B"
    comparison = {
        "label": label,
        "a_value": round(a, 6),
        "b_value": round(b, 6),
        "delta": round(delta, 6),
        "delta_pct": round(delta_pct, 4),
        "trend": trend,
        "unit": unit,
    }
    summary = {
        "winner": winner,
        "significant": abs(delta_pct) > 10,
    }
    return comparison, summary


def _compare_periods(params: dict, metric) -> dict:
    period_a = _period(params.get("period_a"))
    period_b = _period(params.get("period_b"))
    if period_a[0] is None or period_b[0] is None:
        return _error("bad_request", "period_a/period_b tidak valid.")

    group_by = params.get("group_by") or "period"
    a_rows = metric.compute(
        {
            "granularity": "day",
            "group_by": group_by,
            "date_from": period_a[0],
            "date_to": period_a[1],
        }
    )
    b_rows = metric.compute(
        {
            "granularity": "day",
            "group_by": group_by,
            "date_from": period_b[0],
            "date_to": period_b[1],
        }
    )
    a_value, a_count = _average_value(a_rows)
    b_value, b_count = _average_value(b_rows)
    if a_value is None or b_value is None:
        return _error("no_data", "Salah satu periode tidak memiliki data.")

    comparison, summary = _compare(
        "Periode A vs Periode B", a_value, b_value, metric.unit
    )
    return {
        "ok": True,
        "metric_id": metric.metric_id,
        "comparison": [comparison],
        "summary": summary,
        "meta": {"a_rows": a_count, "b_rows": b_count},
    }


def _compare_dimensions(params: dict, metric) -> dict:
    dimension_a = params.get("dimension_a") or {}
    dimension_b = params.get("dimension_b") or {}
    type_a = str(dimension_a.get("type") or "")
    type_b = str(dimension_b.get("type") or "")
    if type_a not in VALID_DIMENSIONS or type_b not in VALID_DIMENSIONS:
        return _error("bad_request", "dimension type harus line/work_center.")
    if type_a != type_b:
        return _error("bad_request", "dimension_a dan dimension_b harus tipe sama.")

    start = parse_datetime(str(params.get("period_from") or ""))
    end = parse_datetime(str(params.get("period_to") or ""))
    if start is None or end is None or start > end:
        return _error("bad_request", "period_from/period_to tidak valid.")

    rows = metric.compute(
        {
            "granularity": "day",
            "group_by": type_a,
            "date_from": start,
            "date_to": end,
        }
    )
    a_value = _dimension_value(rows, dimension_a.get("id"))
    b_value = _dimension_value(rows, dimension_b.get("id"))
    if a_value is None or b_value is None:
        return _error("no_data", "Salah satu dimensi tidak memiliki data.")

    label = f"{type_a} {dimension_a.get('id')} vs {type_b} {dimension_b.get('id')}"
    comparison, summary = _compare(label, a_value, b_value, metric.unit)
    return {
        "ok": True,
        "metric_id": metric.metric_id,
        "comparison": [comparison],
        "summary": summary,
        "meta": {"rows": len(rows or [])},
    }


def handle(method: str, params: dict | None = None, user=None) -> dict[str, Any]:
    """Bandingkan metrik read-only; fail-safe bila data/registry bermasalah."""
    if _role_code(user) not in ALLOWED_ROLES:
        return _error("forbidden", "Role tidak berhak mengakses comparator.")
    if method not in SCHEMA:
        return _error("method_tidak_dikenal", str(method))

    data = params or {}
    metric_id = str(data.get("metric_id") or "").strip()
    metric = _metric(metric_id)
    if metric is None:
        return _error("metric_tidak_dikenal", metric_id)

    try:
        if method == "compare_periods":
            return _compare_periods(data, metric)
        return _compare_dimensions(data, metric)
    except Exception as exc:  # noqa: BLE001 - fail-safe ke AI
        return _error("comparison_error", type(exc).__name__)


def register(registry) -> None:
    registry.register("mcp-comparator", handle, SCHEMA)


__all__ = ("SCHEMA", "handle", "register")

