"""Test CapabilityAllocator: superset match, tidak ada match, paling spesifik."""

from __future__ import annotations

from django.test import TestCase

from apps_industry.garment.services import CapabilityAllocator, CapabilityAllocatorError
from apps_industry.garment.tests.factories import (
    make_line,
    make_routing,
    make_step,
    make_work_center,
    make_work_order,
)


class CapabilityAllocatorTests(TestCase):
    """Routing butuh SABLON + SEWING + QC."""

    @classmethod
    def setUpTestData(cls):
        cls.wc_sablon = make_work_center(code="SABLON-1")
        cls.wc_sewing = make_work_center(code="SEWING-1")
        cls.wc_qc = make_work_center(code="QC-1")
        cls.wc_packing = make_work_center(code="PACKING-1")

        cls.routing = make_routing(code="ROUTE-STD")
        make_step(cls.routing, "SABLON", 10, work_center=cls.wc_sablon)
        make_step(cls.routing, "SEWING", 20, work_center=cls.wc_sewing)
        make_step(cls.routing, "QC", 30, work_center=cls.wc_qc)

        cls.work_order = make_work_order()

        cls.line_besar = make_line(
            code="LINE-BESAR",
            work_centers=[cls.wc_sablon, cls.wc_sewing, cls.wc_qc, cls.wc_packing],
        )
        cls.line_spesifik = make_line(
            code="LINE-SPESIFIK",
            work_centers=[cls.wc_sablon, cls.wc_sewing, cls.wc_qc],
        )
        # Bukan superset: tidak punya QC.
        cls.line_kurang = make_line(
            code="LINE-KURANG", work_centers=[cls.wc_sablon, cls.wc_sewing]
        )

    def setUp(self):
        self.allocator = CapabilityAllocator()

    def test_required_work_centers_dari_routing(self):
        self.assertEqual(
            self.allocator.required_work_centers(self.routing),
            {self.wc_sablon.pk, self.wc_sewing.pk, self.wc_qc.pk},
        )

    def test_candidates_hanya_line_superset_urut_paling_spesifik(self):
        candidates = self.allocator.candidates(self.work_order, self.routing)

        self.assertEqual([line.code for line in candidates], ["LINE-SPESIFIK", "LINE-BESAR"])

    def test_allocate_memilih_line_paling_spesifik(self):
        self.assertEqual(
            self.allocator.allocate(self.work_order, self.routing), self.line_spesifik
        )

    def test_none_kalau_tidak_ada_line_superset(self):
        routing_lain = make_routing(code="ROUTE-BORDIR")
        wc_bordir = make_work_center(code="BORDIR-1")
        make_step(routing_lain, "BORDIR", 10, work_center=wc_bordir)

        self.assertEqual(
            self.allocator.candidates(self.work_order, routing_lain), []
        )
        self.assertIsNone(self.allocator.allocate(self.work_order, routing_lain))

    def test_line_nonaktif_tidak_dipertimbangkan(self):
        self.line_spesifik.is_active = False
        self.line_spesifik.save(update_fields=["is_active"])

        self.assertEqual(
            self.allocator.allocate(self.work_order, self.routing), self.line_besar
        )

    def test_routing_tanpa_work_center_fail_closed(self):
        routing_kosong = make_routing(code="ROUTE-KOSONG")
        make_step(routing_kosong, "CUCI", 10)  # step tanpa work center

        self.assertEqual(
            self.allocator.candidates(self.work_order, routing_kosong), []
        )
        self.assertIsNone(self.allocator.allocate(self.work_order, routing_kosong))

    def test_input_tidak_lengkap_raise(self):
        with self.assertRaises(CapabilityAllocatorError):
            self.allocator.allocate(None, self.routing)
        with self.assertRaises(CapabilityAllocatorError):
            self.allocator.required_work_centers(None)
