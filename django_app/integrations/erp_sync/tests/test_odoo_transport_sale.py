"""Test `OdooTransport` SO sync (I2) — mock client, tanpa jaringan/Odoo.

`fetch_sale_orders(since=None, state='sale')` (header ``sale.order``) dan
`fetch_sale_order_lines(order_ids, since=None)` (``sale.order.line``):
happy path (model + domain + field list), varian ``since``/``state``, dan
fail-safe ``client None`` → ``[]``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from django.test import SimpleTestCase

from integrations.erp_sync.transport import OdooTransport

ROWS = [{"id": 1}]
SINCE = "2026-10-06 00:00:00"

#: Ditulis manual (bukan impor dari modul) supaya perubahan field tertangkap test.
SALE_ORDER_FIELDS = [
    "id",
    "name",
    "partner_id",
    "date_order",
    "client_order_ref",
    "state",
    "amount_total",
    "currency_id",
    "order_line",
]
SALE_ORDER_LINE_FIELDS = [
    "id",
    "order_id",
    "product_id",
    "product_uom_qty",
    "price_unit",
    "name",
    "product_uom",
]


class FetchSaleOrdersTests(SimpleTestCase):
    """``fetch_sale_orders`` — header SO (default state ``sale``)."""

    def _transport(self):
        client = MagicMock()
        client.execute_kw.return_value = ROWS
        return OdooTransport(client=client), client

    def test_happy_path_model_domain_fields(self):
        transport, client = self._transport()

        result = transport.fetch_sale_orders()

        client.execute_kw.assert_called_once_with(
            "sale.order", "search_read", [[("state", "=", "sale")], SALE_ORDER_FIELDS]
        )
        self.assertEqual(result, ROWS)

    def test_since_menambah_domain_write_date(self):
        transport, client = self._transport()

        transport.fetch_sale_orders(since=SINCE)

        client.execute_kw.assert_called_once_with(
            "sale.order",
            "search_read",
            [[("state", "=", "sale"), ("write_date", ">", SINCE)], SALE_ORDER_FIELDS],
        )

    def test_state_bisa_di_override(self):
        transport, client = self._transport()

        transport.fetch_sale_orders(state="done")

        client.execute_kw.assert_called_once_with(
            "sale.order", "search_read", [[("state", "=", "done")], SALE_ORDER_FIELDS]
        )

    def test_client_none_mengembalikan_list_kosong(self):
        self.assertEqual(OdooTransport(client=None).fetch_sale_orders(), [])


class FetchSaleOrderLinesTests(SimpleTestCase):
    """``fetch_sale_order_lines`` — baris SO per ``order_ids``."""

    def _transport(self):
        client = MagicMock()
        client.execute_kw.return_value = ROWS
        return OdooTransport(client=client), client

    def test_happy_path_model_domain_fields(self):
        transport, client = self._transport()

        result = transport.fetch_sale_order_lines([7, 8])

        client.execute_kw.assert_called_once_with(
            "sale.order.line",
            "search_read",
            [[("order_id", "in", [7, 8])], SALE_ORDER_LINE_FIELDS],
        )
        self.assertEqual(result, ROWS)

    def test_since_menambah_domain_write_date(self):
        transport, client = self._transport()

        transport.fetch_sale_order_lines([7], since=SINCE)

        client.execute_kw.assert_called_once_with(
            "sale.order.line",
            "search_read",
            [
                [("order_id", "in", [7]), ("write_date", ">", SINCE)],
                SALE_ORDER_LINE_FIELDS,
            ],
        )

    def test_client_none_mengembalikan_list_kosong(self):
        self.assertEqual(OdooTransport(client=None).fetch_sale_order_lines([7]), [])
