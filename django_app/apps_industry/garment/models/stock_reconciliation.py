"""Model `StockReconciliation` — hasil rekonsiliasi stok MES vs Odoo (fase I7).

Satu baris = satu **produk** pada satu kali *run* rekonsiliasi:

  * ``mes_qty``  — stok yang dicatat MES (WIP + FG, dari bundle di lantai);
  * ``odoo_qty`` — on-hand Odoo (``stock.quant.quantity``) di seluruh lokasi
    ``usage='internal'`` (termasuk lokasi anak);
  * ``diff``     — ``mes_qty - odoo_qty``;
  * ``is_alert`` — ``True`` kalau ``|diff|`` melebihi toleransi
    ``max(RECONCILIATION_TOLERANCE_UNITS, RECONCILIATION_TOLERANCE_PCT × mes_qty)``.

Model ini **laporan append-only per run**, bukan mirror Odoo: ``product`` boleh
``NULL`` (produk belum tersinkron ke master — baris tetap disimpan sebagai
referensi) dan ``product_odoo_id`` disimpan sebagai cache kunci pembanding
supaya baris lama tetap bisa dibaca walau master berubah.
"""

from __future__ import annotations

from django.db import models


class StockReconciliation(models.Model):
    """Satu baris hasil rekonsiliasi stok untuk satu produk."""

    run_at = models.DateTimeField(
        "dijalankan pada",
        auto_now_add=True,
        help_text="Waktu run rekonsiliasi (auto); satu run = satu kelompok baris.",
    )
    product = models.ForeignKey(
        "master.Product",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="stock_reconciliations",
        verbose_name="produk",
        help_text="Produk master; NULL kalau produk belum ada di master.",
    )
    product_odoo_id = models.PositiveBigIntegerField(
        "id produk Odoo",
        help_text=(
            "Cache id product.product Odoo (kunci pembanding dengan MES). "
            "Selalu positif — konsisten konvensi repo untuk kolom odoo_id "
            "(utang teknis I8.4)."
        ),
    )
    mes_qty = models.FloatField("qty MES", default=0)
    odoo_qty = models.FloatField("qty Odoo", default=0)
    diff = models.FloatField(
        "selisih",
        default=0,
        help_text="mes_qty - odoo_qty.",
    )
    is_alert = models.BooleanField(
        "perlu tindak lanjut",
        default=False,
        help_text="True kalau |diff| melebihi toleransi.",
    )
    notes = models.TextField("catatan", blank=True, default="")

    class Meta:
        verbose_name = "Stock Reconciliation"
        verbose_name_plural = "Stock Reconciliation"
        ordering = ("-run_at",)
        indexes = [
            models.Index(fields=["run_at"], name="stock_recon_run_at_idx"),
            models.Index(fields=["product_odoo_id"], name="stock_recon_odoo_id_idx"),
        ]

    def __str__(self) -> str:
        return (
            f"#{self.product_odoo_id} MES={self.mes_qty} "
            f"Odoo={self.odoo_qty} diff={self.diff}"
        )
