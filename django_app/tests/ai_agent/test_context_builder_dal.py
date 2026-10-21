"""Test context builder untuk repository DAL baru (FIX #7)."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from django.test import TestCase

from apps_industry.garment.models import CustomerInvoice, PurchaseOrder
from apps_industry.garment.tests.factories import (
    make_bundle,
    make_order,
    make_order_line,
    make_product,
    make_scrap_accumulator,
    make_work_order,
)
from integrations.ai_agent.orchestrator import context_builder
from master.models import Partner


def _user():
    return SimpleNamespace(role=SimpleNamespace(code="ADMIN"))


class ContextBuilderDalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.customer = Partner.objects.create(
            code="CUST-DAL-CTX", name="Gemini Furniture"
        )
        cls.product = make_product(code="PRD-DAL-CTX", name="Jaket")
        cls.order = make_order(code="ORD-DAL-CTX", customer=cls.customer)
        line = make_order_line(
            order=cls.order, product=cls.product, qty=2, price_unit=100
        )
        cls.work_order = make_work_order(order_line=line, code="WO-DAL-CTX")
        cls.bundle = make_bundle(
            work_order=cls.work_order, code="BND-DAL-CTX", state="SEWING"
        )
        make_scrap_accumulator(
            bundle=cls.bundle, qty=4, rework_qty=1
        )
        CustomerInvoice.objects.create(
            code="INV-DAL-CTX",
            order=cls.order,
            customer=cls.customer,
            invoice_date=date.today(),
            state="CONFIRMED",
            amount_total=200,
        )
        PurchaseOrder.objects.create(
            code="PO-DAL-CTX",
            vendor=cls.customer,
            state="CONFIRMED",
        )

    def _build(self, message):
        return context_builder.build_context(
            "DATA_LOOKUP", [], message, {}, user=_user()
        )

    def test_invoice_belum_dibayar(self):
        data = self._build("invoice belum dibayar?")

        self.assertEqual(data["invoices"][0]["code"], "INV-DAL-CTX")
        self.assertEqual(data["unpaid_invoices"][0]["code"], "INV-DAL-CTX")

    def test_vendor_po_belum_selesai(self):
        data = self._build("vendor PO belum selesai?")

        self.assertEqual(data["purchase_orders"][0]["vendor_name"], "Gemini Furniture")
        self.assertEqual(data["open_purchase_orders"][0]["code"], "PO-DAL-CTX")

    def test_order_bundle_terbanyak(self):
        data = self._build("order bundle terbanyak?")

        row = data["bundles_by_order"][0]
        self.assertEqual(row["work_order__order_line__order__code"], "ORD-DAL-CTX")
        self.assertGreaterEqual(row["bundle_count"], 1)

    def test_customer_scrap_terbanyak(self):
        data = self._build("customer scrap terbanyak?")

        row = data["scrap_by_customer"][0]
        self.assertEqual(
            row["bundle__work_order__order_line__order__customer__name"],
            "Gemini Furniture",
        )
        self.assertEqual(row["total_scrap"], 4)

    def test_top_customer_belanja(self):
        data = self._build("top customer belanja?")

        row = data["customer_total_spend"][0]
        self.assertEqual(row["order__customer__name"], "Gemini Furniture")
        self.assertEqual(row["total_spend"], 200)
