"""Test MCP rule-engine T2.1 — read-only business rules."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase

from apps_industry.garment.models import BundleEvent, MaterialReadiness
from apps_industry.garment.tests.factories import (
    make_bundle,
    make_order,
    make_order_line,
    make_work_center,
)
from core.rule_engine.models import Rule
from integrations.ai_agent.mcp_servers import mcp_rule_engine

MODULE = "integrations.ai_agent.mcp_servers.mcp_rule_engine"


def _user(role="SUPERVISOR"):
    return SimpleNamespace(role=SimpleNamespace(code=role))


def _ready_bundle(status="READY", received=5, required=5):
    bundle = make_bundle(qty=5, current_work_center=make_work_center(code="SEWING-T2"))
    MaterialReadiness.objects.create(
        order_line=bundle.work_order.order_line,
        required_qty=required,
        received_qty=received,
        shortage_qty=max(0, required - received),
        status=status,
    )
    return bundle


class RuleEngineTests(TestCase):
    def test_can_start_ready(self):
        bundle = _ready_bundle()

        result = mcp_rule_engine.handle(
            "can_start_production", {"bundle_id": bundle.pk}, _user()
        )

        self.assertTrue(result["ok"])
        self.assertTrue(result["result"])
        self.assertEqual(result["details"]["material_status"], "READY")

    def test_can_start_waiting(self):
        bundle = _ready_bundle(status="WAITING", received=0)

        result = mcp_rule_engine.handle(
            "can_start_production", {"bundle_id": bundle.pk}, _user()
        )

        self.assertFalse(result["ok"])
        self.assertFalse(result["result"])
        self.assertIn("belum siap", result["reason"])

    def test_check_rework_needed_qc_fail(self):
        bundle = _ready_bundle()
        BundleEvent.objects.create(bundle=bundle, event_type="QC_FAIL", payload={})

        result = mcp_rule_engine.handle(
            "check_rework_needed", {"bundle_id": bundle.pk}, _user()
        )

        self.assertTrue(result["result"])
        self.assertEqual(result["details"]["event_count"], 1)

    def test_stock_sufficient(self):
        order = make_order()
        line = make_order_line(order=order, qty=10)
        MaterialReadiness.objects.create(
            order_line=line,
            required_qty=10,
            received_qty=10,
            shortage_qty=0,
            status="READY",
        )

        result = mcp_rule_engine.handle(
            "check_stock_sufficient", {"order_id": order.pk}, _user()
        )

        self.assertTrue(result["result"])
        self.assertEqual(result["details"]["shortage_total"], 0)

    def test_order_can_confirm(self):
        order = make_order(state="DRAFT")
        line = make_order_line(order=order, qty=3, price_unit=100)
        MaterialReadiness.objects.create(
            order_line=line,
            required_qty=3,
            received_qty=3,
            shortage_qty=0,
            status="READY",
        )

        result = mcp_rule_engine.handle(
            "check_order_can_confirm", {"order_id": order.pk}, _user()
        )

        self.assertTrue(result["result"])

    def test_order_tidak_bisa_confirm_kalau_state_bukan_draft(self):
        order = make_order(state="CONFIRMED")
        line = make_order_line(order=order, qty=3, price_unit=100)
        MaterialReadiness.objects.create(
            order_line=line,
            required_qty=3,
            received_qty=3,
            shortage_qty=0,
            status="READY",
        )

        result = mcp_rule_engine.handle(
            "check_order_can_confirm", {"order_id": order.pk}, _user()
        )

        self.assertFalse(result["result"])
        self.assertIn("bukan DRAFT", result["reason"])

    def test_role_operator_forbidden(self):
        bundle = _ready_bundle()

        result = mcp_rule_engine.handle(
            "can_start_production", {"bundle_id": bundle.pk}, _user("OPERATOR")
        )

        self.assertEqual(result["error"], "forbidden")

    def test_timeout_rule_error(self):
        with patch(f"{MODULE}._timed_out", return_value=True):
            result = mcp_rule_engine.handle("can_start_production", {}, _user())

        self.assertEqual(result["error"], "rule_error")

    def test_evaluate_rule_custom(self):
        Rule.objects.create(code="T2-ALWAYS", name="T2 always", is_active=True)

        result = mcp_rule_engine.handle(
            "evaluate_rule", {"rule_code": "T2-ALWAYS", "facts": {}}, _user()
        )

        self.assertTrue(result["result"])
        self.assertEqual(result["details"]["rule_code"], "T2-ALWAYS")

    def test_bundle_tidak_ada(self):
        result = mcp_rule_engine.handle(
            "can_start_production", {"bundle_id": 999999}, _user()
        )

        self.assertEqual(result["error"], "not_found")
