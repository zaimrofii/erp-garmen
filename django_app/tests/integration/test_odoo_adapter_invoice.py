"""Test TX-INVOICE (`OdooAdapter.push_customer_invoice_wo`) — Django TestCase.

Unit **mock** (client palsu) — **TIDAK** memanggil Odoo nyata. Berbeda dari
`test_odoo_adapter_scrap.py` yang punya test Odoo nyata: invoice nyata sulit
dibersihkan tanpa hak admin (invoice posted tidak bisa di-`unlink`), jadi bukti
E2E dilakukan manual. File ini **self-cleaning** (semua efek di DB test Django).

``wo`` = dict minimal ``{order_id (pk Order Django), ref}`` (+ opsional
``invoice_date``). Adapter me-resolve: ``Order.customer`` → ``Partner.odoo_id``
dan tiap ``OrderLine.product`` → ``Product.odoo_id``.

Jalankan:

    docker compose exec django python manage.py test tests.integration.test_odoo_adapter_invoice
"""

from __future__ import annotations

import re
from unittest.mock import MagicMock

from django.test import TestCase
from django.utils import timezone

from apps_industry.garment.models import Order, OrderLine
from integrations.erp_sync.adapters.base import ERPResponse
from integrations.erp_sync.adapters.odoo import STAGE_INVOICE, OdooAdapter
from master.models import Partner, Product

