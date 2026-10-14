"""Test `SaleOrderSyncService` (I2) — transport di-mock, tanpa jaringan/Odoo.

Cakupan:

* happy path: 1 SO + 2 line → ``created=3`` dan FK (`customer`/`product`) benar;
* idempotensi: 2× data sama → ``updated=3, created=0``;
* partner tidak ketemu → ``Order.customer=None`` + ``skipped>0``;
* product tidak ketemu → ``OrderLine.product=None`` + ``skipped>0``;
* transport ``[]`` → ``created=0`` tanpa error.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from django.test import TestCase

from apps_industry.garment.models import Order, OrderLine
from integrations.erp_sync.services import SaleOrderSyncService
from master.models import Partner, Product

SO_ROWS = [
    {
        "id": 500,
        "name": "S00001",
        "partner_id": [51, "PT Buyer Export"],
        "date_order": "2026-10-06 08:00:00",
        "client_order_ref": "PO-BUYER-1",
        "state": "sale",
        "amount_total": 1500000.0,
        "currency_id": [12, "IDR"],
        "order_line": [900, 901],
    }
]
LINE_ROWS = [
    {
        "id": 900,
        "order_id": [500, "S00001"],
        "product_id": [100, "Kaos Export L"],
        "product_uom_qty": 12.0,
        "price_unit": 100000.0,
        "name": "Kaos Export L",
        "product_uom": [33, "PCS"],
    },
    {
        "id": 901,
        "order_id": [500, "S00001"],
        "product_id": [99, "Kain Cotton 30s"],
        "product_uom_qty": 1.5,
        "price_unit": 30000.0,
        "name": "Kain Cotton 30s",
        "product_uom": [33, "PCS"],
    },
]


def make_transport(so_rows, line_rows):
    """Transport dengan ``fetch_sale_orders``/``fetch_sale_order_lines`` di-mock."""
    transport = MagicMock()
    transport.fetch_sale_orders.return_value = so_rows
    transport.fetch_sale_order_lines.return_value = line_rows
    return transport


class SaleOrderSyncServiceTests(TestCase):
    """``SaleOrderSyncService.sync()`` — upsert `Order`/`OrderLine` via `odoo_id`."""

    def setUp(self):
        self.partner = Partner.objects.create(
            code="PT-BUYER", name="PT Buyer Export", odoo_id=51
        )
        self.product_fg = Product.objects.create(
            code="KTS-EXPORT-L", name="Kaos Export L", odoo_id=100, odoo_tmpl_id=10
        )
        self.product_rm = Product.objects.create(
            code="KAIN-COTTON-30S", name="Kain Cotton 30s", odoo_id=99, odoo_tmpl_id=9
        )

    def _sync(self, so_rows=None, line_rows=None):
        transport = make_transport(
            SO_ROWS if so_rows is None else so_rows,
            LINE_ROWS if line_rows is None else line_rows,
        )
        return SaleOrderSyncService(transport=transport).sync()

    def test_happy_path_created_3_dan_fk_benar(self):
        result = self._sync()

        self.assertEqual(result, {"created": 3, "updated": 0, "skipped": 0})
        order = Order.objects.get(odoo_id=500)
        self.assertEqual(order.code, "S00001")
        self.assertEqual(order.customer, self.partner)
        self.assertEqual(order.lines.count(), 2)

        line = OrderLine.objects.get(odoo_id=900)
        self.assertEqual(line.order, order)
        self.assertEqual(line.product, self.product_fg)
        self.assertEqual(line.qty, 12)
        self.assertEqual(OrderLine.objects.get(odoo_id=901).product, self.product_rm)

    def test_idempotensi_dua_kali_updated_3(self):
        self._sync()

        result = self._sync()

        self.assertEqual(result, {"created": 0, "updated": 3, "skipped": 0})
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(OrderLine.objects.count(), 2)

    def test_partner_tidak_ketemu_order_tanpa_customer(self):
        so_rows = [{**SO_ROWS[0], "partner_id": [999, "Partner Baru"]}]

        result = self._sync(so_rows=so_rows)

        self.assertEqual(result["created"], 3)
        self.assertEqual(result["skipped"], 1)  # hanya customer yang unresolved
        self.assertIsNone(Order.objects.get(odoo_id=500).customer)

    def test_product_tidak_ketemu_orderline_tanpa_product(self):
        line_rows = [
            LINE_ROWS[0],
            {**LINE_ROWS[1], "product_id": [777, "Produk Baru"]},
        ]

        result = self._sync(line_rows=line_rows)

        self.assertEqual(result["created"], 3)
        self.assertEqual(result["skipped"], 1)  # hanya 1 line yang unresolved
        self.assertIsNone(OrderLine.objects.get(odoo_id=901).product)

    def test_transport_kosong_created_0_tanpa_error(self):
        result = self._sync(so_rows=[], line_rows=[])

        self.assertEqual(result, {"created": 0, "updated": 0, "skipped": 0})
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(OrderLine.objects.count(), 0)
