"""Test `ReconciliationService` (I7) — transport dipalsukan, tanpa Odoo/jaringan.

Cakupan: diff nol, toleransi unit (di bawah/atas), toleransi persen (volume
besar), filter produk demo Odoo (tanpa ``master.Product``), agregasi lokasi
induk+anak (``child_of``), FG memakai ``qty_done``, bundle ``DRAFT`` dilewati,
lokasi internal kosong (tidak menulis baris), wiring ``get_transport`` default
(dipanggil + ditutup), dan ``report(days)``.
"""

from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase

from apps_industry.garment.models import StockReconciliation
from apps_industry.garment.tests.factories import (
    make_bundle,
    make_order_line,
    make_routing,
    make_step,
    make_work_center,
    make_work_order,
)
from integrations.erp_sync.services.reconciliation import ReconciliationService
from master.models import Product

GET_TRANSPORT = "integrations.erp_sync.services.reconciliation.get_transport"


class FakeTransport:
    """Transport palsu: lokasi internal + ``stock.quant`` dari data test."""

    def __init__(self, locations=None, quants=None, error=None):
        self.locations = (
            list(locations)
            if locations is not None
            else [{"id": 8, "complete_name": "WH/Stok"}]
        )
        self.quants = list(quants or [])
        self.error = error
        self.calls = []
        self.closed = False

    def fetch_internal_locations(self):
        self.calls.append(("locations",))
        return self.locations

    def fetch_stock_quants(self, location_ids, since=None, child_of=False):
        self.calls.append(("quants", tuple(location_ids), since, child_of))
        if self.error is not None:
            raise self.error
        return self.quants

    def close(self):
        self.closed = True


