"""Regresi Fase 5.1 — relasi order→bundle, operator→bundle, customer+spend."""

from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase

from apps_industry.garment.models import (
    Bundle,
    BundleEvent,
    Order,
    OrderLine,
    WorkOrder,
)
from core.auth.models import Role, User
from integrations.ai_agent.mcp_servers import mcp_event_log
from integrations.ai_agent.orchestrator import context_builder
from master.models import Partner, Product


class Fase51FixTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.customer = Partner.objects.create(
            code="F51-CUST",
            name="PT Retail Fashion Indonesia",
            is_customer=True,
        )
        cls.product = Product.objects.create(
            code="F51-CHN",
            name="Celana Chino",
            sale_price=160000,
            cost_price=100000,
            category="Celana",
        )
        cls.order = Order.objects.create(
            code="SO-F51-0001",
            customer=cls.customer,
            state="DONE",
        )
        cls.line = OrderLine.objects.create(
            order=cls.order,
            product=cls.product,
            qty=10,
            price_unit=160000,
        )
        cls.wo = WorkOrder.objects.create(
            code="F51-WO-1",
            order_line=cls.line,
            qty_planned=10,
        )
        cls.bundle = Bundle.objects.create(
            code="BND-F51-0001",
            work_order=cls.wo,
            qty=10,
            qty_done=10,
            state="DONE",
        )
        cls.bundle2 = Bundle.objects.create(
            code="BND-F51-0002",
            work_order=cls.wo,
            qty=10,
            qty_done=10,
            state="DONE",
        )
        cls.operator = User.objects.create_user(
            username="op-f51",
            first_name="Andi",
            last_name="Operator",
            password="x",
            role=Role.objects.get(code=Role.Code.OPERATOR),
        )
        BundleEvent.objects.create(
            bundle=cls.bundle,
            event_type="BUNDLE_START",
            actor=cls.operator,
            payload={"note": "mulai"},
        )

    def test_order_bundles_collected(self):
        data = context_builder.build_context(
            "DATA_LOOKUP", [], "order SO-F51-0001?", {}
        )

        codes = {row["code"] for row in data["order_bundles"]}
        self.assertEqual(codes, {"BND-F51-0001", "BND-F51-0002"})

    def test_order_bundle_followup(self):
        history = [
            {"role": "user", "content": "order SO-F51-0001?"},
            {"role": "assistant", "content": "Order SO-F51-0001."},
        ]
        data = context_builder.build_context(
            "DATA_LOOKUP", [], "bundle apa?", {}, history=history
        )

        self.assertEqual(
            {row["code"] for row in data["order_bundles"]},
            {"BND-F51-0001", "BND-F51-0002"},
        )

    def test_bundle_operators_collected(self):
        data = context_builder.build_context(
            "DATA_LOOKUP",
            [],
            "operator yang mengerjakan bundle BND-F51-0001?",
            {},
        )

        self.assertEqual(data["bundle_operators"][0]["actor__username"], "op-f51")

    def test_event_log_serializes_actor(self):
        result = mcp_event_log.handle({"bundle_id": self.bundle.pk})

        self.assertTrue(result["ok"])
        self.assertEqual(result["events"][0]["actor_username"], "op-f51")
        self.assertEqual(result["events"][0]["actor_name"], "Andi Operator")

    def test_customer_detail_and_spend(self):
        data = context_builder.build_context(
            "DATA_LOOKUP", [], "customer PT Retail Fashion Indonesia?", {}
        )

        self.assertEqual(
            data["customer_detail"]["name"], "PT Retail Fashion Indonesia"
        )
        self.assertEqual(data["customer_spend"], 1600000.0)

    def test_order_total_spend_followup(self):
        history = [
            {"role": "user", "content": "order SO-F51-0001?"},
            {"role": "assistant", "content": "Order SO-F51-0001."},
        ]
        data = context_builder.build_context(
            "DATA_LOOKUP", [], "total belanjanya?", {}, history=history
        )

        self.assertEqual(data["customer_spend"], 1600000.0)

    def test_mencurigakan_triggers_operator_anomalies(self):
        expected = {
            "operators": [
                {
                    "username": "op-f51",
                    "score": 40,
                    "breakdown": {
                        "phantom_days": 2,
                        "impossible_cycles": 1,
                        "scrap_discrepancies": 1,
                    },
                }
            ]
        }
        with patch(
            "integrations.analytics.plugins.garment.anomaly."
            "operator_anomaly.collect_operator_anomalies",
            return_value=expected,
        ):
            data = context_builder.build_context(
                "DIAGNOSTIC", [], "kenapa operator itu mencurigakan?", {}
            )

        self.assertEqual(data["operator_anomalies"], expected)
