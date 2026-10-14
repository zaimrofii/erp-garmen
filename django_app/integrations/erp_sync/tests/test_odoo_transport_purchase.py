"""Test `OdooTransport` PO (I2 material readiness) — mock client, tanpa Odoo.

`fetch_purchase_orders(since=None, states=("purchase","done"))` (header
``purchase.order``) dan `fetch_purchase_order_lines(order_ids, since=None)`
(``purchase.order.line``): happy path (model + domain + field list), varian
``since``/``states``/``order_ids`` kosong, dan fail-safe ``client None`` → ``[]``.

Dipisah dari `test_odoo_transport_sale.py` supaya satu file = satu ranah
(sejalan dengan `test_odoo_transport_master.py`).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from django.test import SimpleTestCase

from integrations.erp_sync.transport import OdooTransport

ROWS = [{"id": 1}]
SINCE = "2026-10-06 00:00:00"

#: Ditulis manual (bukan impor dari modul) supaya perubahan field tertangkap test.
PURCHASE_ORDER_FIELDS = [
    "id",
    "name",
    "partner_id",
    "date_order",
    "date_planned",
    "state",
    "amount_total",
    "currency_id",
    "order_line",
]
PURCHASE_ORDER_LINE_FIELDS = [
    "id",
    "order_id",
    "product_id",
    "product_qty",
    "qty_received",
    "price_unit",
    "date_planned",
    "product_uom",
]


class FetchPurchaseOrdersTests(SimpleTestCase):
    """``fetch_purchase_orders`` — header PO (default state purchase+done)."""

    def _transport(self):
        client = MagicMock()
        client.execute_kw.return_value = ROWS
        return OdooTransport(client=client), client

    def test_happy_path_model_domain_fields(self):
        transport, client = self._transport()

        result = transport.fetch_purchase_orders()

        client.execute_kw.assert_called_once_with(
            "purchase.order",
            "search_read",
            [[("state", "in", ["purchase", "done"])], PURCHASE_ORDER_FIELDS],
        )
        self.assertEqual(result, ROWS)

    def test_since_menambah_domain_write_date(self):
        transport, client = self._transport()

        transport.fetch_purchase_orders(since=SINCE)

        client.execute_kw.assert_called_once_with(
            "purchase.order",
            "search_read",
            [
                [
                    ("state", "in", ["purchase", "done"]),
                    ("write_date", ">", SINCE),
                ],
                PURCHASE_ORDER_FIELDS,
            ],
        )

    def test_states_bisa_di_override(self):
        transport, client = self._transport()

        transport.fetch_purchase_orders(states=("done",))

        client.execute_kw.assert_called_once_with(
            "purchase.order",
            "search_read",
            [[("state", "in", ["done"])], PURCHASE_ORDER_FIELDS],
        )

    def test_client_none_mengembalikan_list_kosong(self):
        self.assertEqual(OdooTransport(client=None).fetch_purchase_orders(), [])


class FetchPurchaseOrderLinesTests(SimpleTestCase):
    """``fetch_purchase_order_lines`` — baris PO per ``order_ids``."""

    def _transport(self):
        client = MagicMock()
        client.execute_kw.return_value = ROWS
        return OdooTransport(client=client), client

    def test_happy_path_model_domain_fields(self):
        transport, client = self._transport()

        result = transport.fetch_purchase_order_lines([7, 8])

        client.execute_kw.assert_called_once_with(
            "purchase.order.line",
            "search_read",
            [[("order_id", "in", [7, 8])], PURCHASE_ORDER_LINE_FIELDS],
        )
        self.assertEqual(result, ROWS)

    def test_since_menambah_domain_write_date(self):
        transport, client = self._transport()

        transport.fetch_purchase_order_lines([7], since=SINCE)

        client.execute_kw.assert_called_once_with(
            "purchase.order.line",
            "search_read",
            [
                [("order_id", "in", [7]), ("write_date", ">", SINCE)],
                PURCHASE_ORDER_LINE_FIELDS,
            ],
        )

    def test_order_ids_kosong_domain_in_kosong(self):
        transport, client = self._transport()

        transport.fetch_purchase_order_lines(None)

        client.execute_kw.assert_called_once_with(
            "purchase.order.line",
            "search_read",
            [[("order_id", "in", [])], PURCHASE_ORDER_LINE_FIELDS],
        )

    def test_client_none_mengembalikan_list_kosong(self):
        self.assertEqual(OdooTransport(client=None).fetch_purchase_order_lines([7]), [])
