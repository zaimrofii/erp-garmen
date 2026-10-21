"""Test data access layer (FIX #6) — repository template + JOIN nama."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from django.test import TestCase

from apps_industry.garment.tests.factories import (
    make_bundle,
    make_line,
    make_order,
    make_order_line,
    make_product,
    make_scrap_accumulator,
    make_work_center,
    make_work_order,
)
from apps_industry.garment.models import (
    CustomerInvoice,
    Payment,
    PurchaseOrder,
)
from integrations.ai_agent.data_access.metrics import MetricsRepository
from integrations.ai_agent.data_access.registry import (
    REPOSITORIES,
    get_repo,
    list_entities,
)
from integrations.ai_agent.data_access.orders import OrderRepository
from integrations.ai_agent.data_access.bundles import BundleRepository
from integrations.ai_agent.data_access.invoices import InvoiceRepository
from integrations.ai_agent.data_access.payments import PaymentRepository
from integrations.ai_agent.data_access.purchase_orders import PurchaseOrderRepository
from integrations.ai_agent.data_access.work_orders import WorkOrderRepository
from integrations.ai_agent.orchestrator import context_builder
from master.models import Partner


class DataAccessRegistryTests(TestCase):
    def test_registry_punya_10_entity(self):
        self.assertEqual(len(REPOSITORIES), 10)
        self.assertEqual(len(list_entities()), 10)

    def test_unknown_repo_none(self):
        self.assertIsNone(get_repo("unknown"))

    def test_alias_produk_dan_customer(self):
        self.assertIsNotNone(get_repo("produk"))
        self.assertIsNotNone(get_repo("customer"))

    def test_get_repo_invoice_instance(self):
        self.assertIsInstance(get_repo("invoice"), InvoiceRepository)


class RepositoryJoinTests(TestCase):
    def test_order_punya_customer_name(self):
        customer = Partner.objects.create(code="CUST-DAL", name="Gemini Furniture")
        order = make_order(code="ORD-DAL-1", customer=customer)
        make_order_line(order=order, product=make_product(name="Jaket"), qty=2)

        row = OrderRepository().get_list()[0]

        self.assertEqual(row["customer_name"], "Gemini Furniture")
        self.assertEqual(row["customer_code"], "CUST-DAL")
        self.assertEqual(row["lines"][0]["product_name"], "Jaket")

    def test_work_order_punya_product_dan_order(self):
        product = make_product(code="PRD-WO-DAL", name="Kaos DAL")
        order = make_order(code="ORD-WO-DAL")
        make_work_order(
            order_line=make_order_line(order=order, product=product),
            code="WO-DAL-1",
        )

        row = WorkOrderRepository().get_list()[0]

        self.assertEqual(row["product_name"], "Kaos DAL")
        self.assertEqual(row["order_code"], "ORD-WO-DAL")

    def test_bundle_punya_order_dan_product(self):
        bundle = make_bundle(code="BND-DAL-1")

        row = BundleRepository().get_list()[0]

        self.assertEqual(row["code"], "BND-DAL-1")
        self.assertEqual(
            row["order_code"], bundle.work_order.order_line.order.code
        )
        self.assertEqual(
            row["product_name"], bundle.work_order.order_line.product.name
        )

    def test_invoice_punya_customer_name(self):
        customer = Partner.objects.create(code="CUST-INV-DAL", name="Gemini Furniture")
        order = make_order(code="ORD-INV-DAL", customer=customer)
        CustomerInvoice.objects.create(
            code="INV-DAL-1",
            order=order,
            customer=customer,
            invoice_date=date.today(),
            amount_total=1000,
        )

        row = InvoiceRepository().get_list()[0]

        self.assertEqual(row["customer_name"], "Gemini Furniture")
        self.assertEqual(row["customer_code"], "CUST-INV-DAL")

    def test_purchase_order_punya_vendor_name(self):
        vendor = Partner.objects.create(
            code="VEND-DAL", name="PT Vendor", is_vendor=True
        )
        PurchaseOrder.objects.create(code="PO-DAL-1", vendor=vendor, state="CONFIRMED")

        row = PurchaseOrderRepository().get_list()[0]

        self.assertEqual(row["vendor_name"], "PT Vendor")
        self.assertEqual(row["vendor_code"], "VEND-DAL")

    def test_payment_punya_payment_type(self):
        customer = Partner.objects.create(code="CUST-PAY-DAL", name="PT Bayar")
        order = make_order(code="ORD-PAY-DAL", customer=customer)
        invoice = CustomerInvoice.objects.create(
            code="INV-PAY-DAL",
            order=order,
            customer=customer,
            invoice_date=date.today(),
        )
        Payment.objects.create(
            code="PAY-DAL-1",
            payment_type=Payment.PaymentType.INBOUND,
            partner=customer,
            customer_invoice=invoice,
            amount=1000,
            payment_date=date.today(),
        )

        row = PaymentRepository().get_list()[0]

        self.assertEqual(row["payment_type"], "INBOUND")

    def test_bundle_punya_line_name(self):
        line = make_line(code="LINE-BND-DAL")
        make_bundle(code="BND-LINE-DAL", production_line=line)

        row = BundleRepository().get_list()[0]

        self.assertEqual(row["line_name"], "LINE-BND-DAL")


class MetricsRepositoryTests(TestCase):
    def test_customer_orders_punya_nama(self):
        customer = Partner.objects.create(code="CUST-MET", name="Gemini Furniture")
        order = make_order(customer=customer)
        make_order_line(order=order, qty=2, price_unit=100)

        row = MetricsRepository().customer_orders()[0]

        self.assertEqual(row["customer__name"], "Gemini Furniture")
        self.assertEqual(row["customer"], "Gemini Furniture")
        self.assertEqual(row["amount"], 200.0)

    def test_product_production_punya_nama(self):
        bundle = make_bundle(code="BND-MET", qty_done=7, state="DONE")

        row = MetricsRepository().product_production()[0]

        self.assertEqual(
            row["work_order__order_line__product__name"],
            bundle.work_order.order_line.product.name,
        )
        self.assertEqual(row["qty_done"], 7.0)

    def test_metrics_wc_punya_work_center_name(self):
        wc = make_work_center(code="SEWING-DAL")
        make_scrap_accumulator(work_center=wc, qty=4, rework_qty=1)

        row = MetricsRepository().metrics_by_wc()[0]

        self.assertEqual(row["work_center_name"], "SEWING-DAL")
        self.assertEqual(row["work_center_code"], "SEWING-DAL")

    def test_metrics_line_punya_line_name(self):
        line = make_line(code="LINE-DAL")
        make_bundle(code="BND-LINE", state="SEWING", production_line=line)

        row = MetricsRepository().metrics_by_line()[0]

        self.assertEqual(row["line_name"], "LINE-DAL")
        self.assertEqual(row["line_id"], line.pk)

    def test_bundles_by_order_punya_order_code(self):
        bundle = make_bundle(code="BND-BY-ORDER")

        row = MetricsRepository().bundles_by_order()[0]

        self.assertEqual(
            row["work_order__order_line__order__code"],
            bundle.work_order.order_line.order.code,
        )
        self.assertEqual(row["bundle_count"], 1)

    def test_scrap_by_customer_punya_nama(self):
        customer = Partner.objects.create(code="CUST-SCRAP", name="Gemini Furniture")
        order = make_order(customer=customer)
        line = make_order_line(order=order)
        bundle = make_bundle(
            work_order=make_work_order(order_line=line), code="BND-SCRAP"
        )
        make_scrap_accumulator(bundle=bundle, qty=4, rework_qty=1)

        row = MetricsRepository().scrap_by_customer()[0]

        self.assertEqual(
            row["bundle__work_order__order_line__order__customer__name"],
            "Gemini Furniture",
        )
        self.assertEqual(row["total_scrap"], 4)

    def test_customer_total_spend_punya_nama(self):
        customer = Partner.objects.create(code="CUST-SPEND", name="Gemini Furniture")
        order = make_order(customer=customer)
        make_order_line(order=order, qty=2, price_unit=100)

        row = MetricsRepository().customer_total_spend()[0]

        self.assertEqual(row["order__customer__name"], "Gemini Furniture")
        self.assertEqual(row["total_spend"], 200)


class ContextBuilderRepositoryTests(TestCase):
    def test_order_context_punya_customer_name(self):
        customer = Partner.objects.create(code="CUST-CTX-DAL", name="Gemini Furniture")
        make_order(code="ORD-CTX-DAL", customer=customer)

        data = context_builder.build_context(
            "DATA_LOOKUP",
            [],
            "order terbaru?",
            {},
            user=SimpleNamespace(role=SimpleNamespace(code="ADMIN")),
        )

        self.assertEqual(data["orders"][0]["customer_name"], "Gemini Furniture")
