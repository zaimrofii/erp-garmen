"""Spike-2: TUJUH tool generik throwaway (bukan kode produksi).

Semua read-only, di atas DAL (`data_access.registry`) dan analytics registry yang
sudah ada. Tidak ada perubahan pada `src/`, `api/`, `orchestrator/`, atau
`data_access/`. File ini hanya untuk pengukuran.
"""

from __future__ import annotations

from datetime import date
from typing import Any

MAX_LIMIT = 100

ENTITIES = ("product", "order", "customer", "bundle", "work_center", "work_order")
AGG_ENTITIES = ENTITIES + ("scrap", "orderline")

#: Prefix field yang boleh dipakai filter (lookup `__gt`, `__in`, dst ikut).
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
    "scrap": {"id", "qty", "rework_qty", "end_loss_qty", "work_center__code", "bundle__state", "created_at"},
    "orderline": {"id", "order__code", "product_id", "product__name", "qty", "price_unit"},
}

#: Alias group_by yang dipakai LLM → path field Django.
GROUP_ALIASES: dict[str, dict[str, str]] = {
    "scrap": {"work_center": "work_center__code", "bundle": "bundle__code", "state": "bundle__state"},
    "order": {"customer": "customer__name", "state": "state"},
    "orderline": {"product": "product__name", "order": "order__code"},
    "product": {"category": "category"},
    "bundle": {
        "work_center": "current_work_center__code",
        "state": "state",
        "product": "work_order__order_line__product__name",
    },
    "work_order": {"state": "state"},
    "customer": {"city": "city"},
    "work_center": {"type": "wc_type"},
}

OPS = ("sum", "avg", "count", "min", "max", "count_distinct")
METRICS = (
    "garment.bottleneck",
    "garment.buffer_status",
    "garment.lead_time",
    "garment.line_balance",
    "garment.oee",
    "garment.rework_rate",
    "garment.scrap_rate",
    "garment.wc_idle_status",
    "garment.wip_flow",
)


def _repo(entity: str):
    from integrations.ai_agent.data_access.registry import get_repo

    entity = str(entity or "").strip().lower()
    if entity not in ENTITIES:
        raise ValueError(f"entity tidak diizinkan: {entity!r}")
    repo = get_repo(entity)
    if repo is None:
        raise ValueError(f"repository tidak ditemukan: {entity!r}")
    return repo


def _model(entity: str):
    """Model Django untuk entity (termasuk yang tidak punya repository)."""
    from apps_industry.garment.models import (
        Bundle,
        Order,
        OrderLine,
        ScrapAccumulator,
        WorkCenter,
        WorkOrder,
    )
    from master.models import Partner, Product

    mapping = {
        "product": Product,
        "order": Order,
        "customer": Partner,
        "bundle": Bundle,
        "work_center": WorkCenter,
        "work_order": WorkOrder,
        "scrap": ScrapAccumulator,
        "orderline": OrderLine,
    }
    key = str(entity or "").strip().lower()
    if key not in mapping:
        raise ValueError(f"entity tidak diizinkan: {entity!r}")
    return mapping[key]


def _clean_filters(entity: str, filters: Any) -> dict:
    if not filters:
        return {}
    if not isinstance(filters, dict):
        raise ValueError("filters harus object")
    allowed = FILTERABLE[entity]
    cleaned = {}
    for key, value in filters.items():
        key = str(key)
        if not any(key == item or key.startswith(f"{item}__") for item in allowed):
            raise ValueError(f"filter tidak diizinkan untuk {entity}: {key!r}")
        cleaned[key] = value
    return cleaned


def list_records(entity: str, filters: dict | None = None, sort: str = "", limit: int = 20) -> dict:
    repo = _repo(entity)
    limit = max(1, min(int(limit or 20), MAX_LIMIT))
    qs = repo.model.objects.filter(**_clean_filters(entity, filters))
    qs = qs.order_by(str(sort)) if sort else qs.order_by(*repo.order_by)
    rows = [repo._serialize(obj) for obj in qs[:limit]]
    return {"rows": rows, "row_count": len(rows), "truncated": len(rows) >= limit}


