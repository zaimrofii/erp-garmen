"""Test laporan penjualan (H4.1) — ``GET /api/v1/reports/sales/``.

Read-only DB murni: agregat `OrderLine ⋈ Order` (basis ``Order.created_at``) +
`CustomerInvoiceLine` (piutang) + `Payment` INBOUND SENT/DONE (kas masuk), cache
300 detik (``?nocache=1`` = bypass). ``IsAuthenticated`` → anonim **403**.

Cakupan: default bulan berjalan, prioritas ``?period`` > ``?date_from``/
``?date_to`` > ``?from``/``?to``, filter customer/product/order_type,
``group_by=period|customer|product``, nilai tak dikenal → **400**, hasil kosong
tetap valid, cache hit, dan **non-breaking** B13/B16.

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_reports_sales.py -q
"""

from __future__ import annotations

from datetime import timedelta, timezone as dt_timezone
from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps_industry.garment.models import (
    CustomerInvoice,
    CustomerInvoiceLine,
    Order,
    OrderLine,
    Payment,
    VendorBill,
)
from apps_industry.garment.tests.factories import make_product
from core.auth.models import User
from master.models import Partner

SALES_URL = "/api/v1/reports/sales/"
EFFICIENCY_URL = "/api/v1/reports/line-efficiency/"
WIP_URL = "/api/v1/reports/wip/"

TOP_KEYS = {"rows", "summary", "group_by", "filters", "period", "generated_at", "cached"}
SUMMARY_KEYS = {
    "total_qty",
    "total_amount",
    "count_orders",
    "count_lines",
    "invoiced_amount",
    "invoice_count",
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
    "order_count",
    "line_count",
}

#: Anchor waktu: bulan berjalan & bulan sebelumnya (jam 10:00 lokal, tz-aware).
_now = timezone.localtime(timezone.now())
CURRENT_START = _now.replace(day=1, hour=10, minute=0, second=0, microsecond=0)
PREVIOUS_START = (CURRENT_START - timedelta(days=1)).replace(day=1)
NEXT_START = (CURRENT_START + timedelta(days=32)).replace(day=1)
CURRENT_MONTH = CURRENT_START.strftime("%Y-%m")
PREVIOUS_MONTH = PREVIOUS_START.strftime("%Y-%m")
PREVIOUS_LAST_DAY = (CURRENT_START - timedelta(days=1)).date()


