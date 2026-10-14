"""Test `OdooTransport` stock quant (I7) — mock client, tanpa jaringan/Odoo.

`fetch_stock_quants(location_ids, since=None)` membaca ``stock.quant`` per lokasi
(untuk rekonsiliasi stok MES vs Odoo): happy path (model + domain + field list),
varian ``since``, fail-fast ``location_ids`` kosong (tanpa RPC), dan fail-safe
``client None`` → ``[]``.

Field diverifikasi live ``fields_get`` 2026-10-06 (instance punya 132 stock.quant).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from django.test import SimpleTestCase

from integrations.erp_sync.transport import OdooTransport

ROWS = [{"id": 1}]
SINCE = "2026-10-06 00:00:00"
#: WH/WIP & WH/FG (dari .env: ODOO_LOCATION_WIP_ID / ODOO_LOCATION_FG_ID).
LOCATION_IDS = [53, 54]

#: Ditulis manual (bukan impor dari modul) supaya perubahan field tertangkap test.
STOCK_QUANT_FIELDS = [
    "id",
    "product_id",
    "location_id",
    "quantity",
    "reserved_quantity",
]


class FetchStockQuantsTests(SimpleTestCase):
    """``fetch_stock_quants`` — stok Odoo per lokasi."""

    def _transport(self):
        client = MagicMock()
        client.execute_kw.return_value = ROWS
        return OdooTransport(client=client), client

    def test_happy_path_model_domain_fields(self):
        transport, client = self._transport()

        result = transport.fetch_stock_quants(LOCATION_IDS)

        client.execute_kw.assert_called_once_with(
            "stock.quant",
            "search_read",
            [[("location_id", "in", LOCATION_IDS)], STOCK_QUANT_FIELDS],
        )
        self.assertEqual(result, ROWS)

    def test_since_menambah_domain_write_date(self):
        transport, client = self._transport()

        transport.fetch_stock_quants(LOCATION_IDS, since=SINCE)

        client.execute_kw.assert_called_once_with(
            "stock.quant",
            "search_read",
            [
                [
                    ("location_id", "in", LOCATION_IDS),
                    ("write_date", ">", SINCE),
                ],
                STOCK_QUANT_FIELDS,
            ],
        )

    def test_location_ids_kosong_tidak_memanggil_odoo(self):
        # Fail-fast: `location_id in []` selalu kosong → RPC tidak perlu.
        transport, client = self._transport()

        self.assertEqual(transport.fetch_stock_quants([]), [])
        self.assertEqual(transport.fetch_stock_quants(None), [])
        client.execute_kw.assert_not_called()

    def test_client_none_mengembalikan_list_kosong(self):
        transport = OdooTransport(client=None)

        self.assertEqual(transport.fetch_stock_quants(LOCATION_IDS), [])

    def test_child_of_membangun_union_or_per_lokasi(self):
        # `child_of` menerima satu id per tuple → OR-domain prefix Odoo
        # ('|' × (n-1) di depan), supaya lokasi anak (mis. 27 di bawah 8) ikut.
        transport, client = self._transport()

        transport.fetch_stock_quants([8, 27], child_of=True)

        client.execute_kw.assert_called_once_with(
            "stock.quant",
            "search_read",
            [
                [
                    "|",
                    ("location_id", "child_of", 8),
                    ("location_id", "child_of", 27),
                ],
                STOCK_QUANT_FIELDS,
            ],
        )

    def test_child_of_satu_lokasi_tanpa_operator_or(self):
        transport, client = self._transport()

        transport.fetch_stock_quants([8], child_of=True)

        client.execute_kw.assert_called_once_with(
            "stock.quant",
            "search_read",
            [[("location_id", "child_of", 8)], STOCK_QUANT_FIELDS],
        )

    def test_child_of_kosong_tetap_fail_fast(self):
        transport, client = self._transport()

        self.assertEqual(transport.fetch_stock_quants([], child_of=True), [])
        client.execute_kw.assert_not_called()

    def test_fetch_internal_locations(self):
        transport, client = self._transport()

        transport.fetch_internal_locations()

        client.execute_kw.assert_called_once_with(
            "stock.location",
            "search_read",
            [[("usage", "=", "internal")], ["id", "complete_name"]],
        )

    def test_fetch_internal_locations_client_none(self):
        transport = OdooTransport(client=None)

        self.assertEqual(transport.fetch_internal_locations(), [])
