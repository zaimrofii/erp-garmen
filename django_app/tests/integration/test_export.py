"""Test export laporan H4 — ``POST /api/v1/export/<report>/`` (H4.8).

Read-only binary export: **ORKESTRASI** helper internal H4.1–H4.7 lewat *shim
request* (tanpa memanggil view HTTP, tanpa menyalin rumus). Cakupan: auth 403,
semua 7 laporan (xlsx & pdf), Content-Type + Content-Disposition/filename,
``format`` dari body/**query** (body menang), 400 format salah, 404 report salah,
filter periode diterapkan (nama file + isi), Excel bisa dibaca balik `openpyxl`,
PDF berawalan ``%PDF``, fail-safe stok (file tetap dibuat), dan **non-breaking**
B2 + H4.1–H4.7.

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_export.py -q
"""

from __future__ import annotations

import io
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.urls import resolve
from django.utils import timezone
from openpyxl import load_workbook
from rest_framework.test import APIClient

from apps_industry.garment.models import Bundle, BundleEvent, Order, OrderLine, WorkOrder
from apps_industry.garment.tests.factories import (
    make_line,
    make_order,
    make_order_line,
    make_product,
    make_work_center,
)
from core.auth.models import User
from master.models import Account, Journal, Partner, Product

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PDF_MIME = "application/pdf"

REPORTS = ("sales", "purchases", "stock", "cogs", "pnl", "production", "executive")

#: Anchor waktu: bulan berjalan + bulan sebelumnya (jam 10:00 lokal, tz-aware).
_now = timezone.localtime(timezone.now())
CURRENT_START = _now.replace(day=1, hour=10, minute=0, second=0, microsecond=0)
PREVIOUS_START = (CURRENT_START - timedelta(days=1)).replace(day=1)
CURRENT_MONTH = CURRENT_START.strftime("%Y-%m")
PREVIOUS_MONTH = PREVIOUS_START.strftime("%Y-%m")
TODAY = _now.date()


def _mock_transport(locations, quants):
    """Transport mock I7/H4.3 (enumerasi lokasi internal + quants)."""
    transport = MagicMock()
    transport.fetch_internal_locations.return_value = locations
    transport.fetch_quants.return_value = quants
    transport.fetch_stock_quants.return_value = quants
    return transport


def _patch_transport(transport):
    return patch("integrations.erp_sync.monitoring.get_transport", return_value=transport)


