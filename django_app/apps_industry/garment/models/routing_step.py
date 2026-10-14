"""Model `RoutingStep` — node DAG pada sebuah ``ProcessRouting``.

  * ``allowed_next_steps`` — edge DAG (M2M ke diri sendiri, **tidak** simetris):
    dari step ini boleh lanjut ke step mana saja di daftar.
  * ``rework_target_step`` — kalau QC menolak, bundle dikembalikan ke step ini
    (self-FK). Ini yang membuat alur produksi bukan DAG murni, melainkan
    DAG + rework loop (lihat `core.cycle_handler`).

Konsistensi DAG (tidak boleh ada siklus, minimal satu step awal) divalidasi di
service layer (Sprint 2.2), bukan di model.
"""

from __future__ import annotations

from django.db import models


class RoutingStep(models.Model):
    """Satu tahap proses pada routing (mis. "SABLON", "SEWING", "QC")."""

    routing = models.ForeignKey(
        "garment.ProcessRouting",
        on_delete=models.CASCADE,
        related_name="steps",
        verbose_name="routing",
    )
    code = models.CharField("kode", max_length=64)
    label = models.CharField("label", max_length=150, blank=True, default="")
    order = models.PositiveIntegerField("urutan", default=0)
    is_initial = models.BooleanField("step awal", default=False)
    is_terminal = models.BooleanField("step akhir", default=False)
    work_center = models.ForeignKey(
        "garment.WorkCenter",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="routing_steps",
        verbose_name="work center",
    )
    allowed_next_steps = models.ManyToManyField(
        "self",
        symmetrical=False,
        blank=True,
        related_name="allowed_from",
        verbose_name="step lanjutan yang boleh",
    )
    rework_target_step = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rework_sources",
        verbose_name="step tujuan rework",
    )
    created_at = models.DateTimeField("dibuat pada", auto_now_add=True)
    updated_at = models.DateTimeField("diubah pada", auto_now=True)

    class Meta:
        verbose_name = "Routing Step"
        verbose_name_plural = "Routing Steps"
        ordering = ("routing", "order")
        constraints = [
            models.UniqueConstraint(
                fields=["routing", "code"],
                name="uniq_routing_step_code",
            ),
            models.UniqueConstraint(
                fields=["routing", "order"],
                name="uniq_routing_step_order",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.routing.code}:{self.code}"
