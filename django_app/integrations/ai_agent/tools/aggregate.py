"""Tool `aggregate` — agregasi satu field dengan GROUP BY opsional (read-only)."""

from __future__ import annotations

from .base import (
    AGG_ENTITIES,
    DATE_FIELD,
    GROUP_ALIASES,
    MAX_LIMIT,
    OPS,
    ToolResult,
    clean_filters,
    date_criteria,
    fn_schema,
    model_for,
)

NAME = "aggregate"
ALL_ROLES = frozenset({"ADMIN", "INVENTORY", "OPERATOR", "OWNER", "PURCHASING", "QC", "SUPERVISOR"})
SCHEMA = fn_schema(
    NAME,
    "Agregasi satu field (sum/avg/count/min/max/count_distinct), opsional group_by."
    " Kembalikan {rows, row_count, op, field, group_by}. WAJIB isi date_from dan date_to"
    " bila pertanyaan menyebut periode ('minggu ini', 'bulan ini', 'Desember 2025');"
    " tanpa tanggal berarti seluruh periode (all-time).",
    {
        "entity": {"type": "string", "enum": list(AGG_ENTITIES)},
        "field": {"type": "string", "description": "Field numerik, mis. 'qty', 'qty_done'."},
        "op": {"type": "string", "enum": list(OPS)},
        "group_by": {"type": "string", "description": "mis. 'work_center', 'customer', 'state'."},
        "filters": {"type": "object"},
        "date_from": {"type": "string", "description": "ISO date (YYYY-MM-DD), inklusif."},
        "date_to": {"type": "string", "description": "ISO date (YYYY-MM-DD), inklusif."},
    },
    ["entity", "field", "op"],
)


def run(
    entity: str,
    field: str,
    op: str,
    group_by: str | None = None,
    filters: dict | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> ToolResult:
    from django.db.models import Avg, Count, Max, Min, Sum

    entity_key = str(entity or "").strip().lower()
    model = model_for(entity_key)
    # Entity berperiode WAJIB menyertakan rentang tanggal (cegah all-time tak sengaja).
    if entity_key in DATE_FIELD and not (date_from and date_to):
        return ToolResult.failure(
            "missing_date_range",
            "Pertanyaan tentang periode WAJIB menyebutkan date_from dan date_to. Contoh: "
            "'minggu ini' = 2026-10-19 sampai 2026-10-23.",
        )
    op_key = str(op or "").strip().lower()
    if op_key not in OPS:
        raise ValueError(f"op tidak dikenal: {op_key!r}")
    field_name = str(field or "").strip()
    if "__" in field_name or field_name not in {f.name for f in model._meta.fields}:
        raise ValueError(f"field tidak valid untuk {entity_key}: {field_name!r}")

    criteria = clean_filters(entity_key, filters)
    criteria.update(date_criteria(entity_key, date_from, date_to))
    queryset = model.objects.filter(**criteria)

    alias = f"{op_key}_{field_name}"
    if op_key == "count_distinct":
        expression = Count(field_name, distinct=True)
    elif op_key == "count":
        expression = Count("id")
    else:
        expression = {"sum": Sum, "avg": Avg, "min": Min, "max": Max}[op_key](field_name)

    if group_by:
        path = GROUP_ALIASES.get(entity_key, {}).get(str(group_by), str(group_by))
        rows = list(
            queryset.values(path).annotate(**{alias: expression}).order_by(f"-{alias}")[:MAX_LIMIT]
        )
    else:
        rows = [queryset.aggregate(**{alias: expression})]
    return ToolResult.success(
        {"rows": rows, "op": op_key, "field": field_name, "group_by": group_by},
        row_count=len(rows),
        truncated=len(rows) >= MAX_LIMIT,
        filters_applied={"filters": criteria, "group_by": group_by},
        warnings=[] if rows else ["no_rows"],
    )


__all__ = ("ALL_ROLES", "NAME", "SCHEMA", "run")
