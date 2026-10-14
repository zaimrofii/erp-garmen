"""Model app `core.cycle_handler` — definisi siklus/rework loop (generik).

Prinsip blueprint: rework = **sub-process yang dikonfigurasi**, bukan logika
khusus garmen. Definisi siklus (mis. QC -> Sewing -> QC) disimpan di DB:

  * ``CycleDefinition`` — header siklus + batas iterasi (`max_iterations`);
  * ``CycleStep``       — langkah siklus, dipicu `action_id` (mis. "QC_REJECT");
  * ``CycleInstance``   — instance yang menempel ke entitas bisnis apa pun lewat
    pasangan (``ref_type``, ``ref_id``) — mis. ("bundle", "BND-0001").

Referensi ke entitas domain sengaja berupa **string, bukan FK**: `core` tidak
boleh tahu model garmen (module boundary), dan pola ini dipakai konsisten oleh
modul core lain.

Eksekusi (start/advance/rework/complete/cancel) ada di
`core/cycle_handler/services.py`.
"""

from __future__ import annotations

from django.db import models


class CycleDefinition(models.Model):
    """Definisi satu siklus/rework loop (configurable)."""

    code = models.SlugField("kode", max_length=64, unique=True)
    name = models.CharField("nama", max_length=150)
    description = models.TextField("deskripsi", blank=True, default="")
    max_iterations = models.PositiveIntegerField(
        "maksimum iterasi",
        default=3,
        help_text="Batas iterasi rework sebelum instance dianggap EXHAUSTED.",
    )
    is_active = models.BooleanField("aktif", default=True)
    created_at = models.DateTimeField("dibuat pada", auto_now_add=True)
    updated_at = models.DateTimeField("diubah pada", auto_now=True)

    class Meta:
        verbose_name = "Cycle Definition"
        verbose_name_plural = "Cycle Definitions"
        ordering = ("code",)

    def __str__(self) -> str:
        return f"{self.code} (max_iterations={self.max_iterations})"


class CycleStep(models.Model):
    """Satu langkah siklus (mis. QC reject, sewing ulang)."""

    definition = models.ForeignKey(
        CycleDefinition,
        on_delete=models.CASCADE,
        related_name="steps",
        verbose_name="definisi siklus",
    )
    order = models.PositiveIntegerField("urutan", default=0)
    action_id = models.SlugField(
        "action id",
        max_length=64,
        help_text='Aksi pemicu perpindahan ke step ini, mis. "QC_REJECT".',
    )
    is_terminal = models.BooleanField(
        "step terminal",
        default=False,
        help_text="Kalau True, instance dianggap selesai saat masuk step ini.",
    )
    label = models.CharField("label", max_length=150, blank=True, default="")

    class Meta:
        verbose_name = "Cycle Step"
        verbose_name_plural = "Cycle Steps"
        ordering = ("definition", "order")
        constraints = [
            models.UniqueConstraint(
                fields=["definition", "order"],
                name="uniq_cycle_step_order_per_definition",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.definition.code}#{self.order} {self.action_id}"


class CycleInstance(models.Model):
    """Instance siklus untuk satu entitas bisnis (`ref_type` + `ref_id`)."""

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        COMPLETED = "COMPLETED", "Completed"
        EXHAUSTED = "EXHAUSTED", "Exhausted"
        CANCELLED = "CANCELLED", "Cancelled"

    definition = models.ForeignKey(
        CycleDefinition,
        on_delete=models.PROTECT,
        related_name="instances",
        verbose_name="definisi siklus",
    )
    ref_type = models.CharField(
        "tipe referensi",
        max_length=64,
        help_text='Jenis entitas pemilik siklus, mis. "bundle" atau "work_order".',
    )
    ref_id = models.CharField(
        "id referensi",
        max_length=64,
        help_text="ID entitas di app domain (string, bukan FK).",
    )
    current_step = models.ForeignKey(
        CycleStep,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="instances",
        verbose_name="step saat ini",
    )
    iteration_count = models.PositiveIntegerField("jumlah iterasi", default=0)
    status = models.CharField(
        "status",
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    started_at = models.DateTimeField("mulai pada", auto_now_add=True)
    updated_at = models.DateTimeField("diubah pada", auto_now=True)

    class Meta:
        verbose_name = "Cycle Instance"
        verbose_name_plural = "Cycle Instances"
        ordering = ("-started_at",)
        indexes = [
            models.Index(fields=["ref_type", "ref_id"], name="cycle_ref_type_id_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.definition.code}:{self.ref_type}#{self.ref_id} [{self.status}]"