def count_records(entity: str, filters: dict | None = None) -> dict:
    model = _model(entity)
    total = model.objects.filter(**_clean_filters(entity, filters)).count()
    return {"count": total, "rows": [{"count": total}], "row_count": total, "truncated": False}


def get_record(entity: str, id_or_code: str, include: list[str] | None = None) -> dict:
    entity = str(entity or "").strip().lower()
    repo = _repo(entity)
    raw = str(id_or_code)
    record = None
    if raw.isdigit():
        record = repo.get_by_id(int(raw))
    if record is None:
        record = repo.get_list(filters={"code": raw}, limit=1)
        record = record[0] if record else None
    if record is None:
        return {"error": "not_found", "record": None}

    include = include or []
    if "lines" in include and entity == "order":
        from apps_industry.garment.models import OrderLine

        record["lines"] = list(
            OrderLine.objects.filter(order_id=record["id"]).values(
                "id", "product_id", "product__name", "qty", "price_unit"
            )
        )
    if "customer" in include and entity == "order":
        from master.models import Partner

        record["customer"] = (
            Partner.objects.filter(orders__id=record["id"])
            .values("id", "code", "name")
            .first()
        )
    if "bundles" in include:
        from apps_industry.garment.models import Bundle

        if entity == "order":
            qs = Bundle.objects.filter(work_order__order_line__order_id=record["id"])
        elif entity == "work_order":
            qs = Bundle.objects.filter(work_order_id=record["id"])
        else:
            qs = Bundle.objects.none()
        record["bundles"] = list(
            qs.values("id", "code", "state", "qty", "qty_done", "current_work_center__code")[:50]
        )
    if "work_orders" in include and entity == "order":
        from apps_industry.garment.models import WorkOrder

        record["work_orders"] = list(
            WorkOrder.objects.filter(order_line__order_id=record["id"]).values(
                "id", "code", "state", "qty_planned", "qty_done"
            )[:50]
        )
    return {"record": record, "row_count": 1}


