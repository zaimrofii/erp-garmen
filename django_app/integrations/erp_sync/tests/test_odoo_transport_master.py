"""Test `OdooTransport` master data — client di-mock, tanpa jaringan/Odoo nyata.

Isi:

* 1 happy path **per method** (10) — memastikan model + **field list minimal**
  yang dikirim ke ``execute_kw`` persis daftar yang dikunci;
* 1 test ``client None`` → ``[]`` **per method** (10) — fail-safe, tidak raise;
* 1 test tambahan: ``since`` menambah domain ``write_date``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from django.test import SimpleTestCase

from integrations.erp_sync.transport import OdooTransport

ROWS = [{"id": 1}]

#: method -> (model, field minimal). Ditulis manual (bukan impor dari modul)
#: supaya perubahan field di modul benar-benar tertangkap test.
EXPECTED = {
    "fetch_products": (
        "product.product",
        [
            "id",
            "default_code",
            "name",
            "uom_id",
            "categ_id",
            "active",
            "product_tmpl_id",
            # H3.5 — harga ikut ditarik (list_price → sale_price, standard_price → cost_price).
            "list_price",
            "standard_price",
        ],
    ),
    "fetch_boms": (
        "mrp.bom",
        ["id", "code", "product_tmpl_id", "product_qty", "product_uom_id", "type", "active"],
    ),
    "fetch_bom_lines": (
        "mrp.bom.line",
        ["id", "bom_id", "product_id", "product_qty", "product_uom_id", "sequence", "active"],
    ),
    "fetch_partners": (
        "res.partner",
        [
            "id",
            "name",
            "vat",
            "email",
            "is_company",
            "customer_rank",
            "supplier_rank",
            "phone",
            "street",
            "street2",
            "city",
            "active",
        ],
    ),
    "fetch_locations": (
        "stock.location",
        ["id", "name", "complete_name", "usage", "location_id", "warehouse_id", "active"],
    ),
    "fetch_taxes": (
        "account.tax",
        # H3.6 — tarif & jenis ikut ditarik (amount/amount_type/type_tax_use/price_include).
        ["id", "name", "amount", "amount_type", "type_tax_use", "price_include"],
    ),
    "fetch_uoms": ("uom.uom", ["id", "name", "category_id", "factor"]),
    "fetch_warehouses": ("stock.warehouse", ["id", "name", "code"]),
    "fetch_journals": ("account.journal", ["id", "name", "code", "type"]),
    "fetch_currencies": ("res.currency", ["id", "name", "symbol", "rate"]),
}

SINCE = "2026-10-05 00:00:00"


class OdooTransportMasterHappyPathTests(SimpleTestCase):
    """Happy path (mock client): model + field list sesuai daftar minimal."""

    def _assert_fetch(self, method):
        model, fields = EXPECTED[method]
        client = MagicMock()
        client.execute_kw.return_value = ROWS
        transport = OdooTransport(client=client)

        result = getattr(transport, method)()

        client.execute_kw.assert_called_once_with(model, "search_read", [[], fields])
        self.assertEqual(result, ROWS)

    def test_fetch_products(self):
        self._assert_fetch("fetch_products")

    def test_fetch_boms(self):
        self._assert_fetch("fetch_boms")

    def test_fetch_bom_lines(self):
        self._assert_fetch("fetch_bom_lines")

    def test_fetch_partners(self):
        self._assert_fetch("fetch_partners")

    def test_fetch_locations(self):
        self._assert_fetch("fetch_locations")

    def test_fetch_taxes(self):
        self._assert_fetch("fetch_taxes")

    def test_fetch_uoms(self):
        self._assert_fetch("fetch_uoms")

    def test_fetch_warehouses(self):
        self._assert_fetch("fetch_warehouses")

    def test_fetch_journals(self):
        self._assert_fetch("fetch_journals")

    def test_fetch_currencies(self):
        self._assert_fetch("fetch_currencies")


class OdooTransportMasterSinceTests(SimpleTestCase):
    """``since`` (string) menambah domain ``write_date >``."""

    def test_since_menambah_domain_write_date(self):
        client = MagicMock()
        client.execute_kw.return_value = ROWS
        transport = OdooTransport(client=client)

        transport.fetch_products(since=SINCE)

        model, fields = EXPECTED["fetch_products"]
        client.execute_kw.assert_called_once_with(
            model, "search_read", [[("write_date", ">", SINCE)], fields]
        )

    def test_since_kosong_berarti_domain_kosong(self):
        client = MagicMock()
        client.execute_kw.return_value = ROWS
        transport = OdooTransport(client=client)

        transport.fetch_products()

        model, fields = EXPECTED["fetch_products"]
        client.execute_kw.assert_called_once_with(model, "search_read", [[], fields])


class OdooTransportMasterClientNoneTests(SimpleTestCase):
    """Fail-safe: ``client None`` → ``[]`` (tanpa raise) untuk tiap method."""

    def _assert_client_none(self, method):
        transport = OdooTransport(client=None)

        self.assertEqual(getattr(transport, method)(), [])

    def test_client_none_fetch_products(self):
        self._assert_client_none("fetch_products")

    def test_client_none_fetch_boms(self):
        self._assert_client_none("fetch_boms")

    def test_client_none_fetch_bom_lines(self):
        self._assert_client_none("fetch_bom_lines")

    def test_client_none_fetch_partners(self):
        self._assert_client_none("fetch_partners")

    def test_client_none_fetch_locations(self):
        self._assert_client_none("fetch_locations")

    def test_client_none_fetch_taxes(self):
        self._assert_client_none("fetch_taxes")

    def test_client_none_fetch_uoms(self):
        self._assert_client_none("fetch_uoms")

    def test_client_none_fetch_warehouses(self):
        self._assert_client_none("fetch_warehouses")

    def test_client_none_fetch_journals(self):
        self._assert_client_none("fetch_journals")

    def test_client_none_fetch_currencies(self):
        self._assert_client_none("fetch_currencies")
