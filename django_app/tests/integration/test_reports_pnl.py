"""Test laporan laba-rugi (H4.5) — ``GET /api/v1/reports/pnl/``.

Read-only DB murni: rantai PnL ``revenue (OrderLine) → cogs (Product.cost_price)
→ gross_profit → opex (JournalEntryLine expense H3.4) → net_profit``, basis
``Order.created_at`` (accrual); cache 300 dtk; ``?nocache=1`` bypass.

Cakupan: default bulan berjalan, prioritas ``?period`` > ``?date_from``/``?date_to``
> ``?from``/``?to``, ``group_by=period|quarter`` (bucket ``YYYY-MM``/``YYYY-Qn``),
formula revenue/cogs/gross, **opex jurnal** (CONFIRMED|SENT|DONE, akun
expense-family), exclude order ``CANCELLED``, margin 0 saat revenue 0, opex
**unavailable** (chart of accounts belum ada) → ``opex = null`` + net = gross,
cache hit = **0 query**, 400, dan **non-breaking** H4.1–H4.4 + H3.4.

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_reports_pnl.py -q
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

from apps_industry.garment.models import (
    JournalEntry,
    JournalEntryLine,
    Order,
    OrderLine,
)
from core.auth.models import User
from master.models import Account, Journal, Partner, Product

PNL_URL = "/api/v1/reports/pnl/"
SALES_URL = "/api/v1/reports/sales/"
COGS_URL = "/api/v1/reports/cogs/"
STOCK_URL = "/api/v1/reports/stock/"
JOURNAL_ENTRIES_URL = "/api/v1/finance/journal-entries/"

TOP_KEYS = {"rows", "summary", "group_by", "filters", "period", "generated_at", "cached"}
SUMMARY_KEYS = {
    "revenue",
    "cogs",
    "gross_profit",
    "gross_margin_pct",
    "opex",
    "net_profit",
    "net_margin_pct",
    "opex_source",
    "opex_account_types",
    "opex_states",
    "order_count",
    "line_count",
    "rows_with_missing_cost",
    "currency",
}
ROW_KEYS = {
    "key",
    "label",
    "revenue",
    "cogs",
    "gross_profit",
    "gross_margin_pct",
    "opex",
    "net_profit",
    "net_margin_pct",
    "order_count",
    "line_count",
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


def _quarter_label(moment) -> str:
    """Label kuartal lokal ``YYYY-Qn`` (samakan dengan backend)."""
    local = timezone.localtime(moment)
    return f"{local.year}-Q{(local.month - 1) // 3 + 1}"


def seed_order(
    code: str,
    *,
    created_at,
    product,
    qty: int = 10,
    price_unit: str = "100.00",
    state: str = "CONFIRMED",
):
    """Order + satu `OrderLine`; ``created_at`` di-set ulang (auto_now_add)."""
    order = Order.objects.create(code=code, state=state)
    Order.objects.filter(pk=order.pk).update(created_at=created_at)
    OrderLine.objects.create(
        order=order, product=product, qty=qty, price_unit=Decimal(price_unit)
    )
    return order


class PnlReportBase(TestCase):
    """Fixture: user + produk ber-cost & cost 0 + jurnal general + 3 akun."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="rep-pnl", password="x")
        cls.customer = Partner.objects.create(code="CUST-PNL", name="PT PnL")
        cls.kain = Product.objects.create(
            code="KAIN", name="Kain", cost_price=Decimal("40.00"), sale_price=Decimal("100.00")
        )
        cls.zero = Product.objects.create(
            code="ZERO", name="Nol Cost", cost_price=Decimal("0.00"), sale_price=Decimal("200.00")
        )
        cls.journal = Journal.objects.create(
            code="GEN", name="Jurnal Umum", journal_type="general"
        )
        cls.acc_expense = Account.objects.create(
            code="6000", name="Beban Operasional", account_type="expense"
        )
        cls.acc_dep = Account.objects.create(
            code="6100", name="Penyusutan", account_type="expense_depreciation"
        )
        cls.acc_cash = Account.objects.create(
            code="1100", name="Kas", account_type="asset_cash"
        )

    def setUp(self):
        cache.clear()
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def get(self, query: str = ""):
        """GET laporan laba-rugi (query string tanpa tanda tanya)."""
        url = f"{PNL_URL}?{query}" if query else PNL_URL
        return self.api.get(url)

    def seed_entry(self, code: str, *, entry_date, state: str = "SENT"):
        """`JournalEntry` pada journal general (H3.4)."""
        return JournalEntry.objects.create(
            code=code, journal=self.journal, entry_date=entry_date, state=state
        )

    def seed_line(self, entry, account, *, debit: str = "0.00", credit: str = "0.00"):
        """Satu baris jurnal (XOR debit/kredit, pola H3.4)."""
        return JournalEntryLine.objects.create(
            entry=entry,
            account=account,
            name="uji",
            debit=Decimal(debit),
            credit=Decimal(credit),
        )

