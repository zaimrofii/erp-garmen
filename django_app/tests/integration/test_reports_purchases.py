"""Test laporan pembelian (H4.2) — ``GET /api/v1/reports/purchases/``.

Read-only DB murni: agregat `PurchaseOrderLine ⋈ PurchaseOrder` (basis
``PurchaseOrder.created_at``) + `VendorBillLine` (utang) + `Payment` OUTBOUND
SENT/DONE (kas keluar), cache 300 detik (``?nocache=1`` = bypass).
``IsAuthenticated`` → anonim **403**.

Cakupan: default bulan berjalan, prioritas ``?period`` > ``?date_from``/
``?date_to`` > ``?from``/``?to``, filter vendor/product/status,
``group_by=period|vendor|product``, nilai tak dikenal → **400**, hasil kosong
tetap valid, cache hit, dan **non-breaking** B11/H4.1.

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_reports_purchases.py -q
"""

from __future__ import annotations

from datetime import timedelta, timezone as dt_timezone
from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase
from django.urls import resolve
from django.utils import timezone
from rest_framework.test import APIClient

from apps_industry.garment.models import (
    Payment,
    PurchaseOrder,
    PurchaseOrderLine,
    VendorBill,
    VendorBillLine,
)
from apps_industry.garment.tests.factories import make_product
from core.auth.models import User
from master.models import Partner

PURCHASES_URL = "/api/v1/reports/purchases/"
SALES_URL = "/api/v1/reports/sales/"
WIP_URL = "/api/v1/reports/wip/"

TOP_KEYS = {"rows", "summary", "group_by", "filters", "period", "generated_at", "cached"}
SUMMARY_KEYS = {
    "total_qty",
    "total_amount",
    "count_purchases",
    "count_lines",
    "billed_amount",
    "bill_count",
    "paid_amount",
    "payment_count",
    "currency",
}
ROW_BASE_KEYS = {
    "key",
    "label",
    "unit",
    "value",
    "total_qty",
    "total_amount",
    "purchase_count",
    "line_count",
}

#: Anchor waktu: bulan berjalan & bulan sebelumnya (jam 10:00 lokal, tz-aware).
_now = timezone.localtime(timezone.now())
CURRENT_START = _now.replace(day=1, hour=10, minute=0, second=0, microsecond=0)
PREVIOUS_START = (CURRENT_START - timedelta(days=1)).replace(day=1)
CURRENT_MONTH = CURRENT_START.strftime("%Y-%m")
PREVIOUS_MONTH = PREVIOUS_START.strftime("%Y-%m")
PREVIOUS_LAST_DAY = (CURRENT_START - timedelta(days=1)).date()


