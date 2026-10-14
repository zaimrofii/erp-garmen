"""Test ReworkLoopHandler: definisi idempotent, start, rework, exhausted, complete."""

from __future__ import annotations

from django.test import TestCase

from apps_industry.garment.services import ReworkLoopError, ReworkLoopHandler
from apps_industry.garment.tests.factories import make_bundle
from core.cycle_handler.models import CycleDefinition, CycleInstance, CycleStep


class ReworkLoopHandlerTests(TestCase):
    """Siklus QC_REWORK: QC_START -> REWORK -> QC_PASS (terminal)."""

    @classmethod
    def setUpTestData(cls):
        cls.bundle = make_bundle()

    def setUp(self):
        self.handler = ReworkLoopHandler(max_iterations=2)

    def test_ensure_definition_idempotent(self):
        pertama = self.handler._ensure_definition()
        kedua = self.handler._ensure_definition()

        self.assertEqual(pertama.pk, kedua.pk)
        self.assertEqual(CycleDefinition.objects.count(), 1)
        self.assertEqual(CycleStep.objects.count(), 3)
        self.assertEqual(
            list(pertama.steps.order_by("order").values_list("action_id", flat=True)),
            ["QC_START", "REWORK", "QC_PASS"],
        )
        self.assertTrue(pertama.steps.get(action_id="QC_PASS").is_terminal)
        self.assertEqual(pertama.max_iterations, 2)

    def test_start_membuat_instance_aktif_di_step_pertama(self):
        instance = self.handler.start_qc_rework(self.bundle)

        self.assertEqual(instance.status, CycleInstance.Status.ACTIVE)
        self.assertEqual(instance.ref_type, "bundle")
        self.assertEqual(instance.ref_id, str(self.bundle.pk))
        self.assertEqual(instance.current_step.action_id, "QC_START")

    def test_start_idempotent_untuk_bundle_yang_sama(self):
        pertama = self.handler.start_qc_rework(self.bundle)
        kedua = self.handler.start_qc_rework(self.bundle)

        self.assertEqual(pertama.pk, kedua.pk)
        self.assertEqual(CycleInstance.objects.count(), 1)

    def test_record_rework_menaikkan_iterasi(self):
        self.handler.start_qc_rework(self.bundle)

        instance = self.handler.record_rework(self.bundle)

        self.assertEqual(instance.iteration_count, 1)
        self.assertEqual(instance.status, CycleInstance.Status.ACTIVE)
        self.assertFalse(self.handler.is_exhausted(self.bundle))

    def test_exhausted_setelah_mencapai_batas_iterasi(self):
        self.handler.start_qc_rework(self.bundle)
        self.handler.record_rework(self.bundle)
        instance = self.handler.record_rework(self.bundle)  # iterasi 2 = max

        self.assertEqual(instance.status, CycleInstance.Status.EXHAUSTED)
        self.assertTrue(self.handler.is_exhausted(self.bundle))

    def test_complete_menutup_siklus(self):
        self.handler.start_qc_rework(self.bundle)

        instance = self.handler.complete(self.bundle)

        self.assertEqual(instance.status, CycleInstance.Status.COMPLETED)
        self.assertFalse(self.handler.is_exhausted(self.bundle))

    def test_record_rework_tanpa_start_raise(self):
        with self.assertRaises(ReworkLoopError):
            self.handler.record_rework(self.bundle)

    def test_complete_tanpa_siklus_raise(self):
        with self.assertRaises(ReworkLoopError):
            self.handler.complete(self.bundle)

    def test_is_exhausted_false_kalau_belum_ada_siklus(self):
        self.assertFalse(self.handler.is_exhausted(self.bundle))

    def test_siklus_terpisah_per_bundle(self):
        bundle_lain = make_bundle(code="BND-002")
        instance_satu = self.handler.start_qc_rework(self.bundle)
        instance_dua = self.handler.start_qc_rework(bundle_lain)

        self.assertNotEqual(instance_satu.pk, instance_dua.pk)

        self.handler.record_rework(bundle_lain)

        self.assertEqual(instance_satu.iteration_count, 0)
        self.assertEqual(
            self.handler._active_instance(bundle_lain).iteration_count, 1
        )
