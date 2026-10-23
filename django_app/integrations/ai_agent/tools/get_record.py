"""Tool `get_record` — satu baris entity + relasi opsional (read-only)."""

from __future__ import annotations

from .base import (
    ENTITIES,
    INVALID_ARGUMENT,
    NO_DATA,
    ToolResult,
    fn_schema,
    order_derived,
    repo_for,
)

NAME = "get_record"
ALL_ROLES = frozenset({"ADMIN", "INVENTORY", "OPERATOR", "OWNER", "PURCHASING", "QC", "SUPERVISOR"})
INCLUDES = ("lines", "customer", "bundles", "work_orders")
SCHEMA = fn_schema(
    NAME,
    "Ambil satu baris entity berdasarkan id atau kode. `include` menambah relasi:"
    " lines/customer (order), bundles (order/work_order), work_orders (order).",
    {
        "entity": {"type": "string", "enum": list(ENTITIES)},
        "id_or_code": {"type": "string"},
        "include": {"type": "array", "items": {"type": "string", "enum": list(INCLUDES)}},
    },
    ["entity", "id_or_code"],
)


def run(entity: str, id_or_code: str, include: list[str] | None = None) -> ToolResult:
    entity_key = str(entity or "").strip().lower()
    repo = repo_for(entity_key)
    raw = str(id_or_code or "").strip()
    if not raw:
        return ToolResult.failure(INVALID_ARGUMENT, "id_or_code wajib diisi")

    record = repo.get_by_id(int(raw)) if raw.isdigit() else None
    if record is None:
        found = repo.get_list(filters={"code": raw}, limit=1)
        record = found[0] if found else None
    if record is None:
        return ToolResult.failure(NO_DATA, f"record {entity_key} {raw!r} tidak ditemukan")

    include = include or []
    if "lines" in include and entity_key == "order":
        from apps_industry.garment.models import OrderLine

        record["lines"] = list(
            OrderLine.objects.filter(order_id=record["id"]).values(
                "id", "product_id", "product__name", "qty", "price_unit"
            )
        )
    if "customer" in include and entity_key == "order":
        from master.models import Partner

        record["customer"] = (
            Partner.objects.filter(orders__id=record["id"]).values("id", "code", "name").first()
        )
    if "bundles" in include:
        from apps_industry.garment.models import Bundle

        if entity_key == "order":
            queryset = Bundle.objects.filter(work_order__order_line__order_id=record["id"])
        elif entity_key == "work_order":
            queryset = Bundle.objects.filter(work_order_id=record["id"])
        else:
            queryset = Bundle.objects.none()
        record["bundles"] = list(
            queryset.values("id", "code", "state", "qty", "qty_done", "current_work_center__code")[:50]
        )
    if "work_orders" in include and entity_key == "order":
        from apps_industry.garment.models import WorkOrder

        record["work_orders"] = list(
            WorkOrder.objects.filter(order_line__order_id=record["id"]).values(
                "id", "code", "state", "qty_planned", "qty_done"
            )[:50]
        )
    if entity_key == "order":
        order_derived(record)
    return ToolResult.success(
        {"record": record},
        row_count=1,
        filters_applied={"entity": entity_key, "include": include},
    )


__all__ = ("ALL_ROLES", "INCLUDES", "NAME", "SCHEMA", "run")
