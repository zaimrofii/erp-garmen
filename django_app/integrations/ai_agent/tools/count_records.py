"""Tool `count_records` — hitung baris entity (read-only)."""

from __future__ import annotations

from .base import (
    ENTITIES,
    ToolResult,
    clean_filters,
    date_criteria,
    fn_schema,
    model_for,
)

NAME = "count_records"
ALL_ROLES = frozenset({"ADMIN", "INVENTORY", "OPERATOR", "OWNER", "PURCHASING", "QC", "SUPERVISOR"})
SCHEMA = fn_schema(
    NAME,
    "Hitung jumlah baris satu entity. Kembalikan {count, row_count}."
    " Isi date_from/date_to bila pertanyaan berperiode (mis. 'minggu ini')."
    " Untuk pertanyaan 'aktif', WAJIB kirim filters {\"is_active\": true}."
    " Untuk entity=customer: pelanggan = {\"is_customer\": true}.",
    {
        "entity": {"type": "string", "enum": list(ENTITIES)},
        "filters": {
            "type": "object",
            "description": "Filter field entity, mis. {\"is_active\": true} atau"
            " {\"is_customer\": true, \"is_active\": true}.",
        },
        "date_from": {"type": "string", "description": "ISO date (YYYY-MM-DD), inklusif."},
        "date_to": {"type": "string", "description": "ISO date (YYYY-MM-DD), inklusif."},
    },
    ["entity"],
)


def run(
    entity: str,
    filters: dict | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> ToolResult:
    model = model_for(entity)
    criteria = clean_filters(entity, filters)
    criteria.update(date_criteria(entity, date_from, date_to))
    total = model.objects.filter(**criteria).count()
    return ToolResult.success(
        {"count": total},
        row_count=1,
        filters_applied={"filters": criteria},
    )


__all__ = ("ALL_ROLES", "NAME", "SCHEMA", "run")
