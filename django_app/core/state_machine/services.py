"""StateMachineEngine — aturan transisi generik (tanpa menyimpan state).

Engine sengaja **stateless terhadap instance**: ia hanya membaca definisi
(`StateMachine`, `State`, `Transition`) dan menerima kode state saat ini dari
pemanggil. State aktual dipegang model domain (mis. `Bundle.state_code` di
Fase 2) supaya `core` tetap generik dan tidak tahu bisnis garmen.

Contoh pemakaian::

    engine = StateMachineEngine()
    machine = engine.get_machine("BUNDLE")
    engine.get_allowed_actions(machine, "DRAFT")
    ok, reason = engine.can_transition(machine, "DRAFT", "BUNDLE_START", {})
    transition = engine.execute_transition(machine, "DRAFT", "BUNDLE_START", {})

Kontrak guard (`Transition.guard_path`) — callable dipanggil dengan satu
argumen `context` (dict) dan boleh mengembalikan:

  * ``True``              -> transisi diizinkan
  * ``False``             -> ditolak (alasan default)
  * ``(bool, str)``       -> ditolak/diizinkan + alasan
  * ``ValidationError``   -> ditolak, pesan error dipakai sebagai alasan
  * nilai lain / ``None`` -> **ditolak** (fail-closed) supaya guard yang salah
    tulis tidak diam-diam membuka jalur transisi
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from django.core.exceptions import ValidationError
from django.utils.module_loading import import_string

from .models import State, StateMachine, Transition

logger = logging.getLogger(__name__)


class StateMachineEngineError(ValidationError):
    """Error engine (subclass `ValidationError` supaya ramah DRF/Django)."""


class StateMachineEngine:
    """Mesin aturan transisi generik — semua method stateless."""

    # ------------------------------------------------------------------ lookup
    def get_machine(self, code: str) -> StateMachine:
        """Ambil StateMachine aktif berdasarkan `code`."""
        try:
            return StateMachine.objects.get(code=code, is_active=True)
        except StateMachine.DoesNotExist as exc:
            raise StateMachineEngineError(
                f"state machine '{code}' tidak ditemukan atau tidak aktif."
            ) from exc

    def get_state(self, machine: StateMachine, code: str) -> State:
        """Ambil satu `State` pada `machine`."""
        try:
            return State.objects.get(machine=machine, code=code)
        except State.DoesNotExist as exc:
            raise StateMachineEngineError(
                f"state '{code}' tidak ada di mesin '{machine.code}'."
            ) from exc

    def get_allowed_actions(
        self, machine: StateMachine, current_state_code: str
    ) -> list[Transition]:
        """Semua transisi **aktif** yang boleh dijalankan dari state saat ini."""
        return list(
            Transition.objects.filter(
                machine=machine,
                from_state__code=current_state_code,
                is_active=True,
            )
            .select_related("from_state", "to_state")
            .order_by("action_id")
        )

    def get_transition(
        self, machine: StateMachine, from_code: str, action_id: str
    ) -> Transition:
        """Ambil satu transisi aktif (pasangan `from_state` + `action_id`)."""
        try:
            return Transition.objects.select_related("from_state", "to_state").get(
                machine=machine,
                from_state__code=from_code,
                action_id=action_id,
                is_active=True,
            )
        except Transition.DoesNotExist as exc:
            raise StateMachineEngineError(
                f"action '{action_id}' tidak diizinkan dari state '{from_code}' "
                f"pada mesin '{machine.code}'."
            ) from exc

    # ------------------------------------------------------------------- check
    def can_transition(
        self,
        machine: StateMachine,
        from_code: str,
        action_id: str,
        context: Mapping[str, Any] | None = None,
    ) -> tuple[bool, str]:
        """Cek transisi tanpa mengubah apa pun -> `(diizinkan, alasan)`."""
        try:
            transition = self.get_transition(machine, from_code, action_id)
            guard_ok, guard_reason = self._run_guard(transition, dict(context or {}))
        except StateMachineEngineError as exc:
            return False, self._error_message(exc)

        if not guard_ok:
            return False, guard_reason or f"guard menolak action '{action_id}'."
        return True, f"{from_code} -> {transition.to_state.code}"

    def execute_transition(
        self,
        machine: StateMachine,
        from_code: str,
        action_id: str,
        context: Mapping[str, Any] | None = None,
    ) -> Transition:
        """Validasi (termasuk guard) lalu kembalikan `Transition` yang dipakai.

        Engine **tidak** menyimpan state baru: pemanggil yang menyimpan
        `transition.to_state.code` di model domainnya.

        Raises:
            StateMachineEngineError: transisi tidak diizinkan / guard menolak.
        """
        allowed, reason = self.can_transition(machine, from_code, action_id, context)
        if not allowed:
            raise StateMachineEngineError(reason)

        transition = self.get_transition(machine, from_code, action_id)
        logger.info(
            "transisi '%s' mesin '%s': %s -> %s (mode=%s)",
            action_id,
            machine.code,
            from_code,
            transition.to_state.code,
            transition.mode,
        )
        return transition

    # ------------------------------------------------------------------- guard
    def _run_guard(
        self, transition: Transition, context: Mapping[str, Any]
    ) -> tuple[bool, str]:
        """Jalankan guard transisi (kalau `guard_path` diisi) — lihat kontrak modul."""
        if not transition.guard_path:
            return True, ""

        try:
            guard = import_string(transition.guard_path)
        except ImportError as exc:
            raise StateMachineEngineError(
                f"guard '{transition.guard_path}' tidak bisa di-import: {exc}"
            ) from exc

        try:
            result = guard(dict(context))
        except ValidationError as exc:
            return False, self._error_message(exc)

        if isinstance(result, tuple):
            allowed = bool(result[0]) if result else False
            reason = str(result[1]) if len(result) > 1 else ""
            return allowed, reason
        if result is True:
            return True, ""
        if result is False:
            return False, "guard menolak transisi."
        return (
            False,
            f"guard '{transition.guard_path}' mengembalikan nilai tidak dikenal "
            f"({result!r}); transisi ditolak (fail-closed).",
        )

    @staticmethod
    def _error_message(error: ValidationError) -> str:
        """Ambil pesan pertama dari ValidationError (kalau ada)."""
        return error.messages[0] if error.messages else str(error)
