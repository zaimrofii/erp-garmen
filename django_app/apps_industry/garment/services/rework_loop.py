"""ReworkLoopHandler — siklus QC rework per bundle (Sprint 2.2).

Rework loop = bentuk **cycle** di blueprint: QC menolak, bundle dikerjakan
ulang, sampai lolos QC atau batas iterasi habis (EXHAUSTED). Definisi siklus
disimpan di `core.cycle_handler` (`CycleDefinition`/`CycleStep`); handler ini
yang menyambungkannya ke entitas garmen lewat `ref_type="bundle"` +
`ref_id=str(bundle.id)`.

Siklus default (dibuat idempotent oleh `_ensure_definition()`):

  * order 1 — ``QC_START`` (mulai inspeksi)
  * order 2 — ``REWORK``   (kembali dikerjakan)
  * order 3 — ``QC_PASS``  (terminal: lulus QC)

Semua state siklus tersimpan di `CycleInstance` (core) — handler tidak
menyimpan state sendiri dan tidak menyentuh `Bundle.state` (itu tugas service
state/API di Fase 3).
"""

from __future__ import annotations

import logging

from core.cycle_handler.models import CycleDefinition, CycleInstance, CycleStep
from core.cycle_handler.services import CycleHandler, CycleHandlerError

from apps_industry.garment.services.exceptions import ReworkLoopError

logger = logging.getLogger(__name__)

REF_TYPE = "bundle"


class ReworkLoopHandler:
    """Jembatan bundle garmen <-> siklus rework di `core.cycle_handler`."""

    CYCLE_CODE = "QC_REWORK"
    STEPS = (
        {"order": 1, "action_id": "QC_START", "label": "Mulai QC", "is_terminal": False},
        {"order": 2, "action_id": "REWORK", "label": "Rework", "is_terminal": False},
        {"order": 3, "action_id": "QC_PASS", "label": "Lulus QC", "is_terminal": True},
    )

    def __init__(self, cycle_code: str = CYCLE_CODE, max_iterations: int = 3):
        self.cycle_code = cycle_code
        self.max_iterations = max_iterations
        self._handler = CycleHandler()

    # -------------------------------------------------------------- definition
    def _ensure_definition(self) -> CycleDefinition:
        """Ambil/buat definisi siklus + step-nya (idempotent, tidak menimpa admin)."""
        definition, created = CycleDefinition.objects.get_or_create(
            code=self.cycle_code,
            defaults={
                "name": "QC Rework",
                "description": "Siklus rework QC: QC_START -> REWORK -> QC_PASS.",
                "max_iterations": self.max_iterations,
            },
        )
        if created:
            logger.info("definisi siklus '%s' dibuat.", self.cycle_code)

        for step in self.STEPS:
            CycleStep.objects.get_or_create(
                definition=definition,
                order=step["order"],
                defaults={
                    "action_id": step["action_id"],
                    "label": step["label"],
                    "is_terminal": step["is_terminal"],
                },
            )
        return definition

    # ---------------------------------------------------------------- instances
    @staticmethod
    def _ref_id(bundle) -> str:
        if bundle is None or bundle.pk is None:
            raise ReworkLoopError("bundle wajib diisi dan sudah tersimpan.")
        return str(bundle.pk)

    def _instances(self, bundle):
        return CycleInstance.objects.filter(
            definition__code=self.cycle_code,
            ref_type=REF_TYPE,
            ref_id=self._ref_id(bundle),
        )

    def _active_instance(self, bundle) -> CycleInstance | None:
        return (
            self._instances(bundle)
            .filter(status=CycleInstance.Status.ACTIVE)
            .order_by("-started_at")
            .first()
        )

    def _latest_instance(self, bundle) -> CycleInstance | None:
        return self._instances(bundle).order_by("-started_at").first()

    # --------------------------------------------------------------- operations
    def start_qc_rework(self, bundle) -> CycleInstance:
        """Mulai (atau ambil, idempotent) siklus QC rework untuk bundle."""
        self._ensure_definition()
        try:
            return self._handler.start(self.cycle_code, REF_TYPE, self._ref_id(bundle))
        except CycleHandlerError as exc:
            raise ReworkLoopError(str(exc)) from exc

    def record_rework(self, bundle) -> CycleInstance:
        """Catat satu iterasi rework pada instance yang sedang ACTIVE."""
        instance = self._active_instance(bundle)
        if instance is None:
            raise ReworkLoopError(
                f"bundle {self._ref_id(bundle)} tidak punya siklus "
                f"'{self.cycle_code}' yang ACTIVE; panggil start_qc_rework() dulu."
            )
        return self._handler.record_rework(instance)

    def is_exhausted(self, bundle) -> bool:
        """True kalau siklus terakhir bundle sudah EXHAUSTED / iterasi mencapai batas."""
        instance = self._latest_instance(bundle)
        if instance is None:
            return False
        return self._handler.is_exhausted(instance)

    def complete(self, bundle) -> CycleInstance:
        """Tandai siklus selesai (lulus QC atau ditutup manual)."""
        instance = self._active_instance(bundle) or self._latest_instance(bundle)
        if instance is None:
            raise ReworkLoopError(
                f"bundle {self._ref_id(bundle)} belum punya siklus '{self.cycle_code}'."
            )
        return self._handler.complete(instance)
