"""Test laporan stok (H4.3) — ``GET /api/v1/reports/stock/``.

Snapshot stok dari **Odoo ``stock.quant`` LIVE** lewat jalur **I7**
(``fetch_internal_locations`` + ``fetch_stock_quants(child_of=True)``); transport
**di-mock** (tanpa jaringan/Odoo). MES **tidak** menyimpan tabel stok
(CHANGES-DETAIL §4) — uji juga fail-safe ``OdooTransport(client=None)`` dan
transport error (HTTP 200 + warning, bukan 500).

Cakupan: default (group_by=product), group_by=location, filter location/product/
search, only_nonzero, 400 param & entitas tak valid, cache 300 dtk (1 RPC per
filter), fail-safe, dan **non-breaking** I7/B30/H4.1/H4.2.

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_reports_stock.py -q
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import TestCase
from django.urls import resolve
from rest_framework.test import APIClient

from core.auth.models import User
from integrations.erp_sync.transport import OdooTransport
from master.models import Location, Product, UoM

STOCK_URL = "/api/v1/reports/stock/"
SALES_URL = "/api/v1/reports/sales/"
PURCHASES_URL = "/api/v1/reports/purchases/"
INVENTORY_REPORTING_URL = "/api/v1/inventory/reporting/"

TOP_KEYS = {
    "rows",
    "summary",
    "group_by",
    "filters",
    "generated_at",
    "cached",
    "source",
}
SUMMARY_KEYS = {
    "total_qty",
    "reserved_qty",
    "available_qty",
    "product_count",
    "location_count",
    "quant_count",
    "unmapped_product_count",
    "unmapped_qty",
}
ROW_KEYS_PRODUCT = {
    "key",
    "label",
    "unit",
    "product_id",
    "product_code",
    "product_name",
    "uom_code",
    "total_qty",
    "reserved_qty",
    "available_qty",
    "locations_count",
}
ROW_KEYS_LOCATION = {
    "key",
    "label",
    "unit",
    "location_id",
    "location_code",
    "location_name",
    "location_odoo_id",
    "total_qty",
    "reserved_qty",
    "available_qty",
    "products_count",
}

LOCATIONS = [
    {"id": 8, "complete_name": "WH/Stok"},
    {"id": 27, "complete_name": "WH/FG"},
]

#: KAIN (40) + BENANG (0.3) @ dua lokasi; DEMO = produk Odoo TANPA master MES;
#: KEMEJA qty 0 (uji ``only_nonzero``).
QUANTS = [
    {"id": 1, "product_id": [101, "KAIN"], "location_id": [8, "WH/Stok"], "quantity": 30.0, "reserved_quantity": 5.0},
    {"id": 2, "product_id": [101, "KAIN"], "location_id": [27, "WH/FG"], "quantity": 10.0, "reserved_quantity": 0.0},
    {"id": 3, "product_id": [102, "BENANG"], "location_id": [8, "WH/Stok"], "quantity": 0.3, "reserved_quantity": 0.1},
    {"id": 4, "product_id": [999, "DEMO"], "location_id": [8, "WH/Stok"], "quantity": 7.0, "reserved_quantity": 0.0},
    {"id": 5, "product_id": [103, "KEMEJA"], "location_id": [8, "WH/Stok"], "quantity": 0.0, "reserved_quantity": 0.0},
]


def _mock_transport(quants=None, locations=None):
    """Transport mock; ``fetch_stock_quants`` memfilter seperti Odoo (per ``ids``)."""
    rows = QUANTS if quants is None else quants
    transport = MagicMock()
    transport.fetch_internal_locations.return_value = (
        LOCATIONS if locations is None else locations
    )
    transport.fetch_stock_quants.side_effect = (
        lambda ids, since=None, child_of=False: [
            row for row in rows if row["location_id"][0] in set(ids)
        ]
    )
    return transport


def _patch_transport(transport):
    return patch(
        "integrations.erp_sync.monitoring.get_transport", return_value=transport
    )


class StockReportBase(TestCase):
    """Fixture: user + master (UoM, 3 produk sinkron, 2 lokasi internal) + cache."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="rep-stock", password="x")
        cls.uom = UoM.objects.create(code="PCS", name="Pcs", category="Unit")
        cls.kain = Product.objects.create(code="KAIN", name="Kain", odoo_id=101, uom=cls.uom)
        cls.benang = Product.objects.create(code="BENANG", name="Benang", odoo_id=102, uom=cls.uom)
        cls.kemeja = Product.objects.create(code="KEMEJA", name="Kemeja", odoo_id=103, uom=cls.uom)
        cls.stok = Location.objects.create(
            code="WH/STOK", name="Stok Utama", usage=Location.Usage.INTERNAL, odoo_id=8
        )
        cls.fg = Location.objects.create(
            code="WH/FG", name="Barang Jadi", usage=Location.Usage.INTERNAL, odoo_id=27
        )

    def setUp(self):
        cache.clear()
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def get(self, query: str = "", transport=None):
        """GET laporan stok dengan transport di-mock (default QUANTS)."""
        url = f"{STOCK_URL}?{query}" if query else STOCK_URL
        with _patch_transport(transport or _mock_transport()):
            return self.api.get(url)

