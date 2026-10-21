"""Model domain garment untuk analytics: `MetricSnapshot` (append-only).

Kontrak: docs/analytics/CONTRACT.md §2 (shape) & §10 (append-only).
Snapshot TIDAK dihapus saat toggle OFF (TOGGLE-CONTRACT §3.4).
"""

from __future__ import annotations

from django.db import models


class MetricSnapshot(models.Model):
    """Satu baris snapshot metrik (append-only; upsert by unique key)."""

    metric_id = models.CharField("metric id", max_length=100, db_index=True)
    granularity = models.CharField("granularity", max_length=20)  # hour|day
    dimension_key = models.CharField(
        "dimensi", max_length=200, blank=True, default="", db_index=True
    )  # mis. "wc:12" / "line:5" / "" untuk total
    period_start = models.DateTimeField("awal periode", db_index=True)
    period_end = models.DateTimeField("akhir periode")
    value = models.DecimalField(
        "nilai", max_digits=18, decimal_places=6, null=True, blank=True
    )  # null = denominator nol
    extra = models.JSONField("data tambahan", default=dict, blank=True)
    computed_at = models.DateTimeField("dihitung pada", auto_now_add=True)
    formula_version = models.CharField("versi formula", max_length=20, default="1.0")

    class Meta:
        db_table = "analytics_metric_snapshot"
        verbose_name = "Metric Snapshot"
        verbose_name_plural = "Metric Snapshots"
        ordering = ("-period_start",)
        unique_together = [
            ("metric_id", "granularity", "dimension_key", "period_start"),
        ]

    def __str__(self) -> str:
        return f"{self.metric_id} [{self.granularity}] {self.dimension_key}: {self.value}"