class PnlReportAuthTests(TestCase):
    """Izin endpoint: anonim 403 (IsAuthenticated)."""

    def test_anonim_403(self):
        self.assertEqual(APIClient().get(PNL_URL).status_code, 403)


class PnlReportRangeTests(PnlReportBase):
    """Default bulan berjalan + prioritas period > date_from/date_to > from/to."""

    def test_default_bulan_berjalan(self):
        seed_order("SO-CUR", created_at=CURRENT_START, product=self.kain, qty=10, price_unit="100.00")
        seed_order("SO-PREV", created_at=PREVIOUS_START, product=self.kain, qty=100, price_unit="10.00")
        entry = self.seed_entry("JE-1", entry_date=CURRENT_START.date())
        self.seed_line(entry, self.acc_expense, debit="150.00")

        response = self.get()
        body = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(body.keys()), TOP_KEYS)
        self.assertEqual(set(body["summary"].keys()), SUMMARY_KEYS)
        self.assertEqual(body["group_by"], "period")
        self.assertFalse(body["cached"])

        summary = body["summary"]
        # revenue 10 x 100 = 1000; cogs 10 x 40 = 400; gross 600; opex 150; net 450.
        self.assertEqual(summary["revenue"], 1000.0)
        self.assertEqual(summary["cogs"], 400.0)
        self.assertEqual(summary["gross_profit"], 600.0)
        self.assertEqual(summary["gross_margin_pct"], 60.0)
        self.assertEqual(summary["opex"], 150.0)
        self.assertEqual(summary["net_profit"], 450.0)
        self.assertEqual(summary["net_margin_pct"], 45.0)
        self.assertEqual(summary["opex_source"], "journal_entry")
        self.assertEqual(
            summary["opex_account_types"],
            ["expense", "expense_depreciation", "expense_direct_cost"],
        )
        self.assertEqual(summary["opex_states"], ["CONFIRMED", "SENT", "DONE"])
        self.assertEqual(summary["order_count"], 1)
        self.assertEqual(summary["line_count"], 1)
        self.assertEqual(summary["rows_with_missing_cost"], 0)
        self.assertEqual(summary["currency"], "IDR")

        self.assertEqual(len(body["rows"]), 1)
        row = body["rows"][0]
        self.assertEqual(set(row.keys()), ROW_KEYS | {"period"})
        self.assertEqual(row["key"], CURRENT_MONTH)
        self.assertEqual(row["revenue"], 1000.0)
        self.assertEqual(row["opex"], 150.0)
        self.assertEqual(row["net_profit"], 450.0)
        self.assertFalse(row["has_missing_cost"])
        self.assertIsNone(row["missing_cost_reason"])

    def test_parameter_period(self):
        seed_order("SO-PREV", created_at=PREVIOUS_START, product=self.kain, qty=100, price_unit="10.00")
        seed_order("SO-CUR", created_at=CURRENT_START, product=self.kain, qty=1, price_unit="10.00")

        summary = self.get(f"period={PREVIOUS_MONTH}").json()["summary"]

        self.assertEqual(summary["revenue"], 1000.0)
        self.assertEqual(summary["cogs"], 4000.0)
        self.assertEqual(summary["gross_profit"], -3000.0)
        # Chart of accounts ADA tapi tak ada jurnal di bulan itu -> opex 0.0 (bukan null).
        self.assertEqual(summary["opex"], 0.0)
        self.assertEqual(summary["net_profit"], -3000.0)
        self.assertEqual(summary["gross_margin_pct"], -300.0)

    def test_parameter_date_from_date_to(self):
        seed_order("SO-A", created_at=CURRENT_START, product=self.kain, qty=10, price_unit="100.00")
        seed_order("SO-B", created_at=PREVIOUS_START, product=self.kain, qty=100, price_unit="10.00")
        entry = self.seed_entry("JE-1", entry_date=CURRENT_START.date())
        self.seed_line(entry, self.acc_expense, debit="150.00")

        body = self.get(
            f"date_from={PREVIOUS_START.date().isoformat()}"
            f"&date_to={CURRENT_START.date().isoformat()}"
        ).json()

        self.assertEqual(body["summary"]["revenue"], 2000.0)
        self.assertEqual(body["summary"]["cogs"], 4400.0)
        self.assertEqual(body["summary"]["opex"], 150.0)
        self.assertEqual(body["summary"]["order_count"], 2)

    def test_alias_from_to(self):
        seed_order("SO-A", created_at=CURRENT_START, product=self.kain, qty=10, price_unit="100.00")
        entry = self.seed_entry("JE-1", entry_date=CURRENT_START.date())
        self.seed_line(entry, self.acc_expense, debit="150.00")

        body = self.get(
            f"from={_iso_z(CURRENT_START)}&to={_iso_z(CURRENT_START + timedelta(days=1))}"
        ).json()

        self.assertEqual(body["summary"]["revenue"], 1000.0)
        self.assertEqual(body["summary"]["opex"], 150.0)
        self.assertEqual(body["filters"]["from"], _iso_z(CURRENT_START))

    def test_param_tidak_valid_400(self):
        for query, key in (
            ("group_by=nope", "group_by"),
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


class PnlReportGroupTests(PnlReportBase):
    """``?group_by=period|quarter`` — bucket & urutan."""

    def test_group_by_period_dua_bulan(self):
        seed_order("SO-PREV", created_at=PREVIOUS_START, product=self.kain, qty=3, price_unit="100.00")
        seed_order("SO-CUR", created_at=CURRENT_START, product=self.kain, qty=8, price_unit="100.00")

        body = self.get(
            f"group_by=period&date_from={PREVIOUS_START.date().isoformat()}"
            f"&date_to={CURRENT_START.date().isoformat()}"
        ).json()
        rows = body["rows"]

        self.assertEqual(set(rows[0].keys()), ROW_KEYS | {"period"})
        self.assertEqual([row["key"] for row in rows], [PREVIOUS_MONTH, CURRENT_MONTH])
        self.assertEqual([row["revenue"] for row in rows], [300.0, 800.0])
        self.assertEqual([row["cogs"] for row in rows], [120.0, 320.0])
        self.assertEqual(body["summary"]["revenue"], 1100.0)

    def test_group_by_quarter(self):
        seed_order("SO-CUR", created_at=CURRENT_START, product=self.kain, qty=10, price_unit="100.00")
        entry = self.seed_entry("JE-1", entry_date=CURRENT_START.date())
        self.seed_line(entry, self.acc_expense, debit="150.00")

        body = self.get("group_by=quarter").json()
        rows = body["rows"]

        self.assertEqual(body["group_by"], "quarter")
        self.assertEqual(set(rows[0].keys()), ROW_KEYS | {"quarter"})
        self.assertEqual([row["key"] for row in rows], [_quarter_label(CURRENT_START)])
        self.assertEqual(rows[0]["quarter"], _quarter_label(CURRENT_START))
        self.assertRegex(rows[0]["key"], r"^\d{4}-Q[1-4]$")
        self.assertEqual(rows[0]["revenue"], 1000.0)
        self.assertEqual(rows[0]["opex"], 150.0)

    def test_bucket_opex_only_tetap_muncul(self):
        # Bulan sebelumnya: ADA beban, TANPA penjualan -> baris tetap muncul (opex-only).
        entry = self.seed_entry("JE-PREV", entry_date=PREVIOUS_START.date())
        self.seed_line(entry, self.acc_expense, debit="99.00")
        seed_order("SO-CUR", created_at=CURRENT_START, product=self.kain, qty=10, price_unit="100.00")

        body = self.get(
            f"group_by=period&date_from={PREVIOUS_START.date().isoformat()}"
            f"&date_to={CURRENT_START.date().isoformat()}"
        ).json()
        rows = body["rows"]

        self.assertEqual([row["key"] for row in rows], [PREVIOUS_MONTH, CURRENT_MONTH])
        self.assertEqual(rows[0]["revenue"], 0.0)
        self.assertEqual(rows[0]["cogs"], 0.0)
        self.assertEqual(rows[0]["opex"], 99.0)
        self.assertEqual(rows[0]["net_profit"], -99.0)
        # Sigma baris == summary.
        self.assertEqual(sum(row["net_profit"] for row in rows), body["summary"]["net_profit"])


class PnlReportFormulaTests(PnlReportBase):
    """Formula: revenue/cogs/gross + opex jurnal + net + exclude CANCELLED + flag."""

    def test_revenue_cogs_gross_profit(self):
        seed_order("SO-A", created_at=CURRENT_START, product=self.kain, qty=3, price_unit="50.00")

        summary = self.get().json()["summary"]

        self.assertEqual(summary["revenue"], 150.0)
        self.assertEqual(summary["cogs"], 120.0)
        self.assertEqual(summary["gross_profit"], 30.0)
        self.assertEqual(summary["gross_margin_pct"], 20.0)
        self.assertEqual(summary["opex"], 0.0)
        self.assertEqual(summary["net_profit"], 30.0)

    def test_opex_jurnal_kredit_mengurangi(self):
        seed_order("SO-A", created_at=CURRENT_START, product=self.kain, qty=10, price_unit="100.00")
        entry = self.seed_entry("JE-1", entry_date=CURRENT_START.date())
        self.seed_line(entry, self.acc_expense, debit="100.00")
        self.seed_line(entry, self.acc_dep, debit="50.00")
        self.seed_line(entry, self.acc_expense, credit="20.00")

        summary = self.get().json()["summary"]

        # opex = (100 + 50) - 20 = 130 -> net = 600 - 130 = 470.
        self.assertEqual(summary["opex"], 130.0)
        self.assertEqual(summary["net_profit"], 470.0)

    def test_opex_exclude_non_expense_dan_state_bukan_final(self):
        seed_order("SO-A", created_at=CURRENT_START, product=self.kain, qty=10, price_unit="100.00")
        # DRAFT & CANCELLED tidak dihitung; akun non-expense juga tidak.
        draft = self.seed_entry("JE-DRAFT", entry_date=CURRENT_START.date(), state="DRAFT")
        self.seed_line(draft, self.acc_expense, debit="500.00")
        cancel = self.seed_entry("JE-CANCEL", entry_date=CURRENT_START.date(), state="CANCELLED")
        self.seed_line(cancel, self.acc_expense, debit="300.00")
        cash = self.seed_entry("JE-CASH", entry_date=CURRENT_START.date())
        self.seed_line(cash, self.acc_cash, debit="999.00")
        # CONFIRMED DIHITUNG (keputusan H4.5: niat final akuntan, hanya lag push).
        confirmed = self.seed_entry("JE-CONF", entry_date=CURRENT_START.date(), state="CONFIRMED")
        self.seed_line(confirmed, self.acc_expense, debit="25.00")

        summary = self.get().json()["summary"]

        self.assertEqual(summary["opex"], 25.0)
        self.assertEqual(summary["net_profit"], 575.0)

    def test_order_cancelled_dibuang(self):
        seed_order("SO-OK", created_at=CURRENT_START, product=self.kain, qty=10, price_unit="100.00")
        seed_order(
            "SO-DEL", created_at=CURRENT_START, product=self.kain,
            qty=100, price_unit="100.00", state="CANCELLED",
        )

        summary = self.get().json()["summary"]

        self.assertEqual(summary["order_count"], 1)
        self.assertEqual(summary["revenue"], 1000.0)
        self.assertEqual(summary["line_count"], 1)

    def test_revenue_nol_margin_nol(self):
        seed_order("SO-FREE", created_at=CURRENT_START, product=self.kain, qty=10, price_unit="0.00")

        summary = self.get().json()["summary"]

        self.assertEqual(summary["revenue"], 0.0)
        self.assertEqual(summary["cogs"], 400.0)
        self.assertEqual(summary["gross_profit"], -400.0)
        self.assertEqual(summary["gross_margin_pct"], 0.0)
        self.assertEqual(summary["net_margin_pct"], 0.0)

    def test_flag_missing_cost_tetap_ada(self):
        seed_order("SO-Z", created_at=CURRENT_START, product=self.zero, qty=5, price_unit="200.00")

        body = self.get().json()

        self.assertEqual(body["summary"]["revenue"], 1000.0)
        self.assertEqual(body["summary"]["cogs"], 0.0)
        self.assertEqual(body["summary"]["rows_with_missing_cost"], 1)
        self.assertTrue(body["rows"][0]["has_missing_cost"])
        self.assertEqual(body["rows"][0]["missing_cost_reason"], "no_cost")

class PnlReportOpexUnavailableTests(TestCase):
    """Chart of accounts belum punya akun expense → opex unavailable (bukan 0 palsu)."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="rep-pnl-noopex", password="x")
        cls.kain = Product.objects.create(
            code="KAIN2", name="Kain 2", cost_price=Decimal("40.00")
        )
        # HANYA akun non-expense -> `_pnl_opex_available()` False.
        Account.objects.create(code="1100X", name="Kas 2", account_type="asset_cash")

    def setUp(self):
        cache.clear()
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def test_opex_unavailable_net_sama_dengan_gross(self):
        seed_order("SO-A", created_at=CURRENT_START, product=self.kain, qty=10, price_unit="100.00")

        with self.assertLogs("integrations.erp_sync.monitoring", level="WARNING"):
            response = self.api.get(PNL_URL)

        body = response.json()
        summary = body["summary"]

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(summary["opex"])
        self.assertEqual(summary["opex_source"], "unavailable")
        self.assertEqual(summary["gross_profit"], 600.0)
        self.assertEqual(summary["net_profit"], 600.0)
        self.assertEqual(summary["net_margin_pct"], summary["gross_margin_pct"])
        self.assertIsNone(body["rows"][0]["opex"])
        self.assertEqual(body["rows"][0]["net_profit"], 600.0)


class PnlReportCacheTests(PnlReportBase):
    """Cache 300 dtk: hit = **0 query DB** + ``?_nocache=1`` (tidak baca & tidak tulis)."""

    def test_cache_hit_nol_query_dan_key_per_filter(self):
        seed_order("SO-A", created_at=CURRENT_START, product=self.kain, qty=10, price_unit="100.00")
        entry = self.seed_entry("JE-1", entry_date=CURRENT_START.date())
        self.seed_line(entry, self.acc_expense, debit="150.00")

        with CaptureQueriesContext(connection) as pertama:
            response1 = self.get()
        self.assertFalse(response1.json()["cached"])
        self.assertGreater(len(pertama), 0)

        with CaptureQueriesContext(connection) as kedua:
            response2 = self.get()
        self.assertTrue(response2.json()["cached"])
        # Cache hit -> TIDAK ada query DB sama sekali.
        self.assertEqual(len(kedua), 0)
        self.assertEqual(response2.json()["rows"], response1.json()["rows"])
        self.assertEqual(response2.json()["generated_at"], response1.json()["generated_at"])

        bypass = self.get("_nocache=1").json()
        self.assertFalse(bypass["cached"])
        # `_nocache=1` tidak menulis cache -> GET biasa tetap dari entri lama.
        self.assertTrue(self.get().json()["cached"])

        # Key cache memuat filter efektif -> filter berbeda = entri berbeda.
        self.assertFalse(self.get("group_by=quarter").json()["cached"])
        self.assertTrue(self.get("group_by=quarter").json()["cached"])


class PnlReportNonBreakingTests(PnlReportBase):
    """H4.1–H4.4 + H3.4 (`/finance/journal-entries/`) tetap hijau & route baru ada."""

    def test_non_breaking(self):
        self.assertEqual(resolve(PNL_URL).url_name, "reports_pnl")
        self.assertEqual(resolve(SALES_URL).url_name, "reports_sales")
        self.assertEqual(resolve(COGS_URL).url_name, "reports_cogs")
        self.assertEqual(resolve(STOCK_URL).url_name, "reports_stock")
        self.assertEqual(resolve(JOURNAL_ENTRIES_URL).url_name, "journal_entries")

        for url in (SALES_URL, COGS_URL, STOCK_URL):
            with self.subTest(url=url):
                response = self.api.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertIn("summary", response.json())

        jurnal = self.api.get(JOURNAL_ENTRIES_URL)
        self.assertEqual(jurnal.status_code, 200)
        self.assertIsInstance(jurnal.json(), dict)
