"""Model `LineAllocationRule` — aturan alokasi work center ke lini produksi (F3A.2 / B25).

Satu aturan = "work center bertipe ``wc_type`` sebaiknya dialokasikan ke lini
``line`` dengan prioritas ``priority``" (+ ``config`` bebas untuk parameter
tambahan seperti kapasitas/shift).

Dipakai halaman *Line Allocation* (settings) dan nantinya oleh
line allocator berbasis capability (Sprint 2.2).
"""

from __future__ import annotations

from django.db import models


class LineAllocationRule(models.Model):
    """Aturan alokasi: tipe work center -> lini produksi (+ prioritas/config)."""

    name = models.CharField("nama", max_length=150)
    wc_type = models.CharField(
        "tipe work center",
        max_length=64,
        db_index=True,
        help_text='Jenis work center, mis. "SEWING", "CUTTING", "QC".',
    )
    line = models.ForeignKey(
        "garment.ProductionLine",
        on_delete=models.CASCADE,
        related_name="allocation_rules",
        verbose_name="lini produksi",
    )
    priority = models.IntegerField(
        "prioritas",
        default=0,
        help_text="Angka BESAR = lebih diprioritaskan (konsisten prioritas Order).",
    )
    is_active = models.BooleanField("aktif", default=True)
    config = models.JSONField(
        "konfigurasi",
        default=dict,
        blank=True,
        help_text="Parameter tambahan bebas (mis. kapasitas per shift).",
    )
    created_at = models.DateTimeField("dibuat pada", auto_now_add=True)
    updated_at = models.DateTimeField("diubah pada", auto_now=True)

    class Meta:
        verbose_name = "Line Allocation Rule"
        verbose_name_plural = "Line Allocation Rules"
        ordering = ("-priority", "name")

    def __str__(self) -> str:
        return f"{self.name} [{self.wc_type}] -> line={self.line_id}"