PARTNER_ODOO_ID = 51
PRODUCT_A_ODOO_ID = 100
PRODUCT_B_ODOO_ID = 101
MOVE_ID = 42
REF = "INV-ORD-INV-0001"
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class OdooAdapterPushCustomerInvoiceWoMockTests(TestCase):
    """Unit (mock client): payload ``account.move.create`` + jalur gagal tanpa I/O."""

    def setUp(self):
        self.customer = Partner.objects.create(
            code="PT-BUYER-INV", name="PT Buyer", odoo_id=PARTNER_ODOO_ID
        )
        self.product_a = Product.objects.create(
            code="KTS-EXPORT-L", name="Kaos Export L", odoo_id=PRODUCT_A_ODOO_ID
        )
        self.product_b = Product.objects.create(
            code="KTS-EXPORT-M", name="Kaos Export M", odoo_id=PRODUCT_B_ODOO_ID
        )
        # Tanpa `addCleanup(...delete)`: `Order.customer` & `OrderLine.product`
        # bersifat PROTECT, jadi menghapus Partner/Product di teardown akan
        # melempar ProtectedError. TestCase sudah me-rollback seluruh transaksi
        # (tidak ada data test yang menetap), jadi cleanup memang tidak perlu.
        self.order = Order.objects.create(code="ORD-INV-0001", customer=self.customer)
        OrderLine.objects.create(order=self.order, product=self.product_a, qty=12)
        OrderLine.objects.create(order=self.order, product=self.product_b, qty=5)

        self.client_mock = MagicMock()
        self.client_mock.execute_kw.return_value = [MOVE_ID]
        self.adapter = OdooAdapter(client=self.client_mock)

    # ------------------------------------------------------------------ happy
    def test_push_customer_invoice_wo_sukses(self):
        response = self.adapter.push_customer_invoice_wo(
            {"order_id": self.order.pk, "ref": REF}
        )

        self.assertIsInstance(response, ERPResponse)
        self.assertTrue(response.ok, response.error)
        self.assertEqual(response.erp_id, str(MOVE_ID))
        self.assertEqual(response.stage, STAGE_INVOICE)
        self.assertEqual(response.ref, REF)
        self.assertEqual(response.raw["move_id"], MOVE_ID)

        # Tepat SATU panggilan: `account.move`/`create` (tanpa `action_post`).
        self.client_mock.execute_kw.assert_called_once()
        call = self.client_mock.execute_kw.call_args
        self.assertEqual(call.args[0], "account.move")
        self.assertEqual(call.args[1], "create")

        values = call.args[2][0][0]
        self.assertEqual(
            set(values),
            {"partner_id", "move_type", "invoice_date", "ref", "invoice_line_ids"},
        )
        self.assertEqual(values["partner_id"], PARTNER_ODOO_ID)
        self.assertEqual(values["move_type"], "out_invoice")
        self.assertEqual(values["ref"], REF)
        self.assertTrue(ISO_DATE.match(values["invoice_date"]), values["invoice_date"])
        self.assertEqual(values["invoice_date"], str(timezone.localdate()))
        # Odoo pakai default company: journal/currency TIDAK dikirim.
        self.assertNotIn("journal_id", values)
        self.assertNotIn("currency_id", values)

        self.assertEqual(
            values["invoice_line_ids"],
            [
                (
                    0,
                    0,
                    {
                        "product_id": PRODUCT_A_ODOO_ID,
                        "quantity": 12,
                        "price_unit": 0,
                        "name": "KTS-EXPORT-L",
                    },
                ),
                (
                    0,
                    0,
                    {
                        "product_id": PRODUCT_B_ODOO_ID,
                        "quantity": 5,
                        "price_unit": 0,
                        "name": "KTS-EXPORT-M",
                    },
                ),
            ],
        )

    def test_invoice_date_bisa_di_override(self):
        self.adapter.push_customer_invoice_wo(
            {"order_id": self.order.pk, "ref": REF, "invoice_date": "2026-09-30"}
        )

        values = self.client_mock.execute_kw.call_args.args[2][0][0]

        self.assertEqual(values["invoice_date"], "2026-09-30")

    def test_orderline_tanpa_odoo_id_dilewati(self):
        product_tanpa_odoo = Product.objects.create(
            code="KTS-NO-ODOO", name="Belum Sinkron"
        )
        OrderLine.objects.create(order=self.order, product=product_tanpa_odoo, qty=3)

        response = self.adapter.push_customer_invoice_wo(
            {"order_id": self.order.pk, "ref": REF}
        )

        self.assertTrue(response.ok, response.error)
        values = self.client_mock.execute_kw.call_args.args[2][0][0]
        # 3 OrderLine, tapi hanya 2 yang punya product.odoo_id.
        self.assertEqual(len(values["invoice_line_ids"]), 2)

    # ------------------------------------------------------------- jalur gagal
    def test_customer_none_ok_false_tanpa_create(self):
        order = Order.objects.create(code="ORD-INV-0002")  # customer=None

        response = self.adapter.push_customer_invoice_wo(
            {"order_id": order.pk, "ref": "INV-TANPA-CUSTOMER"}
        )

        self.assertFalse(response.ok)
        self.assertIn("customer", response.error)
        self.assertIsNone(response.erp_id)
        self.client_mock.execute_kw.assert_not_called()

    def test_customer_odoo_id_none_ok_false_tanpa_create(self):
        partner = Partner.objects.create(code="PT-NO-ODOO", name="Belum Sinkron")
        order = Order.objects.create(code="ORD-INV-0004", customer=partner)

        response = self.adapter.push_customer_invoice_wo(
            {"order_id": order.pk, "ref": "INV-CUSTOMER-NO-ODOO"}
        )

        self.assertFalse(response.ok)
        self.assertIn("odoo_id", response.error)
        self.client_mock.execute_kw.assert_not_called()

    def test_semua_orderline_tanpa_odoo_id_ok_false(self):
        product = Product.objects.create(code="KTS-NO-ODOO-2", name="Belum Sinkron")
        order = Order.objects.create(code="ORD-INV-0003", customer=self.customer)
        OrderLine.objects.create(order=order, product=product, qty=1)

        response = self.adapter.push_customer_invoice_wo(
            {"order_id": order.pk, "ref": "INV-NO-LINE"}
        )

        self.assertFalse(response.ok)
        self.assertIn("product.odoo_id", response.error)
        self.client_mock.execute_kw.assert_not_called()

    def test_wo_kurang_field_ok_false_tanpa_create(self):
        response = self.adapter.push_customer_invoice_wo({"ref": "INV-KURANG"})

        self.assertFalse(response.ok)
        self.assertIn("tidak lengkap", response.error)
        self.assertIn("order_id", response.error)
        self.client_mock.execute_kw.assert_not_called()

    def test_order_tidak_ada_ok_false(self):
        response = self.adapter.push_customer_invoice_wo(
            {"order_id": 999_999, "ref": "INV-NO-ORDER"}
        )

        self.assertFalse(response.ok)
        self.assertIn("tidak ditemukan", response.error)
        self.client_mock.execute_kw.assert_not_called()

    def test_client_none_ok_false(self):
        # CATATAN: `OdooAdapter(client=None)` justru MEMBANGUN client nyata dari
        # settings (lihat `__init__`), jadi client di-None-kan SETELAH konstruksi
        # supaya test ini tidak menyentuh Odoo sama sekali.
        adapter = OdooAdapter(client=self.client_mock)
        adapter.client = None

        response = adapter.push_customer_invoice_wo(
            {"order_id": self.order.pk, "ref": REF}
        )

        self.assertFalse(response.ok)
        self.assertIn("client", response.error)
        self.client_mock.execute_kw.assert_not_called()

    def test_error_odoo_ok_false_tidak_raise(self):
        self.client_mock.execute_kw.side_effect = RuntimeError(
            "Invalid field 'journal_id' on model 'account.move'"
        )

        response = self.adapter.push_customer_invoice_wo(
            {"order_id": self.order.pk, "ref": REF}
        )

        self.assertFalse(response.ok)
        self.assertIn("Invalid field", response.error)
        self.assertIsNone(response.erp_id)
