"""Model `CustomerInvoice` & `CustomerInvoiceLine` — app `apps_industry.garment` (H3.1).

Padanan **penjualan** dari `purchase_order.py` (H2.2): satu invoice = satu customer,
banyak baris. **Greenfield** (STEP 0: tidak ada model invoice di MES; jalur I5 hanya
memakai `SyncRecord(resource="order", stage="INVOICE")`).

Dua jalur invoice yang **coexist** (keputusan H3.1):

  * **I5 otomatis** (`InvoiceSyncService`, listener `WORK_ORDER_STATE_CHANGED` saat
    semua WorkOrder selesai) → `account.move` **draft** dengan `price_unit=0`
    (pengingat akuntan). **Tidak diubah** oleh H3.1;
  * **H3.1 manual** (model ini) → akuntan memilih order, melengkapi harga & pajak
    nyata, `CONFIRMED` → push `account.move` **draft** lewat
    `push_customer_invoice` (payload baris eksplisit).

Karena itu `order` **tidak** `unique` (satu order boleh >1 invoice: termin/DP);
UI memberi peringatan, backend tidak memblokir (lihat `decisions[]` di JSON).

Arah sync = **satu arah MES → Odoo**: `DRAFT` murni MES, `CONFIRMED` → push (draft
di Odoo), `SENT` setelah push sukses (`odoo_id` tersimpan), `DONE` murni MES,
`CANCELLED` → `action_cancel` bila `odoo_id` ada. Kegagalan push **bukan** state
model — tercatat di `SyncRecord.status = FAILED` (invoice tetap `CONFIRMED` agar
bisa di-retry), konsisten H2.1/H2.2.

Aturan bisnis **tidak** ditulis di model (pola `Order`/`PurchaseOrder`): `state`
cukup string dan logika validasi/transisi tinggal di
`apps_industry/garment/services/customer_invoice_services.py`.
"""

from __future__ import annotations

from django.db import models


class CustomerInvoice(models.Model):
    """Header customer invoice (satu invoice = satu customer + satu order sumber)."""

    class State(models.TextChoices):
        """State **bisnis** invoice (bukan state sync — itu di `SyncRecord`)."""

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
        help_text="ID account.move di Odoo (kunci idempotensi push invoice).",
    )
    code = models.CharField(
        "kode",
        max_length=64,
        unique=True,
        help_text="Nomor MES `INV-<TAHUN>-<SEQ>` (Sprint C `next_number('INV')`).",
    )
    order = models.ForeignKey(
        "garment.Order",
        on_delete=models.PROTECT,
        related_name="customer_invoices",
        verbose_name="order",
        help_text=(
            "Order sumber (H2.1). **Tidak unique** — satu order boleh >1 invoice "
            "(termin/DP); UI memberi peringatan, backend tidak memblokir."
        ),
    )
    customer = models.ForeignKey(
        "master.Partner",
        on_delete=models.PROTECT,
        related_name="customer_invoices",
        verbose_name="customer",
        help_text="Pelanggan (master.Partner); WAJIB — harus punya `odoo_id` sebelum CONFIRMED.",
    )
    invoice_date = models.DateField(
        "tanggal invoice",
        help_text="Dikirim ke `account.move.invoice_date`.",
    )
    due_date = models.DateField(
        "jatuh tempo",
        null=True,
        blank=True,
        help_text="Opsional (dikirim ke `invoice_date_due` bila diisi).",
    )
    state = models.CharField(
        "state",
        max_length=32,
        default=State.DRAFT,
        db_index=True,
        help_text="State bisnis: DRAFT/CONFIRMED/SENT/DONE/CANCELLED.",
    )
    amount_total = models.DecimalField(
        "total",
        max_digits=18,
        decimal_places=2,
        default=0,
        help_text=(
            "Σ(qty × price_unit) baris (**sebelum** pajak) — diisi service setiap baris "
            "ditulis (H3.3 menambah field ini dari serialisasi saja) dan dipakai guard "
            "anti-overpay `Payment`."
        ),
    )
    notes = models.TextField("catatan", blank=True, default="")
    created_at = models.DateTimeField("dibuat pada", auto_now_add=True)
    updated_at = models.DateTimeField("diubah pada", auto_now=True)

    class Meta:
        verbose_name = "Customer Invoice"
        verbose_name_plural = "Customer Invoices"
        ordering = ("-created_at",)
        indexes = (
            models.Index(fields=("order", "state"), name="cust_inv_order_state_idx"),
        )

    def __str__(self) -> str:
        return f"{self.code} [{self.state}]"


class CustomerInvoiceLine(models.Model):
    """Baris invoice: produk + qty + harga + pajak (diambil dari `OrderLine`, editable)."""

    invoice = models.ForeignKey(
        CustomerInvoice,
        on_delete=models.CASCADE,
        related_name="lines",
        verbose_name="invoice",
    )
    order_line = models.ForeignKey(
        "garment.OrderLine",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoice_lines",
        verbose_name="baris order",
        help_text="Jejak asal (H2.1); `null` = baris tanpa OrderLine (mis. ongkos kirim).",
    )
    product = models.ForeignKey(
        "master.Product",
        on_delete=models.PROTECT,
        related_name="customer_invoice_lines",
        verbose_name="produk",
    )
    qty = models.DecimalField("qty", max_digits=18, decimal_places=2, default=0)
    price_unit = models.DecimalField("harga satuan", max_digits=18, decimal_places=2, default=0)
    tax_ids = models.ManyToManyField(
        "master.Tax",
        blank=True,
        related_name="customer_invoice_lines",
        verbose_name="pajak",
        help_text="Pajak baris (`account.move.line.tax_ids` Odoo). Kosong = tanpa pajak.",
    )
    line_total = models.DecimalField(
        "subtotal",
        max_digits=18,
        decimal_places=2,
        default=0,
        help_text="qty × price_unit (SEBELUM pajak); diisi service, bukan Odoo.",
    )
    created_at = models.DateTimeField("dibuat pada", auto_now_add=True)
    updated_at = models.DateTimeField("diubah pada", auto_now=True)

    class Meta:
        verbose_name = "Customer Invoice Line"
        verbose_name_plural = "Customer Invoice Lines"
        ordering = ("id",)

    def __str__(self) -> str:
        return f"{self.invoice_id} - {self.product_id} x{self.qty}"