class ReconciliationServiceTestCase(TestCase):
    """Produk master FG-001/502 + satu bundle di lantai (WIP qty=10)."""

    @classmethod
    def setUpTestData(cls):
        cls.product_a = Product.objects.create(code="FG-001", name="Kaos", odoo_id=501)
        cls.product_b = Product.objects.create(code="FG-002", name="Kemeja", odoo_id=502)
        # Bundle "sudah di lantai" (bukan DRAFT) → dihitung MES sebagai WIP qty=10.
        cls.bundle_a = cls.make_bundle_for(cls.product_a, qty=10)

    # ---------------------------------------------------------------- helpers
    @classmethod
    def make_bundle_for(cls, product, qty, state="CUTTING", qty_done=0, work_center=None):
        """Bundle untuk ``product`` (WorkOrder + OrderLine dibuat otomatis)."""
        work_order = make_work_order(order_line=make_order_line(product=product, qty=qty))
        return make_bundle(
            work_order=work_order,
            qty=qty,
            qty_done=qty_done,
            state=state,
            current_work_center=work_center,
        )

    @staticmethod
    def quant(product_odoo_id, qty, location_id=8):
        """Baris ``stock.quant`` seperti hasil transport (field minimal)."""
        return {
            "id": product_odoo_id * 1000 + location_id,
            "product_id": [product_odoo_id, "produk"],
            "location_id": [location_id, "lokasi"],
            "quantity": qty,
            "reserved_quantity": 0,
        }

    def compare(self, transport):
        """Jalankan ``compare`` dengan transport palsu."""
        return ReconciliationService(transport=transport).compare()

    def rows_by_odoo_id(self):
        """``{product_odoo_id: StockReconciliation}`` dari DB."""
        return {row.product_odoo_id: row for row in StockReconciliation.objects.all()}

    # ------------------------------------------------------------------ tests
    def test_happy_path_diff_nol_tanpa_alert(self):
        transport = FakeTransport(quants=[self.quant(501, 10)])

        result = self.compare(transport)

        self.assertEqual(result, {"total_products": 1, "alert_count": 0, "alerts": []})
        row = StockReconciliation.objects.get()
        self.assertEqual(row.product_id, self.product_a.pk)
        self.assertEqual(row.product_odoo_id, 501)
        self.assertEqual(row.mes_qty, 10.0)
        self.assertEqual(row.odoo_qty, 10.0)
        self.assertEqual(row.diff, 0.0)
        self.assertFalse(row.is_alert)
        self.assertIsNotNone(row.run_at)
        # Transport yang di-inject bukan milik service → tidak boleh ditutup.
        self.assertFalse(transport.closed)

    def test_selisih_di_bawah_toleransi_unit_tidak_alert(self):
        # TOL 5 unit / 1% → threshold = max(5, 0.1) = 5; diff 4 < 5 → aman.
        transport = FakeTransport(quants=[self.quant(501, 6)])

        result = self.compare(transport)

        self.assertEqual(result["alert_count"], 0)
        row = StockReconciliation.objects.get()
        self.assertEqual(row.diff, 4.0)
        self.assertFalse(row.is_alert)

    def test_selisih_melebihi_toleransi_unit_alert(self):
        # diff 6 > 5 → alert.
        transport = FakeTransport(quants=[self.quant(501, 4)])

        result = self.compare(transport)

        self.assertEqual(result["alert_count"], 1)
        self.assertEqual(
            result["alerts"],
            [
                {
                    "product_odoo_id": 501,
                    "product_code": "FG-001",
                    "mes_qty": 10.0,
                    "odoo_qty": 4.0,
                    "diff": 6.0,
                }
            ],
        )
        row = StockReconciliation.objects.get()
        self.assertTrue(row.is_alert)
        self.assertEqual(row.notes, "toleransi=5")

    def test_selisih_melebihi_toleransi_persen_alert(self):
        # MES 1000 → threshold = max(5, 1% × 1000 = 10); diff 15 > 10 → alert.
        self.make_bundle_for(self.product_b, qty=1000)
        transport = FakeTransport(quants=[self.quant(501, 10), self.quant(502, 985)])

        result = self.compare(transport)

        self.assertEqual(result["total_products"], 2)
        self.assertEqual(result["alert_count"], 1)
        self.assertEqual(result["alerts"][0]["product_odoo_id"], 502)
        self.assertEqual(result["alerts"][0]["diff"], 15.0)
        rows = self.rows_by_odoo_id()
        self.assertFalse(rows[501].is_alert)  # 10 vs 10 → aman
        self.assertTrue(rows[502].is_alert)
        self.assertEqual(rows[502].notes, "toleransi=10")

    def test_produk_demo_odoo_diabaikan(self):
        # Odoo punya 5 produk (1 master + 4 demo Furniture) → hanya 1 dihitung.
        transport = FakeTransport(
            quants=[
                self.quant(501, 10),
                self.quant(9001, 3),
                self.quant(9002, 3),
                self.quant(9003, 3),
                self.quant(9004, 3),
            ]
        )

        result = self.compare(transport)

        self.assertEqual(result["total_products"], 1)
        self.assertEqual(result["alert_count"], 0)
        self.assertEqual([row.product_odoo_id for row in StockReconciliation.objects.all()], [501])

    def test_child_of_semua_lokasi_internal_dan_anaknya_terhitung(self):
        # Lokasi 8 (induk) + 27 (anak) + 53/54 → satu panggilan child_of=True;
        # qty lokasi 8 dan 27 dijumlahkan (bukti anak ikut terhitung).
        transport = FakeTransport(
            locations=[
                {"id": 8, "complete_name": "WH/Stok"},
                {"id": 27, "complete_name": "WH/Stok/Shelf 2"},
                {"id": 53, "complete_name": "WH/WIP"},
                {"id": 54, "complete_name": "WH/FG"},
            ],
            quants=[self.quant(501, 4, location_id=8), self.quant(501, 6, location_id=27)],
        )

        result = self.compare(transport)

        self.assertIn(("quants", (8, 27, 53, 54), None, True), transport.calls)
        self.assertEqual(result["alert_count"], 0)
        row = StockReconciliation.objects.get()
        self.assertEqual(row.odoo_qty, 10.0)  # 4 (WH/Stok) + 6 (WH/Stok/Shelf 2)
        self.assertEqual(row.diff, 0.0)

    def test_bundle_di_wc_terminal_memakai_qty_done(self):
        # Bundle di WC step terminal → FG → qty MES = qty_done (bukan bundle.qty).
        routing = make_routing()
        terminal_wc = make_work_center(code="PACKING")
        make_step(routing, "PACK", 10, work_center=terminal_wc, is_terminal=True)
        product_fg = Product.objects.create(code="FG-003", name="Jaket", odoo_id=503)
        self.make_bundle_for(
            product_fg, qty=10, qty_done=7, state="QC", work_center=terminal_wc
        )
        transport = FakeTransport(quants=[self.quant(501, 10), self.quant(503, 7)])

        result = self.compare(transport)

        self.assertEqual(result["alert_count"], 0)
        rows = self.rows_by_odoo_id()
        self.assertEqual(rows[503].mes_qty, 7.0)  # qty_done, bukan qty=10
        self.assertEqual(rows[503].diff, 0.0)

    def test_bundle_draft_dilewati(self):
        # Bundle DRAFT belum dirilis ke lantai → tidak dihitung sebagai stok MES.
        self.make_bundle_for(self.product_b, qty=99, state="DRAFT")
        transport = FakeTransport(quants=[self.quant(501, 10)])

        self.compare(transport)

        self.assertEqual([row.product_odoo_id for row in StockReconciliation.objects.all()], [501])
        self.assertFalse(
            StockReconciliation.objects.filter(product_odoo_id=502).exists()
        )

    def test_bundle_done_tanpa_produksi_tidak_dihitung_sebagai_wip(self):
        """``BUNDLE_SCRAP`` → state ``DONE`` & ``qty_done=0``: bukan stok MES (I8.7)."""
        self.make_bundle_for(self.product_b, qty=9, qty_done=0, state="DONE")
        transport = FakeTransport(quants=[self.quant(501, 10)])

        result = self.compare(transport)

        self.assertEqual(result["total_products"], 1)  # hanya produk_a
        self.assertEqual(result["alert_count"], 0)
        self.assertNotIn(502, self.rows_by_odoo_id())
        self.assertFalse(
            StockReconciliation.objects.filter(product_odoo_id=502).exists()
        )

    def test_tanpa_lokasi_internal_tidak_menulis_baris(self):
        # Anomali Odoo: tidak ada lokasi usage='internal' → tidak ada baris/alert.
        transport = FakeTransport(locations=[], quants=[self.quant(501, 0)])

        result = self.compare(transport)

        self.assertEqual(result, {"total_products": 0, "alert_count": 0, "alerts": []})
        self.assertEqual(StockReconciliation.objects.count(), 0)
        self.assertEqual(transport.calls, [("locations",)])  # quant tidak di-fetch

    def test_get_transport_default_dipanggil_dan_ditutup(self):
        transport = FakeTransport(quants=[self.quant(501, 10)])
        with patch(GET_TRANSPORT, return_value=transport) as get_transport:
            result = ReconciliationService().compare()

        get_transport.assert_called_once_with()
        self.assertTrue(transport.closed)  # dibangun service → wajib ditutup
        self.assertEqual(result["total_products"], 1)

    def test_report_mengembalikan_riwayat(self):
        transport = FakeTransport(quants=[self.quant(501, 4)])
        service = ReconciliationService(transport=transport)

        service.compare()
        report = service.report(days=7)

        self.assertEqual(len(report), 1)
        self.assertEqual(report[0]["product_code"], "FG-001")
        self.assertEqual(report[0]["product_odoo_id"], 501)
        self.assertEqual(report[0]["mes_qty"], 10.0)
        self.assertEqual(report[0]["odoo_qty"], 4.0)
        self.assertEqual(report[0]["diff"], 6.0)
        self.assertTrue(report[0]["is_alert"])
        self.assertEqual(report[0]["notes"], "toleransi=5")
        self.assertIsNotNone(report[0]["run_at"])
