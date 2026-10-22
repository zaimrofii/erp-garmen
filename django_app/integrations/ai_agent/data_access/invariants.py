"""Invariant data lintas tabel (Fase 0-cepat 2026-10-22).

Dipakai oleh seed sebagai guard keras dan oleh test regresi. Modul ini
**read-only**: hanya menghitung pelanggaran, tidak memperbaiki data.

Invariant:
  A. Bundle DONE dengan SUM(scrap.qty) > bundle.qty_done
  B. Produk yang pernah muncul di OrderLine dengan sale_price <= 0 / NULL
  C. Order tanpa OrderLine
  D. OrderLine tanpa product_id
  E. OrderLine dengan qty <= 0
  F. Produk duplikat (name, sale_price) lebih dari satu baris

`F` sengaja TIDAK ditegakkan di seed: duplikat berasal dari impor Odoo
(beberapa product.product dengan nama sama) dan butuh keputusan bisnis.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import CommandError
from django.db.models import Count, F, Q, Sum

#: Invariant yang wajib 0 setelah seed selesai.
ENFORCED = ("B", "C", "D", "E")


def collect_violations(limit: int = 10) -> dict[str, dict[str, Any]]:
    """Hitung semua invariant; kembalikan count + contoh baris (maks `limit`)."""
    from apps_industry.garment.models import (
        Bundle,  # noqa: F401 - memastikan app model siap
        Order,
        OrderLine,
        ScrapAccumulator,
    )
    from master.models import Product

    done_scrap = (
        ScrapAccumulator.objects.filter(bundle__state="DONE")
        .values("bundle_id")
        .annotate(scrap_total=Sum("qty"))
        .filter(scrap_total__gt=F("bundle__qty_done"))
    )
    bad_price = (
        Product.objects.filter(order_lines__isnull=False)
        .filter(Q(sale_price__lte=0) | Q(sale_price__isnull=True))
        .distinct()
        .order_by("pk")
    )
    no_lines = Order.objects.annotate(n=Count("lines")).filter(n=0).order_by("pk")
    no_product = OrderLine.objects.filter(product__isnull=True).order_by("pk")
    bad_qty = OrderLine.objects.filter(qty__lte=0).order_by("pk")
    duplicate = (
        Product.objects.values("name", "sale_price")
        .annotate(n=Count("id"))
        .filter(n__gt=1)
        .order_by("-n", "name")
    )

    return {
        "A": {
            "label": "bundle DONE dengan scrap > qty_done",
            "count": done_scrap.count(),
            "sample": [
                {"bundle_id": row["bundle_id"], "scrap": row["scrap_total"]}
                for row in done_scrap[:limit]
            ],
        },
        "B": {
            "label": "produk di orderline dengan harga <= 0 / NULL",
            "count": bad_price.count(),
            "sample": [
                {
                    "id": product.pk,
                    "code": product.code,
                    "name": product.name,
                    "sale_price": str(product.sale_price),
                }
                for product in bad_price[:limit]
            ],
        },
        "C": {
            "label": "order tanpa orderline",
            "count": no_lines.count(),
            "sample": [{"code": row["code"]} for row in no_lines.values("code")[:limit]],
        },
        "D": {
            "label": "orderline tanpa product_id",
            "count": no_product.count(),
            "sample": [
                {
                    "id": row["id"],
                    "order": row["order__code"],
                    "qty": row["qty"],
                }
                for row in no_product.values("id", "order__code", "qty")[:limit]
            ],
        },
        "E": {
            "label": "orderline dengan qty <= 0",
            "count": bad_qty.count(),
            "sample": [
                {"id": row["id"], "order": row["order__code"], "qty": row["qty"]}
                for row in bad_qty.values("id", "order__code", "qty")[:limit]
            ],
        },
        "F": {
            "label": "produk duplikat nama+harga",
            "count": duplicate.count(),
            "sample": [dict(row) for row in duplicate[:limit]],
        },
    }


def assert_clean(source: str) -> None:
    """Raise `CommandError` bila invariant yang ditegakkan tidak 0.

    `source` dipakai di pesan error (mis. nama management command).
    """
    violations = collect_violations(limit=3)
    broken = {
        key: value
        for key, value in violations.items()
        if key in ENFORCED and value["count"]
    }
    if not broken:
        return

    detail = "; ".join(
        f"{key}={value['count']} ({value['label']})"
        for key, value in sorted(broken.items())
    )
    raise CommandError(
        f"Invariant data gagal setelah {source}: {detail}. "
        f"Contoh: { {key: value['sample'] for key, value in broken.items()} }"
    )


__all__ = ("ENFORCED", "assert_clean", "collect_violations")
