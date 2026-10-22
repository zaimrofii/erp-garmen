"""Tool THROWAWAY untuk spike function calling (bukan kode produksi).

Tiga tool generik di atas DAL/analytics yang sudah ada:
  * list_records(entity, filters, sort, limit)
  * count_records(entity, filters)
  * get_metric(name, range)

Semua read-only. Entity dibatasi allowlist. Filter divalidasi per entity agar
LLM tidak bisa menyusupkan lookup sembarangan.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

MAX_LIMIT = 50

ENTITIES = ("product", "order", "customer", "bundle", "work_center", "work_order")

#: Prefix field yang boleh dipakai untuk filter (lookup `__gt`, `__in`, dst ikut).
FILTERABLE: dict[str, set[str]] = {
    "product": {"id", "code", "name", "category", "sale_price", "cost_price", "is_active"},
    "order": {"id", "code", "state", "customer_id", "created_at", "deadline", "completed_at"},
    "customer": {"id", "code", "name", "city", "is_customer", "is_vendor", "is_active"},
    "bundle": {
        "id",
        "code",
        "state",
        "qty",
        "qty_done",
        "work_order_id",
        "production_line_id",
        "current_work_center__code",
        "created_at",
    },
    "work_center": {"id", "code", "name", "wc_type", "is_active"},
    "work_order": {"id", "code", "state", "order_line_id", "order_line__order__code"},
}

METRICS = (
    "garment.scrap_rate",
    "garment.rework_rate",
    "garment.lead_time",
    "garment.oee",
    "garment.wip_flow",
)

RANGES = ("today", "this_week", "last_7_days", "this_month")

TOOLS_SCHEMA: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_records",
            "description": (
                "Ambil baris data mentah dari MES (read-only). Gunakan untuk "
                "pertanyaan daftar/detail/ranking sederhana. Filter memakai nama "
                "field Django; boleh lookup seperti sale_price__gt, state__in."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "entity": {"type": "string", "enum": list(ENTITIES)},
                    "filters": {
                        "type": "object",
                        "description": (
                            "Field filter yang boleh — product: is_active, sale_price, category, name, code; "
                            "order: state, created_at, deadline, completed_at, code; "
                            "customer: name, city, is_customer; "
                            "bundle: state, current_work_center__code, qty, qty_done; "
                            "work_center: code, name; work_order: state, order_line__order__code. "
                            "Lookup __gt/__lt/__in diperbolehkan. Contoh: "
                            "{\"state\": \"REWORK\", \"current_work_center__code\": \"SEWING-2\"}"
                        ),
                    },
                    "sort": {
                        "type": "string",
                        "description": "Contoh: -sale_price, -created_at, state, deadline",
                    },
                    "limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIMIT},
                },
                "required": ["entity"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "count_records",
            "description": "Hitung jumlah baris MES yang cocok dengan filter (read-only).",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity": {"type": "string", "enum": list(ENTITIES)},
                    "filters": {"type": "object"},
                },
                "required": ["entity"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_metric",
            "description": (
                "Ambil metrik produksi teragregasi per hari. Metrik tersedia: "
                + ", ".join(METRICS)
                + "."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "enum": list(METRICS)},
                    "range": {"type": "string", "enum": list(RANGES)},
                },
                "required": ["name", "range"],
            },
        },
    },
]


def _repo(entity: str):
    from integrations.ai_agent.data_access.registry import get_repo

    entity = str(entity or "").strip().lower()
    if entity not in ENTITIES:
        raise ValueError(f"entity tidak diizinkan: {entity!r}")
    repo = get_repo(entity)
    if repo is None:
        raise ValueError(f"repository tidak ditemukan: {entity!r}")
    return repo


def _clean_filters(entity: str, filters: Any) -> dict[str, Any]:
    if not filters:
        return {}
    if not isinstance(filters, dict):
        raise ValueError("filters harus object")
    allowed = FILTERABLE[entity]
    cleaned: dict[str, Any] = {}
    for key, value in filters.items():
        key = str(key)
        # Izinkan key persis atau lookup di bawahnya (mis. sale_price__gt,
        # current_work_center__code__in). Path relasi di allowlist memakai "__".
        if not any(key == item or key.startswith(f"{item}__") for item in allowed):
            raise ValueError(f"filter tidak diizinkan untuk {entity}: {key!r}")
        cleaned[key] = value
    return cleaned


def _range_dates(name: str) -> tuple[date, date]:
    today = date.today()
    if name == "today":
        return today, today
    if name == "this_week":
        return today - timedelta(days=today.weekday()), today
    if name == "last_7_days":
        return today - timedelta(days=6), today
    if name == "this_month":
        return today.replace(day=1), today
    raise ValueError(f"range tidak dikenal: {name!r}")


def list_records(entity: str, filters: dict | None = None, sort: str = "", limit: int = 20) -> dict:
    repo = _repo(entity)
    limit = max(1, min(int(limit or 20), MAX_LIMIT))
    qs = repo.model.objects.filter(**_clean_filters(entity, filters))
    qs = qs.order_by(str(sort)) if sort else qs.order_by(*repo.order_by)
    rows = [repo._serialize(obj) for obj in qs[:limit]]
    return {"rows": rows, "row_count": len(rows), "truncated": len(rows) >= limit}


def count_records(entity: str, filters: dict | None = None) -> dict:
    repo = _repo(entity)
    total = repo.model.objects.filter(**_clean_filters(entity, filters)).count()
    return {"rows": [{"count": total}], "row_count": total, "truncated": False}


def get_metric(name: str, range: str = "this_week") -> dict:
    from integrations.analytics.core import registry as analytics_registry

    if name not in METRICS:
        raise ValueError(f"metrik tidak diizinkan: {name!r}")
    start, end = _range_dates(range)
    metric = analytics_registry.get_metric(name)
    rows = metric.compute(
        {
            "group_by": "period",
            "granularity": "day",
            "date_from": start,
            "date_to": end,
        }
    )[:MAX_LIMIT]
    return {"rows": rows, "row_count": len(rows), "truncated": len(rows) >= MAX_LIMIT}


def execute(name: str, arguments: dict[str, Any]) -> dict:
    """Dispatch tool; error dikembalikan sebagai data, bukan exception."""
    try:
        if name == "list_records":
            return {"ok": True, **list_records(**arguments)}
        if name == "count_records":
            return {"ok": True, **count_records(**arguments)}
        if name == "get_metric":
            return {"ok": True, **get_metric(**arguments)}
        return {"ok": False, "error": f"tool tidak dikenal: {name}"}
    except Exception as exc:  # noqa: BLE001 - spike: error = hasil pengukuran
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


__all__ = (
    "ENTITIES",
    "METRICS",
    "TOOLS_SCHEMA",
    "count_records",
    "execute",
    "get_metric",
    "list_records",
)