class StockReportAuthTests(TestCase):
    """Izin endpoint: anonim 403 (IsAuthenticated)."""

    def test_anonim_403(self):
        self.assertEqual(APIClient().get(STOCK_URL).status_code, 403)


class StockReportDefaultTests(StockReportBase):
    """Default: snapshot per produk (group_by=product) + summary + unmapped."""

    def test_default_product_snapshot(self):
        response = self.get()
        body = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(body.keys()), TOP_KEYS)
        self.assertEqual(set(body["summary"].keys()), SUMMARY_KEYS)
        self.assertEqual(body["group_by"], "product")
        self.assertEqual(body["source"], "odoo")
        self.assertFalse(body["cached"])
        self.assertIsNone(body["filters"]["location_id"])
        self.assertIsNone(body["filters"]["product_id"])
        self.assertIsNone(body["filters"]["search"])
        self.assertFalse(body["filters"]["only_nonzero"])

        rows = body["rows"]
        self.assertEqual([row["product_code"] for row in rows], ["KAIN", "BENANG", "KEMEJA"])
        self.assertEqual(set(rows[0].keys()), ROW_KEYS_PRODUCT)
        self.assertEqual(rows[0]["key"], "KAIN")
        self.assertEqual(rows[0]["label"], "Kain")
        self.assertEqual(rows[0]["unit"], "unit")
        self.assertEqual(rows[0]["uom_code"], "PCS")
        self.assertEqual(rows[0]["product_id"], self.kain.pk)
        self.assertEqual(rows[0]["total_qty"], 40.0)
        self.assertEqual(rows[0]["reserved_qty"], 5.0)
        self.assertEqual(rows[0]["available_qty"], 35.0)
        self.assertEqual(rows[0]["locations_count"], 2)
        # Qty pecahan (benang 0.3) tetap float 2 desimal.
        self.assertEqual(rows[1]["total_qty"], 0.3)
        self.assertEqual(rows[1]["available_qty"], 0.2)

        summary = body["summary"]
        self.assertEqual(summary["total_qty"], 40.3)
        self.assertEqual(summary["reserved_qty"], 5.1)
        self.assertEqual(summary["available_qty"], 35.2)
        self.assertEqual(summary["product_count"], 3)
        self.assertEqual(summary["location_count"], 2)
        self.assertEqual(summary["quant_count"], 4)
        # Produk Odoo tanpa master MES tetap terlihat (transparansi).
        self.assertEqual(summary["unmapped_product_count"], 1)
        self.assertEqual(summary["unmapped_qty"], 7.0)

    def test_group_by_location(self):
        body = self.get("group_by=location").json()
        rows = body["rows"]

        self.assertEqual(body["group_by"], "location")
        self.assertEqual(set(rows[0].keys()), ROW_KEYS_LOCATION)
        self.assertEqual([row["key"] for row in rows], ["WH/STOK", "WH/FG"])
        self.assertEqual(rows[0]["location_id"], self.stok.pk)
        self.assertEqual(rows[0]["location_code"], "WH/STOK")
        self.assertEqual(rows[0]["location_name"], "Stok Utama")
        self.assertEqual(rows[0]["location_odoo_id"], 8)
        self.assertEqual(rows[0]["total_qty"], 30.3)
        self.assertEqual(rows[0]["reserved_qty"], 5.1)
        self.assertEqual(rows[0]["available_qty"], 25.2)
        self.assertEqual(rows[0]["products_count"], 3)
        self.assertEqual(rows[1]["products_count"], 1)

    def test_hasil_kosong_tetap_valid(self):
        body = self.get("", transport=_mock_transport(quants=[])).json()

        self.assertEqual(body["rows"], [])
        self.assertEqual(body["summary"]["total_qty"], 0)
        self.assertEqual(body["summary"]["product_count"], 0)
        self.assertEqual(body["summary"]["quant_count"], 0)
        self.assertFalse(body["cached"])