def _iso_z(moment) -> str:
    """ISO-8601 UTC berakhiran ``Z`` — ``+`` mentah di query string jadi spasi."""
    return moment.astimezone(dt_timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def seed_po(
    code: str,
    *,
    created_at,
    vendor,
    product,
    qty: str = "10.00",
    price_unit: str = "100.00",
    state: str = "CONFIRMED",
):
    """PO + satu `PurchaseOrderLine`; ``created_at`` di-set ulang (auto_now_add)."""
    po = PurchaseOrder.objects.create(code=code, vendor=vendor, state=state)
    # `created_at` = auto_now_add → di-update langsung supaya rentang bisa diuji.
    PurchaseOrder.objects.filter(pk=po.pk).update(created_at=created_at)
    PurchaseOrderLine.objects.create(
        po=po, product=product, qty=Decimal(qty), price_unit=Decimal(price_unit)
    )
    return po


def seed_bill(
    code: str,
    *,
    vendor,
    invoice_date,
    product,
    qty: str = "10.00",
    price_unit: str = "100.00",
    state: str = "DRAFT",
    purchase_order=None,
):
    """Vendor bill + satu baris; ``line_total`` = qty × price_unit (pola H3.2)."""
    bill = VendorBill.objects.create(
        code=code,
        vendor=vendor,
        invoice_date=invoice_date,
        state=state,
        purchase_order=purchase_order,
    )
    VendorBillLine.objects.create(
        bill=bill,
        product=product,
        qty=Decimal(qty),
        price_unit=Decimal(price_unit),
        line_total=Decimal(qty) * Decimal(price_unit),
    )
    return bill


def seed_payment(
    code: str,
    *,
    partner,
    amount: str,
    payment_date,
    vendor_bill=None,
    invoice=None,
    payment_type: str = "OUTBOUND",
    state: str = "SENT",
):
    """Payment (OUTBOUND → `vendor_bill`, INBOUND → `invoice`) untuk dokumen MES."""
    return Payment.objects.create(
        code=code,
        payment_type=payment_type,
        partner=partner,
        customer_invoice=invoice,
        vendor_bill=vendor_bill,
        amount=Decimal(amount),
        payment_date=payment_date,
        state=state,
    )


class PurchasesReportBase(TestCase):
    """Fixture bersama: user + master (vendor, produk) + pembersihan cache."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="rep-purchases", password="x")
        cls.vendor_a = Partner.objects.create(code="SUP-A", name="PT Alpha")
        cls.vendor_b = Partner.objects.create(code="SUP-B", name="PT Beta")
        cls.product_a = make_product(code="PRD-A", name="Kain")
        cls.product_b = make_product(code="PRD-B", name="Benang")

    def setUp(self):
        # Cache LocMem dipakai bersama antar test (settings mode test) → dibersihkan.
        cache.clear()
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def get(self, query: str = ""):
        """GET laporan purchases (query string tanpa tanda tanya)."""
        url = f"{PURCHASES_URL}?{query}" if query else PURCHASES_URL
        return self.api.get(url)

class PurchasesReportAuthTests(TestCase):
    """Izin endpoint: anonim 403 (IsAuthenticated)."""

    def test_anonim_403(self):
        self.assertEqual(APIClient().get(PURCHASES_URL).status_code, 403)


class PurchasesReportRangeTests(PurchasesReportBase):
    """Rentang: default bulan berjalan + prioritas period > date_from/date_to > from/to."""

    def test_default_bulan_berjalan(self):
        seed_po(
            "PO-CUR",
            created_at=CURRENT_START,
            vendor=self.vendor_a,
            product=self.product_a,
            qty="4.00",
            price_unit="25.00",
        )
        seed_po(
            "PO-PREV",
            created_at=PREVIOUS_START,
            vendor=self.vendor_a,
            product=self.product_a,
            qty="100.00",
            price_unit="10.00",
        )

        response = self.get()
        body = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(body.keys()), TOP_KEYS)
        self.assertEqual(set(body["summary"].keys()), SUMMARY_KEYS)
        self.assertEqual(body["group_by"], "period")
        self.assertFalse(body["cached"])
        self.assertIsNone(body["filters"]["period"])
        # Hanya PO bulan berjalan (akrual `created_at`): 4 × 25 = 100.
        self.assertEqual(body["summary"]["total_amount"], 100.0)
        self.assertEqual(body["summary"]["total_qty"], 4.0)
        self.assertEqual(body["summary"]["count_purchases"], 1)
        self.assertEqual(body["summary"]["count_lines"], 1)
        self.assertEqual(body["summary"]["currency"], "IDR")

    def test_period_menang_atas_date_range(self):
        seed_po(
            "PO-PREV",
            created_at=PREVIOUS_START,
            vendor=self.vendor_a,
            product=self.product_a,
            qty="3.00",
            price_unit="10.00",
        )
        seed_po(
            "PO-CUR",
            created_at=CURRENT_START,
            vendor=self.vendor_a,
            product=self.product_a,
            qty="8.00",
            price_unit="10.00",
        )

        # `?period` menang walau `date_from`/`date_to` menunjuk bulan berjalan.
        body = self.get(
            f"period={PREVIOUS_MONTH}"
            f"&date_from={CURRENT_START.date().isoformat()}"
            f"&date_to={CURRENT_START.date().isoformat()}"
        ).json()

        self.assertEqual(body["filters"]["period"], PREVIOUS_MONTH)
        self.assertEqual(body["summary"]["count_purchases"], 1)
        self.assertEqual(body["summary"]["total_qty"], 3.0)

    def test_alias_from_to_iso(self):
        seed_po(
            "PO-MID",
            created_at=CURRENT_START,
            vendor=self.vendor_a,
            product=self.product_a,
            qty="5.00",
            price_unit="10.00",
        )

        body = self.get(
            f"from={_iso_z(CURRENT_START)}"
            f"&to={_iso_z(CURRENT_START + timedelta(days=1))}"
        ).json()

        self.assertEqual(body["summary"]["count_purchases"], 1)
        self.assertEqual(body["summary"]["total_qty"], 5.0)
        self.assertEqual(body["filters"]["from"], _iso_z(CURRENT_START))

    def test_hanya_date_to_batas_bawah_awal_bulan(self):
        seed_po(
            "PO-CUR",
            created_at=CURRENT_START,
            vendor=self.vendor_a,
            product=self.product_a,
            qty="7.00",
            price_unit="10.00",
        )
        seed_po(
            "PO-PREV",
            created_at=PREVIOUS_START,
            vendor=self.vendor_a,
            product=self.product_a,
            qty="99.00",
            price_unit="10.00",
        )

        body = self.get(f"date_to={CURRENT_START.date().isoformat()}").json()

        self.assertEqual(body["summary"]["count_purchases"], 1)
        self.assertEqual(body["summary"]["total_qty"], 7.0)

    def test_param_rentang_tidak_valid_400(self):
        period = self.get("period=2026-13")
        self.assertEqual(period.status_code, 400)
        self.assertIn("period", period.json()["detail"])

        tanggal = self.get("date_from=kemarin")
        self.assertEqual(tanggal.status_code, 400)
        self.assertIn("tanggal", tanggal.json()["detail"])

        terbalik = self.get(
            f"date_from={CURRENT_START.date().isoformat()}"
            f"&date_to={PREVIOUS_LAST_DAY.isoformat()}"
        )
        self.assertEqual(terbalik.status_code, 400)
        self.assertIn("tidak boleh lebih besar", terbalik.json()["detail"])


class PurchasesReportFilterTests(PurchasesReportBase):
    """Filter vendor/product/status + PO CANCELLED."""

    def test_filter_vendor(self):
        seed_po(
            "PO-A",
            created_at=CURRENT_START,
            vendor=self.vendor_a,
            product=self.product_a,
            qty="4.00",
            price_unit="25.00",
        )
        seed_po(
            "PO-B",
            created_at=CURRENT_START,
            vendor=self.vendor_b,
            product=self.product_a,
            qty="6.00",
            price_unit="10.00",
        )

        body = self.get(f"vendor_id={self.vendor_b.pk}&group_by=vendor").json()

        self.assertEqual([row["label"] for row in body["rows"]], ["PT Beta"])
        self.assertEqual([row["key"] for row in body["rows"]], ["SUP-B"])
        self.assertEqual(body["summary"]["count_purchases"], 1)
        self.assertEqual(body["summary"]["total_qty"], 6.0)
        self.assertEqual(body["summary"]["total_amount"], 60.0)
        self.assertEqual(body["filters"]["vendor_id"], self.vendor_b.pk)

    def test_filter_product(self):
        seed_po(
            "PO-PA",
            created_at=CURRENT_START,
            vendor=self.vendor_a,
            product=self.product_a,
            qty="4.00",
            price_unit="25.00",
        )
        seed_po(
            "PO-PB",
            created_at=CURRENT_START,
            vendor=self.vendor_a,
            product=self.product_b,
            qty="2.00",
            price_unit="30.00",
        )

        body = self.get(f"product_id={self.product_b.pk}").json()

        self.assertEqual(body["summary"]["count_lines"], 1)
        self.assertEqual(body["summary"]["total_qty"], 2.0)
        self.assertEqual(body["summary"]["total_amount"], 60.0)
        self.assertEqual(body["filters"]["product_id"], self.product_b.pk)

    def test_filter_status_case_insensitive(self):
        seed_po(
            "PO-EXP",
            created_at=CURRENT_START,
            vendor=self.vendor_a,
            product=self.product_a,
            qty="4.00",
            price_unit="10.00",
            state="DONE",
        )
        seed_po(
            "PO-CUS",
            created_at=CURRENT_START,
            vendor=self.vendor_a,
            product=self.product_a,
            qty="9.00",
            price_unit="10.00",
            state="CONFIRMED",
        )

        body = self.get("status=done").json()

        self.assertEqual(body["summary"]["total_qty"], 4.0)
        self.assertEqual(body["summary"]["total_amount"], 40.0)
        self.assertEqual(body["filters"]["status"], "DONE")

    def test_po_cancelled_tidak_dihitung(self):
        seed_po("PO-OK", created_at=CURRENT_START, vendor=self.vendor_a, product=self.product_a, qty="5.00")
        seed_po(
            "PO-DEL",
            created_at=CURRENT_START,
            vendor=self.vendor_a,
            product=self.product_a,
            qty="100.00",
            state="CANCELLED",
        )

        body = self.get().json()

        self.assertEqual(body["summary"]["count_purchases"], 1)
        self.assertEqual(body["summary"]["count_lines"], 1)
        self.assertEqual(body["summary"]["total_qty"], 5.0)


class PurchasesReportGroupTests(PurchasesReportBase):
    """``?group_by=period|vendor|product`` — bentuk baris & urutan."""

    def test_group_by_vendor_urut_amount(self):
        seed_po(
            "PO-A",
            created_at=CURRENT_START,
            vendor=self.vendor_a,
            product=self.product_a,
            qty="2.00",
            price_unit="10.00",
        )
        seed_po(
            "PO-B",
            created_at=CURRENT_START,
            vendor=self.vendor_b,
            product=self.product_a,
            qty="9.00",
            price_unit="10.00",
        )

        body = self.get("group_by=vendor").json()
        rows = body["rows"]

        self.assertEqual(body["group_by"], "vendor")
        self.assertEqual(
            set(rows[0].keys()),
            ROW_BASE_KEYS | {"vendor_id", "vendor_code", "vendor_name"},
        )
        self.assertEqual([row["label"] for row in rows], ["PT Beta", "PT Alpha"])
        self.assertEqual([row["total_amount"] for row in rows], [90.0, 20.0])
        self.assertEqual(rows[0]["unit"], "IDR")
        self.assertEqual(rows[0]["value"], 90.0)
        self.assertEqual(rows[1]["vendor_code"], "SUP-A")

    def test_group_by_product(self):
        seed_po(
            "PO-PA",
            created_at=CURRENT_START,
            vendor=self.vendor_a,
            product=self.product_a,
            qty="4.00",
            price_unit="25.00",
        )
        seed_po(
            "PO-PB",
            created_at=CURRENT_START,
            vendor=self.vendor_a,
            product=self.product_b,
            qty="2.00",
            price_unit="30.00",
        )

        body = self.get("group_by=product").json()
        rows = body["rows"]

        self.assertEqual(
            set(rows[0].keys()),
            ROW_BASE_KEYS | {"product_id", "product_code", "product_name"},
        )
        self.assertEqual([row["key"] for row in rows], ["PRD-A", "PRD-B"])
        self.assertEqual([row["total_amount"] for row in rows], [100.0, 60.0])
        self.assertEqual(rows[0]["product_name"], "Kain")
        self.assertEqual(rows[1]["product_name"], "Benang")

    def test_group_by_period_dua_bulan(self):
        seed_po("PO-PREV", created_at=PREVIOUS_START, vendor=self.vendor_a, product=self.product_a, qty="3.00")
        seed_po("PO-CUR", created_at=CURRENT_START, vendor=self.vendor_a, product=self.product_a, qty="8.00")

        body = self.get(
            f"group_by=period&date_from={PREVIOUS_START.date().isoformat()}"
            f"&date_to={CURRENT_START.date().isoformat()}"
        ).json()
        rows = body["rows"]

        self.assertEqual(set(rows[0].keys()), ROW_BASE_KEYS | {"period"})
        self.assertEqual([row["key"] for row in rows], [PREVIOUS_MONTH, CURRENT_MONTH])
        self.assertEqual([row["period"] for row in rows], [PREVIOUS_MONTH, CURRENT_MONTH])
        self.assertEqual([row["purchase_count"] for row in rows], [1, 1])
        self.assertEqual(body["summary"]["count_purchases"], 2)

    def test_group_by_row_qty_pecahan(self):
        # Qty pembelian boleh pecahan (mis. benang 0.3) → `total_qty` = float.
        seed_po(
            "PO-BNG",
            created_at=CURRENT_START,
            vendor=self.vendor_a,
            product=self.product_b,
            qty="0.30",
            price_unit="50000.00",
        )

        rows = self.get("group_by=product").json()["rows"]

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["total_qty"], 0.3)
        self.assertEqual(rows[0]["total_amount"], 15000.0)

class PurchasesReportSummaryTests(PurchasesReportBase):
    """Ringkasan: utang bill + kas keluar payment (bukan `VendorBill.amount_total`)."""

    def test_summary_billed_dan_paid(self):
        po = seed_po(
            "PO-INV",
            created_at=CURRENT_START,
            vendor=self.vendor_a,
            product=self.product_a,
            qty="10.00",
            price_unit="100.00",
        )
        bill = seed_bill(
            "VB-1",
            vendor=self.vendor_a,
            purchase_order=po,
            invoice_date=CURRENT_START.date(),
            product=self.product_a,
            qty="10.00",
            price_unit="100.00",
        )
        seed_bill(
            "VB-DEL",
            vendor=self.vendor_a,
            purchase_order=po,
            invoice_date=CURRENT_START.date(),
            product=self.product_a,
            qty="5.00",
            price_unit="100.00",
            state="CANCELLED",
        )
        seed_payment(
            "PAY-SENT",
            partner=self.vendor_a,
            vendor_bill=bill,
            amount="300.00",
            payment_date=CURRENT_START.date(),
            state="SENT",
        )
        seed_payment(
            "PAY-DONE",
            partner=self.vendor_a,
            vendor_bill=bill,
            amount="200.00",
            payment_date=CURRENT_START.date(),
            state="DONE",
        )
        seed_payment(
            "PAY-DRAFT",
            partner=self.vendor_a,
            vendor_bill=bill,
            amount="999.00",
            payment_date=CURRENT_START.date(),
            state="DRAFT",
        )

        summary = self.get().json()["summary"]

        self.assertEqual(summary["total_amount"], 1000.0)
        # VB-DEL (5 × 100) CANCELLED → tidak dihitung sebagai utang.
        self.assertEqual(summary["billed_amount"], 1000.0)
        self.assertEqual(summary["bill_count"], 1)
        # Hanya OUTBOUND SENT/DONE: 300 + 200 (DRAFT 999 dibuang).
        self.assertEqual(summary["paid_amount"], 500.0)
        self.assertEqual(summary["payment_count"], 2)
        self.assertEqual(summary["currency"], "IDR")

        # Basis `invoice_date`/`payment_date` → periode lain tidak menghitung dokumen ini.
        lain = self.get(f"period={PREVIOUS_MONTH}").json()["summary"]
        self.assertEqual(lain["paid_amount"], 0.0)
        self.assertEqual(lain["billed_amount"], 0.0)

    def test_filter_status_menyempitkan_summary(self):
        po_ok = seed_po(
            "PO-CONF",
            created_at=CURRENT_START,
            vendor=self.vendor_a,
            product=self.product_a,
            qty="4.00",
            price_unit="10.00",
            state="CONFIRMED",
        )
        seed_po(
            "PO-DRAFT",
            created_at=CURRENT_START,
            vendor=self.vendor_a,
            product=self.product_a,
            qty="6.00",
            price_unit="10.00",
            state="DRAFT",
        )
        bill = seed_bill(
            "VB-OK",
            vendor=self.vendor_a,
            purchase_order=po_ok,
            invoice_date=CURRENT_START.date(),
            product=self.product_a,
            qty="4.00",
            price_unit="10.00",
        )
        seed_payment(
            "PAY-OK",
            partner=self.vendor_a,
            vendor_bill=bill,
            amount="40.00",
            payment_date=CURRENT_START.date(),
        )

        body = self.get("status=confirmed").json()
        summary = body["summary"]

        self.assertEqual(body["filters"]["status"], "CONFIRMED")
        self.assertEqual(summary["count_purchases"], 1)
        self.assertEqual(summary["total_qty"], 4.0)
        self.assertEqual(summary["total_amount"], 40.0)
        self.assertEqual(summary["billed_amount"], 40.0)
        self.assertEqual(summary["paid_amount"], 40.0)

    def test_hasil_kosong_tetap_valid(self):
        response = self.get("period=2000-01")
        body = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(body.keys()), TOP_KEYS)
        self.assertEqual(body["rows"], [])
        self.assertEqual(body["summary"]["total_amount"], 0.0)
        self.assertEqual(body["summary"]["count_purchases"], 0)
        self.assertEqual(body["summary"]["paid_amount"], 0.0)
        self.assertEqual(body["filters"]["period"], "2000-01")


class PurchasesReportCacheTests(PurchasesReportBase):
    """Cache 300 dtk + ``?_nocache=1`` (tidak baca **dan** tidak tulis cache)."""

    def test_cache_hit_nocache_dan_key_per_filter(self):
        seed_po(
            "PO-A",
            created_at=CURRENT_START,
            vendor=self.vendor_a,
            product=self.product_a,
            qty="4.00",
        )
        seed_po(
            "PO-B",
            created_at=CURRENT_START,
            vendor=self.vendor_b,
            product=self.product_a,
            qty="6.00",
        )

        pertama = self.get().json()
        self.assertFalse(pertama["cached"])

        kedua = self.get().json()
        self.assertTrue(kedua["cached"])
        self.assertEqual(kedua["rows"], pertama["rows"])
        self.assertEqual(kedua["generated_at"], pertama["generated_at"])

        bypass = self.get("_nocache=1").json()
        self.assertFalse(bypass["cached"])
        self.assertEqual(bypass["rows"], pertama["rows"])
        # `_nocache=1` tidak menulis cache → GET biasa tetap dari entri lama.
        self.assertTrue(self.get().json()["cached"])

        # Key cache memuat filter efektif → filter berbeda = entri berbeda.
        self.assertFalse(self.get(f"vendor_id={self.vendor_a.pk}").json()["cached"])
        self.assertTrue(self.get(f"vendor_id={self.vendor_a.pk}").json()["cached"])
        self.assertFalse(self.get("group_by=vendor").json()["cached"])


class PurchasesReportValidationTests(PurchasesReportBase):
    """Nilai param filter tak dikenal → 400 dengan pesan jelas."""

    def test_param_filter_tidak_valid_400(self):
        for query, kunci in (
            ("vendor_id=abc", "vendor_id"),
            ("vendor_id=0", "vendor_id"),
            ("product_id=abc", "product_id"),
            ("status=NOPE", "status"),
            ("group_by=nope", "group_by"),
        ):
            with self.subTest(query=query):
                response = self.get(query)
                self.assertEqual(response.status_code, 400)
                self.assertIn(kunci, response.json()["detail"])


class PurchasesReportNonBreakingTests(PurchasesReportBase):
    """B11 (`/purchase/reporting/`) + H4.1 (`/reports/sales/`) tidak berubah."""

    def test_non_breaking_b11_dan_h4_1(self):
        self.assertEqual(
            resolve("/api/v1/purchase/reporting/").url_name, "purchase_reporting"
        )
        self.assertEqual(resolve(SALES_URL).url_name, "reports_sales")
        self.assertEqual(resolve(PURCHASES_URL).url_name, "reports_purchases")

        penjualan = self.api.get(SALES_URL)
        self.assertEqual(penjualan.status_code, 200)
        self.assertEqual(set(penjualan.json().keys()), TOP_KEYS)

        wip = self.api.get(WIP_URL)
        self.assertEqual(wip.status_code, 200)
        self.assertEqual(
            set(wip.json().keys()), {"rows", "total_wip", "group_by", "generated_at"}
        )
