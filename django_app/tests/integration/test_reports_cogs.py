"""Test laporan HPP/laba kotor (H4.4) — ``GET /api/v1/reports/cogs/``.

Read-only DB murni: agregat `OrderLine ⋈ Order ⋈ Product` (basis
``Order.created_at``) — omzet ``qty × price_unit`` vs HPP simplified
``qty × product.cost_price``, laba kotor, margin %, dan penanda data hilang
(``cost_price = 0`` / ``product`` NULL). Cache 300 dtk; ``?nocache=1`` bypass.

Cakupan: default bulan berjalan, prioritas ``?period`` > ``?date_from``/
``?date_to`` > ``?from``/``?to``, filter customer/product/order_type, exclude
order ``CANCELLED``, ``group_by=period|customer|product``, HPP nol + flag
``no_cost``/``no_product`` (``no_product`` menang), margin 0 saat sales 0,
cache hit = **0 query**, 400, dan **non-breaking** H4.1/H4.3 + ``cost_price``.

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_reports_cogs.py -q
"""

from __future__ import annotations

from datetime import timedelta, timezone as dt_timezone
from decimal import Decimal

from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import resolve
from django.utils import timezone
from rest_framework.test import APIClient

from apps_industry.garment.models import Order, OrderLine
from core.auth.models import User
from master.models import Partner, Product

COGS_URL = "/api/v1/reports/cogs/"
SALES_URL = "/api/v1/reports/sales/"
STOCK_URL = "/api/v1/reports/stock/"

