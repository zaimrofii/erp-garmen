"""Test 3 MCP dasar (D.3) — 12 skenario."""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps_industry.garment.models import BundleEvent
from apps_industry.garment.tests.factories import make_bundle, make_order, make_product
from integrations.ai_agent.mcp_servers import (
    mcp_calculator,
    mcp_event_log,
    mcp_postgres_query,
    registry,
)


class McpRegistryTests(TestCase):
    def setUp(self):
        registry._reset_for_tests()

    def test_discover_tiga_mcp(self):
        count = registry.discover_mcp_servers()

        self.assertEqual(count, 10)
        self.assertEqual(
            registry.list_mcp(),
            [
                "mcp-aggregator",
                "mcp-analytics",
                "mcp-calculator",
                "mcp-comparator",
                "mcp-event-log",
                "mcp-forecaster",
                "mcp-odoo-rpc",
                "mcp-postgres-query",
                "mcp-rule-engine",
                "mcp-time-series",
            ],
        )


class PostgresQueryTests(TestCase):
    def test_query_valid_allowlist(self):
        make_order(code="ORD-MCP-1")

        result = mcp_postgres_query.handle(
            {"table": "garment_order", "columns": ["id", "code"], "filters": {}}
        )

        self.assertTrue(result["ok"])
        self.assertGreaterEqual(result["count"], 1)

    def test_table_tidak_allowlist(self):
        result = mcp_postgres_query.handle({"table": "auth_user"})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "table_not_allowed")

    def test_sql_injection_table_ditolak(self):
        result = mcp_postgres_query.handle({"table": "garment_order; DROP TABLE x"})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "table_not_allowed")

    def test_limit_dipaksa_100(self):
        result = mcp_postgres_query.handle(
            {"table": "garment_order", "columns": ["id"], "limit": 500}
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["limit"], 100)

    def test_injection_di_filter_ditolak(self):
        result = mcp_postgres_query.handle(
            {
                "table": "garment_order",
                "columns": ["id"],
                "filters": {"code": "x; DROP TABLE garment_order"},
            }
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "unsafe_input")

    def test_master_product_allowlist(self):
        product = make_product(code="PRD-MCP-1")

        result = mcp_postgres_query.handle(
            {
                "table": "master_product",
                "columns": ["id", "code", "name"],
                "filters": {"id": product.pk},
            }
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["rows"][0]["code"], "PRD-MCP-1")

    def test_core_auth_user_ditolak(self):
        result = mcp_postgres_query.handle(
            {"table": "core_auth_user", "columns": ["id"], "limit": 1}
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "table_not_allowed")
        self.assertEqual(result["status"], 400)

    def test_master_partner_tanpa_npwp(self):
        result = mcp_postgres_query.handle(
            {"table": "master_partner", "columns": ["npwp"]}
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "columns_not_allowed")



class EventLogTests(TestCase):
    def setUp(self):
        self.bundle = make_bundle(code="BND-MCP-1", qty=2)
        self.event = BundleEvent.objects.create(
            bundle=self.bundle, event_type="BUNDLE_START", payload={"note": "mulai"}
        )
        BundleEvent.objects.create(
            bundle=self.bundle, event_type="SCRAP", payload={"qty": 1}
        )

    def test_bundle_id_menghasilkan_events(self):
        result = mcp_event_log.handle({"bundle_id": self.bundle.pk})

        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 2)

    def test_filter_event_types(self):
        result = mcp_event_log.handle(
            {"bundle_id": self.bundle.pk, "event_types": ["SCRAP"]}
        )

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["events"][0]["event_type"], "SCRAP")

    def test_filter_date_range(self):
        BundleEvent.objects.filter(pk=self.event.pk).update(
            ts=timezone.now() - timedelta(days=30)
        )

        result = mcp_event_log.handle(
            {
                "bundle_id": self.bundle.pk,
                "date_from": (timezone.now() - timedelta(minutes=1)).isoformat(),
            }
        )

        self.assertEqual(result["count"], 1)  # hanya event SCRAP (baru)


class CalculatorTests(TestCase):
    def test_add_multiply_divide(self):
        self.assertEqual(
            mcp_calculator.handle({"operation": "add", "a": 2, "b": 3})["result"], 5
        )
        self.assertEqual(
            mcp_calculator.handle({"operation": "multiply", "a": 2, "b": 3})["result"],
            6,
        )
        self.assertEqual(
            mcp_calculator.handle({"operation": "divide", "a": 6, "b": 3})["result"],
            2,
        )

    def test_divide_by_zero_rapi(self):
        result = mcp_calculator.handle({"operation": "divide", "a": 1, "b": 0})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "division_by_zero")

    def test_operation_tidak_dikenal(self):
        result = mcp_calculator.handle({"operation": "pow", "a": 2, "b": 3})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "operation_tidak_dikenal")
        self.assertEqual(result["status"], 400)
