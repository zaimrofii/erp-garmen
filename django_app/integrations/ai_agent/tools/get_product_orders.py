"""Tool `get_product_orders` — relasi produk → order line → order (read-only)."""

from __future__ import annotations

from .base import NO_DATA, ToolResult, clamp_limit, fn_schema

NAME = "get_product_orders"
ALL_ROLES = frozenset({"ADMIN", "INVENTORY", "OPERATOR", "OWNER", "PURCHASING", "QC", "SUPERVISOR"})
SCHEMA = fn_schema(
    NAME,
    "Daftar order yang memuat sebuah produk (Product -> OrderLine -> Order)."
    " Kembalikan {product, orders: [{code, customer_name, qty, state}], row_count}.",
    {
        "product_code": {"type": "string", "description": "Kode produk, mis. 'ODOO-65'."},
        "limit": {"type": "integer", "description": "Jumlah order maksimum (default 20)."},
    },
    ["product_code"],
)


def run(product_code: str, limit: int = 20) -> ToolResult:
    from apps_industry.garment.models import OrderLine
    from master.models import Product

    code = str(product_code or "").strip()
    if not code:
        raise ValueError("product_code wajib diisi")
    size = clamp_limit(limit, 20)

    product = Product.objects.filter(code__iexact=code).first()
    if product is None:
        return ToolResult.failure(NO_DATA, f"produk {code!r} tidak ditemukan")

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
    return ToolResult.success(
        {"product": {"code": product.code, "name": product.name}, "orders": orders},
        row_count=len(orders),
        filters_applied={"product_code": code, "limit": size},
        warnings=[] if orders else ["no_order_line_for_product"],
    )


__all__ = ("ALL_ROLES", "NAME", "SCHEMA", "run")
