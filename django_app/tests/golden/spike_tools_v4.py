"""Spike validasi v4: 7 tool generik (v3) + 2 tool baru.

Tool 8 `aggregate_operator` — agregasi per operator dari BundleEvent.actor
(menggantikan celah "metrik per operator" yang tidak tersedia di get_metric).
Tool 9 `get_product_orders` — relasi produk -> order line -> order (celah G027).

Throwaway: hanya untuk pengukuran, bukan kode produksi.
"""

from __future__ import annotations

import copy
from datetime import date
from typing import Any

from tests.golden import spike_tools_v3 as _v3

BASE_TOOLS_SCHEMA = _v3.TOOLS_SCHEMA
MAX_LIMIT = _v3.MAX_LIMIT
OPERATOR_FIELDS = ("event_count", "output_qty")
OPERATOR_OPS = ("sum", "count")
OUTPUT_EVENT_TYPE = "BUNDLE_FINISH"


def _extra_schemas() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "aggregate_operator",
                "description": (
                    "Agregasi per operator (dari BundleEvent.actor). Dipakai untuk pertanyaan"
                    " 'operator siapa yang output-nya terbanyak' atau 'berapa event per operator'."
                    " Kembalikan {rows: [{operator, operator_username, value}], row_count, period,"
                    " warnings}."
                    " Isi date_from/date_to bila pertanyaan berperiode (mis. bulan ini)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "field": {
                            "type": "string",
                            "enum": list(OPERATOR_FIELDS),
                            "description": "event_count = jumlah event; output_qty = qty selesai.",
                        },
                        "op": {
                            "type": "string",
                            "enum": list(OPERATOR_OPS),
                            "description": "sum = jumlahkan nilai; count = hitung baris.",
                        },
                        "date_from": {
                            "type": "string",
                            "description": "ISO date (YYYY-MM-DD), inklusif; kosong = all-time.",
                        },
                        "date_to": {
                            "type": "string",
                            "description": "ISO date (YYYY-MM-DD), inklusif.",
                        },
                        "limit": {
                            "type": "integer",
                            "description": f"Jumlah operator teratas (default 10, maks {MAX_LIMIT}).",
                        },
                    },
                    "required": ["field", "op"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_product_orders",
                "description": (
                    "Daftar order yang memuat sebuah produk (Product -> OrderLine -> Order)."
                    " Kembalikan {product, orders: [{code, customer_name, qty, state}],"
                    " row_count, warnings}. Pakai untuk 'order mana saja yang memuat produk X'."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "product_code": {
                            "type": "string",
                            "description": "Kode produk, mis. 'ODOO-65' atau 'KAOS-001'.",
                        },
                        "limit": {
                            "type": "integer",
                            "description": f"Jumlah order maksimum (default 20, maks {MAX_LIMIT}).",
                        },
                    },
                    "required": ["product_code"],
                },
            },
        },
    ]


TOOLS_SCHEMA = copy.deepcopy(BASE_TOOLS_SCHEMA) + _extra_schemas()


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _period(date_from: str | None, date_to: str | None) -> dict:
    start, end = _parse_date(date_from), _parse_date(date_to)
    return {
        "from": start.isoformat() if start else None,
        "to": end.isoformat() if end else None,
    }


def _format_operator_rows(rows: list[dict]) -> list[dict]:
    """Envelope baris: `operator` (dibaca scorer) + alias `operator_username`."""
    return [
        {
            "operator": row.get("actor__username"),
            "operator_username": row.get("actor__username"),
            "value": float(row.get("value") or 0),
        }
        for row in rows
    ]


def aggregate_operator(
    field: str,
    op: str,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 10,
) -> dict:
    from django.db.models import Count, Sum

    from apps_industry.garment.models import BundleEvent

    field = str(field or "").strip().lower()
    op = str(op or "").strip().lower()
    if field not in OPERATOR_FIELDS:
        return {"error": "field_not_supported", "detail": f"field {field!r} tidak didukung"}
    if op not in OPERATOR_OPS:
        return {"error": "op_not_supported", "detail": f"op {op!r} tidak didukung"}

    try:
        size = max(1, min(int(limit or 10), MAX_LIMIT))
    except (TypeError, ValueError):
        size = 10

    period = _period(date_from, date_to)
    qs = BundleEvent.objects.filter(actor__isnull=False)
    if field == "output_qty":
        qs = qs.filter(event_type=OUTPUT_EVENT_TYPE)
    start, end = _parse_date(date_from), _parse_date(date_to)
    if start:
        qs = qs.filter(ts__date__gte=start)
    if end:
        qs = qs.filter(ts__date__lte=end)

    use_sum = op == "sum" or field == "output_qty"
    expression = Sum("bundle__qty_done") if use_sum else Count("id")
    rows = list(
        qs.values("actor__username")
        .annotate(value=expression)
        .order_by("-value", "actor__username")[:size]
    )
    formatted = _format_operator_rows(rows)
    warnings: list[str] = []
    if not formatted:
        warnings.append("no_data_in_period")
    return {
        "rows": formatted,
        "row_count": len(formatted),
        "field": field,
        "op": "sum" if use_sum else "count",
        "period": period,
        "warnings": warnings,
    }


def get_product_orders(product_code: str, limit: int = 20) -> dict:
    from apps_industry.garment.models import OrderLine
    from master.models import Product

    code = str(product_code or "").strip()
    if not code:
        return {"error": "product_code_required", "detail": "product_code wajib diisi"}

    product = Product.objects.filter(code__iexact=code).first()
    if product is None:
        return {
            "product": {"code": code, "name": None},
            "orders": [],
            "row_count": 0,
            "warnings": ["product_not_found"],
        }

    try:
        size = max(1, min(int(limit or 20), MAX_LIMIT))
    except (TypeError, ValueError):
        size = 20

    lines = (
        OrderLine.objects.filter(product=product)
        .select_related("order", "order__customer")
        .order_by("-order__created_at")[:size]
    )
    orders = [
        {
            "code": line.order.code,
            "customer_name": getattr(line.order.customer, "name", None),
            "qty": int(line.qty or 0),
            "state": line.order.state,
        }
        for line in lines
    ]
    return {
        "product": {"code": product.code, "name": product.name},
        "orders": orders,
        "row_count": len(orders),
        "warnings": [] if orders else ["no_order_line_for_product"],
    }


def execute(name: str, arguments: dict[str, Any]) -> dict:
    if name == "aggregate_operator":
        try:
            return {"ok": True, **aggregate_operator(**arguments)}
        except Exception as exc:  # noqa: BLE001 - spike: error = hasil
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    if name == "get_product_orders":
        try:
            return {"ok": True, **get_product_orders(**arguments)}
        except Exception as exc:  # noqa: BLE001 - spike: error = hasil
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return _v3.execute(name, arguments)


def __getattr__(attribute: str) -> Any:
    """Delegasi ke v3 (list_records, get_metric, ...), termasuk helper privat."""
    return getattr(_v3, attribute)


__all__ = (
    "OPERATOR_FIELDS",
    "OPERATOR_OPS",
    "TOOLS_SCHEMA",
    "aggregate_operator",
    "execute",
    "get_product_orders",
)
