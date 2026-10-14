"""Model `BundleEvent` — jejak audit append-only per bundle.

Setiap aksi operator (scan mulai/selesai, scrap, pindah WC, rework) ditulis satu
baris di sini. Tabel ini sengaja **append-only**:

  * primary key ``UUID`` supaya ID bisa dibuat di client/offline (Fase 2:
    IndexedDB) tanpa bentrok dan tanpa round-trip ke server;
  * ``ts`` = waktu kejadian (auto_now_add) — sekaligus berlaku sebagai
    ``created_at``; tidak ada ``updated_at`` karena event tidak pernah diubah.

Event diterbitkan juga lewat core event bus (`core.event_bus.publisher`) supaya
listener sinkron/async bisa bereaksi (Sprint 2.2+).
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class BundleEvent(models.Model):
    """Satu peristiwa pada satu bundle (log audit)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bundle = models.ForeignKey(
        "garment.Bundle",
        on_delete=models.CASCADE,
        related_name="events",
        verbose_name="bundle",
    )
    ts = models.DateTimeField("waktu", auto_now_add=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bundle_events",
        verbose_name="aktor",
    )
    event_type = models.CharField(
        "tipe event",
        max_length=64,
        db_index=True,
        help_text='Mis. "BUNDLE_START", "BUNDLE_FINISH", "SCRAP", "REWORK".',
    )
    text = models.TextField("keterangan", blank=True, default="")
    payload = models.JSONField(
        "payload",
        default=dict,
        blank=True,
        help_text="Data pendukung event (harus JSON-serializable).",
    )

    class Meta:
        verbose_name = "Bundle Event"
        verbose_name_plural = "Bundle Events"
        ordering = ("-ts",)
        indexes = [
            models.Index(fields=["bundle", "ts"], name="bundle_event_bundle_ts_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.bundle.code} {self.event_type} @{self.ts:%Y-%m-%d %H:%M}"
