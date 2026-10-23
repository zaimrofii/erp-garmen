"""Tool `get_stock` — stok live dari Odoo (read-only)."""

from __future__ import annotations

from .base import ERP_NOT_CONFIGURED, NO_DATA, ToolResult, fn_schema

NAME = "get_stock"
STOCK_ROLES = frozenset({"INVENTORY", "SUPERVISOR", "ADMIN", "OWNER", "PURCHASING"})
SCHEMA = fn_schema(
    NAME,
    "Stok produk dari ERP (Odoo). mode='single' (default) butuh product_code; mode='top_n'"
    " mengembalikan 10 produk dengan stok terbesar {rows: [{product_code, product_name,"
    " quantity, uom}]}.",
    {
        "product_code": {"type": "string", "description": "Kode produk (wajib untuk mode=single)."},
        "location_code": {"type": "string", "description": "Kode/nama lokasi (opsional)."},
        "mode": {"type": "string", "enum": ["single", "top_n"], "description": "Default single."},
        "limit": {"type": "integer", "description": "Jumlah produk untuk mode top_n (default 10)."},
    },
    [],
)


def run(
    product_code: str = "",
    location_code: str | None = None,
    mode: str = "single",
    limit: int = 10,
) -> ToolResult:
    from django.conf import settings

    adapter = str(getattr(settings, "ERP_ADAPTER", "") or "").strip().lower()
    if adapter != "odoo":
        return ToolResult.failure(
            ERP_NOT_CONFIGURED, f"ERP_ADAPTER={adapter or 'kosong'} (butuh 'odoo')"
        )

    mode_key = str(mode or "single").strip().lower()
    if mode_key not in {"single", "top_n"}:
        raise ValueError(f"mode tidak dikenal: {mode!r}")
    if mode_key == "single" and not str(product_code or "").strip():
        raise ValueError("product_code wajib diisi untuk mode=single")

    try:
        from integrations.erp_sync.transport.factory import get_transport

        transport = get_transport()
        if mode_key == "top_n":
            rows = transport.search_read(
                "stock.quant",
                [["location_id.usage", "=", "internal"]],
                ["quantity", "reserved_quantity", "location_id", "product_id"],
                limit=500,
            )
            return _top_n_result(rows, limit)
        domain = [
            ["product_id.default_code", "=", str(product_code).strip()],
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

    code = str(product_code or "").strip()
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
        metadata={
            "metric": "stock_qty",
            "dimension": "product",
            "definition": "stok on-hand (internal) dari Odoo",
            "period": "snapshot",
            "source": "Odoo",
        },
    )
    if not rows:
        result.warnings.append(NO_DATA)
    return result


def _top_n_result(raw_rows: list[dict], limit: int) -> ToolResult:
    """Agregasi stok per produk (Odoo stock.quant), urut qty desc."""
    size = max(1, min(int(limit or 10), 50))
    totals: dict[str, dict] = {}
    for row in raw_rows:
        payload = row.get("product_id") or []
        code = ""
        name = ""
        if isinstance(payload, (list, tuple)) and len(payload) >= 2:
            code, name = str(payload[1] or ""), str(payload[0] or "")
        key = code or name
        if not key:
            continue
        entry = totals.setdefault(
            key,
            {"product_code": code, "product_name": name, "quantity": 0.0, "uom": None},
        )
        entry["quantity"] += float(row.get("quantity") or 0)
    rows = sorted(totals.values(), key=lambda item: item["quantity"], reverse=True)[:size]
    warnings = [] if rows else ["no_quant_found"]
    return ToolResult.success(
        {"rows": rows, "mode": "top_n"},
        row_count=len(rows),
        filters_applied={"mode": "top_n", "limit": size},
        warnings=warnings,
        metadata={
            "metric": "stock_qty",
            "dimension": "product",
            "definition": f"top {size} produk berdasarkan stok on-hand Odoo",
            "period": "snapshot",
            "source": "Odoo",
        },
    )


__all__ = ("NAME", "SCHEMA", "STOCK_ROLES", "run")
