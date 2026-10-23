"""Tool `get_metric` — metrik analytics (read-only, supervisor+)."""

from __future__ import annotations

from .base import METRICS, ToolResult, fn_schema, require_date_range

NAME = "get_metric"
SUPERVISOR_PLUS = frozenset({"SUPERVISOR", "ADMIN", "OWNER"})
SCHEMA = fn_schema(
    NAME,
    "Hitung metrik garment dan kembalikan stats {avg, latest, min, max, count, sum} +"
    " series harian. WAJIB isi range.from dan range.to (YYYY-MM-DD); tanpa itu tool"
    " menolak dengan error missing_date_range. Untuk pertanyaan 'rata-rata' pakai"
    " stats.avg, 'tertinggi' stats.max, 'terendah' stats.min, 'terbaru' stats.latest.",
    {
        "name": {"type": "string", "enum": list(METRICS)},
        "range": {
            "type": "object",
            "properties": {
                "from": {"type": "string", "description": "ISO date (YYYY-MM-DD)."},
                "to": {"type": "string", "description": "ISO date (YYYY-MM-DD)."},
            },
            "required": ["from", "to"],
        },
        "group_by": {"type": "string", "description": "Dimensi metrik, mis. 'work_center'."},
        "filters": {"type": "object"},
    },
    ["name", "range"],
)


def run(
    name: str,
    range: dict | None = None,
    group_by: str | None = None,
    filters: dict | None = None,
) -> ToolResult:
    from integrations.analytics.core import registry as analytics_registry

    if name not in METRICS:
        raise ValueError(f"metrik tidak terdaftar: {name!r}")
    if str(group_by or "").strip().lower() == "operator":
        raise ValueError("tidak ada dimensi operator di registry; pakai aggregate_operator")
    if not isinstance(range, dict) or not range.get("from") or not range.get("to"):
        return ToolResult.failure(
            "missing_date_range",
            "Pertanyaan ini butuh rentang tanggal. Tolong sebutkan periode: "
            "'minggu ini', 'bulan ini', atau tanggal spesifik (YYYY-MM-DD).",
        )
    start, end = require_date_range(range["from"], range["to"])

    metric = analytics_registry.get_metric(name)
    dimensions = list(getattr(metric, "dimensions", []) or [])
    requested = str(group_by or "period")
    chosen = requested if requested in dimensions else "period"
    series = metric.compute(
        {
            "group_by": chosen,
            "granularity": "day",
            "date_from": start,
            "date_to": end,
            **(filters or {}),
        }
    )[:100]

    values = [float(row["value"]) for row in series if isinstance(row.get("value"), (int, float))]
    warnings = [] if values else ["no_data_in_period"]
    stats = {
        "avg": round(sum(values) / len(values), 6) if values else None,
        "latest": values[-1] if values else None,
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "count": len(values),
        "sum": round(sum(values), 6) if values else 0,
    }
    return ToolResult.success(
        {
            "metric": name,
            "period": {"from": start.isoformat(), "to": end.isoformat()},
            "group_by": chosen,
            "stats": stats,
            "series": series,
            "unit": getattr(metric, "unit", ""),
        },
        row_count=len(series),
        filters_applied={"metric": name, "range": {"from": str(start), "to": str(end)}},
        warnings=warnings,
    )


__all__ = ("NAME", "SCHEMA", "SUPERVISOR_PLUS", "run")
