"""Test unified context builder (FIX #5) — page data + keyword data."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import TestCase

from apps_industry.garment.tests.factories import (
    make_bundle,
    make_order,
    make_order_line,
    make_work_center,
    make_work_order,
)
from integrations.ai_agent.orchestrator import context_builder
from master.models import Partner

MODULE = "integrations.ai_agent.orchestrator.context_builder"

PRODUCTS = [
    {"id": 1, "code": "PRD-1", "name": "Kaos", "sale_price": 50000},
    {"id": 2, "code": "PRD-2", "name": "Jaket", "sale_price": 500000},
]
PARTNERS = [{"id": 10, "code": "CUST-1", "name": "PT Pelanggan"}]
ORDERS = [{"id": 20, "code": "SO-1", "state": "CONFIRMED"}]
BUNDLES = [{"id": 30, "code": "BND-1", "state": "SEWING"}]
WORK_ORDERS = [{"id": 40, "code": "WO-1", "state": "IN_PROGRESS"}]


def _user(role="ADMIN"):
    return SimpleNamespace(role=SimpleNamespace(code=role))


def _handler(payload):
    table = payload.get("table")
    rows = {
        "master_product": PRODUCTS,
        "master_partner": PARTNERS,
        "garment_order": ORDERS,
        "garment_orderline": [],
        "garment_bundle": BUNDLES,
        "garment_workorder": WORK_ORDERS,
    }.get(table)
    if rows is None:
        return {"ok": False, "error": "table_not_allowed"}
    return {"ok": True, "rows": list(rows), "count": len(rows)}


PRODUCT_PAGE = {
    "page_type": "list",
    "resource_type": "product",
}


class UnifiedContextBuilderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        make_bundle(code="BND-1", state="SEWING")
        Partner.objects.create(code="CUST-1", name="PT Pelanggan")
        make_order(code="SO-1", state="CONFIRMED")
        make_work_order(code="WO-1", state="IN_PROGRESS")
        make_work_center(code="SEWING-2")

    def _build(self, message, context=None, tools=None):
        with patch(
            f"{MODULE}.mcp_postgres_query.handle", side_effect=_handler
        ) as query:
            data = context_builder.build_context(
                "DATA_LOOKUP",
                tools or [],
                message,
                context if context is not None else dict(PRODUCT_PAGE),
                user=_user(),
            )
        return data, query

    def test_page_product_bundle_keyword(self):
        data, _ = self._build("bundle apa saja?")

        self.assertEqual(data["resource_list"][0]["code"], "PRD-2")
        self.assertEqual(data["bundles"][0]["code"], "BND-1")

    def test_page_product_customer_keyword(self):
        data, _ = self._build("customer siapa saja?")

        self.assertEqual(data["partners"][0]["code"], "CUST-1")
        self.assertEqual(data["resource_list"][0]["code"], "PRD-2")

    def test_page_product_order_keyword(self):
        data, _ = self._build("order terbaru?")

        self.assertIn(
            "SO-1", {row["code"] for row in data["orders"]}
        )
        self.assertEqual(data["resource_list_count"], 2)

    def test_page_product_produk_dedupe(self):
        data, query = self._build("produk apa saja?")

        self.assertEqual(data["resource_list_count"], 2)
        self.assertEqual(data["product_list"][0]["code"], "PRD-2")
        product_calls = [
            call
            for call in query.call_args_list
            if call.args[0].get("table") == "master_product"
        ]
        self.assertEqual(len(product_calls), 1)

    def test_page_detail_product_stock_dan_resource(self):
        stock = [{"product_id": 1, "code": "PRD-1", "quantity": 7}]
        with patch(
            f"{MODULE}.builder._collect_stock", return_value=(stock, [])
        ):
            data, _ = self._build(
                "stok produk ini?",
                {
                    "page_type": "detail",
                    "resource_type": "product",
                    "resource_id": 1,
                },
            )

        self.assertEqual(data["resource"][0]["code"], "PRD-1")
        self.assertEqual(data["stock"][0]["quantity"], 7)

    def test_page_product_work_order_keyword(self):
        data, _ = self._build("wo belum selesai?")

        self.assertEqual(data["work_orders"][0]["code"], "WO-1")

    def test_page_product_wc_keyword(self):
        metrics = {
            "ok": True,
            "rows": [{"key": "SEWING-2", "value": 20.0}],
            "unit": "%",
        }
        with patch(
            f"{MODULE}.mcp_analytics.handle_request", return_value=metrics
        ):
            data, _ = self._build("wc paling sibuk?")

        self.assertEqual(data["metrics_by_wc"][0]["rows"][0]["key"], "SEWING-2")

    def test_page_product_bundle_tidak_query_product_dua_kali(self):
        data, query = self._build("bundle apa saja?")

        self.assertIn("resource_list", data)
        self.assertIn("bundles", data)
        product_calls = [
            call
            for call in query.call_args_list
            if call.args[0].get("table") == "master_product"
        ]
        self.assertEqual(len(product_calls), 1)
        self.assertEqual(data["bundles"][0]["code"], "BND-1")
