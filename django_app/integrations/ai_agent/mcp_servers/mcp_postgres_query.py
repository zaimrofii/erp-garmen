"""MCP `postgres-query` (D.3) — READ-ONLY, allowlist tabel/kolom, ORM parameterized."""

from __future__ import annotations

import re
from typing import Any

from django.apps import apps as django_apps

#: tabel → (app_label, model_name, kolom yang boleh dibaca)
ALLOWLIST: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "garment_order": (
        "garment",
        "Order",
        ("id", "code", "customer_id", "state", "created_at", "deadline"),
    ),
    "garment_workorder": (
        "garment",
        "WorkOrder",
        (
            "id",
            "code",
            "order_line_id",
            "qty_planned",
            "qty_done",
            "state",
            "created_at",
        ),
    ),
    "garment_bundle": (
        "garment",
        "Bundle",
        (
            "id",
            "code",
            "work_order_id",
            "qty",
            "qty_done",
            "state",
            "size",
            "created_at",
        ),
    ),
    "erp_sync_syncrecord": (
        "erp_sync",
        "SyncRecord",
        ("id", "resource", "status", "created_at"),
    ),
    # Sprint H T1.1 — master & produksi (kolom aman, tanpa notes/gambar/PII).
    "master_product": (
        "master",
        "Product",
        (
            "id",
            "code",
            "name",
            "category",
            "sale_price",
            "cost_price",
            "is_active",
            "uom_id",
            "odoo_id",
        ),
    ),
    "master_partner": (
        "master",
        "Partner",
        ("id", "code", "name", "is_customer", "is_vendor", "city", "email", "odoo_id"),
    ),
    # OrderLine tidak punya field `state` di model; `tag` adalah state routing.
    "garment_orderline": (
        "garment",
        "OrderLine",
        ("id", "order_id", "product_id", "qty", "price_unit", "tag"),
    ),
    # ScrapAccumulator tidak punya product_id; scrap terkait bundle/work center.
    "garment_scrapaccumulator": (
        "garment",
        "ScrapAccumulator",
        (
            "id",
            "bundle_id",
            "work_center_id",
            "qty",
            "rework_qty",
            "end_loss_qty",
            "created_at",
        ),
    ),
    # Key mengikuti brief; model sebenarnya ber-app-label garment.
    "master_workcenter": (
        "garment",
        "WorkCenter",
        ("id", "code", "name", "wc_type", "capacity_per_hour"),
    ),
    "master_productionline": (
        "garment",
        "ProductionLine",
        ("id", "code", "name", "capability_tags"),
    ),
}

MAX_LIMIT = 100
_DANGEROUS = re.compile(r"(insert|update|delete|drop|alter|truncate|;|--|/\*)", re.I)
_PRIMITIVES = (str, int, float, bool, type(None))

SCHEMA = {
    "query": {"table": "str", "columns": "list[str]", "filters": "dict", "limit": "int"}
}


def _error(message: str, status: int = 400) -> dict[str, Any]:
    return {"ok": False, "error": message, "status": status}


def _unsafe(value: Any) -> bool:
    if isinstance(value, str):
        return bool(_DANGEROUS.search(value))
    if isinstance(value, (list, tuple)):
        return any(_unsafe(item) for item in value)
    if isinstance(value, dict):
        return any(_unsafe(key) or _unsafe(item) for key, item in value.items())
    return False


def handle(params: dict, user=None) -> dict[str, Any]:
    """Handler `mcp-postgres-query` (parameterized lewat ORM + allowlist)."""
    del user

    table = params.get("table")
    if not isinstance(table, str) or table not in ALLOWLIST:
        return _error("table_not_allowed")

    columns = params.get("columns") or list(ALLOWLIST[table][2])
    allowed = set(ALLOWLIST[table][2])
    if not isinstance(columns, list) or not set(columns).issubset(allowed):
        return _error("columns_not_allowed")

    filters = params.get("filters") or {}
    if not isinstance(filters, dict) or not set(filters).issubset(allowed):
        return _error("filters_not_allowed")
    if any(not isinstance(value, _PRIMITIVES) for value in filters.values()):
        return _error("filter_value_invalid")

    if _unsafe(table) or _unsafe(columns) or _unsafe(filters):
        return _error("unsafe_input")

    limit = params.get("limit", MAX_LIMIT)
    if not isinstance(limit, int) or limit <= 0:
        return _error("limit_invalid")
    limit = min(limit, MAX_LIMIT)

    model = django_apps.get_model(ALLOWLIST[table][0], ALLOWLIST[table][1])
    rows = list(model.objects.filter(**filters).values(*columns)[:limit])

    return {"ok": True, "rows": rows, "count": len(rows), "limit": limit}


def register(registry) -> None:
    registry.register("mcp-postgres-query", handle, SCHEMA)

