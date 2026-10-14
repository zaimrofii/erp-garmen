"""Model `Order` & `OrderLine` — app `apps_industry.garment`.

Order = pintu masuk produksi. Satu order punya banyak line (per produk/SKU), dan
setiap line melahirkan satu atau lebih work order
(`apps_industry/garment/models/work_order.py`).

  * ``Order``     — header order: customer, tipe order, state, prioritas, deadline.
  * ``OrderLine`` — baris order per produk + ``tag`` (dasar tag-router/rule
    engine) dan ``ticket_code`` (kupon piece-rate, unik).

Aturan bisnis tidak ditulis di model: `state` cukup string (definisinya di
`core.state_machine`) dan logika routing/prioritas tinggal di
`apps_industry/garment/services/` (Sprint 2.2) yang memakai engine core.
"""

from __future__ import annotations

from django.db import models


class Order(models.Model):
    """Header order (satu order = satu klien/channel)."""

    class OrderType(models.TextChoices):
        EXPORT = "EXPORT", "Export"
        CUSTOM = "CUSTOM", "Custom"
        BRAND = "BRAND", "Brand"

    odoo_id = models.PositiveBigIntegerField(
        "odoo id",
        null=True,
        blank=True,
        unique=True,
        help_text="ID sale.order di Odoo (kunci idempotensi sync SO).",
    )
    code = models.CharField("kode", max_length=64, unique=True)
    # H2.1 — nomor MES yang dikirim ke Odoo sebagai `sale.order.client_order_ref`
    # (Odoo tetap memakai nomornya sendiri: `S00033`). Dipakai juga sebagai penanda
    # "order ini berasal dari MES" oleh pull I2 (agar `code` MES tidak ditimpa).
    client_order_ref = models.CharField(
        "ref pelanggan (nomor MES)",
        max_length=64,
        blank=True,
        default="",
        db_index=True,
        help_text="Nomor MES yang dikirim ke `client_order_ref` Odoo (mis. SO-2026-0001).",
    )
    customer = models.ForeignKey(
        "master.Partner",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="orders",
        verbose_name="customer",
    )
    order_type = models.CharField(
        "tipe order",
        max_length=16,
        choices=OrderType.choices,
        default=OrderType.EXPORT,
    )
    # `state` sengaja char, bukan TextChoices: definisi state = data di
    # core.state_machine (configurable), bukan enum di kode.
    state = models.CharField("state", max_length=32, default="DRAFT")
    priority = models.IntegerField(
        "prioritas",
        default=0,
        help_text="Angka BESAR = lebih prioritas (dipakai priority scheduler).",
    )
    deadline = models.DateTimeField("deadline", null=True, blank=True)
    created_at = models.DateTimeField("dibuat pada", auto_now_add=True)
    updated_at = models.DateTimeField("diubah pada", auto_now=True)

    class Meta:
        verbose_name = "Order"
        verbose_name_plural = "Orders"
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.code} [{self.state}]"


class OrderLine(models.Model):
    """Baris order: satu produk + qty + tag routing + kupon piece-rate."""

    odoo_id = models.PositiveBigIntegerField(
        "odoo id",
        null=True,
        blank=True,
        unique=True,
        help_text="ID sale.order.line di Odoo (kunci idempotensi sync SO).",
    )
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="lines",
        verbose_name="order",
    )
    product = models.ForeignKey(
        "master.Product",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="order_lines",
        verbose_name="produk",
        help_text="Produk (varian) dari master; NULL kalau belum tersinkron.",
    )
    tag = models.CharField(
        "tag",
        max_length=64,
        blank=True,
        default="",
        db_index=True,
        help_text='Tag routing/prioritas, mis. "FAST_TRACK" atau "EXPORT".',
    )
    ticket_code = models.CharField(
        "kode kupon",
        max_length=64,
        unique=True,
        null=True,
        blank=True,
        help_text="Kode kupon piece-rate (unik); boleh kosong kalau belum dicetak.",
    )
    qty = models.PositiveIntegerField("qty", default=0)
    # H2.1 — harga jual per satuan (CHANGES-DETAIL §5: WAJIB > 0 sebelum CONFIRMED).
    price_unit = models.DecimalField(
        "harga satuan",
        max_digits=18,
        decimal_places=2,
        default=0,
        help_text="Harga jual per unit; auto-isi dari Product.sale_price saat create.",
    )
    # H2.1 — pajak per baris (`sale.order.line.tax_id` Odoo = m2m `account.tax`).
    tax_ids = models.ManyToManyField(
        "master.Tax",
        blank=True,
        related_name="order_lines",
        verbose_name="pajak",
        help_text="Pajak baris (mis. PPN). Kosong = tanpa pajak (tidak ada default).",
    )
    created_at = models.DateTimeField("dibuat pada", auto_now_add=True)
    updated_at = models.DateTimeField("diubah pada", auto_now=True)

    class Meta:
        verbose_name = "Order Line"
        verbose_name_plural = "Order Lines"
        ordering = ("order", "id")

    def __str__(self) -> str:
        return f"{self.order.code}/{self.product.code} x{self.qty}"

