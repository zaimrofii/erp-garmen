"""Regresi FIX #22 — bundle tanpa event, bundle per WC, avg FG, chart metric."""

from __future__ import annotations

from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase

from apps_industry.garment.models import (
    Bundle,
    Order,
    OrderLine,
    WorkCenter,
    WorkOrder,
)
from core.auth.models import Role, User
from integrations.ai_agent.data_access.metrics import MetricsRepository
from integrations.ai_agent.orchestrator.chart_builder import build_chart_data
from integrations.ai_agent.orchestrator.context_builder import build_context
from master.models import Product


class Fix22ContextTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(
            username="f22-owner",
            password="x",
            role=Role.objects.get(code=Role.Code.OWNER),
        )
        cls.product = Product.objects.create(
            code="F22-PROD",
            name="Kaos F22",
            category="Material",
            sale_price=100000,
            cost_price=70000,
        )
        cls.order = Order.objects.create(code="F22-ORDER")
        cls.line = OrderLine.objects.create(
            order=cls.order,
            product=cls.product,
            qty=10,
            price_unit=100000,
        )
        cls.wo = WorkOrder.objects.create(
            code="F22-WO", order_line=cls.line, qty_planned=10
        )
        cls.no_event = Bundle.objects.create(
            code="F22-BND-NOEVENT",
            work_order=cls.wo,
            qty=10,
            state="DRAFT",
        )
        cls.wc = WorkCenter.objects.create(code="SEWING-2", name="Sewing 2")
        cls.in_wc = Bundle.objects.create(
            code="F22-BND-WC",
            work_order=cls.wo,
            qty=10,
            state="SEWING",
            current_work_center=cls.wc,
        )
        for code, name, category, price in (
            ("F22-FG-A", "Kaos F22 A", "Kaos", 100000),
            ("F22-FG-B", "Jaket F22 B", "Jaket", 200000),
            ("F22-RM", "Kain F22", "Material", 9000000),
        ):
            Product.objects.create(
                code=code,
                name=name,
                category=category,
                sale_price=price,
                cost_price=price,
            )

    def context(self, message: str) -> dict:
        return build_context(
            "DATA_LOOKUP", ["mcp-postgres-query"], message, {}, user=self.owner
        )

    def test_bundle_tanpa_event_muncul_di_context(self):
        data = self.context("bundle tanpa event?")

        self.assertIn("F22-BND-NOEVENT", [row["code"] for row in data["bundles"]])

    def test_bundle_per_wc_muncul_di_context(self):
        data = self.context("WC SEWING-2 bundle?")

        self.assertIn(
            "F22-BND-WC",
            [row["bundle_code"] for row in data["bundles_in_wc"]],
        )

    def test_bundle_per_wc_via_current_work_center(self):
        rows = MetricsRepository().bundles_in_work_center("SEWING-2")

        self.assertIn("F22-BND-WC", [row["bundle_code"] for row in rows])
        self.assertEqual(rows[0]["events_count"], 0)

    def test_rata_rata_harga_default_fg(self):
        data = self.context("rata-rata harga?")

        self.assertEqual(data["price_aggregate"]["value"], 150000.0)
        self.assertEqual(data["price_aggregate"]["count"], 2)
        self.assertTrue(
            all(row["category"] != "Material" for row in data["product_list"])
        )


class Fix22ChartTests(SimpleTestCase):
    METRICS = [
        {
            "metric_id": "garment.scrap_rate",
            "dimension": "period",
            "rows": [
                {"label": "2026-10-18", "value": 1.6},
                {"label": "2026-10-19", "value": 2.0},
            ],
        },
        {
            "metric_id": "garment.lead_time",
            "dimension": "period",
            "rows": [
                {"label": "2026-10-18", "value": 20.0},
                {"label": "2026-10-19", "value": 21.0},
            ],
        },
        {
            "metric_id": "garment.oee",
            "dimension": "period",
            "rows": [
                {"label": "2026-10-18", "value": 70.0},
                {"label": "2026-10-19", "value": 72.0},
            ],
        },
    ]

    def test_chart_scrap(self):
        chart = build_chart_data(
            {"metrics": self.METRICS}, "ANALYTICS_QUERY", "tren scrap?"
        )

        self.assertEqual(chart["metric_id"], "garment.scrap_rate")

    def test_chart_lead_time(self):
        chart = build_chart_data(
            {"metrics": self.METRICS}, "ANALYTICS_QUERY", "tren lead time?"
        )

        self.assertEqual(chart["metric_id"], "garment.lead_time")

    def test_chart_oee(self):
        chart = build_chart_data(
            {"metrics": self.METRICS}, "ANALYTICS_QUERY", "OEE SEWING-2?"
        )

        self.assertEqual(chart["metric_id"], "garment.oee")
