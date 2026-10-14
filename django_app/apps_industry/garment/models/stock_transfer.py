"""Model `StockTransfer` — **LOG** transfer stok antar lokasi MES → Odoo (H2.6).

Patuh `docs/CHANGES-DETAIL-H1H5.md` §4: **MES TIDAK menyimpan stok**. Transfer hanya
dicatat sebagai jejak audit (siapa memindahkan apa, dari mana, ke mana, berapa) lalu
dikirim SATU ARAH ke Odoo; saldo tetap di Odoo:

  * ``qty``       — jumlah yang dipindahkan (> 0);
  * ``qty_before``— snapshot on-hand lokasi ASAL di Odoo saat dibuat (nullable; **tidak
    memblokir** commit — stok bisa berubah antara snapshot & push, Odoo yang memutuskan);
  * ``odoo_picking_id``/``odoo_picking_name`` — jejak `stock.picking` Odoo (mis.
    ``WH/INT/00003``) hasil `button_validate()`;
  * ``state``     — `DRAFT` (MES-only) → `COMMITTED` (dienqueue) → `SYNCED`/`FAILED`.

TIDAK ada kolom stok/mirror di sini.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models


class StockTransfer(models.Model):
    """Satu baris log transfer stok antar dua lokasi internal (MES → Odoo)."""

    class State(models.TextChoices):
        """Status pengiriman transfer (state machine MES, bukan seed Odoo)."""

        DRAFT = "DRAFT", "Draft (belum dikirim)"
        COMMITTED = "COMMITTED", "Dikirim (menunggu Odoo)"
        SYNCED = "SYNCED", "Tersinkron ke Odoo"
        FAILED = "FAILED", "Gagal (boleh dicoba ulang)"

    #: State yang boleh di-commit (hanya draft).
    COMMITTABLE_STATES: tuple[str, ...] = (State.DRAFT,)

    code = models.CharField(
        "kode",
        max_length=64,
        unique=True,
        help_text="Nomor MES (Sprint C `next_number('TRF')`), mis. TRF-2026-0001.",
    )
    product = models.ForeignKey(
        "master.Product",
        on_delete=models.PROTECT,
        related_name="stock_transfers",
        verbose_name="produk",
    )
    from_location = models.ForeignKey(
        "master.Location",
        on_delete=models.PROTECT,
        related_name="transfers_out",
        verbose_name="lokasi asal",
        help_text="Hanya lokasi usage='internal'.",
    )
    to_location = models.ForeignKey(
        "master.Location",
        on_delete=models.PROTECT,
        related_name="transfers_in",
        verbose_name="lokasi tujuan",
        help_text="Hanya lokasi usage='internal'; WAJIB beda dari lokasi asal.",
    )
    qty = models.DecimalField(
        "qty",
        max_digits=18,
        decimal_places=2,
        help_text="Jumlah yang dipindahkan; WAJIB > 0.",
    )
    qty_before = models.DecimalField(
        "qty asal sebelum",
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Snapshot on-hand lokasi asal di Odoo (stock.quant.quantity) — informatif.",
    )
    reason = models.TextField(
        "catatan",
        blank=True,
        default="",
        help_text="Catatan transfer (opsional) — ikut dikirim sebagai nama move Odoo.",
    )
    state = models.CharField(
        "state",
        max_length=32,
        choices=State.choices,
        default=State.DRAFT,
        db_index=True,
        help_text="DRAFT → COMMITTED → SYNCED/FAILED (MES, bukan seed Odoo).",
    )
    odoo_picking_id = models.PositiveBigIntegerField(
        "id stock.picking Odoo",
        null=True,
        blank=True,
        db_index=True,
        help_text="ID stock.picking internal transfer di Odoo (hasil button_validate).",
    )
    odoo_picking_name = models.CharField(
        "nama picking Odoo",
        max_length=64,
        blank=True,
        default="",
        help_text="Nama picking Odoo (mis. WH/INT/00003) untuk telusur cepat.",
    )
    last_error = models.TextField(
        "error terakhir",
        blank=True,
        default="",
        help_text="Pesan gagal terakhir (mis. stok asal kurang → UserError Odoo).",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_transfers",
        verbose_name="dibuat oleh",
    )
    created_at = models.DateTimeField("dibuat pada", auto_now_add=True)
    updated_at = models.DateTimeField("diubah pada", auto_now=True)

    class Meta:
        verbose_name = "Stock Transfer"
        verbose_name_plural = "Stock Transfers"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["state", "created_at"], name="stock_trf_state_idx"),
            models.Index(fields=["product", "from_location", "to_location"], name="stock_trf_route_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.code} [{self.state}] {self.product_id} {self.from_location_id}→{self.to_location_id} {self.qty}"
