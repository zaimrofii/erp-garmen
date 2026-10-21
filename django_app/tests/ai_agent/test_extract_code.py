"""Test ekstraksi kode spesifik dari pesan (FIX #11)."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from django.test import TestCase

from apps_industry.garment.models import CustomerInvoice, PurchaseOrder
from apps_industry.garment.tests.factories import make_bundle, make_order
from integrations.ai_agent.orchestrator import context_builder
from master.models import Partner


def _user():
    return SimpleNamespace(role=SimpleNamespace(code="ADMIN"))


class ExtractCodeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.bundle = make_bundle(code="RICH-BND-02")
        cls.order = make_order(code="SO-2026-0001")
        customer = Partner.objects.create(code="CUST-CODE", name="Gemini Furniture")
        make_order(code="ORD-INV-CODE", customer=customer)
        cls.invoice = CustomerInvoice.objects.create(
            code="RICH-INV-08",
            order=cls.order,
            customer=customer,
            invoice_date=date.today(),
        )
        cls.vendor = Partner.objects.create(
            code="VEND-CODE", name="PT Vendor", is_vendor=True
        )
        cls.po = PurchaseOrder.objects.create(
            code="RICH-PO-05", vendor=cls.vendor, state="CONFIRMED"
        )

    def _build(self, message):
        return context_builder.build_context("DATA_LOOKUP", [], message, {}, user=_user())

    def test_bundle_specific(self):
        data = self._build("order terkait RICH-BND-02?")

        self.assertEqual(data["bundle_specific"][0]["code"], "RICH-BND-02")

    def test_order_specific(self):
        data = self._build("status SO-2026-0001?")

        self.assertEqual(data["order_specific"][0]["code"], "SO-2026-0001")

    def test_invoice_specific(self):
        data = self._build("invoice RICH-INV-08?")

        self.assertEqual(data["invoice_specific"][0]["code"], "RICH-INV-08")

    def test_po_specific(self):
        data = self._build("PO RICH-PO-05?")

        self.assertEqual(data["po_specific"][0]["code"], "RICH-PO-05")

    def test_tanpa_kode_tidak_ada_specific(self):
        data = self._build("produk apa saja?")

        for key in (
            "bundle_specific",
            "order_specific",
            "invoice_specific",
            "po_specific",
            "wo_specific",
        ):
            self.assertNotIn(key, data)
