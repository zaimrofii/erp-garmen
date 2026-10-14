"""Model `Payment` — app `apps_industry.garment` (H3.3).

Pembayaran invoice MES (H3.1 `CustomerInvoice`) **atau** tagihan vendor MES
(H3.2 `VendorBill`): **satu model, dua arah** lewat `payment_type`
(`INBOUND` = customer membayar kita, `OUTBOUND` = kita membayar vendor) — padanan
`account.payment` Odoo yang juga satu model dengan `payment_type`
`inbound`/`outbound`.

**Greenfield** (STEP 0: tidak ada entitas payment di MES; I6 hanya **membaca**
`payment_state` dari `account.move` Odoo untuk `MaterialReadiness.vendor_bill_*`).

Relasi ke sumber memakai **dua FK nullable** (keputusan STEP 0 = Opsi A, bukan
`content_type`): `customer_invoice` **atau** `vendor_bill`, dan `CheckConstraint`
di level DB memastikan **tepat satu** yang terisi. 1 payment = 1 dokumen
(termin/partial dicapai dengan membuat beberapa payment; multi-dokumen = sprint
terpisah).

Arah sync = **satu arah MES → Odoo**: `DRAFT` murni MES, `CONFIRMED` → push
`account.payment` **draft** (tanpa `action_post`), `SENT` setelah push sukses
(`odoo_id` tersimpan), `DONE` murni MES, `CANCELLED` → `action_cancel` bila
`odoo_id` ada. Kegagalan push **bukan** state model — tercatat di
`SyncRecord.status = FAILED` (payment tetap `CONFIRMED` agar bisa di-retry),
konsisten H2.1/H2.2/H3.1/H3.2.

**Rekonsiliasi BUKAN tanggung jawab MES** (keputusan STEP 0): probe membuktikan
`account.payment.reconciled_invoice_ids`/`reconciled_bill_ids` bersifat
`readonly=True`, jadi MES hanya membuat payment (draft) — posting &
rekonsiliasi dilakukan akuntan di Odoo.

Aturan bisnis **tidak** ditulis di model (pola `Order`/`VendorBill`): `state`
cukup string dan logika validasi/transisi (termasuk guard overpay) tinggal di
`apps_industry/garment/services/payment_services.py`.
"""

from __future__ import annotations

from django.db import models
from django.db.models import Q


class Payment(models.Model):
    """Pembayaran satu dokumen (invoice customer ATAU bill vendor)."""

    class PaymentType(models.TextChoices):
        """Arah pembayaran (padanan `account.payment.payment_type` Odoo)."""

        #: Customer membayar kita → sumber = `customer_invoice` (Odoo `inbound`).
        INBOUND = "INBOUND", "Pembayaran Masuk (customer)"
        #: Kita membayar vendor → sumber = `vendor_bill` (Odoo `outbound`).
        OUTBOUND = "OUTBOUND", "Pembayaran Keluar (vendor)"

    class Method(models.TextChoices):
        """Cara bayar (MES-only, tidak dikirim ke Odoo)."""

        MANUAL = "manual", "Manual"
        BANK = "bank", "Transfer Bank"
        CASH = "cash", "Kas"

    class State(models.TextChoices):
        """State **bisnis** payment (bukan state sync — itu di `SyncRecord`)."""

        DRAFT = "DRAFT", "Draft"
        CONFIRMED = "CONFIRMED", "Terkonfirmasi"
        SENT = "SENT", "Terkirim ke Odoo"
        DONE = "DONE", "Selesai"
        CANCELLED = "CANCELLED", "Dibatalkan"

    odoo_id = models.PositiveBigIntegerField(
        "odoo id",
        null=True,
        blank=True,
        unique=True,
        help_text="ID account.payment di Odoo (kunci idempotensi push payment).",
    )
    code = models.CharField(
        "kode",
        max_length=64,
        unique=True,
        help_text="Nomor MES `PAY-<TAHUN>-<SEQ>` (Sprint C `next_number('PAY')`).",
    )
    payment_type = models.CharField(
        "tipe pembayaran",
        max_length=16,
        choices=PaymentType.choices,
        default=PaymentType.INBOUND,
        db_index=True,
        help_text="INBOUND = customer bayar kita (sumber `customer_invoice`); OUTBOUND = kita bayar vendor.",
    )
    partner = models.ForeignKey(
        "master.Partner",
        on_delete=models.PROTECT,
        related_name="payments",
        verbose_name="partner",
        help_text="Customer (INBOUND) atau vendor (OUTBOUND); WAJIB punya `odoo_id` sebelum CONFIRMED.",
    )
    customer_invoice = models.ForeignKey(
        "garment.CustomerInvoice",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="payments",
        verbose_name="customer invoice",
        help_text="Sumber untuk INBOUND (**tepat satu** dari customer_invoice/vendor_bill).",
    )
    vendor_bill = models.ForeignKey(
        "garment.VendorBill",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="payments",
        verbose_name="vendor bill",
        help_text="Sumber untuk OUTBOUND (**tepat satu** dari customer_invoice/vendor_bill).",
    )
    amount = models.DecimalField(
        "jumlah",
        max_digits=18,
        decimal_places=2,
        default=0,
        help_text="Jumlah dibayar (WAJIB > 0); guard anti-overpay dihitung di service.",
    )
    currency = models.CharField(
        "mata uang",
        max_length=8,
        default="IDR",
        help_text=(
            "Kode mata uang MES-only (tidak dikirim: Odoo menghitung `currency_id` "
            "dari `journal_id`/company)."
        ),
    )
    payment_date = models.DateField(
        "tanggal bayar",
        help_text="Dikirim ke `account.payment.date`.",
    )
    payment_method = models.CharField(
        "cara bayar",
        max_length=16,
        choices=Method.choices,
        default=Method.MANUAL,
        help_text="MES-only (bank/kas/manual) — Odoo memakai `journal_id` + payment method line.",
    )
    reference = models.CharField(
        "referensi bank",
        max_length=64,
        blank=True,
        default="",
        help_text="No. referensi transfer/cheque MES (dikirim ke `account.payment.ref`).",
    )
    memo = models.TextField(
        "catatan",
        blank=True,
        default="",
        help_text=(
            "Catatan bebas MES; tidak dikirim sebagai `memo` karena field itu **tidak ada** "
            "di Odoo 17 (probe STEP 0) — kode MES dikirim lewat `payment_reference`."
        ),
    )
    state = models.CharField(
        "state",
        max_length=32,
        default=State.DRAFT,
        db_index=True,
        help_text="State bisnis: DRAFT/CONFIRMED/SENT/DONE/CANCELLED.",
    )
    notes = models.TextField("catatan internal", blank=True, default="")
    created_at = models.DateTimeField("dibuat pada", auto_now_add=True)
    updated_at = models.DateTimeField("diubah pada", auto_now=True)

    class Meta:
        verbose_name = "Payment"
        verbose_name_plural = "Payments"
        ordering = ("-created_at",)
        constraints = (
            # TEPAT SATU sumber: `customer_invoice` XOR `vendor_bill`.
            models.CheckConstraint(
                check=(
                    Q(customer_invoice__isnull=False, vendor_bill__isnull=True)
                    | Q(customer_invoice__isnull=True, vendor_bill__isnull=False)
                ),
                name="chk_payment_tepat_satu_sumber",
            ),
        )
        indexes = (
            models.Index(fields=("payment_type", "state"), name="payment_type_state_idx"),
            models.Index(fields=("partner", "state"), name="payment_partner_state_idx"),
        )

    def __str__(self) -> str:
        return f"{self.code} [{self.payment_type}/{self.state}]"

