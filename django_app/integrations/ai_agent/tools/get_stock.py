"""Tool `get_stock` — stok live dari Odoo (read-only)."""

from __future__ import annotations

from .base import ERP_NOT_CONFIGURED, NO_DATA, ToolResult, fn_schema

NAME = "get_stock"
STOCK_ROLES = frozenset({"INVENTORY", "SUPERVISOR", "ADMIN", "OWNER", "PURCHASING"})
SCHEMA = fn_schema(
    NAME,
    "Stok satu produk dari ERP (Odoo). Kembalikan {product_code, product_name, quantity,"
    " reserved, available, uom, location_code, rows}.",
    {
        "product_code": {"type": "string", "description": "Kode produk, mis. 'ODOO-65'."},
        "location_code": {"type": "string", "description": "Kode/nama lokasi (opsional)."},
    },
    ["product_code"],
)


def run(product_code: str, location_code: str | None = None) -> ToolResult:
    from django.conf import settings

    adapter = str(getattr(settings, "ERP_ADAPTER", "") or "").strip().lower()
    if adapter != "odoo":
        return ToolResult.failure(
            ERP_NOT_CONFIGURED, f"ERP_ADAPTER={adapter or 'kosong'} (butuh 'odoo')"
        )

    code = str(product_code or "").strip()
    if not code:
        raise ValueError("product_code wajib diisi")

    try:
        from integrations.erp_sync.transport.factory import get_transport

        transport = get_transport()
        domain = [
            ["product_id.default_code", "=", code],
            ["location_id.usage", "=", "internal"],
        ]
        if location_code:
            domain.append(["location_id.complete_name", "ilike", str(location_code)])
        rows = transport.search_read(
            "stock.quant",
            domain,
            ["quantity", "reserved_quantity", "location_id", "product_id"],
            limit=50,
        )
    except Exception as exc:  # noqa: BLE001 - ERP down = hasil, bukan crash
        return ToolResult.failure(ERP_NOT_CONFIGURED, f"ERP tidak tersedia: {type(exc).__name__}")

    quantity = sum(float(row.get("quantity") or 0) for row in rows)
    reserved = sum(float(row.get("reserved_quantity") or 0) for row in rows)
    from master.models import Product

    product = Product.objects.filter(code__iexact=code).first()
    warnings = [] if rows else ["no_quant_found"]
    result = ToolResult.success(
        {
            "product_code": code,
            "product_name": product.name if product else None,
            "quantity": quantity,
            "reserved": reserved,
            "available": quantity - reserved,
            "uom": getattr(getattr(product, "uom", None), "name", None),
            "location_code": location_code or "internal",
            "rows": rows[:10],
        },
        row_count=len(rows),
        filters_applied={"product_code": code, "location_code": location_code},
        warnings=warnings,
    )
    if not rows:
        result.warnings.append(NO_DATA)
    return result


__all__ = ("NAME", "SCHEMA", "STOCK_ROLES", "run")
