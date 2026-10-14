"""Model ``PrintJob`` — audit trail percobaan cetak (Fase 5).

Satu baris = satu percobaan cetak (bundle tag / kupon) ke satu backend beserta
hasilnya. Manfaatnya di lantai produksi:

  * tahu tag/kupon mana yang **sudah** dicetak (dan berapa kali) waktu tag fisik
    hilang atau rusak;
  * error terakhir tersimpan, jadi supervisor bisa melihat masalah printer
    (offline, kertas habis, IP salah) tanpa membaca log container.

Catatan: **tanpa** unique constraint — mencetak ulang tag yang sama adalah hal
normal (mis. tag rusak), jadi setiap percobaan adalah baris baru.
"""

from __future__ import annotations

from django.db import models


class PrintJob(models.Model):
    """Catatan satu percobaan cetak."""

    class Resource(models.TextChoices):
        BUNDLE = "bundle", "Bundle tag"
        COUPON = "coupon", "Kupon piece-rate"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Menunggu"
        SENT = "SENT", "Terkirim ke printer"
        FAILED = "FAILED", "Gagal"

    resource = models.CharField(
        "resource",
        max_length=32,
        choices=Resource.choices,
        db_index=True,
        help_text='Jenis cetakan: "bundle" (tag) atau "coupon" (kupon).',
    )
    resource_id = models.CharField(
        "id resource",
        max_length=64,
        db_index=True,
        help_text="PK objek sumber yang dicetak (bundle id / order line id).",
    )
    backend = models.CharField(
        "backend",
        max_length=32,
        default="mock",
        help_text='Backend yang dipakai: "mock" / "usb" / "network".',
    )
    status = models.CharField(
        "status",
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    bytes_sent = models.PositiveIntegerField(
        "bytes terkirim", null=True, blank=True, help_text="Kosong kalau belum terkirim."
    )
    last_error = models.TextField(
        "error terakhir", blank=True, default="", help_text="Diisi kalau status FAILED."
    )
    ref = models.CharField(
        "ref",
        max_length=64,
        blank=True,
        default="",
        help_text="Penanda job (mis. kode bundle/kupon) — dicocokkan dengan file mock.",
    )
    created_at = models.DateTimeField("dibuat pada", auto_now_add=True)
    updated_at = models.DateTimeField("diperbarui pada", auto_now=True)

    class Meta:
        verbose_name = "Print Job"
        verbose_name_plural = "Print Jobs"
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.resource}#{self.resource_id} [{self.status}] via {self.backend}"
