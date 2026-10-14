"""Model `ScrapAccumulator` — akumulasi scrap per work center per bundle.

Blueprint memisahkan tiga jenis kehilangan supaya bisa dianalisis terpisah:

  * ``qty``          — scrap total (dibuang);
  * ``rework_qty``   — qty yang masuk loop rework (masih bisa diselamatkan);
  * ``end_loss_qty`` — kehilangan di akhir (end-loss), mis. sisa potongan.

Baris diakumulasi per (work_center, bundle) — constraint unik dijaga di DB
supaya penulisan paralel dari beberapa perangkat tidak membuat baris dobel.

Catatan: ``bundle`` boleh NULL (scrap non-bundle). Di PostgreSQL, NULL tidak
dianggap sama, jadi kombinasi (work_center, NULL) boleh lebih dari satu baris —
perilaku ini sengaja dibiarkan untuk mencatat kehilangan umum per work center.
"""

from __future__ import annotations

from django.db import models


class ScrapAccumulator(models.Model):
    """Akumulator scrap/rework/end-loss untuk satu work center."""

    work_center = models.ForeignKey(
        "garment.WorkCenter",
        on_delete=models.PROTECT,
        related_name="scraps",
        verbose_name="work center",
    )
    bundle = models.ForeignKey(
        "garment.Bundle",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="scraps",
        verbose_name="bundle",
    )
    qty = models.PositiveIntegerField("qty scrap", default=0)
    rework_qty = models.PositiveIntegerField("qty rework", default=0)
    end_loss_qty = models.PositiveIntegerField("qty end-loss", default=0)
    reason = models.CharField("alasan", max_length=150, blank=True, default="")
    notes = models.TextField("catatan", blank=True, default="")
    created_at = models.DateTimeField("dibuat pada", auto_now_add=True)
    updated_at = models.DateTimeField("diubah pada", auto_now=True)

    class Meta:
        verbose_name = "Scrap Accumulator"
        verbose_name_plural = "Scrap Accumulators"
        ordering = ("work_center", "bundle")
        constraints = [
            models.UniqueConstraint(
                fields=["work_center", "bundle"],
                name="uniq_scrap_per_wc_bundle",
            ),
        ]

    def __str__(self) -> str:
        bundle_code = self.bundle.code if self.bundle_id else "-"
        return f"{self.work_center.code}/{bundle_code}: scrap={self.qty}"
