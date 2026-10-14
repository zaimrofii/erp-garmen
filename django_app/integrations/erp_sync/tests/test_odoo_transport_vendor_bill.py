"""Test `OdooTransport` vendor bill (I6) — mock client, tanpa jaringan/Odoo.

`fetch_vendor_bills(since=None, states=("draft","posted"))` membaca
``account.move`` dengan ``move_type`` in (``in_invoice``, ``in_refund``): happy
path (model + domain + field list), varian ``since``, override ``states``,
default states, dan fail-safe ``client None`` → ``[]``.

Catatan state (``fields_get`` live 2026-10-06): ``draft`` / ``posted`` /
``cancel`` — **tidak ada** ``paid`` (status bayar = ``payment_state``).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from django.test import SimpleTestCase

from integrations.erp_sync.transport import OdooTransport
from integrations.erp_sync.transport.odoo_transport import (
    VENDOR_BILL_FIELDS as TRANSPORT_VENDOR_BILL_FIELDS,
)

ROWS = [{"id": 1}]
SINCE = "2026-10-06 00:00:00"

#: Ditulis manual (bukan impor dari modul) supaya perubahan field tertangkap test.
VENDOR_BILL_FIELDS = [
    "id",
    "name",
    "partner_id",
    "invoice_date",
    "date",
    "state",
    "payment_state",
    "amount_total",
    "currency_id",
    "invoice_origin",
    "ref",
]

MOVE_TYPES = ["in_invoice", "in_refund"]
DEFAULT_STATES = ["draft", "posted"]


class FetchVendorBillsTests(SimpleTestCase):
    """``fetch_vendor_bills`` — vendor bill (default state ``draft``+``posted``)."""

    def _transport(self):
        client = MagicMock()
        client.execute_kw.return_value = ROWS
        return OdooTransport(client=client), client

    def test_happy_path_model_domain_fields(self):
        transport, client = self._transport()

        result = transport.fetch_vendor_bills()

        client.execute_kw.assert_called_once_with(
            "account.move",
            "search_read",
            [
                [
                    ("move_type", "in", MOVE_TYPES),
                    ("state", "in", DEFAULT_STATES),
                ],
                VENDOR_BILL_FIELDS,
            ],
        )
        self.assertEqual(result, ROWS)

    def test_since_menambah_domain_write_date(self):
        transport, client = self._transport()

        transport.fetch_vendor_bills(since=SINCE)

        client.execute_kw.assert_called_once_with(
            "account.move",
            "search_read",
            [
                [
                    ("move_type", "in", MOVE_TYPES),
                    ("state", "in", DEFAULT_STATES),
                    ("write_date", ">", SINCE),
                ],
                VENDOR_BILL_FIELDS,
            ],
        )

    def test_states_bisa_di_override(self):
        transport, client = self._transport()

        transport.fetch_vendor_bills(states=("posted",))

        client.execute_kw.assert_called_once_with(
            "account.move",
            "search_read",
            [
                [("move_type", "in", MOVE_TYPES), ("state", "in", ["posted"])],
                VENDOR_BILL_FIELDS,
            ],
        )

    def test_default_states_draft_posted_tanpa_paid(self):
        # `paid` BUKAN nilai valid `account.move.state` di Odoo 17 (status bayar
        # ada di `payment_state`) → default hanya draft+posted, tanpa `cancel`.
        transport, client = self._transport()

        transport.fetch_vendor_bills()

        domain = client.execute_kw.call_args.args[2][0]
        filters = {field: value for field, _op, value in domain}

        self.assertEqual(filters["state"], DEFAULT_STATES)
        self.assertNotIn("paid", filters["state"])
        self.assertNotIn("cancel", filters["state"])
        self.assertEqual(filters["move_type"], MOVE_TYPES)

    def test_payment_state_ada_di_field_list(self):
        # `payment_state` dipakai service I6.2 untuk menentukan status PAID
        # (bukan kirim ke Odoo) — sekaligus guard agar daftar manual di test ini
        # tidak menyimpang dari konstanta transport.
        self.assertIn("payment_state", TRANSPORT_VENDOR_BILL_FIELDS)
        self.assertEqual(TRANSPORT_VENDOR_BILL_FIELDS, VENDOR_BILL_FIELDS)

    def test_client_none_mengembalikan_list_kosong(self):
        self.assertEqual(OdooTransport(client=None).fetch_vendor_bills(), [])