def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    """Bangun satu deklarasi function-calling (format OpenAI-compatible)."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


TOOLS_SCHEMA: list[dict] = [
    _fn(
        "list_records",
        "Ambil baris data mentah (read-only). Untuk daftar/detail/ranking sederhana.",
        {
            "entity": {"type": "string", "enum": list(ENTITIES)},
            "filters": {
                "type": "object",
                "description": (
                    "Filter field — product: is_active,sale_price,category,name; "
                    "order: state,created_at,deadline; customer: name,city,is_customer; "
                    "bundle: state,current_work_center__code,qty,qty_done; "
                    "work_center: code,name; work_order: state. Lookup __gt/__lt/__in boleh."
                ),
            },
            "sort": {"type": "string", "description": "Contoh: -sale_price, -created_at, deadline"},
            "limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIMIT},
        },
        ["entity"],
    ),
    _fn(
        "count_records",
        "Hitung jumlah baris yang cocok filter (read-only).",
        {
            "entity": {"type": "string", "enum": list(ENTITIES)},
            "filters": {"type": "object"},
        },
        ["entity"],
    ),
    _fn(
        "get_record",
        "Ambil satu record berdasarkan id atau kode (read-only).",
        {
            "entity": {"type": "string", "enum": list(ENTITIES)},
            "id_or_code": {"type": "string", "description": "ID numerik atau kode, mis. 'S00004'"},
            "include": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Relasi tambahan: lines, customer, bundles, work_orders",
            },
        },
        ["entity", "id_or_code"],
    ),
    _fn(
        "aggregate",
        "Agregasi satu field dengan GROUP BY opsional. Contoh: sum scrap.qty per work_center.",
        {
            "entity": {"type": "string", "enum": list(AGG_ENTITIES)},
            "field": {"type": "string", "description": "Field numerik, mis. qty, sale_price, qty_done"},
            "op": {"type": "string", "enum": list(OPS)},
            "group_by": {
                "type": "string",
                "description": "Dimensi: work_center, customer, product, state, line, category",
            },
            "filters": {"type": "object"},
        },
        ["entity", "field", "op"],
    ),
    _fn(
        "get_metric",
        "Metrik produksi teragregasi per periode (read-only).",
        {
            "name": {"type": "string", "enum": list(METRICS)},
            "range": {
                "type": "object",
                "properties": {
                    "from": {"type": "string", "description": "ISO date, mis. 2026-10-19"},
                    "to": {"type": "string", "description": "ISO date, mis. 2026-10-22"},
                },
                "required": ["from", "to"],
            },
            "group_by": {"type": "string", "enum": ["period", "work_center", "line", "operator"]},
            "filters": {"type": "object"},
        },
        ["name", "range"],
    ),
    _fn(
        "get_stock",
        "Stok produk di gudang dari Odoo (read-only, live).",
        {
            "product_code": {"type": "string", "description": "Kode/default_code produk"},
            "location_code": {"type": "string", "description": "Kode/nama lokasi, opsional"},
        },
        ["product_code"],
    ),
    _fn(
        "find_entity",
        "Cari id record dari nama/kode (mis. 'SEWING-2'). Mengembalikan kandidat.",
        {
            "entity": {"type": "string", "enum": list(ENTITIES)},
            "text": {"type": "string"},
        },
        ["entity", "text"],
    ),
]


def aggregate(
    entity: str,
    field: str,
    op: str,
    group_by: str | None = None,
    filters: dict | None = None,
) -> dict:
    """Agregasi satu field, opsional GROUP BY (read-only)."""
    from django.db.models import Avg, Count, Max, Min, Sum

    entity = str(entity or "").strip().lower()
    model = _model(entity)
    op = str(op or "").strip().lower()
    if op not in OPS:
        raise ValueError(f"op tidak dikenal: {op!r}")
    field = str(field or "").strip()
    if "__" in field or field not in {f.name for f in model._meta.fields}:
        raise ValueError(f"field tidak valid untuk {entity}: {field!r}")

    qs = model.objects.filter(**_clean_filters(entity, filters))
    alias = f"{op}_{field}"
    if op == "count_distinct":
        expression = Count(field, distinct=True)
    elif op == "count":
        expression = Count("id")
    else:
        expression = {"sum": Sum, "avg": Avg, "min": Min, "max": Max}[op](field)

    if group_by:
        path = GROUP_ALIASES.get(entity, {}).get(str(group_by), str(group_by))
        rows = list(qs.values(path).annotate(**{alias: expression}).order_by(f"-{alias}")[:MAX_LIMIT])
    else:
        rows = [qs.aggregate(**{alias: expression})]
    return {
        "rows": rows,
        "row_count": len(rows),
        "op": op,
        "field": field,
        "group_by": group_by,
    }


def get_metric(
    name: str,
    range: dict,
    group_by: str | None = None,
    filters: dict | None = None,
) -> dict:
    """Metrik dari analytics registry (read-only)."""
    from integrations.analytics.core import registry as analytics_registry

    if name not in METRICS:
        return {"error": "metric_not_available", "detail": f"metrik {name!r} tidak terdaftar"}
    if str(group_by or "").lower() == "operator":
        return {
            "error": "metric_not_available",
            "detail": "tidak ada metrik per operator di registry",
        }
    try:
        start = date.fromisoformat(str(range["from"]))
        end = date.fromisoformat(str(range["to"]))
    except (KeyError, TypeError, ValueError):
        raise ValueError("range harus {from: YYYY-MM-DD, to: YYYY-MM-DD}")

    metric = analytics_registry.get_metric(name)
    dims = list(getattr(metric, "dimensions", []) or [])
    requested = str(group_by or "period")
    chosen = requested if requested in dims else "period"
    rows = metric.compute(
        {
            "group_by": chosen,
            "granularity": "day",
            "date_from": start,
            "date_to": end,
            **(filters or {}),
        }
    )[:MAX_LIMIT]
    return {
        "metric": name,
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "group_by": chosen,
        "rows": rows,
        "value": rows[-1].get("value") if rows else None,
        "unit": getattr(metric, "unit", ""),
        "row_count": len(rows),
    }


def get_stock(product_code: str, location_code: str | None = None) -> dict:
    """Stok live dari Odoo (read-only)."""
    from django.conf import settings

    adapter = str(getattr(settings, "ERP_ADAPTER", "") or "").strip().lower()
    if adapter != "odoo":
        return {"error": "erp_not_configured", "detail": f"ERP_ADAPTER={adapter or 'kosong'}"}
    try:
        from integrations.erp_sync.transport.factory import get_transport

        transport = get_transport()
        domain = [
            ["product_id.default_code", "=", str(product_code)],
            ["location_id.usage", "=", "internal"],  # stok gudang, bukan lokasi virtual
        ]
        if location_code:
            domain.append(["location_id.complete_name", "ilike", str(location_code)])
        rows = transport.search_read(
            "stock.quant",
            domain,
            ["quantity", "reserved_quantity", "location_id", "product_id"],
            limit=50,
        )
    except Exception as exc:  # noqa: BLE001 - spike: error = hasil
        return {"error": "erp_unavailable", "detail": f"{type(exc).__name__}: {exc}"}

    quantity = sum(float(row.get("quantity") or 0) for row in rows)
    reserved = sum(float(row.get("reserved_quantity") or 0) for row in rows)
    return {
        "product_code": str(product_code),
        "locations": [row.get("location_id") for row in rows][:10],
        "quantity": quantity,
        "reserved": reserved,
        "available": quantity - reserved,
        "rows": rows[:10],
        "row_count": len(rows),
    }


def find_entity(entity: str, text: str) -> dict:
    """Resolve nama/kode → kandidat id."""
    from django.db.models import Q

    entity = str(entity or "").strip().lower()
    model = _model(entity)
    fields = {f.name for f in model._meta.fields}
    query = Q()
    if "code" in fields:
        query |= Q(code__icontains=str(text))
    if "name" in fields:
        query |= Q(name__icontains=str(text))
    if not query:
        return {"error": "not_found", "candidates": [], "ambiguous": False}
    columns = [name for name in ("id", "code", "name") if name in fields]
    rows = list(model.objects.filter(query).values(*columns)[:10])
    if not rows:
        return {"error": "not_found", "candidates": [], "ambiguous": False}
    return {"candidates": rows, "ambiguous": len(rows) > 1, "row_count": len(rows)}


def execute(name: str, arguments: dict[str, Any]) -> dict:
    """Dispatch tool; error dikembalikan sebagai data, bukan exception."""
    try:
        if name == "list_records":
            return {"ok": True, **list_records(**arguments)}
        if name == "count_records":
            return {"ok": True, **count_records(**arguments)}
        if name == "get_record":
            return {"ok": True, **get_record(**arguments)}
        if name == "aggregate":
            return {"ok": True, **aggregate(**arguments)}
        if name == "get_metric":
            return {"ok": True, **get_metric(**arguments)}
        if name == "get_stock":
            return {"ok": True, **get_stock(**arguments)}
        if name == "find_entity":
            return {"ok": True, **find_entity(**arguments)}
        return {"ok": False, "error": f"tool tidak dikenal: {name}"}
    except Exception as exc:  # noqa: BLE001 - spike: error = hasil pengukuran
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


__all__ = (
    "AGG_ENTITIES",
    "ENTITIES",
    "METRICS",
    "TOOLS_SCHEMA",
    "aggregate",
    "count_records",
    "execute",
    "find_entity",
    "get_metric",
    "get_record",
    "get_stock",
    "list_records",
)