class StockReportFilterTests(StockReportBase):
    """Filter MES pk (location/product), search, only_nonzero, 400."""

    def test_filter_location_id(self):
        transport = _mock_transport()
        body = self.get(f"location_id={self.stok.pk}", transport=transport).json()

        # Map MES pk -> odoo_id + `child_of=True` (pola I7).
        self.assertEqual(transport.fetch_stock_quants.call_args.args[0], [8])
        self.assertTrue(transport.fetch_stock_quants.call_args.kwargs["child_of"])
        self.assertEqual(body["filters"]["location_id"], self.stok.pk)
        self.assertEqual(body["summary"]["location_count"], 1)
        self.assertEqual(body["summary"]["total_qty"], 30.3)

    def test_filter_product_id(self):
        body = self.get(f"product_id={self.kain.pk}").json()

        self.assertEqual(body["filters"]["product_id"], self.kain.pk)
        self.assertEqual([row["product_code"] for row in body["rows"]], ["KAIN"])
        self.assertEqual(body["summary"]["total_qty"], 40.0)
        self.assertEqual(body["summary"]["quant_count"], 2)
        self.assertEqual(body["summary"]["product_count"], 1)

    def test_filter_search_case_insensitive(self):
        body = self.get("search=BEN").json()

        self.assertEqual(body["filters"]["search"], "BEN")
        self.assertEqual([row["product_code"] for row in body["rows"]], ["BENANG"])
        self.assertEqual(body["summary"]["total_qty"], 0.3)

    def test_only_nonzero(self):
        body = self.get("only_nonzero=1").json()

        self.assertTrue(body["filters"]["only_nonzero"])
        self.assertEqual([row["product_code"] for row in body["rows"]], ["KAIN", "BENANG"])
        self.assertEqual(body["summary"]["product_count"], 2)

    def test_param_tidak_valid_400(self):
        for query, key in (
            ("group_by=nope", "group_by"),
            ("location_id=abc", "location_id"),
            ("product_id=0", "product_id"),
        ):
            with self.subTest(query=query):
                response = self.get(query)
                self.assertEqual(response.status_code, 400)
                self.assertIn(key, response.json()["detail"])

    def test_location_tidak_valid_400(self):
        view = Location.objects.create(
            code="VIEW-1", name="View", usage=Location.Usage.VIEW, odoo_id=777
        )
        belum = Location.objects.create(
            code="NOSYNC-1", name="Belum Sinkron", usage=Location.Usage.INTERNAL
        )

        tidak_ada = self.get("location_id=999999")
        self.assertEqual(tidak_ada.status_code, 400)
        self.assertIn("tidak ditemukan", tidak_ada.json()["detail"])

        non_internal = self.get(f"location_id={view.pk}")
        self.assertEqual(non_internal.status_code, 400)
        self.assertIn("usage", non_internal.json()["detail"])

        tanpa_odoo = self.get(f"location_id={belum.pk}")
        self.assertEqual(tanpa_odoo.status_code, 400)
        self.assertIn("odoo_id", tanpa_odoo.json()["detail"])

    def test_product_filter_tidak_valid_400(self):
        belum = Product.objects.create(code="NOODOO-1", name="Belum Sinkron")

        tidak_ada = self.get("product_id=999999")
        self.assertEqual(tidak_ada.status_code, 400)
        self.assertIn("tidak ditemukan", tidak_ada.json()["detail"])

        tanpa_odoo = self.get(f"product_id={belum.pk}")
        self.assertEqual(tanpa_odoo.status_code, 400)
        self.assertIn("odoo_id", tanpa_odoo.json()["detail"])

    def test_summary_tanpa_currency(self):
        summary = self.get().json()["summary"]

        # H4.3 murni quantity (fisik) - nilai Rp / COGS = H4.4.
        self.assertNotIn("currency", summary)

    def test_group_by_location_dengan_filter_produk(self):
        body = self.get(f"group_by=location&product_id={self.kain.pk}").json()
        rows = body["rows"]

        self.assertEqual([row["key"] for row in rows], ["WH/STOK", "WH/FG"])
        self.assertEqual(rows[0]["total_qty"], 30.0)
        self.assertEqual(rows[0]["products_count"], 1)
        self.assertEqual(rows[1]["total_qty"], 10.0)
        self.assertEqual(body["summary"]["product_count"], 1)
        self.assertEqual(body["summary"]["location_count"], 2)


