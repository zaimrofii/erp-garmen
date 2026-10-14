"""Model ``AuditLog`` — jejak audit aksi penting (Fase 6, hardening).

Satu baris = satu aksi yang mengubah data atau memicu proses (aksi operator,
sync ERP, cetak, dsb) beserta hasilnya. Manfaatnya:

  * menjawab "siapa memicu/mengubah apa, kapan, dari device mana" waktu ada
    selisih angka produksi;
  * menautkan catatan audit ke log aplikasi lewat ``request_id``
    (header ``X-Request-ID`` yang sama juga dipakai access log).

Index yang disiapkan: ``(timestamp)`` (lewat ``db_index=True``, untuk paging
kronologis), ``(resource, resource_id)`` (riwayat satu bundle/kupon) dan
``(user, timestamp)`` (aktivitas satu operator). Tabel ini append-only:
tidak diubah/dihapus dari admin.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """Satu catatan audit (append-only)."""

    class Result(models.TextChoices):
        OK = "OK", "Berhasil"
        FAILED = "FAILED", "Gagal"
        CONFLICT = "CONFLICT", "Konflik versi (409)"
        DENIED = "DENIED", "Ditolak (izin/validasi)"

    timestamp = models.DateTimeField(
        "waktu", auto_now_add=True, db_index=True, help_text="Saat aksi terjadi (index)."
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
        verbose_name="user",
        help_text="Pelaku; NULL kalau anonim/sistem atau user sudah dihapus.",
    )
    action = models.CharField(
        "aksi", max_length=64, help_text='Mis. "BUNDLE_START" atau "SYNC_WIP".'
    )
    resource = models.CharField("resource", max_length=64, help_text='Mis. "bundles".')
    resource_id = models.CharField("id resource", max_length=64)
    request_id = models.CharField(
        "request id",
        max_length=64,
        blank=True,
        default="",
        help_text="Nilai header X-Request-ID (untuk korelasi dengan log).",
    )
    ip_address = models.GenericIPAddressField("ip", null=True, blank=True)
    user_agent = models.TextField("user agent", blank=True, default="")
    payload = models.JSONField(
        "payload", default=dict, blank=True, help_text="Data yang dikirim/diproses."
    )
    result = models.CharField(
        "hasil", max_length=16, choices=Result.choices, default=Result.OK
    )
    metadata = models.JSONField(
        "metadata", default=dict, blank=True, help_text="Info tambahan (bebas, JSON)."
    )

    class Meta:
        verbose_name = "Audit Log"
        verbose_name_plural = "Audit Logs"
        ordering = ("-timestamp", "-id")
        indexes = (
            models.Index(fields=("resource", "resource_id"), name="audit_resource_idx"),
            models.Index(fields=("user", "timestamp"), name="audit_user_ts_idx"),
        )

    def __str__(self) -> str:
        return f"{self.action} {self.resource}#{self.resource_id} [{self.result}]"
