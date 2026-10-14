"""Test OverlapRelease: step saat ini, step lanjutan, kandidat rilis, eligibility."""

from __future__ import annotations

from django.test import TestCase

from apps_industry.garment.services import OverlapRelease, OverlapReleaseError
from apps_industry.garment.tests.factories import (
    make_bundle,
    make_routing,
    make_step,
    make_work_center,
)


class OverlapReleaseTests(TestCase):
    """Routing dummy: SABLON -> SEWING -> PACKING (terminal)."""

    @classmethod
    def setUpTestData(cls):
        cls.wc_sablon = make_work_center(code="SABLON-1")
        cls.wc_sewing = make_work_center(code="SEWING-1")
        cls.wc_qc = make_work_center(code="QC-1")

        cls.routing = make_routing(code="ROUTE-STD")
        cls.step_sablon = make_step(
            cls.routing, "SABLON", 10, is_initial=True, work_center=cls.wc_sablon
        )
        cls.step_sewing = make_step(cls.routing, "SEWING", 20, work_center=cls.wc_sewing)
        cls.step_packing = make_step(
            cls.routing, "PACKING", 30, is_terminal=True, work_center=cls.wc_qc
        )
        cls.step_sablon.allowed_next_steps.add(cls.step_sewing)

    def setUp(self):
        self.service = OverlapRelease()

    def test_get_current_step_dari_work_center_bundle(self):
        bundle = make_bundle(current_work_center=self.wc_sablon)

        self.assertEqual(self.service.get_current_step(bundle), self.step_sablon)

    def test_get_next_steps_dari_allowed_next_steps(self):
        bundle = make_bundle(current_work_center=self.wc_sablon)

        self.assertEqual(self.service.get_next_steps(bundle), [self.step_sewing])

    def test_release_mengembalikan_step_berikutnya(self):
        bundle = make_bundle(current_work_center=self.wc_sablon)

        self.assertEqual(self.service.release(bundle), self.step_sewing)

    def test_release_mengembalikan_none_kalau_terminal(self):
        bundle = make_bundle(current_work_center=self.wc_qc)

        self.assertEqual(self.service.get_current_step(bundle), self.step_packing)
        self.assertIsNone(self.service.release(bundle))

    def test_none_kalau_belum_ada_current_work_center(self):
        bundle = make_bundle()  # current_work_center None

        self.assertIsNone(self.service.get_current_step(bundle))
        self.assertEqual(self.service.get_next_steps(bundle), [])
        self.assertIsNone(self.service.release(bundle))

    def test_step_lanjutan_dengan_work_center_nonaktif_dilewati(self):
        wc_nonaktif = make_work_center(code="SABLON-LAMA", is_active=False)
        step_nonaktif = make_step(
            self.routing, "SABLON2", 15, work_center=wc_nonaktif
        )
        self.step_sablon.allowed_next_steps.add(step_nonaktif)
        bundle = make_bundle(current_work_center=self.wc_sablon)

        # step_nonaktif (order 15) lebih dulu, tapi WC-nya nonaktif -> dilewati.
        self.assertEqual(self.service.release(bundle), self.step_sewing)

    def test_routing_bisa_di_inject(self):
        routing_lain = make_routing(code="ROUTE-LAIN")
        wc_cutting = make_work_center(code="CUTTING-1")
        step_cutting = make_step(routing_lain, "CUTTING", 10, work_center=wc_cutting)
        bundle = make_bundle(current_work_center=wc_cutting)

        self.assertEqual(
            OverlapRelease(routing_lain).get_current_step(bundle), step_cutting
        )
        # Tanpa inject: routing aktif pertama (ROUTE-STD) tidak punya step CUTTING.
        self.assertIsNone(self.service.get_current_step(bundle))

    def test_get_current_step_tanpa_bundle_raise(self):
        with self.assertRaises(OverlapReleaseError):
            self.service.get_current_step(None)
