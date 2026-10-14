"""Transport master data Odoo — **read-only** (``search_read`` saja).

:class:`OdooTransport` membungkus :class:`~integrations.erp_sync.client.OdooClient`
untuk menarik master data Odoo (produk, BOM, partner, lokasi, pajak, UoM, gudang,
jurnal, mata uang). Sifatnya **murni transport**:

* **hanya baca** (``search_read``) — tidak ada ``create``/``write``;
* **tidak** memakai Celery;
* **tidak** menyentuh ``SyncRecord`` (idempotency bukan urusan transport);
* fail-safe: kalau ``self.client is None`` → kembalikan ``[]``, **tidak** raise.

Penulisan hasilnya ke MES dilakukan di task terpisah (``tasks_master.py``).

Client di-*inject* supaya mudah diuji (mock) dan bisa dibangun dari settings:

    from integrations.erp_sync.client import get_odoo_rpc_client
    transport = OdooTransport(get_odoo_rpc_client())

Konvensi ``odoo_id`` (lihat ``docs/integrations/CONTRACT.md``, bagian
"Mapping produk"): field ``id`` pada hasil ``fetch_*`` adalah id record Odoo,
yang dipetakan ke ``master.*.odoo_id`` (mis. ``product.product.id`` →
``master.Product.odoo_id``).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: Field minimal per model — JANGAN ambil semua field (hemat bandwidth Odoo).
#: H3.5 — `list_price` (harga jual) & `standard_price` (HPP) ikut ditarik supaya harga
#: Odoo bisa masuk ke MES (mapper `_product_defaults` hanya mengisi bila MES masih 0).
PRODUCT_FIELDS = [
    "id",
    "default_code",
    "name",
    "uom_id",
    "categ_id",
    "active",
    "product_tmpl_id",
    "list_price",
    "standard_price",
]
BOM_FIELDS = ["id", "code", "product_tmpl_id", "product_qty", "product_uom_id", "type", "active"]
BOM_LINE_FIELDS = [
    "id",
    "bom_id",
    "product_id",
    "product_qty",
    "product_uom_id",
    # H1.5 — dipetakan ke master.BOMLine (sequence + is_active).
    "sequence",
    "active",
]
PARTNER_FIELDS = [
    "id",
    "name",
    "vat",
    "email",
    "is_company",
    "customer_rank",
    "supplier_rank",
    # H1.6 — dipetakan ke master.Partner (phone/city/address/active).
    "phone",
    "street",
    "street2",
    "city",
    "active",
]
LOCATION_FIELDS = [
    "id",
    "name",
    "complete_name",
    "usage",
    "location_id",
    # H1.4 — dipetakan ke master.Location (warehouse_id = gudang pemilik lokasi).
    "warehouse_id",
    "active",
]
UOM_FIELDS = ["id", "name", "category_id", "factor"]
WAREHOUSE_FIELDS = ["id", "name", "code"]
TAX_FIELDS = ["id", "name", "amount", "amount_type", "type_tax_use", "price_include"]
JOURNAL_FIELDS = ["id", "name", "code", "type"]
#: H3.4 — chart of accounts (`account.account`). **TANPA** `active`: probe STEP 0
#: membuktikan Odoo 17 tidak punya field itu (penanda nonaktif = `deprecated`).
ACCOUNT_FIELDS = ["id", "code", "name", "account_type", "reconcile", "deprecated"]
CURRENCY_FIELDS = ["id", "name", "symbol", "rate"]
#: SO sync (I2) — header `sale.order` + baris `sale.order.line`.
SALE_ORDER_FIELDS = [
    "id",
    "name",
    "partner_id",
    "date_order",
    "client_order_ref",
    "state",
    "amount_total",
    "currency_id",
    "order_line",
]
SALE_ORDER_LINE_FIELDS = [
    "id",
    "order_id",
    "product_id",
    "product_uom_qty",
    "price_unit",
    "name",
    "product_uom",
]
#: Material readiness (I2) — PO Odoo: header `purchase.order` + baris
#: `purchase.order.line` (dua model terpisah). `qty_received` = dasar hitung
#: `received_qty`, `date_planned` = dasar `expected_date`.
PURCHASE_ORDER_FIELDS = [
    "id",
    "name",
    "partner_id",
    "date_order",
    "date_planned",
    "state",
    "amount_total",
    "currency_id",
    "order_line",
]
PURCHASE_ORDER_LINE_FIELDS = [
    "id",
    "order_id",
    "product_id",
    "product_qty",
    "qty_received",
    "price_unit",
    "date_planned",
    "product_uom",
]
#: Vendor bill (I6) — ``account.move`` dengan ``move_type`` in
#: (``in_invoice``, ``in_refund``); surat jalan/PO penghubung ada di
#: ``invoice_origin``. ``state`` yang **valid** (hasil ``fields_get`` live
#: 2026-10-06): ``draft`` / ``posted`` / ``cancel`` — **TIDAK ADA** ``paid``;
#: status pembayaran dibaca dari field terpisah ``payment_state``
#: (``required: false`` → aman ikut di-fetch).
VENDOR_BILL_FIELDS = [
    "id",
    "name",
    "partner_id",
    "invoice_date",
    "date",
    "state",
    "payment_state",
    "amount_total",
    "currency_id",
    "invoice_origin",
    "ref",
]
#: Stok Odoo per lokasi (I7) — ``stock.quant`` untuk rekonsiliasi MES vs Odoo.
#: Field diverifikasi **live** ``fields_get`` 2026-10-06 (instance punya 132
#: ``stock.quant``); ``quantity`` = on-hand, ``reserved_quantity`` = tertahan.
STOCK_QUANT_FIELDS = [
    "id",
    "product_id",
    "location_id",
    "quantity",
    "reserved_quantity",
]
#: Enumerasi lokasi internal (I7) — daftar lokasi ``usage='internal'`` diambil
#: langsung dari Odoo (anti-hardcode; ``complete_name``/``parent_path`` hanya
#: milik Odoo). KOREKSI H4.3: sejak **H1.4** ``master.Location`` SUDAH punya
#: ``usage`` (7 nilai) sehingga teks lama "MES tidak menyimpan usage" TIDAK lagi
#: berlaku; enumerasi live tetap dipakai agar tidak bergantung hasil sinkron MES.
INTERNAL_LOCATION_FIELDS = ["id", "complete_name"]

__all__ = ("OdooTransport",)


def _write_date_domain(since):
    """Domain ``write_date > since`` (``since`` = string ``"YYYY-MM-DD HH:MM:SS"``).

    Sengaja memakai **string** (bukan objek ``datetime``) supaya aman dikirim
    apa adanya ke ``execute_kw`` Odoo.
    """
    return [("write_date", ">", since)] if since else []


class OdooTransport:
    """Transport master data Odoo (read-only; tanpa Celery / ``SyncRecord``)."""

    name = "odoo-master"

    def __init__(self, client=None):
        """``client`` = :class:`OdooClient` (bisa di-inject/mock). ``None`` → fail-safe."""
        self.client = client

    # --------------------------------------------------------------- internal
    def _search_read(self, model, domain, fields):
        """Kirim ``search_read`` mentah; fail-safe ``[]`` kalau client belum siap."""
        if self.client is None:
            logger.warning(
                "OdooTransport: client Odoo belum siap -> %s dilewati (return []).", model
            )
            return []
        return self.client.execute_kw(model, "search_read", [domain, fields])

    # ------------------------------------------------------------ master data
    def fetch_products(self, since=None):
        """Baca ``product.product`` (field minimal)."""
        return self._search_read("product.product", _write_date_domain(since), PRODUCT_FIELDS)

    def fetch_boms(self, since=None):
        """Baca ``mrp.bom`` (field minimal)."""
        return self._search_read("mrp.bom", _write_date_domain(since), BOM_FIELDS)

    def fetch_bom_lines(self, since=None):
        """Baca ``mrp.bom.line`` (field minimal) — komponen BOM."""
        return self._search_read(
            "mrp.bom.line", _write_date_domain(since), BOM_LINE_FIELDS
        )

    def fetch_partners(self, since=None):
        """Baca ``res.partner`` (field minimal)."""
        return self._search_read("res.partner", _write_date_domain(since), PARTNER_FIELDS)

    def fetch_locations(self, since=None):
        """Baca ``stock.location`` (field minimal)."""
        return self._search_read("stock.location", _write_date_domain(since), LOCATION_FIELDS)

    def fetch_taxes(self, since=None):
        """Baca ``account.tax`` (field minimal)."""
        return self._search_read("account.tax", _write_date_domain(since), TAX_FIELDS)

    def fetch_uoms(self, since=None):
        """Baca ``uom.uom`` (field minimal) — **BUKAN** ``product.uom``."""
        return self._search_read("uom.uom", _write_date_domain(since), UOM_FIELDS)

    def fetch_warehouses(self, since=None):
        """Baca ``stock.warehouse`` (field minimal)."""
        return self._search_read(
            "stock.warehouse", _write_date_domain(since), WAREHOUSE_FIELDS
        )

    def fetch_journals(self, since=None):
        """Baca ``account.journal`` (field minimal)."""
        return self._search_read("account.journal", _write_date_domain(since), JOURNAL_FIELDS)

    def fetch_accounts(self, since=None):
        """Baca ``account.account`` — chart of accounts (H3.4, pull-only)."""
        return self._search_read("account.account", _write_date_domain(since), ACCOUNT_FIELDS)

    def fetch_currencies(self, since=None):
        """Baca ``res.currency`` (field minimal)."""
        return self._search_read(
            "res.currency", _write_date_domain(since), CURRENCY_FIELDS
        )

    # ------------------------------------------------- sales order (I2)
    def fetch_sale_orders(self, since=None, state="sale"):
        """Baca ``sale.order`` (field minimal) — default hanya ``state='sale'``.

        Domain: ``[('state','=',state)]`` (+ ``write_date > since`` kalau diisi).
        """
        domain = [("state", "=", state)] + _write_date_domain(since)
        return self._search_read("sale.order", domain, SALE_ORDER_FIELDS)

    def fetch_sale_order_lines(self, order_ids, since=None):
        """Baca ``sale.order.line`` untuk ``order_ids`` (field minimal).

        Domain: ``[('order_id','in',order_ids)]`` (+ ``write_date > since``).
        """
        domain = [("order_id", "in", list(order_ids or []))] + _write_date_domain(since)
        return self._search_read("sale.order.line", domain, SALE_ORDER_LINE_FIELDS)

    # --------------------------------------------------------- purchase order
    def fetch_purchase_orders(self, since=None, states=("purchase", "done")):
        """Baca ``purchase.order`` (field minimal) — PO **confirmed** atau **locked**.

        Default ``states=("purchase", "done")``: PO yang sudah dikonfirmasi
        (``purchase``) dan yang sudah dikunci/selesai (``done``) — keduanya relevan
        untuk menghitung kesiapan material.

        Domain: ``[('state','in',states)]`` (+ ``write_date > since`` kalau diisi).
        """
        domain = [("state", "in", list(states))] + _write_date_domain(since)
        return self._search_read("purchase.order", domain, PURCHASE_ORDER_FIELDS)

    def fetch_purchase_order_lines(self, order_ids, since=None):
        """Baca ``purchase.order.line`` untuk ``order_ids`` (field minimal).

        Domain: ``[('order_id','in',order_ids)]`` (+ ``write_date > since``).
        """
        domain = [("order_id", "in", list(order_ids or []))] + _write_date_domain(since)
        return self._search_read(
            "purchase.order.line", domain, PURCHASE_ORDER_LINE_FIELDS
        )

    # --------------------------------------------------------- vendor bill (I6)
    def fetch_vendor_bills(self, since=None, states=("draft", "posted")):
        """Baca ``account.move`` **vendor bill** (field minimal).

        ``move_type`` dibatasi ``("in_invoice", "in_refund")`` — retur vendor
        (``in_refund``) ikut dikirim supaya koreksi tetap terhitung.

        Default ``states=("draft", "posted")``: nilai ``state`` yang **valid** di
        instance ini adalah ``draft`` / ``posted`` / ``cancel`` (hasil
        ``fields_get``); ``cancel`` (bill dibatalkan) **tidak** diambil, dan
        ``paid`` **bukan** nilai ``state`` (lihat ``payment_state``).

        Domain: ``[('move_type','in',[...]), ('state','in',states)]``
        (+ ``write_date > since`` kalau diisi).
        """
        domain = [
            ("move_type", "in", ["in_invoice", "in_refund"]),
            ("state", "in", list(states)),
        ] + _write_date_domain(since)
        return self._search_read("account.move", domain, VENDOR_BILL_FIELDS)

    # ---------------------------------------------------------- stock quant (I7)
    def fetch_stock_quants(self, location_ids, since=None, child_of=False):
        """Baca ``stock.quant`` untuk ``location_ids`` (field minimal).

        Dipakai rekonsiliasi stok MES vs Odoo — lokasi internal dari
        :meth:`fetch_internal_locations` (tidak di-hardcode).

        ``location_ids`` **wajib**: kalau kosong/``None`` → return ``[]`` **tanpa**
        memanggil Odoo (domain kosong pasti tidak menghasilkan apa pun;
        fail-fast).

        ``child_of=True`` → lokasi **anak** ikut terhitung (mis. ``WH/Stok`` juga
        menarik ``WH/Stok/Shelf 1``/``Shelf 2``/``Gate A`` …) memakai operator
        Odoo ``child_of`` — dipilih **OR-domain** (bukan ekspansi daftar id di
        MES) karena MES tidak menyimpan hierarki lokasi; lihat
        :meth:`_location_domain`.

        Domain: ``[...lokasi...]`` (+ ``write_date > since`` kalau diisi).
        """
        ids = list(location_ids or [])
        if not ids:
            return []
        domain = self._location_domain(ids, child_of=child_of) + _write_date_domain(since)
        return self._search_read("stock.quant", domain, STOCK_QUANT_FIELDS)

    @staticmethod
    def _location_domain(location_ids, child_of=False):
        """Domain filter lokasi: ``in`` (default) atau OR-union ``child_of``.

        ``child_of`` hanya menerima **satu** id per tuple, jadi untuk banyak
        lokasi dibentuk domain OR notasi prefix Odoo:
        ``['|', ('location_id','child_of',8), ('location_id','child_of',27), ...]``
        (n term ⇒ n-1 operator ``|`` di depan, asosiatif kiri).
        """
        if not child_of:
            return [("location_id", "in", list(location_ids))]

        terms = [("location_id", "child_of", int(location_id)) for location_id in location_ids]
        return ["|"] * (len(terms) - 1) + terms

    def fetch_internal_locations(self):
        """Baca semua ``stock.location`` **internal** (``id`` + ``complete_name``).

        Dipakai enumerasi lokasi internal langsung dari Odoo (anti-hardcode).
        Odoo mengecualikan lokasi arsip secara default.
        """
        return self._search_read(
            "stock.location",
            [("usage", "=", "internal")],
            INTERNAL_LOCATION_FIELDS,
        )

    # -------------------------------------------------------------- resource
    def close(self):
        """Tutup client kalau ada (aman dipanggil berkali-kali)."""
        client = self.client
        if client is not None and hasattr(client, "close"):
            client.close()
