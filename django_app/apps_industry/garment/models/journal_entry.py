"""Model `JournalEntry` + `JournalEntryLine` — app `apps_industry.garment` (H3.4).

Jurnal **manual** double-entry yang di-input akuntan/admin di MES, lalu dikirim ke
Odoo sebagai ``account.move`` ``move_type='entry'`` **draft** (bukan invoice/bill).

**Greenfield** (STEP 0 H3.4): MES belum punya entitas jurnal manual apa pun;
H3.1/H3.2/H3.3 hanya membuat `account.move`/`account.payment` lewat dokumen mereka
sendiri (Odoo yang membukukan), dan I6 hanya **membaca** `payment_state`/bill.

Perbedaan penting dari H3.1–H3.3 (hasil probe STEP 0 H3.4):
  * ``account.move.move_type`` **wajib dikirim eksplisit** ``"entry"``;
  * ``journal_id`` **wajib** (Odoo required) ⇒ MES menyimpan FK ke
    ``master.Journal`` (mirror ``account.journal``) dan **hanya journal
    ``general``** yang boleh dipakai (keputusan STEP 0 — journal sale/purchase/
    bank/cash milik alur invoice/bill/payment Odoo);
  * baris dikirim lewat ``line_ids`` sebagai command One2many ``(0, 0, {...})``
    dengan ``account_id`` (FK ``master.Account`` — mirror pull-only),
    ``name``, ``debit``, ``credit``, dan ``partner_id`` opsional;
  * ``date`` wajib (``entry_date``), ``ref`` opsional;
  * ``currency_id``/``company_id`` **tidak** dikirim (dihitung Odoo dari journal/company);
  * ``action_post`` **tidak** pernah dipanggil ⇒ entry tetap **draft**; posting &
    rekonsiliasi = akuntan di Odoo (konsisten H3.1–H3.3).

Aturan bisnis **tidak** ditulis di model (pola `Payment`/`VendorBill`): `state`
cukup string dan seluruh validasi/transisi tinggal di
`apps_industry/garment/services/journal_entry_services.py`. Model hanya menyimpan
constraint yang **struktural**: tiap baris tidak boleh negatif dan tidak boleh
punya debit **dan** kredit sekaligus (XOR), plus denormalisasi `total_debit`/
`total_credit` (di-set service) untuk guard keseimbangan + audit.

Arah sync = **satu arah MES → Odoo**: `DRAFT` murni MES, `CONFIRMED` → push
`account.move` draft, `SENT` setelah push sukses (`odoo_id` tersimpan), `DONE`
murni MES, `CANCELLED` → `button_cancel` bila `odoo_id` ada. Kegagalan push
**bukan** state model — tercatat di `SyncRecord.status = FAILED` (entry tetap
`CONFIRMED` supaya bisa di-retry).
"""

from __future__ import annotations

from django.db import models
from django.db.models import Q


class JournalEntry(models.Model):
    """Satu jurnal manual (header) — padanan ``account.move`` ``move_type='entry'``."""

    class State(models.TextChoices):
        """State **bisnis** jurnal (bukan state sync — itu di `SyncRecord`)."""

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
        help_text="ID account.move (move_type='entry') di Odoo — kunci idempotensi push.",
    )
    code = models.CharField(
        "kode",
        max_length=64,
        unique=True,
        help_text="Nomor MES `JE-<TAHUN>-<SEQ>` (Sprint C `next_number('JE')`).",
    )
    journal = models.ForeignKey(
        "master.Journal",
        on_delete=models.PROTECT,
        related_name="journal_entries",
        verbose_name="jurnal",
        help_text="Buku besar tujuan; di Odoo `account.move.journal_id` (WAJIB, hanya journal general).",
    )
    entry_date = models.DateField(
        "tanggal", help_text="Dikirim ke `account.move.date` (WAJIB di Odoo)."
    )
    ref = models.CharField(
        "referensi",
        max_length=64,
        blank=True,
        default="",
        help_text="Referensi bebas (dikirim ke `account.move.ref`; kosong → kode MES).",
    )
    memo = models.TextField(
        "memo",
        blank=True,
        default="",
        help_text=(
            "Keterangan MES; tidak dikirim sebagai `narration` (HTML) — dipakai "
            "sebagai bagian `ref` bila `ref` kosong."
        ),
    )
    total_debit = models.DecimalField(
        "total debit",
        max_digits=18,
        decimal_places=2,
        default=0,
        help_text="Denormalisasi Σ debit (di-set service) — dipakai guard + audit.",
    )
    total_credit = models.DecimalField(
        "total kredit",
        max_digits=18,
        decimal_places=2,
        default=0,
        help_text="Denormalisasi Σ kredit (di-set service) — dipakai guard + audit.",
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
        verbose_name = "Journal Entry"
        verbose_name_plural = "Journal Entries"
        ordering = ("-created_at",)
        indexes = (
            models.Index(fields=("state", "entry_date"), name="je_state_date_idx"),
            models.Index(fields=("journal", "state"), name="je_journal_state_idx"),
        )

    def __str__(self) -> str:
        return f"{self.code} [{self.state}]"


class JournalEntryLine(models.Model):
    """Baris jurnal (debit/kredit) — padanan satu `account.move.line`."""

    entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.CASCADE,
        related_name="lines",
        verbose_name="jurnal",
        help_text="Parent jurnal (dibuat/diganti menyatu dengan header — atomic).",
    )
    account = models.ForeignKey(
        "master.Account",
        on_delete=models.PROTECT,
        related_name="journal_entry_lines",
        verbose_name="akun",
        help_text="Akun buku besar (WAJIB punya `odoo_id` sebelum CONFIRMED).",
    )
    partner = models.ForeignKey(
        "master.Partner",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="journal_entry_lines",
        verbose_name="partner",
        help_text="Partner pada baris (opsional; dikirim ke `account.move.line.partner_id`).",
    )
    name = models.CharField(
        "keterangan",
        max_length=255,
        blank=True,
        default="",
        help_text="Label baris (dikirim ke `account.move.line.name`).",
    )
    debit = models.DecimalField(
        "debit", max_digits=18, decimal_places=2, default=0, help_text="Nilai debit (>= 0)."
    )
    credit = models.DecimalField(
        "kredit", max_digits=18, decimal_places=2, default=0, help_text="Nilai kredit (>= 0)."
    )
    created_at = models.DateTimeField("dibuat pada", auto_now_add=True)
    updated_at = models.DateTimeField("diubah pada", auto_now=True)

    class Meta:
        verbose_name = "Journal Entry Line"
        verbose_name_plural = "Journal Entry Lines"
        ordering = ("id",)
        constraints = (
            # Tidak boleh negatif (nilai negatif di Odoo = membalik sisi; MES tidak
            # mengizinkan supaya Σ debit/Σ kredit tetap bermakna).
            models.CheckConstraint(
                check=Q(debit__gte=0) & Q(credit__gte=0),
                name="chk_journal_entry_line_non_negatif",
            ),
            # XOR: satu baris hanya boleh debit ATAU kredit (tidak keduanya > 0).
            models.CheckConstraint(
                check=~(Q(debit__gt=0) & Q(credit__gt=0)),
                name="chk_journal_entry_line_xor",
            ),
        )

    def __str__(self) -> str:
        return f"{self.account_id}: D={self.debit} K={self.credit}"
