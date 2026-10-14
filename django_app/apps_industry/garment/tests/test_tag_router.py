"""Test TagRouter: rule match, no match, priority, kupon, dan error handling."""

from __future__ import annotations

from django.test import TestCase

from apps_industry.garment.services import TagRouter, TagRouterError
from apps_industry.garment.tests.factories import (
    make_order_line,
    make_routing,
    make_tag_rule,
)
from core.rule_engine.models import Rule


class TagRouterTests(TestCase):
    """Tag -> routing/kupon lewat Rule (bukan if di kode)."""

    @classmethod
    def setUpTestData(cls):
        cls.routing_fast = make_routing(code="ROUTE-FAST")
        cls.routing_export = make_routing(code="ROUTE-EXPORT")

    def setUp(self):
        self.router = TagRouter()

    def test_match_fast_track(self):
        make_tag_rule(
            "FAST_TRACK", routing_code="ROUTE-FAST", ticket_format="PR-{order_line_id}"
        )
        order_line = make_order_line(tag="FAST_TRACK", qty=20)

        plan = self.router.resolve(order_line)

        self.assertEqual(plan.routing, self.routing_fast)
        self.assertEqual(plan.piece_rate_ticket, f"PR-{order_line.pk}")
        self.assertEqual(plan.matched_rule, "tag_router.FAST_TRACK")

    def test_no_match_mengembalikan_plan_kosong(self):
        make_tag_rule("FAST_TRACK", routing_code="ROUTE-FAST", tag="FAST_TRACK")
        order_line = make_order_line(tag="CUSTOM", qty=5)

        plan = self.router.resolve(order_line)

        self.assertIsNone(plan.routing)
        self.assertIsNone(plan.piece_rate_ticket)
        self.assertIsNone(plan.matched_rule)
        self.assertIn("tidak ada rule", plan.reason)

    def test_priority_menentukan_rule_pemenang(self):
        make_tag_rule("slow", routing_code="ROUTE-EXPORT", priority=20)
        make_tag_rule("fast", routing_code="ROUTE-FAST", priority=10)
        order_line = make_order_line(tag="FAST_TRACK", qty=1)

        plan = self.router.resolve(order_line)

        self.assertEqual(plan.matched_rule, "tag_router.fast")
        self.assertEqual(plan.routing, self.routing_fast)

    def test_rule_nonaktif_diabaikan(self):
        make_tag_rule("fast", routing_code="ROUTE-FAST", is_active=False)
        order_line = make_order_line(tag="FAST_TRACK", qty=1)

        plan = self.router.resolve(order_line)

        self.assertIsNone(plan.routing)
        self.assertIsNone(plan.matched_rule)

    def test_hanya_aksi_ticket_issue(self):
        make_tag_rule("ticket_only", ticket_format="TKT-{order_code}-{qty}")
        order_line = make_order_line(tag="FAST_TRACK", qty=7)

        plan = self.router.resolve(order_line)

        self.assertIsNone(plan.routing)
        self.assertEqual(plan.piece_rate_ticket, f"TKT-{order_line.order.code}-7")

    def test_routing_code_tidak_ditemukan_raise(self):
        make_tag_rule("fast", routing_code="ROUTE-GAIB")
        order_line = make_order_line(tag="FAST_TRACK", qty=1)

        with self.assertRaises(TagRouterError):
            self.router.resolve(order_line)

    def test_placeholder_tidak_dikenal_raise(self):
        make_tag_rule("fast", ticket_format="PR-{tidak_ada}")
        order_line = make_order_line(tag="FAST_TRACK", qty=1)

        with self.assertRaises(TagRouterError):
            self.router.resolve(order_line)

    def test_order_line_none_raise(self):
        with self.assertRaises(TagRouterError):
            self.router.resolve(None)

    def test_fallback_semua_rule_aktif_kalau_belum_ada_rule_tag_router(self):
        rule = make_tag_rule("FAST_TRACK", routing_code="ROUTE-FAST")
        # Rule tanpa prefix tag_router. -> hanya dievaluasi sebagai fallback.
        Rule.objects.filter(pk=rule.pk).update(code="routing.FAST_TRACK")
        order_line = make_order_line(tag="FAST_TRACK", qty=1)

        plan = self.router.resolve(order_line)

        self.assertEqual(plan.matched_rule, "routing.FAST_TRACK")
        self.assertEqual(plan.routing, self.routing_fast)
