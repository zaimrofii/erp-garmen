"""Test minimal `StateMachineEngine` — workflow dummy DRAFT -> SEWING -> DONE.

Fokus: aturan allowed actions, guard (allow/reject), dan bukti bahwa engine
**tidak** menyimpan state instance (state itu tanggung jawab model domain).
"""

from __future__ import annotations

from django.test import TestCase

from core.state_machine.models import State, StateMachine, Transition
from core.state_machine.services import StateMachineEngine, StateMachineEngineError

GUARD_QTY_POSITIVE = "core.state_machine.tests.guards.qty_positive"
GUARD_REJECT = "core.state_machine.tests.guards.reject_with_message"
GUARD_TIDAK_ADA = "core.state_machine.tests.guards.tidak_ada_guard_ini"


class StateMachineEngineTests(TestCase):
    """Engine generik dengan definisi state/transisi di DB."""

    @classmethod
    def setUpTestData(cls):
        cls.machine = StateMachine.objects.create(code="DUMMY", name="Dummy Workflow")
        cls.draft = State.objects.create(
            machine=cls.machine, code="DRAFT", label="Draft", is_initial=True, order=1
        )
        cls.sewing = State.objects.create(
            machine=cls.machine, code="SEWING", label="Sewing", order=2
        )
        cls.done = State.objects.create(
            machine=cls.machine, code="DONE", label="Done", is_terminal=True, order=3
        )
        cls.transition_start = Transition.objects.create(
            machine=cls.machine,
            from_state=cls.draft,
            to_state=cls.sewing,
            action_id="START",
            label="Mulai",
        )
        cls.transition_finish = Transition.objects.create(
            machine=cls.machine,
            from_state=cls.sewing,
            to_state=cls.done,
            action_id="FINISH",
        )
        cls.transition_guarded = Transition.objects.create(
            machine=cls.machine,
            from_state=cls.draft,
            to_state=cls.done,
            action_id="FORCE_DONE",
            guard_path=GUARD_QTY_POSITIVE,
        )
        cls.transition_guard_reject = Transition.objects.create(
            machine=cls.machine,
            from_state=cls.sewing,
            to_state=cls.done,
            action_id="REJECT_ME",
            guard_path=GUARD_REJECT,
        )
        cls.transition_nonaktif = Transition.objects.create(
            machine=cls.machine,
            from_state=cls.draft,
            to_state=cls.done,
            action_id="OLD_ACTION",
            is_active=False,
        )

    def setUp(self):
        self.engine = StateMachineEngine()

    # ---------------------------------------------------------------- lookup
    def test_get_machine_dan_state(self):
        self.assertEqual(self.engine.get_machine("DUMMY"), self.machine)
        self.assertEqual(self.engine.get_state(self.machine, "DRAFT"), self.draft)

    def test_get_machine_tidak_ada_raise(self):
        with self.assertRaises(StateMachineEngineError):
            self.engine.get_machine("TIDAK_ADA")

    def test_get_machine_nonaktif_raise(self):
        StateMachine.objects.filter(pk=self.machine.pk).update(is_active=False)
        with self.assertRaises(StateMachineEngineError):
            self.engine.get_machine("DUMMY")

    def test_get_allowed_actions_hanya_transisi_aktif(self):
        actions = {
            transition.action_id
            for transition in self.engine.get_allowed_actions(self.machine, "DRAFT")
        }
        self.assertEqual(actions, {"START", "FORCE_DONE"})

    # ----------------------------------------------------------------- check
    def test_can_transition_diizinkan(self):
        diizinkan, alasan = self.engine.can_transition(self.machine, "DRAFT", "START", {})
        self.assertTrue(diizinkan)
        self.assertEqual(alasan, "DRAFT -> SEWING")

    def test_can_transition_action_tidak_ada_dari_state_itu(self):
        diizinkan, alasan = self.engine.can_transition(self.machine, "DRAFT", "FINISH", {})
        self.assertFalse(diizinkan)
        self.assertIn("FINISH", alasan)

    def test_transisi_nonaktif_tidak_bisa_dipakai(self):
        diizinkan, _ = self.engine.can_transition(self.machine, "DRAFT", "OLD_ACTION", {})
        self.assertFalse(diizinkan)

    def test_guard_bool_menerima_dan_menolak(self):
        diizinkan, _ = self.engine.can_transition(
            self.machine, "DRAFT", "FORCE_DONE", {"qty": 5}
        )
        self.assertTrue(diizinkan)

        diizinkan, alasan = self.engine.can_transition(
            self.machine, "DRAFT", "FORCE_DONE", {"qty": 0}
        )
        self.assertFalse(diizinkan)
        self.assertTrue(alasan)

    def test_guard_raise_validation_error_jadi_alasan_penolakan(self):
        diizinkan, alasan = self.engine.can_transition(
            self.machine, "SEWING", "REJECT_ME", {"bundle_id": 1}
        )
        self.assertFalse(diizinkan)
        self.assertIn("guard contoh menolak", alasan)

    def test_guard_path_salah_menolak_transisi(self):
        Transition.objects.create(
            machine=self.machine,
            from_state=self.draft,
            to_state=self.done,
            action_id="BAD_GUARD",
            guard_path=GUARD_TIDAK_ADA,
        )
        diizinkan, alasan = self.engine.can_transition(
            self.machine, "DRAFT", "BAD_GUARD", {}
        )
        self.assertFalse(diizinkan)
        self.assertIn("tidak bisa di-import", alasan)

    # --------------------------------------------------------------- execute
    def test_execute_transition_mengembalikan_transition(self):
        transition = self.engine.execute_transition(self.machine, "DRAFT", "START", {})
        self.assertIsInstance(transition, Transition)
        self.assertEqual(transition.to_state.code, "SEWING")
        # Engine stateless: tidak ada state instance yang disimpan di app ini.
        self.assertEqual(State.objects.filter(machine=self.machine).count(), 3)

    def test_execute_transition_guard_gagal_raise(self):
        with self.assertRaises(StateMachineEngineError):
            self.engine.execute_transition(
                self.machine, "DRAFT", "FORCE_DONE", {"qty": 0}
            )
