"""Model app `core.state_machine` — definisi state machine (generik).

Prinsip blueprint: **semua aturan = konfigurasi, bukan kode**. Karena itu
definisi state & transisi disimpan di DB (`StateMachine`, `State`, `Transition`)
bukan enum hardcode, sehingga alur berbeda antar klien cukup dikonfigurasi
lewat admin.

Pembagian tanggung jawab:

  * file ini        -> hanya **definisi** (data);
  * `services.py`   -> `StateMachineEngine`: aturan, validasi guard, eksekusi;
  * **state aktual** -> dipegang model domain (mis. `Bundle.state_code` di
    Fase 2), BUKAN di app ini. Itulah yang membuat `core` tetap generik —
    engine tidak perlu tahu siapa pemilik state-nya.
"""

from __future__ import annotations

from django.db import models


class StateMachine(models.Model):
    """Definisi satu mesin state (mis. "BUNDLE", "WORK_ORDER")."""

    code = models.CharField("kode", max_length=64, unique=True)
    name = models.CharField("nama", max_length=150)
    description = models.TextField("deskripsi", blank=True, default="")
    is_active = models.BooleanField("aktif", default=True)
    created_at = models.DateTimeField("dibuat pada", auto_now_add=True)
    updated_at = models.DateTimeField("diubah pada", auto_now=True)

    class Meta:
        verbose_name = "State Machine"
        verbose_name_plural = "State Machines"
        ordering = ("code",)

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class State(models.Model):
    """Node state pada sebuah StateMachine (data, bukan enum di kode)."""

    machine = models.ForeignKey(
        StateMachine,
        on_delete=models.CASCADE,
        related_name="states",
        verbose_name="state machine",
    )
    code = models.CharField("kode", max_length=64)
    label = models.CharField("label", max_length=150, blank=True, default="")
    is_initial = models.BooleanField("state awal", default=False)
    is_terminal = models.BooleanField("state akhir", default=False)
    order = models.PositiveIntegerField("urutan", default=0)

    class Meta:
        verbose_name = "State"
        verbose_name_plural = "States"
        ordering = ("machine", "order", "code")
        constraints = [
            models.UniqueConstraint(
                fields=["machine", "code"],
                name="uniq_state_code_per_machine",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.machine.code}.{self.code}"


class Transition(models.Model):
    """Transisi antar state, diidentifikasi `action_id` (mis. "BUNDLE_START")."""

    class Mode(models.TextChoices):
        """Mode eksekusi: PESSIMISTIC = lock dulu (aman), OPTIMISTIC = cek versi."""

        OPTIMISTIC = "OPTIMISTIC", "Optimistic"
        PESSIMISTIC = "PESSIMISTIC", "Pessimistic"

    machine = models.ForeignKey(
        StateMachine,
        on_delete=models.CASCADE,
        related_name="transitions",
        verbose_name="state machine",
    )
    from_state = models.ForeignKey(
        State,
        on_delete=models.CASCADE,
        related_name="transitions_from",
        verbose_name="dari state",
    )
    to_state = models.ForeignKey(
        State,
        on_delete=models.CASCADE,
        related_name="transitions_to",
        verbose_name="ke state",
    )
    action_id = models.SlugField("action id", max_length=64)
    label = models.CharField("label", max_length=150, blank=True, default="")
    mode = models.CharField(
        "mode",
        max_length=16,
        choices=Mode.choices,
        default=Mode.PESSIMISTIC,
    )
    guard_path = models.CharField(
        "guard path",
        max_length=255,
        blank=True,
        default="",
        help_text=(
            "Dotted path opsional ke callable guard, mis. "
            "'apps_industry.garment.services.guards.can_start_bundle'."
        ),
    )
    is_active = models.BooleanField("aktif", default=True)

    class Meta:
        verbose_name = "Transition"
        verbose_name_plural = "Transitions"
        ordering = ("machine", "from_state", "action_id")
        constraints = [
            # Satu action_id hanya boleh punya satu tujuan dari state yang sama,
            # supaya `can_transition()` tidak ambigu.
            models.UniqueConstraint(
                fields=["machine", "from_state", "action_id"],
                name="uniq_action_per_from_state",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.machine.code}: "
            f"{self.from_state.code} -[{self.action_id}]-> {self.to_state.code}"
        )