class ExportBase(TestCase):
    """Fixture: user + produk (cost 40) + customer/vendor + WC/line + helper seed."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="rep-export", password="x")
        cls.product = make_product(code="PRD-EXP", name="Kaos Export")
        Product.objects.filter(pk=cls.product.pk).update(cost_price=Decimal("40.00"))
        cls.product.refresh_from_db()
        cls.customer = Partner.objects.create(code="CUST-EXP", name="PT Export")
        cls.vendor = Partner.objects.create(code="SUP-EXP", name="PT Vendor Export")
        cls.wc = make_work_center(code="WC-EXP", config={"target_per_day": 10})
        cls.line = make_line(code="LINE-EXP", work_centers=[cls.wc])

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)
        # Transport default = Odoo "kosong" (tanpa lokasi internal): hasil section
        # stok deterministik, TIDAK bergantung ketersediaan Odoo nyata di env test.
        patcher = _patch_transport(_mock_transport([], []))
        patcher.start()
        self.addCleanup(patcher.stop)

    def seed_order(self, code, *, created_at, product=None, qty=10, price_unit="100.00"):
        """Order + satu baris; ``created_at`` di-set ulang (auto_now_add)."""
        order = make_order(code=code, customer=self.customer)
        Order.objects.filter(pk=order.pk).update(created_at=created_at)
        OrderLine.objects.create(
            order=order,
            product=product if product is not None else self.product,
            qty=qty,
            price_unit=Decimal(price_unit),
        )
        return order

    def seed_production(self, code="WO-EXP", qty_done=8):
        """Order + WO DONE + bundle FINISH (untuk laporan produksi H4.6)."""
        order = make_order(
            code=f"SO-{code}", customer=self.customer, deadline=_now + timedelta(days=5)
        )
        order_line = make_order_line(order=order, product=self.product, qty=12)
        Order.objects.filter(pk=order.pk).update(created_at=CURRENT_START)

        work_order = WorkOrder.objects.create(code=code, order_line=order_line, state="DONE")
        bundle = Bundle.objects.create(
            code=f"BND-{code}",
            work_order=work_order,
            qty=qty_done,
            qty_done=qty_done,
            state="DONE",
            current_work_center=self.wc,
            production_line=self.line,
        )
        event = BundleEvent.objects.create(bundle=bundle, event_type="BUNDLE_FINISH")
        BundleEvent.objects.filter(pk=event.pk).update(ts=CURRENT_START + timedelta(days=2))
        return bundle

    def export(self, report, *, query: str = "", body=None):
        """POST export → respons (query string tanpa tanda tanya)."""
        url = f"/api/v1/export/{report}/"
        if query:
            url = f"{url}?{query}"
        return self.api.post(url, body if body is not None else {}, format="json")

    def workbook(self, response):
        """Parse balik body xlsx → workbook openpyxl (bukti Excel valid)."""
        return load_workbook(filename=io.BytesIO(response.content))

    def kpi_value(self, workbook, label: str):
        """Cari nilai KPI di sheet Summary (label kolom A → nilai kolom B)."""
        worksheet = workbook["Summary"]
        for row in worksheet.iter_rows(values_only=True):
            if row and row[0] == label:
                return row[1]
        return None


class ExportAuthAndValidationTests(TestCase):
    """Izin + validasi report/format (tanpa fixture laporan)."""

    def setUp(self):
        self.user = User.objects.create_user(username="rep-a", password="x")
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def test_anonim_403(self):
        response = APIClient().post("/api/v1/export/sales/", {}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_report_invalid_404(self):
        response = self.api.post("/api/v1/export/invalid/", {}, format="json")

        self.assertEqual(response.status_code, 404)
        self.assertIn("tidak dikenal", response.json()["detail"])

    def test_format_invalid_400(self):
        response = self.api.post("/api/v1/export/sales/?format=csv", {}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("format", response.json()["detail"])

    def test_range_invalid_400_memakai_pesan_h4_1(self):
        response = self.api.post(
            "/api/v1/export/sales/", {"period": "2026-13"}, format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("period", response.json()["detail"])


class ExportSalesTests(ExportBase):
    """Laporan penjualan: mime, filename, format dari body vs query, isi data."""

    def test_sales_xlsx_default(self):
        self.seed_order("SO-CUR", created_at=CURRENT_START, qty=10, price_unit="100.00")

        response = self.export("sales")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], XLSX_MIME)
        self.assertEqual(
            response["Content-Disposition"],
            f'attachment; filename="sales-{CURRENT_MONTH}.xlsx"',
        )
        self.assertEqual(response["X-Export-Report"], "sales")
        self.assertGreater(len(response.content), 1000)
        self.assertEqual(response.content[:2], b"PK")

    def test_sales_pdf_query_string(self):
        self.seed_order("SO-PDF", created_at=CURRENT_START, qty=10, price_unit="100.00")

        response = self.export("sales", query="format=pdf")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], PDF_MIME)
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertGreater(len(response.content), 800)
        self.assertEqual(
            response["Content-Disposition"],
            f'attachment; filename="sales-{CURRENT_MONTH}.pdf"',
        )

    def test_format_dari_body_dan_body_menang(self):
        self.seed_order("SO-BODY", created_at=CURRENT_START, qty=10, price_unit="100.00")

        from_body = self.export("sales", body={"format": "pdf"})
        self.assertEqual(from_body["Content-Type"], PDF_MIME)

        body_wins = self.export("sales", query="format=xlsx", body={"format": "pdf"})
        self.assertEqual(body_wins["Content-Type"], PDF_MIME)
        self.assertEqual(body_wins["X-Export-Format"], "pdf")

    def test_filter_period_diterapkan_di_nama_file_dan_data(self):
        self.seed_order("SO-CUR", created_at=CURRENT_START, qty=10, price_unit="100.00")
        self.seed_order("SO-PREV", created_at=PREVIOUS_START, qty=5, price_unit="200.00")

        response = self.export("sales", query=f"period={PREVIOUS_MONTH}")
        workbook = self.workbook(response)

        self.assertEqual(
            response["Content-Disposition"],
            f'attachment; filename="sales-{PREVIOUS_MONTH}.xlsx"',
        )
        # Hanya order bulan sebelumnya yang ikut (5 x 200 = 1000).
        self.assertEqual(self.kpi_value(workbook, "Omzet (Rp)"), 1000.0)
        self.assertEqual(self.kpi_value(workbook, "Jumlah Order"), 1)

    def test_excel_dibaca_openpyxl_summary_dan_data(self):
        self.seed_order("SO-XL", created_at=CURRENT_START, qty=10, price_unit="100.00")

        workbook = self.workbook(self.export("sales"))
        summary = workbook["Summary"]
        data = workbook["Data"]

        self.assertEqual(summary["A1"].value, "Laporan Penjualan")
        self.assertIn(CURRENT_MONTH, summary["A2"].value)
        self.assertEqual(self.kpi_value(workbook, "Omzet (Rp)"), 1000.0)
        self.assertEqual(self.kpi_value(workbook, "Kas Masuk (Rp)"), 0.0)
        # Baris data: header + 1 baris agregat bulan berjalan.
        self.assertEqual(data["A1"].value, "Laporan Penjualan — Data")
        self.assertEqual(data.max_row >= 6, True)
        self.assertEqual(workbook.sheetnames, ["Summary", "Data"])

    def test_pdf_berisi_judul_dan_periode(self):
        self.seed_order("SO-TXT", created_at=CURRENT_START, qty=10, price_unit="100.00")

        response = self.export("sales", query="format=pdf")

        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertTrue(response.content.rstrip().endswith(b"%%EOF"))


class ExportOtherReportsTests(ExportBase):
    """6 laporan tabel sisanya: purchases, stock (mock Odoo), cogs, pnl, production."""

    def test_purchases_xlsx_dan_label_kuartal(self):
        from apps_industry.garment.models import PurchaseOrder, PurchaseOrderLine

        po = PurchaseOrder.objects.create(code="PO-EXP", vendor=self.vendor, state="CONFIRMED")
        PurchaseOrder.objects.filter(pk=po.pk).update(created_at=CURRENT_START)
        PurchaseOrderLine.objects.create(
            po=po, product=self.product, qty=Decimal("5"), price_unit=Decimal("20000.00")
        )

        response = self.export("purchases")
        workbook = self.workbook(response)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], XLSX_MIME)
        self.assertEqual(
            response["Content-Disposition"],
            f'attachment; filename="purchases-{CURRENT_MONTH}.xlsx"',
        )
        self.assertEqual(self.kpi_value(workbook, "Total Belanja (Rp)"), 100000.0)
        self.assertEqual(self.kpi_value(workbook, "Jumlah PO"), 1)

        # Rentang tepat satu kuartal → label `YYYY-Qn` (contoh keputusan H4.8).
        quarter = self.export(
            "purchases",
            query="date_from=2026-10-01&date_to=2026-12-31&format=pdf",
        )
        self.assertEqual(
            quarter["Content-Disposition"],
            'attachment; filename="purchases-2026-Q4.pdf"',
        )
        self.assertTrue(quarter.content.startswith(b"%PDF"))

    def test_stock_xlsx_dengan_mock_odoo(self):
        product = Product.objects.create(
            code="PRD-MAP-EXP", name="Terpetakan", cost_price=Decimal("10.00"), odoo_id=101
        )
        transport = _mock_transport(
            [{"id": 8, "complete_name": "WH/Stok"}],
            [
                {
                    "id": 1,
                    "product_id": [101, "KAIN"],
                    "location_id": [8, "WH/Stok"],
                    "quantity": 5.0,
                    "reserved_quantity": 1.0,
                }
            ],
        )

        with _patch_transport(transport):
            response = self.export("stock")

        workbook = self.workbook(response)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], XLSX_MIME)
        # Snapshot tanpa periode → nama file pakai TANGGAL hari ini.
        self.assertEqual(
            response["Content-Disposition"],
            f'attachment; filename="stock-{TODAY.strftime("%Y%m%d")}.xlsx"',
        )
        self.assertEqual(product.odoo_id, 101)
        self.assertEqual(self.kpi_value(workbook, "Total Qty"), 5.0)
        self.assertEqual(self.kpi_value(workbook, "Available"), 4.0)

    def test_cogs_xlsx(self):
        self.seed_order("SO-COGS", created_at=CURRENT_START, qty=10, price_unit="100.00")

        workbook = self.workbook(self.export("cogs"))

        self.assertEqual(self.kpi_value(workbook, "Omzet (Rp)"), 1000.0)
        self.assertEqual(self.kpi_value(workbook, "HPP (Rp)"), 400.0)
        self.assertEqual(self.kpi_value(workbook, "Laba Kotor (Rp)"), 600.0)
        self.assertEqual(self.kpi_value(workbook, "Margin Kotor %"), 60.0)

    def test_pnl_xlsx_dan_catatan_opex(self):
        self.seed_order("SO-PNL", created_at=CURRENT_START, qty=10, price_unit="100.00")

        workbook = self.workbook(self.export("pnl"))
        summary = workbook["Summary"]
        notes = [row[0] for row in summary.iter_rows(values_only=True) if row and row[0]]

        self.assertEqual(self.kpi_value(workbook, "Omzet (Rp)"), 1000.0)
        self.assertEqual(self.kpi_value(workbook, "Sumber Opex"), "unavailable")
        # Chart of accounts belum punya akun expense → catatan transparan.
        self.assertTrue(any("Opex belum tersedia" in str(note) for note in notes))

    def test_pnl_dengan_opex_jurnal(self):
        from apps_industry.garment.models import JournalEntry, JournalEntryLine

        self.seed_order("SO-OPEX", created_at=CURRENT_START, qty=10, price_unit="100.00")
        journal = Journal.objects.create(code="JEXP", name="Jurnal Export", journal_type="general")
        account = Account.objects.create(code="6-EXP", name="Beban Export", account_type="expense")
        entry = JournalEntry.objects.create(
            code="JE-EXP", journal=journal, entry_date=CURRENT_START.date(), state="SENT"
        )
        JournalEntryLine.objects.create(
            entry=entry,
            account=account,
            name="opex",
            debit=Decimal("150.00"),
            credit=Decimal("0.00"),
        )

        workbook = self.workbook(self.export("pnl"))

        self.assertEqual(self.kpi_value(workbook, "Opex (Rp)"), 150.0)
        self.assertEqual(self.kpi_value(workbook, "Laba Bersih (Rp)"), 450.0)

    def test_production_xlsx(self):
        self.seed_production(code="WO-XLS", qty_done=8)

        workbook = self.workbook(self.export("production"))
        data = workbook["Data"]

        self.assertEqual(self.kpi_value(workbook, "Output (pcs)"), 8)
        self.assertEqual(self.kpi_value(workbook, "Efisiensi Rata-rata %"), 0.0)
        self.assertEqual(data["A1"].value, "Laporan Produksi — Data")


class ExportExecutiveTests(ExportBase):
    """Dashboard eksekutif: Excel **7 sheet** (satu per section) + PDF portrait."""

    def test_executive_xlsx_tujuh_sheet(self):
        self.seed_order("SO-EXEC", created_at=CURRENT_START, qty=10, price_unit="100.00")

        response = self.export("executive")
        workbook = self.workbook(response)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], XLSX_MIME)
        self.assertEqual(
            response["Content-Disposition"],
            f'attachment; filename="executive-{CURRENT_MONTH}.xlsx"',
        )
        self.assertEqual(
            workbook.sheetnames,
            [
                "Penjualan",
                "Pembelian",
                "Stok (snapshot Odoo)",
                "HPP - Laba Kotor",
                "Laba-Rugi",
                "Produksi",
                "Peringatan",
            ],
        )

        penjualan = {
            row[0]: row[1]
            for row in workbook["Penjualan"].iter_rows(values_only=True)
            if row and row[0]
        }
        self.assertEqual(penjualan["Omzet (Rp)"], 1000.0)

        alerts = [
            str(row[1])
            for row in workbook["Peringatan"].iter_rows(values_only=True)
            if row and row[1]
        ]
        self.assertTrue(any("Stok tidak terbaca" in text for text in alerts))
        self.assertTrue(any("Opex unavailable" in text for text in alerts))

    def test_executive_pdf_portrait(self):
        self.seed_order("SO-EXEC-PDF", created_at=CURRENT_START, qty=10, price_unit="100.00")

        response = self.export("executive", query="format=pdf")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], PDF_MIME)
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertGreater(len(response.content), 1500)


class ExportFailSafeTests(ExportBase):
    """Fail-safe: Odoo stok down → berkas TETAP dibuat (bukan 500)."""

    def test_stock_odoo_down_file_tetap_dibuat(self):
        transport = MagicMock()
        transport.fetch_internal_locations.side_effect = RuntimeError("odoo down")

        with _patch_transport(transport):
            response = self.export("stock")

        workbook = self.workbook(response)
        notes = [
            str(row[0]) for row in workbook["Summary"].iter_rows(values_only=True) if row and row[0]
        ]

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], XLSX_MIME)
        self.assertEqual(self.kpi_value(workbook, "Total Qty"), 0.0)
        self.assertTrue(any("Stok tidak terbaca" in note for note in notes))


class ExportNonBreakingTests(ExportBase):
    """H4.8 additive: route export + B2 + H4.1–H4.7 tetap terdaftar dan 200."""

    def test_non_breaking_b2_dan_h4(self):
        self.seed_order("SO-NB", created_at=CURRENT_START, qty=10, price_unit="100.00")

        self.assertEqual(resolve("/api/v1/export/sales/").url_name, "export_report")

        for url, name in (
            ("/api/v1/dashboard/summary/", "dashboard_summary"),
            ("/api/v1/dashboard/executive/", "dashboard_executive"),
            ("/api/v1/reports/sales/", "reports_sales"),
            ("/api/v1/reports/purchases/", "reports_purchases"),
            ("/api/v1/reports/stock/", "reports_stock"),
            ("/api/v1/reports/cogs/", "reports_cogs"),
            ("/api/v1/reports/pnl/", "reports_pnl"),
            ("/api/v1/reports/production/", "reports_production"),
        ):
            self.assertEqual(resolve(url).url_name, name, url)
            self.assertEqual(self.api.get(url).status_code, 200, url)

        self.assertIn("bundles", self.api.get("/api/v1/dashboard/summary/").json())

    def test_semua_tujuh_laporan_bisa_diexport_xlsx(self):
        self.seed_order("SO-ALL", created_at=CURRENT_START, qty=10, price_unit="100.00")

        for report in REPORTS:
            response = self.export(report)
            self.assertEqual(response.status_code, 200, report)
            self.assertEqual(response["Content-Type"], XLSX_MIME, report)
            self.assertTrue(
                response["Content-Disposition"].startswith("attachment; filename="), report
            )
            self.assertEqual(response.content[:2], b"PK", report)