def _iso_z(moment) -> str:
    """ISO-8601 UTC berakhiran ``Z`` — ``+`` mentah di query string jadi spasi."""
    return moment.astimezone(dt_timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def seed_order(
    code: str,
    *,
    created_at,
    product,
    qty: int = 10,
    price_unit: str = "100.00",
    customer=None,
    order_type: str = "EXPORT",
    state: str = "CONFIRMED",
):
    """Order + satu `OrderLine`; ``created_at`` di-set ulang (auto_now_add)."""
    order = Order.objects.create(
        code=code, customer=customer, order_type=order_type, state=state
    )
    # `created_at` = auto_now_add → di-update langsung supaya rentang bisa diuji.
    Order.objects.filter(pk=order.pk).update(created_at=created_at)
    OrderLine.objects.create(
        order=order, product=product, qty=qty, price_unit=Decimal(price_unit)
    )
    return order


def seed_invoice(
    code: str,
    *,
    order,
    customer,
    invoice_date,
    product,
    qty: str = "10.00",
    price_unit: str = "100.00",
    state: str = "DRAFT",
):
    """Invoice + satu baris; ``line_total`` = qty × price_unit (pola H3.1)."""
    invoice = CustomerInvoice.objects.create(
        code=code,
        order=order,
        customer=customer,
        invoice_date=invoice_date,
        state=state,
    )
    CustomerInvoiceLine.objects.create(
        invoice=invoice,
        product=product,
        qty=Decimal(qty),
        price_unit=Decimal(price_unit),
        line_total=Decimal(qty) * Decimal(price_unit),
    )
    return invoice


def seed_payment(
    code: str,
    *,
    partner,
    amount: str,
    payment_date,
    invoice=None,
    vendor_bill=None,
    payment_type: str = "INBOUND",
    state: str = "SENT",
):
    """Payment (INBOUND → `invoice`, OUTBOUND → `vendor_bill`) untuk dokumen MES."""
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


class SalesReportBase(TestCase):
    """Fixture bersama: user + master (customer, produk) + pembersihan cache."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="rep-sales", password="x")
        cls.customer_a = Partner.objects.create(code="CUST-A", name="PT Alpha")
        cls.customer_b = Partner.objects.create(code="CUST-B", name="PT Beta")
        cls.product_a = make_product(code="PRD-A", name="Kaos Polos")
        cls.product_b = make_product(code="PRD-B", name="Kemeja")

    def setUp(self):
        # Cache LocMem dipakai bersama antar test (settings mode test) → dibersihkan.
        cache.clear()
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def get(self, query: str = ""):
        """GET laporan sales (query string tanpa tanda tanya)."""
        url = f"{SALES_URL}?{query}" if query else SALES_URL
        return self.api.get(url)


class SalesReportAuthTests(TestCase):
    """Izin endpoint: anonim 403 (IsAuthenticated)."""

    def test_anonim_403(self):
        self.assertEqual(APIClient().get(SALES_URL).status_code, 403)


class SalesReportRangeTests(SalesReportBase):
    """Rentang: default bulan berjalan + prioritas period > date_from/date_to > from/to."""

    def test_default_bulan_berjalan(self):
        seed_order(
            "SO-CUR",
            created_at=CURRENT_START,
            product=self.product_a,
            customer=self.customer_a,
            qty=4,
            price_unit="25.00",
        )
        seed_order(
            "SO-PREV",
            created_at=PREVIOUS_START,
            product=self.product_a,
            qty=100,
            price_unit="10.00",
        )

        response = self.get()
        body = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(body.keys()), TOP_KEYS)
        self.assertEqual(set(body["summary"].keys()), SUMMARY_KEYS)
        self.assertEqual(body["group_by"], "period")
        self.assertFalse(body["cached"])
        self.assertEqual([row["key"] for row in body["rows"]], [CURRENT_MONTH])
        self.assertEqual(body["summary"]["count_orders"], 1)
        self.assertEqual(body["summary"]["count_lines"], 1)
        self.assertEqual(body["summary"]["total_qty"], 4)
        self.assertEqual(body["summary"]["total_amount"], 100.0)
        self.assertTrue(body["period"]["from"].startswith(CURRENT_START.date().isoformat()))
        self.assertIsNone(body["filters"]["period"])
        self.assertIsNone(body["filters"]["customer_id"])
        self.assertEqual(body["filters"]["resolved_from"], body["period"]["from"])

    def test_period_filter(self):
        seed_order("SO-CUR", created_at=CURRENT_START, product=self.product_a, qty=4)
        seed_order(
            "SO-PREV",
            created_at=PREVIOUS_START,
            product=self.product_a,
            qty=7,
            price_unit="50.00",
        )

        response = self.get(f"period={PREVIOUS_MONTH}")
        body = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["key"] for row in body["rows"]], [PREVIOUS_MONTH])
        self.assertEqual(body["summary"]["count_orders"], 1)
        self.assertEqual(body["summary"]["total_qty"], 7)
        self.assertEqual(body["summary"]["total_amount"], 350.0)
        self.assertEqual(body["filters"]["period"], PREVIOUS_MONTH)

    def test_date_from_date_to(self):
        seed_order("SO-CUR", created_at=CURRENT_START, product=self.product_a, qty=4)
        seed_order(
            "SO-PREV",
            created_at=PREVIOUS_START,
            product=self.product_a,
            qty=9,
            price_unit="10.00",
        )

        response = self.get(
            f"date_from={PREVIOUS_START.date().isoformat()}"
            f"&date_to={PREVIOUS_LAST_DAY.isoformat()}"
        )
        body = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["summary"]["count_orders"], 1)
        self.assertEqual(body["summary"]["total_qty"], 9)
        self.assertEqual(body["filters"]["date_from"], PREVIOUS_START.date().isoformat())

    def test_prioritas_period_menang_atas_date_from(self):
        seed_order("SO-CUR", created_at=CURRENT_START, product=self.product_a, qty=4)
        seed_order("SO-PREV", created_at=PREVIOUS_START, product=self.product_a, qty=9)

        response = self.get(
            f"period={PREVIOUS_MONTH}&date_from={CURRENT_START.date().isoformat()}"
        )
        body = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["summary"]["total_qty"], 9)
        self.assertEqual([row["key"] for row in body["rows"]], [PREVIOUS_MONTH])

    def test_alias_from_to(self):
        seed_order(
            "SO-PREV",
            created_at=PREVIOUS_START,
            product=self.product_a,
            qty=3,
            price_unit="20.00",
        )
        seed_order("SO-CUR", created_at=CURRENT_START, product=self.product_a, qty=5)

        response = self.get(
            f"from={_iso_z(PREVIOUS_START)}&to={PREVIOUS_LAST_DAY.isoformat()}"
        )
        body = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["summary"]["total_qty"], 3)
        self.assertEqual(body["filters"]["from"], _iso_z(PREVIOUS_START))

    def test_rentang_tidak_valid_400(self):
        """`period` cacat, tanggal bukan ISO, dan `from > to` → 400."""
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


class SalesReportFilterTests(SalesReportBase):
    """Filter customer/product/order_type + order CANCELLED."""

    def test_filter_customer(self):
        seed_order(
            "SO-A",
            created_at=CURRENT_START,
            product=self.product_a,
            customer=self.customer_a,
            qty=4,
            price_unit="25.00",
        )
        seed_order(
            "SO-B",
            created_at=CURRENT_START,
            product=self.product_a,
            customer=self.customer_b,
            qty=6,
            price_unit="10.00",
        )

        body = self.get(f"customer_id={self.customer_b.pk}&group_by=customer").json()

        self.assertEqual([row["label"] for row in body["rows"]], ["PT Beta"])
        self.assertEqual([row["key"] for row in body["rows"]], ["CUST-B"])
        self.assertEqual(body["summary"]["count_orders"], 1)
        self.assertEqual(body["summary"]["total_qty"], 6)
        self.assertEqual(body["summary"]["total_amount"], 60.0)
        self.assertEqual(body["filters"]["customer_id"], self.customer_b.pk)

    def test_filter_product(self):
        seed_order(
            "SO-PA",
            created_at=CURRENT_START,
            product=self.product_a,
            qty=4,
            price_unit="25.00",
        )
        seed_order(
            "SO-PB",
            created_at=CURRENT_START,
            product=self.product_b,
            qty=2,
            price_unit="30.00",
        )

        body = self.get(f"product_id={self.product_b.pk}").json()

        self.assertEqual(body["summary"]["count_lines"], 1)
        self.assertEqual(body["summary"]["total_qty"], 2)
        self.assertEqual(body["summary"]["total_amount"], 60.0)
        self.assertEqual(body["filters"]["product_id"], self.product_b.pk)

    def test_filter_order_type_case_insensitive(self):
        seed_order(
            "SO-EXP",
            created_at=CURRENT_START,
            product=self.product_a,
            order_type="EXPORT",
            qty=4,
            price_unit="10.00",
        )
        seed_order(
            "SO-CUS",
            created_at=CURRENT_START,
            product=self.product_a,
            order_type="CUSTOM",
            qty=9,
            price_unit="10.00",
        )

        body = self.get("order_type=custom").json()

        self.assertEqual(body["summary"]["total_qty"], 9)
        self.assertEqual(body["summary"]["total_amount"], 90.0)
        self.assertEqual(body["filters"]["order_type"], "CUSTOM")

    def test_order_cancelled_tidak_dihitung(self):
        seed_order("SO-OK", created_at=CURRENT_START, product=self.product_a, qty=5)
        seed_order(
            "SO-DEL",
            created_at=CURRENT_START,
            product=self.product_a,
            qty=100,
            state="CANCELLED",
        )

        body = self.get().json()

        self.assertEqual(body["summary"]["count_orders"], 1)
        self.assertEqual(body["summary"]["count_lines"], 1)
        self.assertEqual(body["summary"]["total_qty"], 5)


class SalesReportGroupTests(SalesReportBase):
    """``?group_by=period|customer|product`` — bentuk baris & urutan."""

    def test_group_by_customer_urut_amount(self):
        seed_order(
            "SO-A",
            created_at=CURRENT_START,
            product=self.product_a,
            customer=self.customer_a,
            qty=2,
            price_unit="10.00",
        )
        seed_order(
            "SO-B",
            created_at=CURRENT_START,
            product=self.product_a,
            customer=self.customer_b,
            qty=9,
            price_unit="10.00",
        )

        body = self.get("group_by=customer").json()
        rows = body["rows"]

        self.assertEqual(body["group_by"], "customer")
        self.assertEqual(
            set(rows[0].keys()),
            ROW_BASE_KEYS | {"customer_id", "customer_code", "customer_name"},
        )
        self.assertEqual([row["label"] for row in rows], ["PT Beta", "PT Alpha"])
        self.assertEqual([row["total_amount"] for row in rows], [90.0, 20.0])
        self.assertEqual(rows[0]["unit"], "IDR")
        self.assertEqual(rows[0]["value"], 90.0)
        self.assertEqual(rows[1]["customer_code"], "CUST-A")

    def test_group_by_product(self):
        seed_order(
            "SO-PA",
            created_at=CURRENT_START,
            product=self.product_a,
            qty=4,
            price_unit="25.00",
        )
        seed_order(
            "SO-PB",
            created_at=CURRENT_START,
            product=self.product_b,
            qty=2,
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
        self.assertEqual(rows[0]["product_name"], "Kaos Polos")
        self.assertEqual(rows[1]["product_name"], "Kemeja")

    def test_group_by_period_dua_bulan(self):
        seed_order("SO-PREV", created_at=PREVIOUS_START, product=self.product_a, qty=3)
        seed_order("SO-CUR", created_at=CURRENT_START, product=self.product_a, qty=8)

        body = self.get(
            f"group_by=period&date_from={PREVIOUS_START.date().isoformat()}"
            f"&date_to={CURRENT_START.date().isoformat()}"
        ).json()
        rows = body["rows"]

        self.assertEqual(set(rows[0].keys()), ROW_BASE_KEYS | {"period"})
        self.assertEqual([row["key"] for row in rows], [PREVIOUS_MONTH, CURRENT_MONTH])
        self.assertEqual([row["period"] for row in rows], [PREVIOUS_MONTH, CURRENT_MONTH])
        self.assertEqual([row["order_count"] for row in rows], [1, 1])
        self.assertEqual(body["summary"]["count_orders"], 2)


class SalesReportSummaryTests(SalesReportBase):
    """Ringkasan: piutang invoice + kas masuk payment (bukan `amount_total`)."""

    def test_summary_invoiced_dan_paid(self):
        order = seed_order(
            "SO-INV",
            created_at=CURRENT_START,
            product=self.product_a,
            customer=self.customer_a,
            qty=10,
            price_unit="100.00",
        )
        invoice = seed_invoice(
            "INV-1",
            order=order,
            customer=self.customer_a,
            invoice_date=CURRENT_START.date(),
            product=self.product_a,
            qty="10.00",
            price_unit="100.00",
        )
        seed_invoice(
            "INV-DEL",
            order=order,
            customer=self.customer_a,
            invoice_date=CURRENT_START.date(),
            product=self.product_a,
            qty="5.00",
            price_unit="100.00",
            state="CANCELLED",
        )
        seed_payment(
            "PAY-SENT",
            partner=self.customer_a,
            invoice=invoice,
            amount="300.00",
            payment_date=CURRENT_START.date(),
            state="SENT",
        )
        seed_payment(
            "PAY-DONE",
            partner=self.customer_a,
            invoice=invoice,
            amount="200.00",
            payment_date=CURRENT_START.date(),
            state="DONE",
        )
        seed_payment(
            "PAY-DRAFT",
            partner=self.customer_a,
            invoice=invoice,
            amount="999.00",
            payment_date=CURRENT_START.date(),
            state="DRAFT",
        )
        vendor = Partner.objects.create(code="SUP-1", name="PT Vendor")
        bill = VendorBill.objects.create(
            code="VB-1", vendor=vendor, invoice_date=CURRENT_START.date()
        )
        seed_payment(
            "PAY-OUT",
            partner=vendor,
            vendor_bill=bill,
            amount="777.00",
            payment_date=CURRENT_START.date(),
            payment_type="OUTBOUND",
            state="SENT",
        )

        summary = self.get().json()["summary"]

        self.assertEqual(summary["total_amount"], 1000.0)
        # INV-DEL (5 × 100) CANCELLED → tidak dihitung sebagai piutang.
        self.assertEqual(summary["invoiced_amount"], 1000.0)
        self.assertEqual(summary["invoice_count"], 1)
        # Hanya INBOUND SENT/DONE: 300 + 200 (DRAFT 999 & OUTBOUND 777 dibuang).
        self.assertEqual(summary["paid_amount"], 500.0)
        self.assertEqual(summary["payment_count"], 2)
        self.assertEqual(summary["currency"], "IDR")

        # Basis `invoice_date`/`payment_date` → periode lain tidak menghitung dokumen ini.
        lain = self.get(f"period={PREVIOUS_MONTH}").json()["summary"]
        self.assertEqual(lain["paid_amount"], 0.0)
        self.assertEqual(lain["invoiced_amount"], 0.0)

    def test_hasil_kosong_tetap_valid(self):
        response = self.get("period=2000-01")
        body = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(body.keys()), TOP_KEYS)
        self.assertEqual(body["rows"], [])
        self.assertEqual(body["summary"]["total_amount"], 0.0)
        self.assertEqual(body["summary"]["count_orders"], 0)
        self.assertEqual(body["summary"]["paid_amount"], 0.0)
        self.assertEqual(body["filters"]["period"], "2000-01")

    def test_baris_tanpa_customer(self):
        seed_order("SO-NOCUST", created_at=CURRENT_START, product=self.product_a, qty=3)

        rows = self.get("group_by=customer").json()["rows"]

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["key"], "")
        self.assertEqual(rows[0]["label"], "(tanpa customer)")
        self.assertIsNone(rows[0]["customer_id"])


class SalesReportCacheTests(SalesReportBase):
    """Cache 300 dtk + ``?_nocache=1`` (tidak baca **dan** tidak tulis cache)."""

    def test_cache_hit_nocache_dan_key_per_filter(self):
        seed_order(
            "SO-A",
            created_at=CURRENT_START,
            product=self.product_a,
            customer=self.customer_a,
            qty=4,
        )
        seed_order(
            "SO-B",
            created_at=CURRENT_START,
            product=self.product_a,
            customer=self.customer_b,
            qty=6,
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
        self.assertFalse(self.get(f"customer_id={self.customer_a.pk}").json()["cached"])
        self.assertTrue(self.get(f"customer_id={self.customer_a.pk}").json()["cached"])
        self.assertFalse(self.get("group_by=customer").json()["cached"])


class SalesReportValidationTests(SalesReportBase):
    """Nilai param filter tak dikenal → 400 dengan pesan jelas."""

    def test_param_filter_tidak_valid_400(self):
        for query, kunci in (
            ("customer_id=abc", "customer_id"),
            ("customer_id=0", "customer_id"),
            ("product_id=abc", "product_id"),
            ("order_type=NOPE", "order_type"),
            ("group_by=nope", "group_by"),
        ):
            with self.subTest(query=query):
                response = self.get(query)
                self.assertEqual(response.status_code, 400)
                self.assertIn(kunci, response.json()["detail"])


class SalesReportNonBreakingTests(SalesReportBase):
    """Endpoint report lama (B13/B16) tidak berubah bentuk."""

    def test_b13_b16_tetap_hijau(self):
        efisiensi = self.api.get(EFFICIENCY_URL)
        wip = self.api.get(WIP_URL)

        self.assertEqual(efisiensi.status_code, 200)
        self.assertEqual(set(efisiensi.json().keys()), {"rows", "generated_at", "period"})
        self.assertEqual(wip.status_code, 200)
        self.assertEqual(
            set(wip.json().keys()), {"rows", "total_wip", "group_by", "generated_at"}
        )
        self.assertEqual(self.api.get(SALES_URL).status_code, 200)
