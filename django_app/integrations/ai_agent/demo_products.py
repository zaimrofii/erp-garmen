"""Produk demo "Kaos Polos" (Fix #15) — pembeda realistis, idempoten.

Owner/operator butuh pembeda nyata (nama, harga, kategori) saat AI
menanyakan pilihan; produk ODOO-65..69 sebelumnya bernilai 0/kosong.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

#: (kode, nama, kategori, harga jual) — urutan = urutan tampil.
DEMO_POLOS_PRODUCTS = (
    ("ODOO-64", "Kaos Polos Basic", "Kaos", Decimal("40000")),
    ("ODOO-65", "Kaos Polos Cotton Combed 30s", "Kaos", Decimal("50000")),
    ("ODOO-66", "Kaos Polos Premium", "Kaos", Decimal("75000")),
    ("ODOO-67", "Kaos Polos Putih Dewasa V2", "Kaos", Decimal("45000")),
    ("ODOO-68", "Kaos Polos Lengan Panjang", "Kaos", Decimal("60000")),
    ("ODOO-69", "Kaos Polos Anak", "Kaos", Decimal("35000")),
)


def ensure_demo_polos_products(uom=None) -> list[Any]:
    """Update/create 5 produk demo; aman dipanggil berulang."""
    from master.models import Product

    products = []
    for code, name, category, sale_price in DEMO_POLOS_PRODUCTS:
        defaults = {
            "name": name,
            "category": category,
            "sale_price": sale_price,
            "is_active": True,
        }
        if uom is not None:
            defaults["uom"] = uom
        product, _created = Product.objects.update_or_create(
            code=code, defaults=defaults
        )
        products.append(product)
    return products


__all__ = ("DEMO_POLOS_PRODUCTS", "ensure_demo_polos_products")
