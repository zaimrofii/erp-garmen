"""Model `PurchaseOrder` & `PurchaseOrderLine` — app `apps_industry.garment` (H2.2).

Padanan **pembelian** dari `order.py` (H2.1): satu PO = satu vendor, banyak baris.
**Greenfield** (probe STEP 0: tidak ada model PO di MES sebelumnya; PO Odoo hanya
dibaca lewat transport di B10/B11 dan `MaterialReadiness.po_ids`).

Arah sync = **satu arah MES → Odoo** (CHANGES-DETAIL §1): `DRAFT` murni MES,
`CONFIRMED` → push `purchase.order` (create **draft** di Odoo, `partner_ref` = nomor
MES `PO-<TAHUN>-<SEQ>`), `DONE` murni MES (Odoo `done` = *Locked* yang dipicu
receipt), `CANCELLED` → `action_cancel` bila sudah punya `odoo_id`.

Aturan bisnis **tidak** ditulis di model (pola `Order`): `state` cukup string dan
logika validasi/transisi tinggal di
`apps_industry/garment/services/purchase_order_services.py`.
"""

from __future__ import annotations

from django.db import models


class PurchaseOrder(models.Model):
    """Header purchase order (satu PO = satu vendor/supplier)."""

    odoo_id = models.PositiveBigIntegerField(
        "odoo id",
        null=True,
        blank=True,
        unique=True,
        help_text="ID purchase.order di Odoo (kunci idempotensi push PO).",
    )
    code = models.CharField("kode", max_length=64, unique=True)
    #: Nomor MES yang dikirim ke Odoo sebagai `purchase.order.partner_ref`
    #: (Odoo tetap memakai nomornya sendiri: `P00013`). Bukti `partner_ref` ADA &
    #: writable dari probe STEP 0 (`fields_get purchase.order`).
    partner_ref = models.CharField(
        "ref vendor (nomor MES)",
        max_length=64,
        blank=True,
        default="",
        db_index=True,
        help_text="Nomor MES yang dikirim ke `partner_ref` Odoo (mis. PO-2026-0001).",
    )
    vendor = models.ForeignKey(
        "master.Partner",
        on_delete=models.PROTECT,
        related_name="purchase_orders",
        verbose_name="vendor",
        help_text="Supplier (master.Partner); WAJIB — beda dari Order.customer yang nullable.",
    )
    state = models.CharField("state", max_length=32, default="DRAFT")
    expected_date = models.DateField(
        "tanggal diharapkan",
        null=True,
        blank=True,
        help_text="Perkiraan kedatangan barang (dikirim ke `date_planned` Odoo bila diisi).",
    )
    notes = models.TextField("catatan", blank=True, default="")
    created_at = models.DateTimeField("dibuat pada", auto_now_add=True)
    updated_at = models.DateTimeField("diubah pada", auto_now=True)

    class Meta:
        verbose_name = "Purchase Order"
        verbose_name_plural = "Purchase Orders"
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.code} [{self.state}]"


class PurchaseOrderLine(models.Model):
    """Baris PO: satu produk + qty (Desimal) + harga + pajak + tanggal rencana."""

    odoo_id = models.PositiveBigIntegerField(
        "odoo id",
        null=True,
        blank=True,
        unique=True,
        help_text="ID purchase.order.line di Odoo (kunci idempotensi push PO).",
    )
    po = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.CASCADE,
        related_name="lines",
        verbose_name="purchase order",
    )
    product = models.ForeignKey(
        "master.Product",
        on_delete=models.PROTECT,
        related_name="purchase_order_lines",
        verbose_name="produk",
        help_text="Produk (varian) dari master; WAJIB.",
    )
    #: Odoo `product_qty` = **float** (mis. benang 0.3) ⇒ MES memakai Decimal,
    #: beda dari `OrderLine.qty` (PositiveInteger) yang khusus garmen jadi.
    qty = models.DecimalField("qty", max_digits=18, decimal_places=2, default=0)
    price_unit = models.DecimalField(
        "harga satuan",
        max_digits=18,
        decimal_places=2,
        default=0,
        help_text="Harga beli per unit; auto-isi dari Product.cost_price saat create.",
    )
    tax_ids = models.ManyToManyField(
        "master.Tax",
        blank=True,
        related_name="purchase_order_lines",
        verbose_name="pajak",
        help_text="Pajak baris (`purchase.order.line.taxes_id` Odoo). Kosong = tanpa pajak.",
    )
    date_planned = models.DateField(
        "tanggal rencana",
        null=True,
        blank=True,
        help_text="Tanggal rencana baris (dikirim ke `date_planned` Odoo bila diisi).",
    )
    created_at = models.DateTimeField("dibuat pada", auto_now_add=True)
    updated_at = models.DateTimeField("diubah pada", auto_now=True)

    class Meta:
        verbose_name = "Purchase Order Line"
        verbose_name_plural = "Purchase Order Lines"
        ordering = ("po", "id")

    def __str__(self) -> str:
        return f"{self.po.code}/{self.product.code} x{self.qty}"
