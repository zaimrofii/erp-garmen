"""MCP `odoo-rpc` (H T1.2) — READ-ONLY query Odoo lewat OdooTransport."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from integrations.erp_sync.client import get_odoo_rpc_client
from integrations.erp_sync.transport.odoo_transport import (
    PARTNER_FIELDS,
    PRODUCT_FIELDS,
    PURCHASE_ORDER_FIELDS,
    SALE_ORDER_FIELDS,
    STOCK_QUANT_FIELDS,
    OdooTransport,
)

from ..config import AI_CONFIG

ALLOWED_ROLES = {"SUPERVISOR", "OWNER", "ADMIN"}
MAX_ROWS = 20
INVOICE_FIELDS = [
    "id",
    "name",
    "partner_id",
    "invoice_date",
    "state",
    "payment_state",
    "move_type",
    "amount_total",
    "currency_id",
]
STOCK_MOVE_FIELDS = [
    "id",
    "name",
    "product_id",
    "location_id",
    "location_dest_id",
    "quantity",
    "state",
    "date",
]
SCHEMA = {
    "get_stock": {"product_odoo_id": "int", "location_id": "int?"},
    "get_invoice": {"invoice_odoo_id": "int"},
    "get_purchase_order": {"purchase_order_odoo_id": "int"},
    "get_sale_order": {"sale_order_odoo_id": "int"},
    "get_product_info": {"product_odoo_id": "int"},
    "get_partner_info": {"partner_odoo_id": "int"},
    "list_recent_moves": {"limit": "int?"},
}
_VALID_METHODS = set(SCHEMA)


def _role_code(user) -> str:
    role = getattr(user, "role", None)
    return str(getattr(role, "code", "") or "").strip().upper()


def _error(error: str, detail: str = "") -> dict[str, Any]:
    return {"ok": False, "error": error, "detail": detail}


def _limit(value: Any = None) -> int:
    try:
        requested = int(value or MAX_ROWS)
    except (TypeError, ValueError):
        requested = MAX_ROWS
    return max(1, min(requested, MAX_ROWS))


def _oid(params: dict, key: str) -> int | None:
    value = params.get(key)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _make_transport():
    """Bangun transport Odoo (timeout AI_CONFIG) — bisa di-patch di test."""
    timeout = float(AI_CONFIG.get("mcp", {}).get("timeout_seconds", 5))
    client = get_odoo_rpc_client(timeout=timeout)
    return OdooTransport(client), client


def _ok(method: str, rows: list) -> dict[str, Any]:
    data = list(rows or [])[:MAX_ROWS]
    return {"ok": True, "method": method, "data": data, "count": len(data)}


def handle(method: str, params: dict | None = None, user=None) -> dict[str, Any]:
    """Handler `mcp-odoo-rpc`; read-only dan fail-safe."""
    data = params or {}

    if _role_code(user) not in ALLOWED_ROLES:
        return _error("forbidden", "Role tidak berhak mengakses Odoo RPC.")

    if method not in _VALID_METHODS:
        return _error("method_tidak_dikenal", str(method))

    if str(getattr(settings, "ERP_ADAPTER", "odoo") or "").strip().lower() == "null":
        return _error("erp_not_configured", "ERP_ADAPTER=null (Odoo tidak aktif).")

    transport = client = None
    try:
        transport, client = _make_transport()
        limit = _limit(data.get("limit"))

        if method == "get_stock":
            product_id = _oid(data, "product_odoo_id")
            if product_id is None:
                return _error("not_found", "product_odoo_id wajib integer.")
            location_id = _oid(data, "location_id")
            if location_id is not None:
                rows = transport.fetch_stock_quants([location_id])
                rows = [
                    row
                    for row in rows
                    if int(row.get("product_id") or 0) == product_id
                ][:MAX_ROWS]
            else:
                rows = transport.search_read(
                    "stock.quant",
                    [("product_id", "=", product_id)],
                    STOCK_QUANT_FIELDS,
                    limit=limit,
                )
            if not rows:
                return _error("not_found", "Stock quant tidak ditemukan.")
            return _ok(method, rows)

        if method == "list_recent_moves":
            rows = transport.search_read(
                "stock.move", [], STOCK_MOVE_FIELDS, limit=limit
            )
            return _ok(method, rows)

        if method == "get_invoice":
            invoice_id = _oid(data, "invoice_odoo_id")
            if invoice_id is None:
                return _error("not_found", "invoice_odoo_id wajib integer.")
            rows = transport.search_read(
                "account.move",
                [("id", "=", invoice_id)],
                INVOICE_FIELDS,
                limit=1,
            )
            return _ok(method, rows) if rows else _error("not_found")

        if method == "get_purchase_order":
            po_id = _oid(data, "purchase_order_odoo_id")
            if po_id is None:
                return _error("not_found", "purchase_order_odoo_id wajib integer.")
            rows = transport.search_read(
                "purchase.order",
                [("id", "=", po_id)],
                PURCHASE_ORDER_FIELDS,
                limit=1,
            )
            return _ok(method, rows) if rows else _error("not_found")

        if method == "get_sale_order":
            so_id = _oid(data, "sale_order_odoo_id")
            if so_id is None:
                return _error("not_found", "sale_order_odoo_id wajib integer.")
            rows = transport.search_read(
                "sale.order",
                [("id", "=", so_id)],
                SALE_ORDER_FIELDS,
                limit=1,
            )
            return _ok(method, rows) if rows else _error("not_found")

        if method == "get_product_info":
            product_id = _oid(data, "product_odoo_id")
            if product_id is None:
                return _error("not_found", "product_odoo_id wajib integer.")
            rows = transport.search_read(
                "product.product",
                [("id", "=", product_id)],
                PRODUCT_FIELDS,
                limit=1,
            )
            return _ok(method, rows) if rows else _error("not_found")

        if method == "get_partner_info":
            partner_id = _oid(data, "partner_odoo_id")
            if partner_id is None:
                return _error("not_found", "partner_odoo_id wajib integer.")
            rows = transport.search_read(
                "res.partner",
                [("id", "=", partner_id)],
                PARTNER_FIELDS,
                limit=1,
            )
            return _ok(method, rows) if rows else _error("not_found")

        return _error("method_tidak_dikenal", str(method))
    except ImproperlyConfigured as exc:
        return _error("odoo_unavailable", str(exc)[:200])
    except Exception as exc:  # noqa: BLE001 - fail-safe ke API
        return _error("odoo_unavailable", type(exc).__name__)
    finally:
        if client is not None and hasattr(client, "close"):
            try:
                client.close()
            except Exception:  # pragma: no cover - close best-effort
                pass


def register(registry) -> None:
    registry.register("mcp-odoo-rpc", handle, SCHEMA)


__all__ = ("SCHEMA", "handle", "register")

