"""Service **audit produk** MES ↔ Odoo (fase I8.8).

Menjawab pertanyaan "produk mana yang belum punya ``odoo_id``?" — produk seperti
itu **tidak bisa** diikuti rekonsiliasi stok (``ReconciliationService`` memfilter
``Product.odoo_id``) dan tidak bisa ditautkan ke baris PO/vendor bill/invoice
Odoo, jadi user perlu tahu **sebelum** menyimpulkan "data kurang".

Dua potret:

* :meth:`ProductAuditService.missing_odoo_id` — semua produk tanpa ``odoo_id``
  (dibatasi :data:`PRODUCT_LIMIT` supaya response tidak membengkak);
* :meth:`ProductAuditService.used_in_open_bundles` — subset yang **sedang
  dipakai** bundle di lantai (state bukan ``DONE``/``DRAFT``) — inilah yang
  paling mendesak karena material/WIP-nya berjalan sekarang.

Read-only: **tidak** mengubah model ``Product`` dan **tidak** memanggil Odoo
(mengisi ``odoo_id`` tetap tugas ``erp_sync.sync_master_products``).
"""

from __future__ import annotations

import logging

from master.models import Product

logger = logging.getLogger(__name__)

__all__ = ("ProductAuditService",)

#: Batas jumlah produk yang dikembalikan (jangan dump seluruh tabel).
PRODUCT_LIMIT = 100

#: State bundle yang dianggap **sudah tidak berjalan** (patokan "terbuka").
CLOSED_BUNDLE_STATES = ("DONE", "DRAFT")


class ProductAuditService:
    """Audit produk master yang belum tersinkron ke Odoo (read-only)."""

    def missing_odoo_id(self) -> dict:
        """Produk tanpa ``odoo_id`` (daftar dipotong di :data:`PRODUCT_LIMIT`).

        Return ``{"count", "limit", "products": [{"id", "code", "name"}, ...]}``
        — ``count`` = jumlah sesungguhnya, ``products`` = halaman pertama.
        """
        queryset = Product.objects.filter(odoo_id__isnull=True).order_by("code")
        return {
            "count": queryset.count(),
            "limit": PRODUCT_LIMIT,
            "products": [self._product_payload(product) for product in queryset[:PRODUCT_LIMIT]],
        }

    def used_in_open_bundles(self) -> dict:
        """Subset :meth:`missing_odoo_id` yang dipakai bundle belum selesai.

        Rantai relasi: ``Product.order_lines → OrderLine.work_orders →
        WorkOrder.bundles``; bundle "terbuka" = ``state`` **bukan**
        ``DONE``/``DRAFT`` (:data:`CLOSED_BUNDLE_STATES`).

        ``filter(...bundles__isnull=False)`` dipakai **eksplisit**: kalau hanya
        memakai ``exclude(bundles__state__in=...)``, produk yang **tidak punya
        bundle sama sekali** juga ikut terambil (``exclude`` = subquery
        ``NOT IN`` — sama pelajarannya dengan query readiness I3).
        """
        queryset = (
            Product.objects.filter(odoo_id__isnull=True)
            .filter(order_lines__work_orders__bundles__isnull=False)
            .exclude(order_lines__work_orders__bundles__state__in=CLOSED_BUNDLE_STATES)
            .distinct()
            .order_by("code")
        )
        return {
            "count": queryset.count(),
            "limit": PRODUCT_LIMIT,
            "products": [self._product_payload(product) for product in queryset[:PRODUCT_LIMIT]],
        }

    def audit(self) -> dict:
        """Gabungan kedua potret — bentuk yang dikembalikan endpoint."""
        missing = self.missing_odoo_id()
        return {
            "count": missing["count"],
            "products": missing["products"],
            "used_in_open_bundles": self.used_in_open_bundles(),
        }

    # ---------------------------------------------------------------- internal
    @staticmethod
    def _product_payload(product) -> dict:
        """Dict ringkas satu produk (read-only, tanpa menyentuh Odoo)."""
        return {"id": product.pk, "code": product.code, "name": product.name}
