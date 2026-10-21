"""Test expand relasi halaman detail (FIX #8)."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase

from apps_industry.garment.models import CustomerInvoice
from apps_industry.garment.tests.factories import (
    make_bundle,
    make_order,
    make_order_line,
    make_product,
    make_work_order,
)
from integrations.ai_agent.orchestrator import context_builder
from master.models import Partner

MODULE = "integrations.ai_agent.orchestrator.context_builder"


def _user():
    return SimpleNamespace(role=SimpleNamespace(code="ADMIN"))


class DetailExpandTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.customer = Partner.objects.create(
            code="CUST-EXPAND", name="Gemini Furniture"
        )
        cls.product = make_product(code="PRD-EXPAND", name="Jaket Expand")
        cls.order = make_order(code="ORD-EXPAND", customer=cls.customer)
        line = make_order_line(
            order=cls.order, product=cls.product, qty=2, price_unit=100
        )
        cls.work_order = make_work_order(order_line=line, code="WO-EXPAND")
        cls.bundle = make_bundle(
            work_order=cls.work_order,
            code="BND-EXPAND",
            state="DONE",
            qty_done=7,
        )
        CustomerInvoice.objects.create(
            code="INV-EXPAND",
            order=cls.order,
            customer=cls.customer,
            invoice_date=date.today(),
            state="CONFIRMED",
        )

    def _handler(self, payload):
        table = payload.get("table")
        rows = {
            "master_product": [{"id": self.product.pk, "code": self.product.code}],
            "garment_order": [{"id": self.order.pk, "code": self.order.code}],
            "garment_bundle": [{"id": self.bundle.pk, "code": self.bundle.code}],
        }.get(table, [])
        return {"ok": True, "rows": rows, "count": len(rows)}

    def _build(self, resource_type, resource_id, page_type="detail", message="ini?"):
        context = {
            "page_type": page_type,
            "resource_type": resource_type,
            "resource_id": resource_id,
        }
        with patch(
            f"{MODULE}.mcp_postgres_query.handle", side_effect=self._handler
        ):
            return context_builder.build_context(
                "DATA_LOOKUP", [], message, context, user=_user()
            )

    def test_product_production_count(self):
        data = self._build("product", self.product.pk, message="produksi berapa kali?")

        self.assertEqual(data["product_production_count"], 7)

    def test_product_related_orders(self):
        data = self._build("product", self.product.pk)

        self.assertEqual(data["related_orders"][0]["code"], "ORD-EXPAND")

    def test_product_related_bundles(self):
        data = self._build("product", self.product.pk)

        self.assertEqual(data["related_bundles"][0]["code"], "BND-EXPAND")

    def test_product_related_customers(self):
        data = self._build("product", self.product.pk)

        self.assertEqual(data["related_customers"][0]["name"], "Gemini Furniture")

    def test_order_related_bundles(self):
        data = self._build("order", self.order.pk)

        self.assertEqual(data["related_bundles"][0]["code"], "BND-EXPAND")

    def test_order_related_invoices(self):
        data = self._build("order", self.order.pk)

        self.assertEqual(data["related_invoices"][0]["code"], "INV-EXPAND")

    def test_bundle_order_exists(self):
        data = self._build("bundle", self.bundle.pk)

        self.assertIn("bundle_order", data)

    def test_bundle_order_has_names(self):
        data = self._build("bundle", self.bundle.pk)

        self.assertEqual(data["bundle_order"]["order_code"], "ORD-EXPAND")
        self.assertEqual(data["bundle_order"]["customer_name"], "Gemini Furniture")
        self.assertEqual(data["bundle_order"]["product_name"], "Jaket Expand")

    def test_detail_resource_still_exists(self):
        data = self._build("product", self.product.pk)

        self.assertEqual(data["resource"][0]["code"], "PRD-EXPAND")

    def test_expand_tidak_jalan_di_list(self):
        data = self._build("product", self.product.pk, page_type="list")

        self.assertNotIn("product_production_count", data)
        self.assertNotIn("related_orders", data)
