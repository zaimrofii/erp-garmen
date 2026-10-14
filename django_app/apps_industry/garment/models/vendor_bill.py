"""Model `VendorBill` & `VendorBillLine` — app `apps_industry.garment` (H3.2).

Padanan **pembelian** dari `customer_invoice.py` (H3.1): satu bill = satu vendor,
banyak baris. **Greenfield** (STEP 0: tidak ada model bill di MES; jalur I6 hanya
membaca `account.move` Odoo lewat `fetch_vendor_bills` + menyimpan jejaknya di
`MaterialReadiness.vendor_bill_*`).

Dua jalur vendor bill yang **coexist** (keputusan H3.2):

  * **I6 tarik (Odoo → MES, read-only)** — `erp_sync.recompute_readiness` harian
    04:00 + `MaterialReadiness.vendor_bill_ids/vendor_bill_status` (observasi
    `account.move` `in_invoice`/`in_refund` milik Odoo). **Tidak diubah** H3.2;
  * **H3.2 dorong (MES → Odoo)** — model ini: operator MES membuat bill (dari PO
    H2.2 atau manual), `CONFIRMED` → push `account.move` **draft** lewat
    `erp_sync.push_vendor_bill`.

Karena itu `purchase_order` **nullable** (bill tanpa PO diizinkan, mis. biaya jasa)
dan **tidak** `unique` (satu PO boleh >1 bill: termin/partial); UI memberi
peringatan, backend tidak memblokir (lihat `decisions[]` di JSON).

Arah sync = **satu arah MES → Odoo**: `DRAFT` murni MES, `CONFIRMED` → push (draft
di Odoo), `SENT` setelah push sukses (`odoo_id` tersimpan), `DONE` murni MES,
`CANCELLED` → `button_cancel` bila `odoo_id` ada. Kegagalan push **bukan** state
model — tercatat di `SyncRecord.status = FAILED` (bill tetap `CONFIRMED` agar bisa
di-retry), konsisten H2.1/H2.2/H3.1.

`ref` = nomor bill dari **vendor** (mis. `INV-VENDOR-001`) dan hanya *best-effort*:
probe STEP 0 membuktikan `account.move.ref` Odoo **tidak** wajib (`required=False`
di model, tanpa `required="1"` di view, tanpa constraint duplikasi) ⇒ MES tidak
pernah memblokir create karena `ref` kosong/duplikat.

Aturan bisnis **tidak** ditulis di model (pola `PurchaseOrder`): `state` cukup
string dan logika validasi/transisi tinggal di
`apps_industry/garment/services/vendor_bill_services.py`.
"""

from __future__ import annotations

from django.db import models


class VendorBill(models.Model):
    """Header vendor bill (satu bill = satu vendor + opsional satu PO sumber)."""

    class State(models.TextChoices):
        """State **bisnis** bill (bukan state sync — itu di `SyncRecord`)."""

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
        help_text="ID account.move (in_invoice) di Odoo (kunci idempotensi push bill).",
    )
    code = models.CharField(
        "kode",
        max_length=64,
        unique=True,
        help_text="Nomor MES `VB-<TAHUN>-<SEQ>` (Sprint C `next_number('VB')`).",
    )
    purchase_order = models.ForeignKey(
        "garment.PurchaseOrder",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="vendor_bills",
        verbose_name="purchase order",
        help_text=(
            "PO sumber (H2.2) — **nullable** (bill tanpa PO, mis. biaya jasa) dan "
            "**tidak unique** (satu PO boleh >1 bill: termin/partial)."
        ),
    )
    vendor = models.ForeignKey(
        "master.Partner",
        on_delete=models.PROTECT,
        related_name="vendor_bills",
        verbose_name="vendor",
        help_text="Supplier (master.Partner); WAJIB — harus punya `odoo_id` sebelum CONFIRMED.",
    )
    ref = models.CharField(
        "ref vendor",
        max_length=64,
        blank=True,
        default="",
        db_index=True,
        help_text=(
            "Nomor bill dari VENDOR (mis. INV-VENDOR-001). Best-effort: boleh kosong "
            "dan boleh duplikat — Odoo tidak mewajibkannya (probe STEP 0)."
        ),
    )
    invoice_date = models.DateField(
        "tanggal bill",
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
        verbose_name = "Vendor Bill"
        verbose_name_plural = "Vendor Bills"
        ordering = ("-created_at",)
        indexes = (
            models.Index(fields=("purchase_order", "state"), name="vend_bill_po_state_idx"),
        )

    def __str__(self) -> str:
        return f"{self.code} [{self.state}]"


class VendorBillLine(models.Model):
    """Baris bill: produk + qty + harga + pajak (dari `PurchaseOrderLine`, editable)."""

    bill = models.ForeignKey(
        VendorBill,
        on_delete=models.CASCADE,
        related_name="lines",
        verbose_name="vendor bill",
    )
    po_line = models.ForeignKey(
        "garment.PurchaseOrderLine",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="vendor_bill_lines",
        verbose_name="baris PO",
        help_text="Jejak asal (H2.2); `null` = baris tanpa PO Line (mis. biaya jasa).",
    )
    product = models.ForeignKey(
        "master.Product",
        on_delete=models.PROTECT,
        related_name="vendor_bill_lines",
        verbose_name="produk",
    )
    qty = models.DecimalField("qty", max_digits=18, decimal_places=2, default=0)
    price_unit = models.DecimalField("harga satuan", max_digits=18, decimal_places=2, default=0)
    tax_ids = models.ManyToManyField(
        "master.Tax",
        blank=True,
        related_name="vendor_bill_lines",
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
        verbose_name = "Vendor Bill Line"
        verbose_name_plural = "Vendor Bill Lines"
        ordering = ("id",)

    def __str__(self) -> str:
        return f"{self.bill_id} - {self.product_id} x{self.qty}"
