"""Test context injection T1.4 — list, general status, auto-detect."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from integrations.ai_agent.orchestrator import context_builder
from master.models import Partner, Product

MODULE = "integrations.ai_agent.orchestrator.context_builder"


def _user(role="SUPERVISOR"):
    return SimpleNamespace(role=SimpleNamespace(code=role))


def _rows(*rows):
    return {"ok": True, "rows": list(rows), "count": len(rows)}


class ContextListTests(SimpleTestCase):
    def test_page_list_product_mengisi_resource_list(self):
        with patch(
            f"{MODULE}.mcp_postgres_query.handle",
            return_value=_rows({"id": 1, "code": "PRD-1", "name": "Kaos"}),
        ) as query:
            data = context_builder.build_context(
                "DATA_LOOKUP",
                ["mcp-postgres-query"],
                "produk apa saja?",
                {"page_type": "list", "resource_type": "product"},
                user=_user(),
            )

        self.assertEqual(data["resource_list"][0]["code"], "PRD-1")
        self.assertEqual(data["resource_list_count"], 1)
        self.assertEqual(query.call_args.args[0]["table"], "master_product")

    def test_page_list_order_mengisi_resource_list(self):
        with patch(
            f"{MODULE}.mcp_postgres_query.handle",
            return_value=_rows({"id": 2, "code": "SO-1", "state": "DONE"}),
        ) as query:
            data = context_builder.build_context(
                "DATA_LOOKUP",
                ["mcp-postgres-query"],
                "order?",
                {"page_type": "list", "resource_type": "order"},
                user=_user(),
            )

        self.assertEqual(data["resource_list_count"], 1)
        self.assertEqual(query.call_args.args[0]["table"], "garment_order")

    def test_page_list_bundle(self):
        with patch(
            f"{MODULE}.mcp_postgres_query.handle",
            return_value=_rows({"id": 3, "code": "B-1", "state": "SEWING"}),
        ) as query:
            data = context_builder.build_context(
                "DATA_LOOKUP",
                ["mcp-postgres-query"],
                "bundle?",
                {"page_type": "list", "resource_type": "bundle"},
                user=_user(),
            )

        self.assertEqual(data["resource_list_count"], 1)
        self.assertEqual(query.call_args.args[0]["table"], "garment_bundle")


class ContextAutoDetectTests(TestCase):
    def test_auto_deteksi_produk(self):
        Product.objects.create(code="PRD-1", name="Kaos")
        data = context_builder.build_context(
            "DATA_LOOKUP",
            ["mcp-postgres-query"],
            "produk apa saja?",
            {},
            user=_user(),
        )

        self.assertEqual(data["auto_detected"]["resource_type"], "product")
        self.assertEqual(data["auto_detected"]["count"], 1)
        self.assertEqual(data["product_list"][0]["code"], "PRD-1")

    def test_auto_deteksi_customer(self):
        Partner.objects.create(code="CUST-1", name="PT Customer")
        data = context_builder.build_context(
            "DATA_LOOKUP",
            ["mcp-postgres-query"],
            "customer siapa saja?",
            {},
            user=_user(),
        )

        self.assertEqual(data["auto_detected"]["resource_type"], "partner")
        self.assertEqual(data["partners"][0]["code"], "CUST-1")

    def test_harga_disembunyikan_untuk_supervisor(self):
        Product.objects.create(code="PRD-1", name="Kaos", sale_price=75000)
        data = context_builder.build_context(
            "DATA_LOOKUP",
            ["mcp-postgres-query"],
            "produk?",
            {},
            user=_user("SUPERVISOR"),
        )

        self.assertNotIn("sale_price", data["auto_detected"]["rows"][0])

    def test_odoo_note_bila_tanpa_odoo_id(self):
        data = context_builder.build_context(
            "DATA_LOOKUP",
            ["mcp-postgres-query", "mcp-odoo-rpc"],
            "stok odoo?",
            {},
            user=_user(),
        )

        self.assertIn("product_odoo_id", data["odoo_note"])

    def test_odoo_stock_bila_snapshot_punya_odoo_id(self):
        with patch(
            f"{MODULE}.mcp_odoo_rpc.handle",
            return_value={"ok": True, "data": [{"id": 1, "quantity": 5}]},
        ) as handler:
            data = context_builder.build_context(
                "DATA_LOOKUP",
                ["mcp-postgres-query", "mcp-odoo-rpc"],
                "stok di odoo?",
                {
                    "visible_fields_snapshot": {"odoo_id": 88},
                    "resource_type": "product",
                    "resource_id": "1",
                },
                user=_user(),
            )

        self.assertEqual(data["odoo_stock"][0]["quantity"], 5)
        handler.assert_called_once()
        self.assertEqual(handler.call_args.args[1]["product_odoo_id"], 88)


class ContextGeneralStatusTests(TestCase):
    def test_general_chat_system_status(self):
        data = context_builder.build_context("GENERAL_CHAT", [], "halo", {})

        status = data["system_status"]
        self.assertIn("analytics_enabled", status)
        self.assertIn("product_count", status)
        self.assertIn("order_count", status)
        self.assertIn("bundle_active", status)
        self.assertEqual(
            status["metrics"], ["scrap_rate", "rework_rate", "lead_time"]
        )

    def test_unknown_juga_system_status(self):
        data = context_builder.build_context("UNKNOWN", [], "apa kabar", {})

        self.assertIn("system_status", data)

