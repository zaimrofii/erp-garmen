"""Tool `list_records` — daftar baris entity (read-only)."""

from __future__ import annotations

from .base import (
    ENTITIES,
    ToolResult,
    clean_filters,
    clamp_limit,
    date_criteria,
    fn_schema,
    order_derived,
    repo_for,
)

NAME = "list_records"
ALL_ROLES = frozenset({"ADMIN", "INVENTORY", "OPERATOR", "OWNER", "PURCHASING", "QC", "SUPERVISOR"})
SCHEMA = fn_schema(
    NAME,
    "Daftar baris satu entity (order/bundle/produk/customer/work center/work order)."
    " Kembalikan {rows, row_count, truncated}. Untuk entity=order setiap baris memuat"
    " is_late, days_late, days_remaining. Isi date_from/date_to hanya bila pertanyaan"
    " berperiode (minggu ini/bulan ini).",
    {
        "entity": {"type": "string", "enum": list(ENTITIES)},
        "filters": {
            "type": "object",
            "description": "Filter field entity, mis. {\"state\": \"DONE\"} atau"
            " {\"current_work_center__code\": \"SEWING-2\"}.",
        },
        "sort": {"type": "string", "description": "Urutan Django, mis. '-created_at'."},
        "limit": {"type": "integer", "description": "Maks baris (default 20, maks 100)."},
        "date_from": {"type": "string", "description": "ISO date (YYYY-MM-DD), inklusif."},
        "date_to": {"type": "string", "description": "ISO date (YYYY-MM-DD), inklusif."},
    },
    ["entity"],
)


def run(
    entity: str,
    filters: dict | None = None,
    sort: str = "",
    limit: int = 20,
    date_from: str | None = None,
    date_to: str | None = None,
) -> ToolResult:
    repo = repo_for(entity)
    size = clamp_limit(limit, 20)
    criteria = clean_filters(entity, filters)
    criteria.update(date_criteria(entity, date_from, date_to))
    queryset = repo.model.objects.filter(**criteria)
    queryset = queryset.order_by(str(sort)) if sort else queryset.order_by(*repo.order_by)
    rows = [repo._serialize(obj) for obj in queryset[:size]]
    if str(entity).strip().lower() == "order":
        rows = [order_derived(row) for row in rows]
    result = ToolResult.success(
        {"rows": rows},
        row_count=len(rows),
        truncated=len(rows) >= size,
        filters_applied={"filters": criteria, "sort": sort, "limit": size},
    )
    if not rows:
        result.warnings.append("no_rows")
    return result


__all__ = ("ALL_ROLES", "NAME", "SCHEMA", "run")
