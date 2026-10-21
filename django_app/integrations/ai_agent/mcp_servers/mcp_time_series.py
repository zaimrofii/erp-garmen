"""MCP `time-series` (H T2.3) — series metrik dari snapshot / compute live."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from integrations.analytics.core import registry
from integrations.analytics.plugins.garment.models import MetricSnapshot

ALLOWED_ROLES = {"SUPERVISOR", "OWNER", "ADMIN"}
VALID_METRICS = {"garment.scrap_rate", "garment.rework_rate", "garment.lead_time"}
VALID_GRANULARITIES = {"hour", "day"}
SCHEMA = {
    "get_metric_series": {
        "metric_id": "str",
        "granularity": "str",
        "period_from": "str?",
        "period_to": "str?",
        "group_by": "str?",
    }
}


def _role_code(user) -> str:
    role = getattr(user, "role", None)
    return str(getattr(role, "code", "") or "").strip().upper()


def _error(error: str, detail: str = "") -> dict[str, Any]:
    return {"ok": False, "error": error, "detail": detail}


def _period(value: Any, fallback):
    if value is None:
        return fallback
    parsed = parse_datetime(str(value))
    return parsed


def _snapshot_series(metric_id, granularity, period_from, period_to, group_by):
    queryset = MetricSnapshot.objects.filter(
        metric_id=metric_id,
        granularity=granularity,
        period_start__gte=period_from,
        period_start__lte=period_to,
    )
    if group_by:
        prefix = "wc:" if group_by == "work_center" else "line:"
        queryset = queryset.filter(dimension_key__startswith=prefix)
    else:
        queryset = queryset.filter(dimension_key="")
    return [
        {
            "period": row.period_start.isoformat(),
            "value": float(row.value) if row.value is not None else None,
            "group": row.dimension_key or None,
        }
        for row in queryset.order_by("period_start")
    ]


def _live_series(metric_id, granularity, period_from, period_to, group_by):
    metric = registry.get_metric(metric_id)
    rows = metric.compute(
        {
            "granularity": granularity,
            "group_by": group_by or "period",
            "date_from": period_from,
            "date_to": period_to,
        }
    )
    return [
        {
            "period": str(row.get("key") or row.get("label") or ""),
            "value": row.get("value"),
            "group": row.get("label") if group_by else None,
        }
        for row in rows
    ]


def handle(method: str, params: dict | None = None, user=None) -> dict[str, Any]:
    """Series metrik read-only; fallback ke compute bila snapshot kosong."""
    if _role_code(user) not in ALLOWED_ROLES:
        return _error("forbidden", "Role tidak berhak mengakses time-series.")
    if method != "get_metric_series":
        return _error("method_tidak_dikenal", str(method))

    data = params or {}
    metric_id = str(data.get("metric_id") or "").strip()
    granularity = str(data.get("granularity") or "day").strip().lower()
    group_by = data.get("group_by")
    if metric_id not in VALID_METRICS:
        return _error("metric_id_tidak_dikenal", metric_id)
    if granularity not in VALID_GRANULARITIES:
        return _error("granularity_invalid", granularity)
    if group_by is not None and group_by not in {"work_center", "line"}:
        return _error("group_by_invalid", str(group_by))

    now = timezone.now()
    period_to = _period(data.get("period_to"), now)
    period_from = _period(data.get("period_from"), now - timedelta(days=30))
    if period_from is None or period_to is None or period_from > period_to:
        return _error("period_invalid", "period_from/period_to tidak valid.")

    try:
        series = _snapshot_series(
            metric_id, granularity, period_from, period_to, group_by
        )
        fallback = False
        if not series:
            series = _live_series(
                metric_id, granularity, period_from, period_to, group_by
            )
            fallback = True
        return {
            "ok": True,
            "method": method,
            "metric_id": metric_id,
            "granularity": granularity,
            "series": series,
            "count": len(series),
            "fallback_live": fallback,
        }
    except Exception as exc:  # noqa: BLE001 - fail-safe ke AI
        return _error("series_error", type(exc).__name__)


def register(registry) -> None:
    registry.register("mcp-time-series", handle, SCHEMA)


__all__ = ("SCHEMA", "handle", "register")
