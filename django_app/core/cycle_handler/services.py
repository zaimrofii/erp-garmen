"""CycleHandler — eksekusi siklus/rework loop generik (stateless).

Handler ini **tidak** tahu model garmen: ia hanya bekerja dengan
`CycleDefinition`/`CycleStep`/`CycleInstance`, dan referensi entitasnya berupa
string (`ref_type` + `ref_id`). App domain yang memanggilnya, mis.::

    handler = CycleHandler()
    instance = handler.start("REWORK_QC", "bundle", "BND-0001")
    instance = handler.advance(instance, "QC_REJECT")   # QC -> Sewing
    if handler.is_exhausted(instance):
        ...  # eskalasi ke supervisor

Aturan penting:

  * `advance()` menaikkan `iteration_count` **hanya jika** step tujuan adalah
    step awal (artinya satu putaran rework baru dimulai), lalu langsung mengecek
    `max_iterations` -> status EXHAUSTED;
  * `record_rework()` menaikkan `iteration_count` **tanpa** memindahkan step
    (dipakai kalau pemanggil mengurus perpindahan step sendiri). Jangan
    memanggil keduanya untuk satu kejadian rework yang sama (terhitung dobel);
  * semua kegagalan (definisi/step tidak ada, instance bukan ACTIVE) di-raise
    sebagai `CycleHandlerError` (subclass `ValidationError`).
"""

from __future__ import annotations

import logging

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import CycleDefinition, CycleInstance

logger = logging.getLogger(__name__)


class CycleHandlerError(ValidationError):
    """Error cycle handler (definisi/step tidak valid, status bukan ACTIVE, ...)."""


class CycleHandler:
    """Operasi siklus: start / advance / record_rework / complete / cancel."""

    def start(self, cycle_code: str, ref_type: str, ref_id: str) -> CycleInstance:
        """Ambil instance ACTIVE yang sudah ada (**idempotent**) atau buat baru.

        Instance baru selalu ditempatkan di step pertama (`order` terkecil).
        """
        definition = self._get_definition(cycle_code)
        ref_type = str(ref_type)
        ref_id = str(ref_id)

        existing = (
            CycleInstance.objects.filter(
                definition=definition,
                ref_type=ref_type,
                ref_id=ref_id,
                status=CycleInstance.Status.ACTIVE,
            )
            .select_related("current_step", "definition")
            .first()
        )
        if existing is not None:
            return existing

        first_step = definition.steps.order_by("order").first()
        if first_step is None:
            raise CycleHandlerError(f"definisi siklus '{cycle_code}' belum punya step.")

        instance = CycleInstance.objects.create(
            definition=definition,
            ref_type=ref_type,
            ref_id=ref_id,
            current_step=first_step,
            status=CycleInstance.Status.ACTIVE,
        )
        logger.info(
            "siklus '%s' dimulai untuk %s#%s (step awal: %s).",
            definition.code,
            ref_type,
            ref_id,
            first_step.action_id,
        )
        return instance

    @transaction.atomic
    def advance(self, instance: CycleInstance, action_id: str) -> CycleInstance:
        """Pindahkan instance ke step yang dipicu `action_id`.

        - step tujuan `is_terminal` -> status COMPLETED;
        - step tujuan = step awal (satu putaran baru) -> `iteration_count += 1`,
          dan kalau sudah mencapai `max_iterations` -> status EXHAUSTED.
        """
        self._ensure_active(instance)
        action_id = str(action_id)

        target = instance.definition.steps.filter(action_id=action_id).first()
        if target is None:
            raise CycleHandlerError(
                f"action '{action_id}' tidak ada di siklus "
                f"'{instance.definition.code}'."
            )

        first_step = instance.definition.steps.order_by("order").first()
        is_new_iteration = first_step is not None and target.pk == first_step.pk

        instance.current_step = target
        update_fields = ["current_step", "updated_at"]

        if is_new_iteration:
            instance.iteration_count += 1
            update_fields.append("iteration_count")

        if target.is_terminal:
            instance.status = CycleInstance.Status.COMPLETED
        elif (
            is_new_iteration
            and instance.iteration_count >= instance.definition.max_iterations
        ):
            instance.status = CycleInstance.Status.EXHAUSTED
        else:
            instance.status = CycleInstance.Status.ACTIVE
        update_fields.append("status")

        instance.save(update_fields=update_fields)
        logger.info(
            "siklus '%s' %s#%s -> step '%s' (iterasi=%d, status=%s).",
            instance.definition.code,
            instance.ref_type,
            instance.ref_id,
            target.action_id,
            instance.iteration_count,
            instance.status,
        )
        return instance

    @transaction.atomic
    def record_rework(self, instance: CycleInstance) -> CycleInstance:
        """Catat satu iterasi rework **tanpa** memindahkan step.

        Setelah `iteration_count += 1`, kalau sudah mencapai `max_iterations`
        status menjadi EXHAUSTED (butuh keputusan manusia).
        """
        self._ensure_active(instance)
        instance.iteration_count += 1

        if instance.iteration_count >= instance.definition.max_iterations:
            instance.status = CycleInstance.Status.EXHAUSTED

        instance.save(update_fields=["iteration_count", "status", "updated_at"])
        logger.info(
            "siklus '%s' %s#%s iterasi ke-%d (max=%d, status=%s).",
            instance.definition.code,
            instance.ref_type,
            instance.ref_id,
            instance.iteration_count,
            instance.definition.max_iterations,
            instance.status,
        )
        return instance

    def is_exhausted(self, instance: CycleInstance) -> bool:
        """True kalau iterasi sudah habis (status EXHAUSTED atau count >= max)."""
        if instance.status == CycleInstance.Status.EXHAUSTED:
            return True
        return instance.iteration_count >= instance.definition.max_iterations

    def complete(self, instance: CycleInstance) -> CycleInstance:
        """Tandai siklus selesai (idempotent; CANCELLED tidak bisa diselesaikan)."""
        if instance.status == CycleInstance.Status.CANCELLED:
            raise CycleHandlerError(
                f"instance {instance.pk} sudah CANCELLED, tidak bisa di-complete."
            )

        instance.status = CycleInstance.Status.COMPLETED
        instance.save(update_fields=["status", "updated_at"])
        logger.info("siklus instance %s di-complete.", instance.pk)
        return instance

    def cancel(self, instance: CycleInstance, reason: str = "") -> CycleInstance:
        """Batalkan siklus.

        `reason` dicatat di **log** (model `CycleInstance` sengaja tidak menambah
        kolom baru di Sprint 1.2); kalau nanti perlu persistensi, tinggal tambah
        field + migration kecil.
        """
        instance.status = CycleInstance.Status.CANCELLED
        instance.save(update_fields=["status", "updated_at"])
        logger.info(
            "siklus instance %s dibatalkan. alasan: %s", instance.pk, reason or "-"
        )
        return instance

    # ---------------------------------------------------------------- internal
    @staticmethod
    def _get_definition(cycle_code: str) -> CycleDefinition:
        definition = CycleDefinition.objects.filter(
            code=cycle_code, is_active=True
        ).first()
        if definition is None:
            raise CycleHandlerError(
                f"definisi siklus '{cycle_code}' tidak ditemukan atau tidak aktif."
            )
        return definition

    @staticmethod
    def _ensure_active(instance: CycleInstance) -> None:
        if instance.status != CycleInstance.Status.ACTIVE:
            raise CycleHandlerError(
                f"instance {instance.pk} berstatus {instance.status}; "
                "hanya instance ACTIVE yang bisa dilanjutkan."
            )