TOP_KEYS = {"rows", "summary", "group_by", "filters", "period", "generated_at", "cached"}
SUMMARY_KEYS = {
    "total_sales",
    "total_cogs",
    "total_gross_profit",
    "gross_margin_pct",
    "order_count",
    "line_count",
    "qty_total",
    "rows_with_missing_cost",
    "currency",
}
ROW_BASE_KEYS = {
    "key",
    "label",
    "sales_amount",
    "cogs_amount",
    "gross_profit",
    "gross_margin_pct",
    "order_count",
    "line_count",
    "qty_total",
    "has_missing_cost",
    "missing_cost_reason",
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
    Order.objects.filter(pk=order.pk).update(created_at=created_at)
    OrderLine.objects.create(
        order=order, product=product, qty=qty, price_unit=Decimal(price_unit)
    )
    return order


class CogsReportBase(TestCase):
    """Fixture bersama: user + master (customer, produk ber-cost & cost 0) + cache."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="rep-cogs", password="x")
        cls.customer_a = Partner.objects.create(code="CUST-A", name="PT Alpha")
        cls.customer_b = Partner.objects.create(code="CUST-B", name="PT Beta")
        #: HPP 40/unit — dasar perhitungan COGS.
        cls.kain = Product.objects.create(
            code="KAIN", name="Kain", cost_price=Decimal("40.00"), sale_price=Decimal("100.00")
        )
        #: cost_price 0 — COGS tidak boleh difabrikasi.
        cls.zero = Product.objects.create(
            code="ZERO", name="Nol Cost", cost_price=Decimal("0.00"), sale_price=Decimal("200.00")
        )

    def setUp(self):
        # Cache LocMem dipakai bersama antar test (settings mode test) → dibersihkan.
        cache.clear()
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def get(self, query: str = ""):
        """GET laporan HPP (query string tanpa tanda tanya)."""
        url = f"{COGS_URL}?{query}" if query else COGS_URL
        return self.api.get(url)

class CogsReportAuthTests(TestCase):
    """Izin endpoint: anonim 403 (IsAuthenticated)."""

    def test_anonim_403(self):
        self.assertEqual(APIClient().get(COGS_URL).status_code, 403)


class CogsReportRangeTests(CogsReportBase):
    """Default bulan berjalan + prioritas period > date_from/date_to > from/to."""

    def test_default_bulan_berjalan(self):
        seed_order(
            "SO-CUR",
            created_at=CURRENT_START,
            product=self.kain,
            customer=self.customer_a,
            qty=10,
            price_unit="100.00",
        )
        seed_order(
            "SO-PREV",
            created_at=PREVIOUS_START,
            product=self.kain,
            customer=self.customer_a,
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

        summary = body["summary"]
        # omzet = 10 x 100 = 1000; HPP = 10 x 40 = 400; laba = 600; margin 60%.
        self.assertEqual(summary["total_sales"], 1000.0)
        self.assertEqual(summary["total_cogs"], 400.0)
        self.assertEqual(summary["total_gross_profit"], 600.0)
        self.assertEqual(summary["gross_margin_pct"], 60.0)
        self.assertEqual(summary["order_count"], 1)
        self.assertEqual(summary["line_count"], 1)
        self.assertEqual(summary["qty_total"], 10)
        self.assertEqual(summary["rows_with_missing_cost"], 0)
        self.assertEqual(summary["currency"], "IDR")

        self.assertEqual(len(body["rows"]), 1)
        row = body["rows"][0]
        self.assertEqual(set(row.keys()), ROW_BASE_KEYS | {"period"})
        self.assertEqual(row["key"], CURRENT_MONTH)
        self.assertEqual(row["period"], CURRENT_MONTH)
        self.assertEqual(row["sales_amount"], 1000.0)
        self.assertEqual(row["cogs_amount"], 400.0)
        self.assertEqual(row["gross_profit"], 600.0)
        self.assertEqual(row["gross_margin_pct"], 60.0)
        self.assertFalse(row["has_missing_cost"])
        self.assertIsNone(row["missing_cost_reason"])

    def test_parameter_period(self):
        seed_order("SO-PREV", created_at=PREVIOUS_START, product=self.kain, qty=100, price_unit="10.00")
        seed_order("SO-CUR", created_at=CURRENT_START, product=self.kain, qty=1, price_unit="10.00")

        summary = self.get(f"period={PREVIOUS_MONTH}").json()["summary"]

        self.assertEqual(summary["total_sales"], 1000.0)
        self.assertEqual(summary["total_cogs"], 4000.0)
        self.assertEqual(summary["total_gross_profit"], -3000.0)
        self.assertEqual(summary["gross_margin_pct"], -300.0)

    def test_parameter_date_from_date_to(self):
        seed_order("SO-A", created_at=CURRENT_START, product=self.kain, qty=10, price_unit="100.00")
        seed_order("SO-B", created_at=PREVIOUS_START, product=self.kain, qty=100, price_unit="10.00")

        body = self.get(
            f"date_from={PREVIOUS_START.date().isoformat()}"
            f"&date_to={CURRENT_START.date().isoformat()}"
        ).json()

        self.assertEqual(body["summary"]["total_sales"], 2000.0)
        self.assertEqual(body["summary"]["total_cogs"], 4400.0)
        self.assertEqual(body["summary"]["order_count"], 2)

    def test_alias_from_to(self):
        seed_order("SO-A", created_at=CURRENT_START, product=self.kain, qty=10, price_unit="100.00")

        body = self.get(
            f"from={_iso_z(CURRENT_START)}&to={_iso_z(CURRENT_START + timedelta(days=1))}"
        ).json()

        self.assertEqual(body["summary"]["total_sales"], 1000.0)
        self.assertEqual(body["filters"]["from"], _iso_z(CURRENT_START))


class CogsReportFilterTests(CogsReportBase):
    """Filter customer/product/order_type + order CANCELLED."""

    def test_filter_customer(self):
        seed_order(
            "SO-A", created_at=CURRENT_START, product=self.kain,
            customer=self.customer_a, qty=10, price_unit="100.00",
        )
        seed_order(
            "SO-B", created_at=CURRENT_START, product=self.kain,
            customer=self.customer_b, qty=3, price_unit="100.00",
        )

        body = self.get(f"customer_id={self.customer_b.pk}&group_by=customer").json()

        self.assertEqual([row["label"] for row in body["rows"]], ["PT Beta"])
        self.assertEqual([row["key"] for row in body["rows"]], ["CUST-B"])
        self.assertEqual(body["summary"]["total_sales"], 300.0)
        self.assertEqual(body["summary"]["total_cogs"], 120.0)
        self.assertEqual(body["summary"]["order_count"], 1)
        self.assertEqual(body["filters"]["customer_id"], self.customer_b.pk)

    def test_filter_product(self):
        seed_order("SO-K", created_at=CURRENT_START, product=self.kain, qty=10, price_unit="100.00")
        seed_order("SO-Z", created_at=CURRENT_START, product=self.zero, qty=5, price_unit="200.00")

        body = self.get(f"product_id={self.zero.pk}").json()

        self.assertEqual(body["summary"]["total_sales"], 1000.0)
        self.assertEqual(body["summary"]["total_cogs"], 0.0)
        self.assertEqual(body["summary"]["line_count"], 1)
        self.assertEqual(body["summary"]["rows_with_missing_cost"], 1)
        self.assertEqual(body["filters"]["product_id"], self.zero.pk)

    def test_filter_order_type_case_insensitive(self):
        seed_order(
            "SO-EXP", created_at=CURRENT_START, product=self.kain,
            order_type="EXPORT", qty=4, price_unit="10.00",
        )
        seed_order(
            "SO-CUS", created_at=CURRENT_START, product=self.kain,
            order_type="CUSTOM", qty=9, price_unit="10.00",
        )

        body = self.get("order_type=custom").json()

        self.assertEqual(body["summary"]["total_sales"], 90.0)
        self.assertEqual(body["summary"]["total_cogs"], 360.0)
        self.assertEqual(body["filters"]["order_type"], "CUSTOM")

    def test_order_cancelled_dibuang(self):
        seed_order("SO-OK", created_at=CURRENT_START, product=self.kain, qty=10, price_unit="100.00")
        seed_order(
            "SO-DEL", created_at=CURRENT_START, product=self.kain,
            qty=100, price_unit="100.00", state="CANCELLED",
        )

        summary = self.get().json()["summary"]

        self.assertEqual(summary["order_count"], 1)
        self.assertEqual(summary["line_count"], 1)
        self.assertEqual(summary["total_sales"], 1000.0)
        self.assertEqual(summary["qty_total"], 10)


class CogsReportGroupTests(CogsReportBase):
    """``?group_by=period|customer|product`` — bentuk baris & urutan."""

    def test_group_by_period_dua_bulan(self):
        seed_order("SO-PREV", created_at=PREVIOUS_START, product=self.kain, qty=3, price_unit="100.00")
        seed_order("SO-CUR", created_at=CURRENT_START, product=self.kain, qty=8, price_unit="100.00")

        body = self.get(
            f"group_by=period&date_from={PREVIOUS_START.date().isoformat()}"
            f"&date_to={CURRENT_START.date().isoformat()}"
        ).json()
        rows = body["rows"]

        self.assertEqual(set(rows[0].keys()), ROW_BASE_KEYS | {"period"})
        self.assertEqual([row["key"] for row in rows], [PREVIOUS_MONTH, CURRENT_MONTH])
        self.assertEqual([row["sales_amount"] for row in rows], [300.0, 800.0])
        self.assertEqual([row["cogs_amount"] for row in rows], [120.0, 320.0])
        self.assertEqual(body["summary"]["order_count"], 2)

    def test_group_by_customer_urut_sales(self):
        seed_order(
            "SO-A", created_at=CURRENT_START, product=self.kain,
            customer=self.customer_a, qty=1, price_unit="100.00",
        )
        seed_order(
            "SO-B", created_at=CURRENT_START, product=self.kain,
            customer=self.customer_b, qty=9, price_unit="100.00",
        )

        body = self.get("group_by=customer").json()
        rows = body["rows"]

        self.assertEqual(
            set(rows[0].keys()),
            ROW_BASE_KEYS | {"customer_id", "customer_code", "customer_name"},
        )
        self.assertEqual([row["label"] for row in rows], ["PT Beta", "PT Alpha"])
        self.assertEqual([row["sales_amount"] for row in rows], [900.0, 100.0])
        self.assertEqual(rows[0]["cogs_amount"], 360.0)
        self.assertEqual(rows[1]["customer_code"], "CUST-A")

    def test_group_by_product_qty(self):
        seed_order("SO-K", created_at=CURRENT_START, product=self.kain, qty=10, price_unit="100.00")
        seed_order("SO-Z", created_at=CURRENT_START, product=self.zero, qty=2, price_unit="200.00")

        body = self.get("group_by=product").json()
        rows = body["rows"]

        self.assertEqual(
            set(rows[0].keys()),
            ROW_BASE_KEYS | {"product_id", "product_code", "product_name", "qty"},
        )
        self.assertEqual([row["key"] for row in rows], ["KAIN", "ZERO"])
        self.assertEqual(rows[0]["qty"], 10)
        self.assertEqual(rows[0]["cogs_amount"], 400.0)
        self.assertEqual(rows[1]["qty"], 2)
        self.assertEqual(rows[1]["cogs_amount"], 0.0)
        self.assertTrue(rows[1]["has_missing_cost"])

class CogsReportMissingCostTests(CogsReportBase):
    """HPP TIDAK difabrikasi: ``cost_price = 0`` / ``product`` NULL → COGS 0 + flag."""

    def test_cost_price_nol_cogs_nol_dan_flag(self):
        seed_order("SO-Z", created_at=CURRENT_START, product=self.zero, qty=5, price_unit="200.00")

        body = self.get().json()
        summary = body["summary"]
        row = body["rows"][0]

        # omzet 1000; HPP 0 (tidak difabrikasi) → laba kotor = omzet; margin 100%.
        self.assertEqual(summary["total_sales"], 1000.0)
        self.assertEqual(summary["total_cogs"], 0.0)
        self.assertEqual(summary["total_gross_profit"], 1000.0)
        self.assertEqual(summary["gross_margin_pct"], 100.0)
        self.assertEqual(summary["rows_with_missing_cost"], 1)
        self.assertTrue(row["has_missing_cost"])
        self.assertEqual(row["missing_cost_reason"], "no_cost")

    def test_product_null_sales_tetap_dan_reason_no_product(self):
        order = seed_order(
            "SO-NP", created_at=CURRENT_START, product=self.zero, qty=5, price_unit="100.00"
        )
        # Baris kedua TANPA produk (belum tersinkron) — omzet tetap dihitung, COGS tidak.
        OrderLine.objects.create(order=order, product=None, qty=4, price_unit=Decimal("25.00"))

        body = self.get().json()
        summary = body["summary"]
        row = body["rows"][0]

        # omzet = (5 x 100) + (4 x 25) = 600; HPP = 5 x 0 = 0.
        self.assertEqual(summary["total_sales"], 600.0)
        self.assertEqual(summary["total_cogs"], 0.0)
        self.assertEqual(summary["line_count"], 2)
        self.assertEqual(summary["qty_total"], 9)
        # 2 baris kehilangan HPP: satu ``cost_price=0``, satu ``product`` NULL.
        self.assertEqual(summary["rows_with_missing_cost"], 2)
        self.assertTrue(row["has_missing_cost"])
        # ``no_product`` MENANG atas ``no_cost`` (alasan lebih fundamental).
        self.assertEqual(row["missing_cost_reason"], "no_product")

    def test_sales_nol_margin_nol(self):
        # price_unit = 0 → omzet 0 → margin 0 (tanpa divide-by-zero), laba negatif.
        seed_order("SO-FREE", created_at=CURRENT_START, product=self.kain, qty=10, price_unit="0.00")

        summary = self.get().json()["summary"]

        self.assertEqual(summary["total_sales"], 0.0)
        self.assertEqual(summary["total_cogs"], 400.0)
        self.assertEqual(summary["total_gross_profit"], -400.0)
        self.assertEqual(summary["gross_margin_pct"], 0.0)


class CogsReportCacheTests(CogsReportBase):
    """Cache 300 dtk: hit = **0 query DB** + ``?_nocache=1`` (tidak baca & tidak tulis)."""

    def test_cache_hit_nol_query_dan_key_per_filter(self):
        seed_order("SO-A", created_at=CURRENT_START, product=self.kain, qty=10, price_unit="100.00")

        with CaptureQueriesContext(connection) as pertama:
            response1 = self.get()
        self.assertFalse(response1.json()["cached"])
        self.assertGreater(len(pertama), 0)

        with CaptureQueriesContext(connection) as kedua:
            response2 = self.get()
        self.assertTrue(response2.json()["cached"])
        # Cache hit -> TIDAK ada query DB sama sekali (laporan uang ini "berat").
        self.assertEqual(len(kedua), 0)
        self.assertEqual(response2.json()["rows"], response1.json()["rows"])
        self.assertEqual(response2.json()["generated_at"], response1.json()["generated_at"])

        bypass = self.get("_nocache=1").json()
        self.assertFalse(bypass["cached"])
        # `_nocache=1` tidak menulis cache -> GET biasa tetap dari entri lama.
        self.assertTrue(self.get().json()["cached"])

        # Key cache memuat filter efektif -> filter berbeda = entri berbeda.
        self.assertFalse(self.get("group_by=customer").json()["cached"])
        self.assertTrue(self.get("group_by=customer").json()["cached"])


class CogsReportValidationTests(CogsReportBase):
    """Nilai param tak dikenal → 400 dengan pesan jelas."""

    def test_param_tidak_valid_400(self):
        for query, key in (
            ("group_by=nope", "group_by"),
            ("order_type=NOPE", "order_type"),
            ("customer_id=abc", "customer_id"),
            ("product_id=0", "product_id"),
            ("period=2026-13", "period"),
            ("date_from=kemarin", "tanggal"),
        ):
            with self.subTest(query=query):
                response = self.get(query)
                self.assertEqual(response.status_code, 400)
                self.assertIn(key, response.json()["detail"])

        terbalik = self.get(
            f"date_from={CURRENT_START.date().isoformat()}"
            f"&date_to={PREVIOUS_LAST_DAY.isoformat()}"
        )
        self.assertEqual(terbalik.status_code, 400)
        self.assertIn("tidak boleh lebih besar", terbalik.json()["detail"])


class CogsReportNonBreakingTests(CogsReportBase):
    """H4.1 + H4.3 + `Product.cost_price` (H3.5) tetap hijau — endpoint read-only."""

    def test_non_breaking_h4_1_h4_3_dan_cost_price(self):
        self.assertEqual(resolve(COGS_URL).url_name, "reports_cogs")
        self.assertEqual(resolve(SALES_URL).url_name, "reports_sales")
        self.assertEqual(resolve(STOCK_URL).url_name, "reports_stock")

        penjualan = self.api.get(SALES_URL)
        self.assertEqual(penjualan.status_code, 200)
        self.assertEqual(set(penjualan.json().keys()), TOP_KEYS)

        stok = self.api.get(STOCK_URL)
        self.assertEqual(stok.status_code, 200)
        self.assertIn("summary", stok.json())

        # Read-only: laporan tidak menyentuh master harga (H3.5) / auto-fill H2.2.
        seed_order("SO-A", created_at=CURRENT_START, product=self.kain, qty=10, price_unit="100.00")
        self.get()
        kain = Product.objects.get(pk=self.kain.pk)
        self.assertEqual(kain.cost_price, Decimal("40.00"))
        self.assertEqual(kain.sale_price, Decimal("100.00"))
