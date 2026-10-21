"""MCP `analytics` (D.4) — WAJIB lewat service layer, bukan DB/HTTP.

Kontrak: docs/ai/MCP-REGISTRY.md §4.
"""

from __future__ import annotations

from typing import Any

from integrations.analytics.core import registry as analytics_registry
from integrations.analytics.services import analytics_config_services

MAX_ROWS = 50
ALLOWED_ROLES = {"SUPERVISOR", "OWNER", "ADMIN"}
VALID_DIMENSIONS = {"period", "work_center", "line"}

SCHEMA = {
    "get_metric": {"metric_id": "str", "dimension": "str"},
    "list_metrics": {"domain": "str"},
}


def _role_code(user) -> str:
    role = getattr(user, "role", None)
    return str(getattr(role, "code", "") or "").strip().upper()


def handle_request(method: str, params: dict | None = None, user=None) -> dict[str, Any]:
    """Handler `mcp-analytics` (service layer + role check)."""
    data = params or {}

    # KUNCI: WAJIB service layer (bukan AnalyticsConfig.objects / HTTP).
    config = analytics_config_services.get_config()
    if not config.enabled:
        return {
            "ok": False,
            "error": "analytics_disabled",
            "reason": "analytics_disabled",
        }

    if _role_code(user) not in ALLOWED_ROLES:
        return {"ok": False, "error": "forbidden"}

    if method == "list_metrics":
        domain = str(data.get("domain") or "garment")
        metrics = analytics_registry.list_metrics(domain)
        return {
            "ok": True,
            "metrics": [
                {
                    "metric_id": metric.metric_id,
                    "label": metric.label,
                    "unit": metric.unit,
                    "enabled": True,
                }
                for metric in metrics
            ],
        }

    if method == "get_metric":
        metric_id = str(data.get("metric_id") or "")
        try:
            metric = analytics_registry.get_metric(metric_id)
        except KeyError:
            return {"ok": False, "error": "metric_tidak_dikenal"}

        dimension = str(data.get("dimension") or "period")
        group_by = dimension if dimension in VALID_DIMENSIONS else "period"
        rows = metric.compute({"group_by": group_by, "granularity": "day"})
        truncated = len(rows) > MAX_ROWS

        return {
            "ok": True,
            "metric_id": metric.metric_id,
            "unit": metric.unit,
            "rows": rows[:MAX_ROWS],
            "truncated": truncated,
            "enabled": True,
        }

    return {"ok": False, "error": "method_tidak_dikenal"}


def register(registry) -> None:
    registry.register("mcp-analytics", handle_request, SCHEMA)

