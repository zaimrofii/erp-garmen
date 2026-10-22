"""Model inti analytics (Sprint B.2).

`AnalyticsConfig` = singleton konfigurasi toggle (TOGGLE-CONTRACT §2).
`MetricSnapshot` didefinisikan di plugin garment (model domain), lalu
**diimpor di sini** supaya Django mendaftarkannya ke app `analytics` — file
plugin bukan app Django terpisah, jadi tanpa import ini `makemigrations`
tidak akan menemukan model tersebut.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from .plugins.garment.models import MetricSnapshot  # noqa: F401  (registrasi model)

__all__ = ("AnalyticsConfig", "DailySummary", "Document", "MetricSnapshot")


class AnalyticsConfig(models.Model):
    """Konfigurasi analytics — **singleton** (pk=1), default OFF."""

    enabled = models.BooleanField("aktif", default=False)
    enabled_domains = models.JSONField("domain aktif", default=list, blank=True)
    enabled_metrics = models.JSONField("metrik aktif", default=list, blank=True)
    data_readiness_acknowledged_at = models.DateTimeField(
        "readiness terakhir lolos", null=True, blank=True
    )
    enabled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        verbose_name="diaktifkan oleh",
    )
    enabled_at = models.DateTimeField("diaktifkan pada", null=True, blank=True)
    disabled_reason = models.TextField(
        "kode alasan OFF", default="not_yet_enabled", blank=True
    )
    updated_at = models.DateTimeField("diubah pada", auto_now=True)

    class Meta:
        db_table = "analytics_analyticsconfig"
        verbose_name = "Analytics Config"
        verbose_name_plural = "Analytics Config"

    def save(self, *args, **kwargs):
        """Paksa pk=1 supaya tidak pernah ada baris kedua (singleton)."""
        self.pk = 1
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"AnalyticsConfig(enabled={self.enabled})"


class Document(models.Model):
    """Dokumen SOP/QC untuk pencarian (TEMPORARY — ganti ChromaDB)."""

    title = models.CharField("judul", max_length=200)
    content = models.TextField("isi")
    category = models.CharField("kategori", max_length=80, blank=True, default="")
    tags = models.JSONField("tag", default=list, blank=True)
    uploaded_at = models.DateTimeField("diunggah", auto_now_add=True)

    class Meta:
        db_table = "analytics_document"
        verbose_name = "Document"
        verbose_name_plural = "Documents"
        ordering = ("title",)

    def __str__(self) -> str:
        return f"{self.title} [{self.category}]"


class DailySummary(models.Model):
    """Ringkasan harian (L2/L3) — TEMPORARY sampai summary store penuh."""

    date = models.DateField("tanggal", unique=True)
    total_output = models.FloatField("total output", default=0)
    total_scrap = models.FloatField("total scrap", default=0)
    total_rework = models.FloatField("total rework", default=0)
    avg_lead_time = models.FloatField("rata-rata lead time", default=0)
    oee = models.FloatField("oee", default=0)
    top_wc = models.CharField("WC teratas", max_length=120, blank=True, default="")
    top_operator = models.CharField(
        "operator teratas", max_length=120, blank=True, default=""
    )
    computed_at = models.DateTimeField("dihitung pada", auto_now=True)

    class Meta:
        db_table = "analytics_daily_summary"
        verbose_name = "Daily Summary"
        verbose_name_plural = "Daily Summaries"
        ordering = ("-date",)

    def __str__(self) -> str:
        return f"Summary {self.date}: output={self.total_output}"
