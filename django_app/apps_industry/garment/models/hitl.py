"""Model ``HITLRequest`` — antrean approval manusia (Human-in-the-Loop, F5.4.2).

Agen AI (dan aksi otomatis lain) **tidak** mengeksekusi tindakan berdampak
sendiri: ia mengajukan permintaan approval ke tabel ini, lalu supervisor/admin
memutuskan lewat ``POST /api/v1/ai/hitl/<id>/approve|reject/``.

Desain:

  * **generik** — ``request_type`` + ``resource_type``/``resource_id`` (string) +
    ``payload`` JSON, jadi jenis permintaan baru tidak butuh kolom/migration baru
    (mis. ``OVERLAP_RELEASE`` untuk bundle 42);
  * **state machine sederhana** — ``PENDING`` → ``APPROVED`` / ``REJECTED`` /
    ``EXPIRED``;
  * ``expires_at`` boleh NULL (tanpa kedaluwarsa). Penandaan otomatis ``EXPIRED``
    **belum** ada (butuh task beat) — lihat `docs/known-limitations.md`;
  * **standalone** (keputusan F5.4.2): belum ada hook otomatis dari
    ``ActionExecutor``; pemanggil (agen/endpoint lain) mengisi baris lewat ORM.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models


class HITLRequest(models.Model):
    """Satu permintaan approval (lihat docstring modul)."""

    class State(models.TextChoices):
        """State permintaan; ``PENDING`` = menunggu keputusan."""

        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        EXPIRED = "EXPIRED", "Expired"

    class Priority(models.TextChoices):
        """Prioritas antrean (``URGENT`` paling atas di UI)."""

        LOW = "LOW", "Low"
        MEDIUM = "MEDIUM", "Medium"
        HIGH = "HIGH", "High"
        URGENT = "URGENT", "Urgent"

    request_type = models.CharField("tipe permintaan", max_length=64)
    resource_type = models.CharField("tipe resource", max_length=32)
    resource_id = models.CharField("id resource", max_length=64)
    payload = models.JSONField("payload", default=dict, blank=True)
    reason = models.TextField("alasan", blank=True, default="")

    state = models.CharField(
        "state",
        max_length=16,
        choices=State.choices,
        default=State.PENDING,
    )

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="hitl_requests",
        verbose_name="peminta",
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="hitl_decisions",
        verbose_name="pemutus",
    )
    decided_at = models.DateTimeField("diputuskan pada", null=True, blank=True)
    decision_note = models.TextField("catatan keputusan", blank=True, default="")

    priority = models.CharField(
        "prioritas",
        max_length=8,
        choices=Priority.choices,
        default=Priority.MEDIUM,
    )
    expires_at = models.DateTimeField("kedaluwarsa", null=True, blank=True)

    created_at = models.DateTimeField("dibuat pada", auto_now_add=True)
    updated_at = models.DateTimeField("diubah pada", auto_now=True)

    class Meta:
        verbose_name = "HITL Request"
        verbose_name_plural = "HITL Requests"
        ordering = ("-created_at",)
        indexes = (
            models.Index(fields=["state", "-created_at"], name="hitl_state_created_idx"),
            models.Index(fields=["resource_type", "resource_id"], name="hitl_resource_idx"),
        )

    def __str__(self) -> str:
        return f"HITL#{self.pk} {self.request_type} [{self.state}]"