class StockReportCacheTests(StockReportBase):
    """Cache 300 dtk: 1 RPC per filter + ``?_nocache=1`` (tidak baca & tidak tulis)."""

    def test_cache_hit_satu_rpc_dan_key_per_filter(self):
        transport = _mock_transport()

        pertama = self.get(transport=transport).json()
        self.assertFalse(pertama["cached"])
        self.assertEqual(transport.fetch_stock_quants.call_count, 1)
        self.assertEqual(transport.fetch_internal_locations.call_count, 1)

        kedua = self.get(transport=transport).json()
        self.assertTrue(kedua["cached"])
        # Cache hit -> TIDAK ada RPC tambahan sama sekali (jangan flood Odoo).
        self.assertEqual(transport.fetch_stock_quants.call_count, 1)
        self.assertEqual(transport.fetch_internal_locations.call_count, 1)
        self.assertEqual(kedua["rows"], pertama["rows"])
        self.assertEqual(kedua["generated_at"], pertama["generated_at"])

        bypass = self.get("_nocache=1", transport=transport).json()
        self.assertFalse(bypass["cached"])
        self.assertEqual(transport.fetch_stock_quants.call_count, 2)
        # `_nocache=1` tidak menulis cache -> GET biasa tetap dari entri lama.
        self.assertTrue(self.get(transport=transport).json()["cached"])
        self.assertEqual(transport.fetch_stock_quants.call_count, 2)

        # Key cache memuat filter efektif -> filter berbeda = entri berbeda.
        self.assertFalse(self.get("group_by=location", transport=transport).json()["cached"])
        self.assertTrue(self.get("group_by=location", transport=transport).json()["cached"])


class StockReportFailSafeTests(StockReportBase):
    """Fail-safe: tanpa client Odoo / Odoo error / tanpa lokasi internal -> 200 kosong."""

    def test_erp_adapter_tanpa_client_kosong(self):
        with _patch_transport(OdooTransport(client=None)):
            response = self.api.get(STOCK_URL)

        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["rows"], [])
        self.assertEqual(set(body["summary"].keys()), SUMMARY_KEYS)
        self.assertEqual(body["summary"]["total_qty"], 0)
        self.assertEqual(body["summary"]["quant_count"], 0)
        self.assertEqual(body["summary"]["unmapped_qty"], 0)
        self.assertFalse(body["cached"])
        self.assertEqual(body["source"], "odoo")

    def test_transport_error_200_kosong_dan_warning(self):
        transport = _mock_transport()
        transport.fetch_stock_quants.side_effect = RuntimeError("odoo down")

        with self.assertLogs("integrations.erp_sync.monitoring", level="WARNING"):
            response = self.get("", transport=transport)

        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["rows"], [])
        self.assertEqual(body["summary"]["total_qty"], 0)

    def test_tanpa_lokasi_internal_tidak_panggil_quants(self):
        transport = _mock_transport(locations=[])

        body = self.get(transport=transport).json()

        self.assertEqual(body["rows"], [])
        self.assertEqual(body["summary"]["quant_count"], 0)
        # Fail-fast I7: tanpa lokasi internal, `fetch_stock_quants` TIDAK dipanggil.
        transport.fetch_stock_quants.assert_not_called()


class StockReportNonBreakingTests(StockReportBase):
    """I7 + B30 + H4.1 + H4.2 tetap hijau & route baru terdaftar."""

    def test_non_breaking(self):
        self.assertEqual(resolve(STOCK_URL).url_name, "reports_stock")
        self.assertEqual(resolve(SALES_URL).url_name, "reports_sales")
        self.assertEqual(resolve(PURCHASES_URL).url_name, "reports_purchases")
        self.assertEqual(resolve(INVENTORY_REPORTING_URL).url_name, "inventory_reporting")
        self.assertEqual(
            resolve("/api/v1/reconciliation/report/").url_name, "reconciliation_report"
        )

        penjualan = self.api.get(SALES_URL)
        self.assertEqual(penjualan.status_code, 200)
        self.assertEqual(
            set(penjualan.json().keys()),
            {"rows", "summary", "group_by", "filters", "period", "generated_at", "cached"},
        )

        pembelian = self.api.get(PURCHASES_URL)
        self.assertEqual(pembelian.status_code, 200)
        self.assertIn("summary", pembelian.json())

        inventori = self.api.get(INVENTORY_REPORTING_URL)
        self.assertEqual(inventori.status_code, 200)
        self.assertIn("rows", inventori.json())
