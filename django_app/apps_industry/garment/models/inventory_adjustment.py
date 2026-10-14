"""Model `InventoryAdjustment` — **LOG** adjustment stok MES → Odoo (H2.5).

Patuh `docs/CHANGES-DETAIL-H1H5.md` §4: **MES TIDAK menyimpan stok**. Stok master ada
di Odoo (per lokasi); model ini hanya **jejak audit** siapa menyesuaikan apa, kapan,
berapa, dan apa hasilnya di Odoo:

  * ``qty_delta``  — perubahan yang diminta (boleh negatif);
  * ``qty_before`` — snapshot on-hand Odoo saat baris dibuat/push (nullable);
  * ``qty_after``  — on-hand Odoo setelah apply (nullable; diisi saat sukses);
  * ``odoo_move_id``/``odoo_reference`` — jejak `stock.move` Odoo yang dibuat Odoo
    sendiri di dalam `stock.quant.action_apply_inventory()` (nama move memakai
    ``inventory_name`` = ``<code> <reason>`` supaya bisa ditelusuri dari Odoo);
  * ``state`` — `DRAFT` (MES-only) → `COMMITTED` (dienqueue) → `SYNCED`/`FAILED`.

TIDAK ada kolom stok di sini (tidak ada `qty_on_hand`/mirror) — permintaan on-hand
selalu dibaca **on-demand** dari Odoo (`/api/v1/inventory/stock-qty/`).
"""

from __future__ import annotations

from django.conf import settings
from django.db import models


class InventoryAdjustment(models.Model):
    """Satu baris log adjustment stok (MES → Odoo)."""

    class State(models.TextChoices):
        """Status pengiriman adjustment (state machine MES, bukan seed Odoo)."""

        DRAFT = "DRAFT", "Draft (belum dikirim)"
        COMMITTED = "COMMITTED", "Dikirim (menunggu Odoo)"
        SYNCED = "SYNCED", "Tersinkron ke Odoo"
        FAILED = "FAILED", "Gagal (boleh dicoba ulang)"

    #: State yang boleh di-commit (hanya draft) & yang dianggap final.
    COMMITTABLE_STATES: tuple[str, ...] = (State.DRAFT,)
    FINAL_STATES: tuple[str, ...] = (State.SYNCED, State.FAILED)

    code = models.CharField(
        "kode",
        max_length=64,
        unique=True,
        help_text="Nomor MES (Sprint C `next_number('ADJ')`), mis. ADJ-2026-0001.",
    )
    product = models.ForeignKey(
        "master.Product",
        on_delete=models.PROTECT,
        related_name="inventory_adjustments",
        verbose_name="produk",
    )
    location = models.ForeignKey(
        "master.Location",
        on_delete=models.PROTECT,
        related_name="inventory_adjustments",
        verbose_name="lokasi",
        help_text="Hanya lokasi usage='internal' yang boleh disesuaikan.",
    )
    qty_delta = models.DecimalField(
        "selisih qty",
        max_digits=18,
        decimal_places=2,
        help_text="Perubahan qty (boleh negatif); TIDAK boleh 0.",
    )
    qty_before = models.DecimalField(
        "qty sebelum",
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Snapshot on-hand Odoo (stock.quant.quantity) saat dibuat/dikirim.",
    )
    qty_after = models.DecimalField(
        "qty sesudah",
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="On-hand Odoo setelah adjustment diterapkan (diisi saat SYNCED).",
    )
    reason = models.TextField(
        "alasan",
        blank=True,
        default="",
        help_text="Alasan adjustment (WAJIB di service) — ikut dikirim sebagai nama move Odoo.",
    )
    state = models.CharField(
        "state",
        max_length=32,
        choices=State.choices,
        default=State.DRAFT,
        db_index=True,
        help_text="DRAFT → COMMITTED → SYNCED/FAILED (MES, bukan seed Odoo).",
    )
    odoo_move_id = models.PositiveBigIntegerField(
        "id stock.move Odoo",
        null=True,
        blank=True,
        db_index=True,
        help_text="ID stock.move yang dibuat Odoo saat inventory adjustment di-apply.",
    )
    odoo_reference = models.CharField(
        "referensi Odoo",
        max_length=100,
        blank=True,
        default="",
        help_text="Nilai `inventory_name` yang dikirim (dipakai mencari move di Odoo).",
    )
    last_error = models.TextField(
        "error terakhir",
        blank=True,
        default="",
        help_text="Pesan gagal terakhir (mis. prerequisite grup Inventory/Manager).",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inventory_adjustments",
        verbose_name="dibuat oleh",
    )
    created_at = models.DateTimeField("dibuat pada", auto_now_add=True)
    updated_at = models.DateTimeField("diubah pada", auto_now=True)

    class Meta:
        verbose_name = "Inventory Adjustment"
        verbose_name_plural = "Inventory Adjustments"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["state", "created_at"], name="inv_adj_state_created_idx"),
            models.Index(fields=["product", "location"], name="inv_adj_product_loc_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.code} [{self.state}] {self.product_id}@{self.location_id} {self.qty_delta}"
