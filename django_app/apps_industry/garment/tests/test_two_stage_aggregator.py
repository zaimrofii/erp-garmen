"""Test TwoStageAggregator: deteksi WIP/FG, payload, dan agregasi per work order."""

from __future__ import annotations

from django.test import TestCase

from apps_industry.garment.services import (
    AggregatedMove,
    TwoStageAggregator,
    TwoStageAggregatorError,
)
from apps_industry.garment.tests.factories import (
    make_bundle,
    make_routing,
    make_step,
    make_work_center,
    make_work_order,
)


class TwoStageAggregatorTests(TestCase):
    """Routing dummy: SABLON (WIP) -> PACKING (terminal = FG)."""

    @classmethod
    def setUpTestData(cls):
        cls.wc_sablon = make_work_center(code="SABLON-1")
        cls.wc_packing = make_work_center(code="PACKING-1")
        cls.routing = make_routing(code="ROUTE-STD")
        make_step(
            cls.routing, "SABLON", 10, is_initial=True, work_center=cls.wc_sablon
        )
        make_step(
            cls.routing, "PACKING", 20, is_terminal=True, work_center=cls.wc_packing
        )

    def setUp(self):
        self.service = TwoStageAggregator()

    # ------------------------------------------------------------------- stage
    def test_compute_stage_wip_di_wc_biasa(self):
        bundle = make_bundle(current_work_center=self.wc_sablon)

        self.assertEqual(self.service.compute_stage(bundle), "WIP")

    def test_compute_stage_fg_di_wc_terminal(self):
        bundle = make_bundle(current_work_center=self.wc_packing)

        self.assertEqual(self.service.compute_stage(bundle), "FG")

    def test_compute_stage_wip_kalau_belum_punya_work_center(self):
        bundle = make_bundle()

        self.assertEqual(self.service.compute_stage(bundle), "WIP")

    # ----------------------------------------------------------------- payload
    def test_build_payload_stage_otomatis_wip(self):
        bundle = make_bundle(current_work_center=self.wc_sablon, qty=7)

        move = self.service.build_payload(bundle)

        self.assertIsInstance(move, AggregatedMove)
        self.assertEqual(move.stage, "WIP")
        self.assertEqual(move.qty, 7)  # WIP pakai qty rencana
        self.assertEqual(move.ref, bundle.code)
        self.assertEqual(move.wc_code, "SABLON-1")
        self.assertEqual(
            move.product_ref, bundle.work_order.order_line.product.code
        )
        self.assertEqual(move.metadata["work_order"], bundle.work_order.code)
        self.assertEqual(move.metadata["bundle_version"], bundle.version)

    def test_build_fg_payload_memakai_qty_done(self):
        bundle = make_bundle(
            current_work_center=self.wc_packing, qty=10, qty_done=8
        )

        move = self.service.build_fg_payload(bundle)

        self.assertEqual(move.stage, "FG")
        self.assertEqual(move.qty, 8)
        self.assertEqual(move.wc_code, "PACKING-1")

    def test_build_wip_payload_error_kalau_sudah_terminal(self):
        bundle = make_bundle(current_work_center=self.wc_packing)

        with self.assertRaises(TwoStageAggregatorError):
            self.service.build_wip_payload(bundle)

    def test_build_fg_payload_error_kalau_belum_terminal(self):
        bundle = make_bundle(current_work_center=self.wc_sablon)

        with self.assertRaises(TwoStageAggregatorError):
            self.service.build_fg_payload(bundle)

    # --------------------------------------------------------------- aggregate
    def test_aggregate_for_work_order_group_per_stage(self):
        work_order = make_work_order()
        make_bundle(
            work_order=work_order,
            code="BND-001",
            qty=5,
            current_work_center=self.wc_sablon,
        )
        make_bundle(
            work_order=work_order,
            code="BND-002",
            qty=5,
            current_work_center=self.wc_sablon,
        )
        make_bundle(
            work_order=work_order,
            code="BND-003",
            qty=4,
            qty_done=4,
            current_work_center=self.wc_packing,
        )

        moves = self.service.aggregate_for_work_order(work_order)

        self.assertEqual([move.stage for move in moves], ["WIP", "FG"])
        self.assertEqual(moves[0].qty, 10)  # 5 + 5
        self.assertEqual(moves[0].ref, work_order.code)
        self.assertIsNone(moves[0].wc_code)
        self.assertEqual(moves[0].metadata["bundle_count"], 2)
        self.assertEqual(moves[0].metadata["bundle_codes"], ["BND-001", "BND-002"])
        self.assertEqual(moves[0].metadata["wc_codes"], ["SABLON-1"])
        self.assertEqual(moves[1].qty, 4)
        self.assertEqual(moves[1].metadata["wc_codes"], ["PACKING-1"])

    def test_aggregate_for_work_order_tanpa_bundle(self):
        work_order = make_work_order()

        self.assertEqual(self.service.aggregate_for_work_order(work_order), [])

    def test_input_none_raise(self):
        with self.assertRaises(TwoStageAggregatorError):
            self.service.compute_stage(None)
        with self.assertRaises(TwoStageAggregatorError):
            self.service.aggregate_for_work_order(None)
