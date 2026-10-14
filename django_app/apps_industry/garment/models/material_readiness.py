"""Model `MaterialReadiness` — kesiapan material per ``OrderLine`` (fase I2).

Satu ``OrderLine`` membutuhkan komponen (mengikuti BOM — lihat ``master.BOMLine``);
sebagian sudah diterima lewat PO Odoo. Ringkasan per OrderLine disimpan di sini:
``required_qty`` (kebutuhan dari BOM), ``received_qty`` (sudah diterima dari PO),
``shortage_qty`` = ``max(0, required_qty - received_qty)``.

Idempotensi: repo ini **tidak** punya ``ODOO_MAPPING`` dan model ini **bukan mirror
Odoo** (ia turunan dari SO + PO), jadi kuncinya bukan ``odoo_id`` melainkan
**OneToOne unik ke** ``OrderLine`` — satu baris ringkasan per OrderLine yang
ditulis ulang (recompute) tiap data PO/SO berubah; jejak PO asalnya disimpan di
``po_ids``/``po_line_ids``.

Sejak I6 ringkasan ini juga menyimpan **jejak vendor bill** Odoo
(``account.move`` dengan ``move_type`` ``in_invoice``/``in_refund``) yang
``invoice_origin``-nya menaut ke PO di atas: ``vendor_bill_ids``,
``vendor_bill_status`` (status agregat), dan ``vendor_bill_amount`` (opname
tagihan). MES tetap **tidak** menyimpan model PO/Bill — hanya id sebagai referensi.

Detail per komponen BOM sengaja belum dimodelkan (menyusul bila perlu).
"""

from __future__ import annotations

from django.db import models
from django.db.models import Q


class MaterialReadiness(models.Model):
    """Ringkasan kesiapan material untuk satu baris order."""

    class Status(models.TextChoices):
        # WAITING = belum ada yang diterima (received_qty == 0)
        WAITING = "WAITING", "Waiting"
        # PARTIAL = sebagian diterima (0 < received_qty < required_qty)
        PARTIAL = "PARTIAL", "Partial"
        # READY = penerimaan sudah menutup kebutuhan (received_qty >= required_qty)
        READY = "READY", "Ready"

    class VendorBillStatus(models.TextChoices):
        """Status agregat vendor bill Odoo untuk PO OrderLine ini."""

        # NONE   = belum ada vendor bill yang cocok (invoice_origin = nama PO)
        NONE = "NONE", "Belum ada"
        # DRAFT  = bill masih draft (belum di-post)
        DRAFT = "DRAFT", "Draft"
        # POSTED = bill sudah di-post (tercatat di akuntansi)
        POSTED = "POSTED", "Posted"
        # PAID   = bill sudah dibayar penuh (payment_state == "paid")
        PAID = "PAID", "Paid"

    order_line = models.OneToOneField(
        "garment.OrderLine",
        on_delete=models.CASCADE,
        related_name="readiness",
        verbose_name="baris order",
        help_text="Satu baris ringkasan per OrderLine (kunci idempotensi recompute).",
    )
    required_qty = models.FloatField("qty dibutuhkan", default=0)
    received_qty = models.FloatField("qty diterima", default=0)
    shortage_qty = models.FloatField(
        "qty kurang",
        default=0,
        help_text="Kekurangan material = max(0, required_qty - received_qty).",
    )
    expected_date = models.DateField(
        "ETA",
        null=True,
        blank=True,
        help_text="Perkiraan tanggal material tiba (dari PO Odoo).",
    )
    status = models.CharField(
        "status",
        max_length=16,
        choices=Status.choices,
        default=Status.WAITING,
    )
    po_ids = models.JSONField(
        "id PO Odoo",
        default=list,
        blank=True,
        help_text="Daftar id purchase.order Odoo yang menutup kebutuhan ini.",
    )
    po_line_ids = models.JSONField(
        "id baris PO Odoo",
        default=list,
        blank=True,
        help_text="Daftar id purchase.order.line Odoo (referensi, bukan mirror).",
    )
    vendor_bill_ids = models.JSONField(
        "id vendor bill Odoo",
        default=list,
        blank=True,
        help_text=(
            "Daftar id account.move (in_invoice/in_refund) yang invoice_origin-nya "
            "cocok dengan nama PO — referensi, bukan mirror."
        ),
    )
    vendor_bill_status = models.CharField(
        "status vendor bill",
        max_length=16,
        choices=VendorBillStatus.choices,
        default=VendorBillStatus.NONE,
        help_text="Status agregat: yang TERTINGGI di antara vendor bill yang cocok.",
    )
    vendor_bill_amount = models.FloatField(
        "total vendor bill",
        default=0,
        help_text="Jumlah amount_total vendor bill yang cocok (opname tagihan).",
    )
    last_computed_at = models.DateTimeField("kapan dihitung", null=True, blank=True)

    class Meta:
        verbose_name = "Material Readiness"
        verbose_name_plural = "Material Readiness"
        ordering = ("-last_computed_at",)
        constraints = [
            models.CheckConstraint(
                check=Q(shortage_qty__gte=0),
                name="chk_material_readiness_shortage_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.order_line} - {self.status} ({self.shortage_qty})"
