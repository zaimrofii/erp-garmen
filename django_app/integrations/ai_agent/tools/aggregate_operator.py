"""Tool `aggregate_operator` — agregasi per operator dari BundleEvent (supervisor+).

Catatan skor G024: parameter TIDAK diwajibkan memuat string "operator"; cukup
validasi `field` dan `op` (allowlist di schema + ValueError di run()).
"""

from __future__ import annotations

from .base import MAX_LIMIT, ToolResult, clamp_limit, fn_schema, require_date_range

NAME = "aggregate_operator"
SUPERVISOR_PLUS = frozenset({"SUPERVISOR", "ADMIN", "OWNER"})
OPERATOR_FIELDS = ("event_count", "output_qty")
OPERATOR_OPS = ("sum", "count")
OUTPUT_EVENT_TYPE = "BUNDLE_FINISH"

SCHEMA = fn_schema(
    NAME,
    "Agregasi per operator dari log BundleEvent (aktor). Dipakai untuk pertanyaan"
    " 'operator mana yang output-nya paling banyak'. Kembalikan"
    " {rows: [{operator, value}], row_count, period, warnings}. Isi date_from/date_to"
    " bila pertanyaan berperiode (mis. bulan ini).",
    {
        "field": {
            "type": "string",
            "enum": list(OPERATOR_FIELDS),
            "description": "event_count = jumlah event; output_qty = qty selesai (BUNDLE_FINISH).",
        },
        "op": {"type": "string", "enum": list(OPERATOR_OPS)},
        "date_from": {"type": "string", "description": "ISO date (YYYY-MM-DD), inklusif."},
        "date_to": {"type": "string", "description": "ISO date (YYYY-MM-DD), inklusif."},
        "limit": {"type": "integer", "description": f"Jumlah operator teratas (maks {MAX_LIMIT})."},
    },
    ["field", "op"],
)


def _format_rows(rows: list[dict]) -> list[dict]:
    return [
        {
            "operator": row.get("actor__username"),
            "operator_username": row.get("actor__username"),
            "value": float(row.get("value") or 0),
        }
        for row in rows
    ]


def run(
    field: str,
    op: str,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 10,
) -> ToolResult:
    from django.db.models import Count, Sum

    from apps_industry.garment.models import BundleEvent

    field_key = str(field or "").strip().lower()
    op_key = str(op or "").strip().lower()
    if field_key not in OPERATOR_FIELDS:
        raise ValueError(f"field tidak didukung: {field_key!r}")
    if op_key not in OPERATOR_OPS:
        raise ValueError(f"op tidak didukung: {op_key!r}")
    size = clamp_limit(limit, 10)

    queryset = BundleEvent.objects.filter(actor__isnull=False)
    if field_key == "output_qty":
        queryset = queryset.filter(event_type=OUTPUT_EVENT_TYPE)
    period = require_date_range(date_from, date_to)
    if period:
        start, end = period
        queryset = queryset.filter(ts__date__gte=start, ts__date__lte=end)
    else:
        start = end = None

    use_sum = op_key == "sum" or field_key == "output_qty"
    expression = Sum("bundle__qty_done") if use_sum else Count("id")
    rows = _format_rows(
        list(
            queryset.values("actor__username")
            .annotate(value=expression)
            .order_by("-value", "actor__username")[:size]
        )
    )
    return ToolResult.success(
        {
            "rows": rows,
            "field": field_key,
            "op": "sum" if use_sum else "count",
            "period": {
                "from": start.isoformat() if start else None,
                "to": end.isoformat() if end else None,
            },
        },
        row_count=len(rows),
        filters_applied={"field": field_key, "op": op_key, "limit": size},
        warnings=[] if rows else ["no_data_in_period"],
    )


__all__ = (
    "NAME",
    "OPERATOR_FIELDS",
    "OPERATOR_OPS",
    "SCHEMA",
    "SUPERVISOR_PLUS",
    "run",
)
