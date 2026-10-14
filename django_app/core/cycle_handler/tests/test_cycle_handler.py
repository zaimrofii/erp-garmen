"""Test CycleHandler: start idempotent, advance, rework, exhausted, complete, cancel."""

from __future__ import annotations

from django.test import TestCase

from core.cycle_handler.models import CycleDefinition, CycleInstance, CycleStep
from core.cycle_handler.services import CycleHandler, CycleHandlerError


class CycleHandlerTests(TestCase):
    """Siklus dummy: step 0 SEWING (awal) -> step 1 QC -> step 2 DONE (terminal)."""

    @classmethod
    def setUpTestData(cls):
        cls.definition = CycleDefinition.objects.create(
            code="REWORK_QC", name="Rework QC", max_iterations=2
        )
        cls.step_sewing = CycleStep.objects.create(
            definition=cls.definition, order=0, action_id="SEWING_START", label="Sewing"
        )
        cls.step_qc = CycleStep.objects.create(
            definition=cls.definition, order=1, action_id="QC_CHECK", label="QC"
        )
        cls.step_done = CycleStep.objects.create(
            definition=cls.definition,
            order=2,
            action_id="QC_PASS",
            label="Done",
            is_terminal=True,
        )

    def setUp(self):
        self.handler = CycleHandler()

    # ------------------------------------------------------------------- start
    def test_start_membuat_instance_di_step_pertama(self):
        instance = self.handler.start("REWORK_QC", "bundle", "BND-0001")

        self.assertEqual(instance.status, CycleInstance.Status.ACTIVE)
        self.assertEqual(instance.current_step, self.step_sewing)
        self.assertEqual(instance.iteration_count, 0)

    def test_start_idempotent_untuk_ref_yang_sama(self):
        pertama = self.handler.start("REWORK_QC", "bundle", "BND-0001")
        kedua = self.handler.start("REWORK_QC", "bundle", "BND-0001")

        self.assertEqual(pertama.pk, kedua.pk)
        self.assertEqual(CycleInstance.objects.count(), 1)

    def test_start_ref_berbeda_bikin_instance_baru(self):
        self.handler.start("REWORK_QC", "bundle", "BND-0001")
        self.handler.start("REWORK_QC", "bundle", "BND-0002")
        self.handler.start("REWORK_QC", "work_order", "BND-0001")

        self.assertEqual(CycleInstance.objects.count(), 3)

    def test_start_cycle_tidak_dikenal_raise(self):
        with self.assertRaises(CycleHandlerError):
            self.handler.start("TIDAK_ADA", "bundle", "BND-0001")

    # ----------------------------------------------------------------- advance
    def test_advance_pindah_step(self):
        instance = self.handler.start("REWORK_QC", "bundle", "BND-0001")

        instance = self.handler.advance(instance, "QC_CHECK")

        self.assertEqual(instance.current_step, self.step_qc)
        self.assertEqual(instance.iteration_count, 0)
        self.assertEqual(instance.status, CycleInstance.Status.ACTIVE)

    def test_advance_ke_step_terminal_menjadi_completed(self):
        instance = self.handler.start("REWORK_QC", "bundle", "BND-0001")
        instance = self.handler.advance(instance, "QC_CHECK")

        instance = self.handler.advance(instance, "QC_PASS")

        self.assertEqual(instance.current_step, self.step_done)
        self.assertEqual(instance.status, CycleInstance.Status.COMPLETED)

    def test_advance_kembali_ke_step_awal_menambah_iterasi_lalu_exhausted(self):
        instance = self.handler.start("REWORK_QC", "bundle", "BND-0001")
        instance = self.handler.advance(instance, "QC_CHECK")

        instance = self.handler.advance(instance, "SEWING_START")  # putaran 1
        self.assertEqual(instance.iteration_count, 1)
        self.assertFalse(self.handler.is_exhausted(instance))

        instance = self.handler.advance(instance, "QC_CHECK")
        instance = self.handler.advance(instance, "SEWING_START")  # putaran 2 = max
        self.assertEqual(instance.iteration_count, 2)
        self.assertEqual(instance.status, CycleInstance.Status.EXHAUSTED)
        self.assertTrue(self.handler.is_exhausted(instance))

    def test_advance_action_tidak_dikenal_raise(self):
        instance = self.handler.start("REWORK_QC", "bundle", "BND-0001")

        with self.assertRaises(CycleHandlerError):
            self.handler.advance(instance, "ACTION_NGAWUR")

    # ------------------------------------------------------------ record_rework
    def test_record_rework_increment_tanpa_pindah_step_dan_exhausted(self):
        instance = self.handler.start("REWORK_QC", "bundle", "BND-0001")

        instance = self.handler.record_rework(instance)
        self.assertEqual(instance.iteration_count, 1)
        self.assertEqual(instance.current_step, self.step_sewing)  # step tidak pindah
        self.assertEqual(instance.status, CycleInstance.Status.ACTIVE)

        instance = self.handler.record_rework(instance)
        self.assertEqual(instance.iteration_count, 2)
        self.assertEqual(instance.status, CycleInstance.Status.EXHAUSTED)
        self.assertTrue(self.handler.is_exhausted(instance))

    def test_record_rework_pada_instance_cancelled_raise(self):
        instance = self.handler.start("REWORK_QC", "bundle", "BND-0001")
        self.handler.cancel(instance)

        with self.assertRaises(CycleHandlerError):
            self.handler.record_rework(instance)

    # ------------------------------------------------------- complete / cancel
    def test_complete_dan_cancel_mengubah_status(self):
        instance = self.handler.start("REWORK_QC", "bundle", "BND-0001")
        self.assertEqual(
            self.handler.complete(instance).status, CycleInstance.Status.COMPLETED
        )

        lain = self.handler.start("REWORK_QC", "bundle", "BND-0002")
        hasil = self.handler.cancel(lain, reason="order dibatalkan klien")
        self.assertEqual(hasil.status, CycleInstance.Status.CANCELLED)

    def test_instance_cancelled_tidak_bisa_dilanjutkan(self):
        instance = self.handler.start("REWORK_QC", "bundle", "BND-0001")
        self.handler.cancel(instance)

        with self.assertRaises(CycleHandlerError):
            self.handler.advance(instance, "QC_CHECK")

        with self.assertRaises(CycleHandlerError):
            self.handler.complete(instance)

    def test_instance_completed_tidak_bisa_advance_dan_start_bikin_baru(self):
        instance = self.handler.start("REWORK_QC", "bundle", "BND-0001")
        instance = self.handler.advance(instance, "QC_CHECK")
        instance = self.handler.advance(instance, "QC_PASS")  # terminal -> COMPLETED

        with self.assertRaises(CycleHandlerError):
            self.handler.advance(instance, "QC_CHECK")

        # Instance lama tidak lagi ACTIVE -> start() membuat instance baru.
        baru = self.handler.start("REWORK_QC", "bundle", "BND-0001")
        self.assertNotEqual(baru.pk, instance.pk)
        self.assertEqual(CycleInstance.objects.count(), 2)
