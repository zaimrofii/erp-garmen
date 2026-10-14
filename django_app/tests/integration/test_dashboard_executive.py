"""Test dashboard eksekutif (H4.7) — ``GET /api/v1/dashboard/executive/``.

**Orkestrasi** read-only: seluruh section dihitung dari helper internal H4.1–H4.6
(tanpa memanggil view HTTP, tanpa menyalin rumus). Cakupan: default bulan berjalan,
``?period`` (+alias rentang via `_sales_range`), 400, tiap section (sales/purchases/
stock/cogs/pnl/production), **budget ≤ 15 query DB**, alert (opex unavailable /
produk tanpa odoo_id / baris tanpa cost_price / stok tak terbaca), **fail-safe
partial** per-section, cache 300 dtk (hit = 0 query) + ``?_nocache=1``, dan
**non-breaking** B2 + H4.1–H4.6.

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_dashboard_executive.py -q
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import resolve
from django.utils import timezone
from rest_framework.test import APIClient

from apps_industry.garment.models import (
    Bundle,
    BundleEvent,
    JournalEntry,
    JournalEntryLine,
    Order,
    OrderLine,
    PurchaseOrder,
    PurchaseOrderLine,
    ScrapAccumulator,
)
from apps_industry.garment.tests.factories import (
    make_line,
    make_order,
    make_order_line,
    make_product,
    make_work_center,
)
from core.auth.models import User
from master.models import Account, Journal, Partner, Product

EXEC_URL = "/api/v1/dashboard/executive/"
SUMMARY_URL = "/api/v1/dashboard/summary/"
SALES_URL = "/api/v1/reports/sales/"
COGS_URL = "/api/v1/reports/cogs/"
PNL_URL = "/api/v1/reports/pnl/"
PRODUCTION_URL = "/api/v1/reports/production/"
STOCK_URL = "/api/v1/reports/stock/"

TOP_KEYS = {
    "period",
    "filters",
    "sales",
    "purchases",
    "stock",
    "cogs",
    "pnl",
    "production",
    "alerts",
    "generated_at",
    "cached",
}
SALES_KEYS = {"total_amount", "count_orders", "count_lines"}
PURCHASES_KEYS = {"total_amount", "count_purchases", "count_lines"}
STOCK_KEYS = {"total_qty", "product_count", "location_count", "unmapped_product_count"}
COGS_KEYS = {"total_cogs", "gross_profit", "gross_margin_pct", "rows_with_missing_cost"}
PNL_KEYS = {
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
}
PRODUCTION_KEYS = {
    "output_pcs",
    "scrap_pcs",
    "scrap_pct",
    "rework_pcs",
    "end_loss_pcs",
    "avg_efficiency_pct",
    "otd_pct",
    "total_bundles",
    "total_work_orders",
}

#: Budget query DB dashboard eksekutif (keputusan H4.7 — diuji eksplisit).
EXEC_QUERY_BUDGET = 15

#: Anchor waktu: bulan berjalan & bulan sebelumnya (jam 10:00 lokal, tz-aware).
_now = timezone.localtime(timezone.now())
CURRENT_START = _now.replace(day=1, hour=10, minute=0, second=0, microsecond=0)
PREVIOUS_START = (CURRENT_START - timedelta(days=1)).replace(day=1)
CURRENT_MONTH = CURRENT_START.strftime("%Y-%m")
PREVIOUS_MONTH = PREVIOUS_START.strftime("%Y-%m")
CURRENT_FIRST_DAY = CURRENT_START.date()


def _iso_z(moment) -> str:
    """ISO-8601 UTC berakhiran ``Z`` — ``+`` mentah di query string jadi spasi."""
    return moment.astimezone(dt_timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _mock_transport(locations, quants):
    """Transport mock H4.3 (enumerasi lokasi internal + quants)."""
    transport = MagicMock()
    transport.fetch_internal_locations.return_value = locations
    transport.fetch_stock_quants.return_value = quants
    return transport


def _patch_transport(transport):
    return patch(
        "integrations.erp_sync.monitoring.get_transport", return_value=transport
    )


class ExecutiveDashboardBase(TestCase):
    """Fixture: user + produk (cost 40 / cost 0) + customer + 1 WC + 1 line + Order.

    TANPA akun expense → kondisi default ``opex_source = 'unavailable'`` (H4.7
    menguji alert-nya); test yang butuh opex terisi membuat akun sendiri.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="rep-exec", password="x")
        cls.product = make_product(code="PRD-EXEC", name="Kaos Eksekutif")
        Product.objects.filter(pk=cls.product.pk).update(cost_price=Decimal("40.00"))
        cls.product.refresh_from_db()
        cls.zero = Product.objects.create(
            code="PRD-ZERO-EXEC", name="Nol Cost Eksekutif", cost_price=Decimal("0.00")
        )
        cls.customer = Partner.objects.create(code="CUST-EXEC", name="PT Eksekutif")
        cls.vendor = Partner.objects.create(code="SUP-EXEC", name="PT Vendor Eksekutif")
        cls.wc = make_work_center(code="WC-EXEC", config={"target_per_day": 10})
        cls.line = make_line(code="LINE-EXEC", work_centers=[cls.wc])
        cls.order = make_order(code="SO-EXEC", deadline=CURRENT_START + timedelta(days=5))
        # Order baseline sengaja di BULAN SEBELUMNYA (harga 0): fixture tidak boleh
        # mencemari agregat bulan berjalan. `cls.ol` tetap dipakai test produksi
        # (WorkOrder/OTD memakai deadline order, bukan `Order.created_at`).
        Order.objects.filter(pk=cls.order.pk).update(created_at=PREVIOUS_START)
        cls.ol = make_order_line(
            order=cls.order, product=cls.product, qty=10, price_unit=Decimal("0.00")
        )

    def setUp(self):
        cache.clear()
        # Transport default = Odoo `kosong` (tanpa lokasi internal): section stok
        # deterministik `null` + alert, TIDAK bergantung ketersediaan Odoo nyata
        # (test yang menguji stok terisi menimpa patch ini di dalam test).
        patcher = _patch_transport(_mock_transport([], []))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def get(self, query: str = ""):
        """GET dashboard eksekutif (query string tanpa tanda tanya)."""
        url = f"{EXEC_URL}?{query}" if query else EXEC_URL
        return self.api.get(url)

    def seed_order(
        self, code, *, created_at, product=None, qty=10, price_unit="100.00", state="CONFIRMED"
    ):
        """Order + satu OrderLine; ``created_at`` di-set ulang (auto_now_add)."""
        order = Order.objects.create(code=code, customer=self.customer, state=state)
        Order.objects.filter(pk=order.pk).update(created_at=created_at)
        OrderLine.objects.create(
            order=order,
            product=product if product is not None else self.product,
            qty=qty,
            price_unit=Decimal(price_unit),
        )
        return order

    def seed_po(self, code, *, created_at, qty=5, price_unit="20000.00", state="CONFIRMED"):
        """PurchaseOrder + satu baris (basis periode = ``created_at``)."""
        po = PurchaseOrder.objects.create(code=code, vendor=self.vendor, state=state)
        PurchaseOrder.objects.filter(pk=po.pk).update(created_at=created_at)
        PurchaseOrderLine.objects.create(
            po=po, product=self.product, qty=Decimal(qty), price_unit=Decimal(price_unit)
        )
        return po

    def seed_bundle(self, code, *, work_order, qty_done=5, state="DONE", finish_at=None, start_at=None):
        """Bundle (+ event START/FINISH dengan ``ts`` yang dikontrol)."""
        bundle = Bundle.objects.create(
            code=code,
            work_order=work_order,
            qty=qty_done,
            qty_done=qty_done,
            state=state,
            current_work_center=self.wc,
            production_line=self.line,
        )
        for event_type, moment in (("BUNDLE_START", start_at), ("BUNDLE_FINISH", finish_at)):
            if moment is None:
                continue
            event = BundleEvent.objects.create(bundle=bundle, event_type=event_type)
            BundleEvent.objects.filter(pk=event.pk).update(ts=moment)
        return bundle

    def seed_scrap(self, *, at, qty=0, rework=0, end_loss=0):
        """ScrapAccumulator (WC fixture) dengan ``created_at`` yang dikontrol."""
        scrap = ScrapAccumulator.objects.create(
            work_center=self.wc, qty=qty, rework_qty=rework, end_loss_qty=end_loss
        )
        ScrapAccumulator.objects.filter(pk=scrap.pk).update(created_at=at)
        return scrap

class ExecutiveDashboardAuthTests(TestCase):
    """Izin endpoint: anonim 403 (IsAuthenticated)."""

    def test_anonim_403(self):
        self.assertEqual(APIClient().get(EXEC_URL).status_code, 403)


class ExecutiveDashboardShapeTests(ExecutiveDashboardBase):
    """Default bulan berjalan: bentuk lengkap + setiap section terisi benar."""

    def test_default_bulan_berjalan(self):
        self.seed_order("SO-CUR", created_at=CURRENT_START, qty=10, price_unit="100.00")
        self.seed_order("SO-PREV", created_at=PREVIOUS_START, qty=7, price_unit="100.00")

        response = self.get()
        body = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(body.keys()), TOP_KEYS)
        self.assertFalse(body["cached"])
        self.assertEqual(body["filters"]["resolved_from"], body["period"]["from"])
        self.assertIsNone(body["filters"]["period"])

        self.assertEqual(set(body["sales"].keys()), SALES_KEYS)
        self.assertEqual(body["sales"]["total_amount"], 1000.0)
        self.assertEqual(body["sales"]["count_orders"], 1)
        self.assertEqual(body["sales"]["count_lines"], 1)

        self.assertEqual(set(body["purchases"].keys()), PURCHASES_KEYS)
        self.assertEqual(body["purchases"]["total_amount"], 0.0)
        self.assertEqual(body["purchases"]["count_purchases"], 0)

        self.assertEqual(set(body["cogs"].keys()), COGS_KEYS)
        self.assertEqual(body["cogs"]["total_cogs"], 400.0)
        self.assertEqual(body["cogs"]["gross_profit"], 600.0)
        self.assertEqual(body["cogs"]["gross_margin_pct"], 60.0)
        self.assertEqual(body["cogs"]["rows_with_missing_cost"], 0)

        self.assertEqual(set(body["pnl"].keys()), PNL_KEYS)
        self.assertEqual(body["pnl"]["revenue"], 1000.0)
        self.assertEqual(body["pnl"]["cogs"], 400.0)
        self.assertEqual(body["pnl"]["opex"], None)
        self.assertEqual(body["pnl"]["net_profit"], 600.0)
        self.assertEqual(body["pnl"]["net_margin_pct"], 60.0)
        self.assertEqual(body["pnl"]["opex_source"], "unavailable")
        self.assertEqual(
            body["pnl"]["opex_account_types"],
            ["expense", "expense_depreciation", "expense_direct_cost"],
        )

        self.assertEqual(set(body["production"].keys()), PRODUCTION_KEYS)
        self.assertEqual(body["production"]["output_pcs"], 0)

        # Tanpa mock Odoo: lokasi internal kosong -> section stok `null` + alert.
        self.assertIsNone(body["stock"])
        self.assertIsInstance(body["alerts"], list)
        self.assertIn("Stok tidak terbaca dari Odoo", body["alerts"])
        self.assertIn("Opex unavailable: chart of accounts belum di-pull", body["alerts"])

    def test_parameter_period_dan_alias_rentang(self):
        self.seed_order("SO-CUR", created_at=CURRENT_START, qty=10, price_unit="100.00")
        self.seed_order("SO-PREV", created_at=PREVIOUS_START, qty=5, price_unit="100.00")

        prev = self.get(f"period={PREVIOUS_MONTH}").json()
        self.assertEqual(prev["filters"]["period"], PREVIOUS_MONTH)
        self.assertEqual(prev["sales"]["total_amount"], 500.0)

        cache.clear()
        harian = self.get(
            f"date_from={CURRENT_FIRST_DAY.isoformat()}"
            f"&date_to={CURRENT_FIRST_DAY.isoformat()}"
        ).json()
        self.assertEqual(harian["sales"]["total_amount"], 1000.0)

        cache.clear()
        alias = self.get(
            f"from={_iso_z(CURRENT_START)}&to={_iso_z(CURRENT_START + timedelta(days=1))}"
        ).json()
        self.assertEqual(alias["sales"]["total_amount"], 1000.0)

    def test_period_invalid_400(self):
        response = self.get("period=2026-13")

        self.assertEqual(response.status_code, 400)
        self.assertIn("period", response.json()["detail"])

    def test_section_sales_dan_purchases(self):
        self.seed_order("SO-A", created_at=CURRENT_START, qty=5, price_unit="100.00")
        self.seed_order("SO-B", created_at=CURRENT_START, qty=10, price_unit="100.00")
        self.seed_po("PO-A", created_at=CURRENT_START, qty=5, price_unit="20000.00")
        self.seed_po("PO-DEL", created_at=CURRENT_START, qty=100, price_unit="1000.00", state="CANCELLED")

        body = self.get().json()

        self.assertEqual(body["sales"]["total_amount"], 1500.0)
        self.assertEqual(body["sales"]["count_orders"], 2)
        self.assertEqual(body["sales"]["count_lines"], 2)
        # PO CANCELLED dibuang (reuse H4.2).
        self.assertEqual(body["purchases"]["total_amount"], 100000.0)
        self.assertEqual(body["purchases"]["count_purchases"], 1)
        self.assertEqual(body["purchases"]["count_lines"], 1)

    def test_section_stock_dengan_mock_odoo(self):
        counted = Product.objects.create(
            code="PRD-ODOO-EXEC", name="Produk Odoo", cost_price=Decimal("10.00"), odoo_id=101
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
            body = self.get().json()

        self.assertEqual(set(body["stock"].keys()), STOCK_KEYS)
        self.assertEqual(body["stock"]["total_qty"], 5.0)
        self.assertEqual(body["stock"]["product_count"], 1)
        self.assertEqual(body["stock"]["location_count"], 1)
        self.assertEqual(body["stock"]["unmapped_product_count"], 0)
        self.assertNotIn("Stok tidak terbaca dari Odoo", body["alerts"])
        self.assertEqual(counted.odoo_id, 101)

    def test_section_cogs_flag_hpp_hilang(self):
        self.seed_order("SO-Z", created_at=CURRENT_START, product=self.zero, qty=5, price_unit="200.00")

        body = self.get().json()

        self.assertEqual(body["cogs"]["total_cogs"], 0.0)
        self.assertEqual(body["cogs"]["gross_profit"], 1000.0)
        self.assertEqual(body["cogs"]["gross_margin_pct"], 100.0)
        self.assertEqual(body["cogs"]["rows_with_missing_cost"], 1)
        self.assertIn("1 baris OrderLine tanpa cost_price", body["alerts"])

class ExecutiveDashboardSectionTests(ExecutiveDashboardBase):
    """Section PnL (opex jurnal tersedia) + produksi (basis ganda H4.6)."""

    def test_section_pnl_dengan_opex_jurnal(self):
        self.seed_order("SO-PNL", created_at=CURRENT_START, qty=10, price_unit="100.00")
        journal = Journal.objects.create(code="JEX", name="Jurnal Eksekutif", journal_type="general")
        account = Account.objects.create(code="6-EX", name="Beban Eksekutif", account_type="expense")
        entry = JournalEntry.objects.create(
            code="JE-EXEC", journal=journal, entry_date=CURRENT_FIRST_DAY, state="SENT"
        )
        JournalEntryLine.objects.create(
            entry=entry, account=account, name="opex", debit=Decimal("150.00"), credit=Decimal("0.00")
        )

        body = self.get().json()

        self.assertEqual(body["pnl"]["revenue"], 1000.0)
        self.assertEqual(body["pnl"]["cogs"], 400.0)
        self.assertEqual(body["pnl"]["gross_profit"], 600.0)
        self.assertEqual(body["pnl"]["opex"], 150.0)
        self.assertEqual(body["pnl"]["net_profit"], 450.0)
        self.assertEqual(body["pnl"]["net_margin_pct"], 45.0)
        self.assertEqual(body["pnl"]["opex_source"], "journal_entry")
        self.assertEqual(body["pnl"]["opex_states"], ["CONFIRMED", "SENT", "DONE"])
        self.assertNotIn("Opex unavailable: chart of accounts belum di-pull", body["alerts"])

    def test_section_production_basis_ganda(self):
        from apps_industry.garment.models import WorkOrder

        wo = WorkOrder.objects.create(code="WO-EXEC", order_line=self.ol, state="DONE")
        self.seed_bundle(
            "BND-EXEC",
            work_order=wo,
            qty_done=8,
            state="DONE",
            finish_at=CURRENT_START + timedelta(days=2),
        )
        # Scrap memakai basis waktu `ScrapAccumulator.created_at` (basis ganda H4.6).
        self.seed_scrap(at=CURRENT_START + timedelta(days=3), qty=2, rework=1, end_loss=1)

        production = self.get().json()["production"]

        self.assertEqual(production["output_pcs"], 8)
        self.assertEqual(production["scrap_pcs"], 2)
        self.assertEqual(production["scrap_pct"], 20.0)
        self.assertEqual(production["rework_pcs"], 1)
        self.assertEqual(production["end_loss_pcs"], 1)
        self.assertEqual(production["total_bundles"], 1)
        self.assertEqual(production["total_work_orders"], 1)
        self.assertEqual(production["otd_pct"], 100.0)
        self.assertEqual(production["avg_efficiency_pct"], 0.0)


class ExecutiveDashboardAlertTests(ExecutiveDashboardBase):
    """Alert informatif (``list[str]``) — 4 sumber keputusan H4.7."""

    def test_alert_opex_unavailable(self):
        body = self.get().json()

        self.assertIsNone(body["pnl"]["opex"])
        self.assertEqual(body["pnl"]["opex_source"], "unavailable")
        self.assertEqual(body["pnl"]["net_profit"], body["pnl"]["gross_profit"])
        self.assertIn("Opex unavailable: chart of accounts belum di-pull", body["alerts"])

    def test_alert_produk_tanpa_odoo_id(self):
        mapped = Product.objects.create(
            code="PRD-MAP-EXEC", name="Terpetakan", cost_price=Decimal("10.00"), odoo_id=101
        )
        transport = _mock_transport(
            [{"id": 8, "complete_name": "WH/Stok"}],
            [
                {
                    "id": 1,
                    "product_id": [101, "KAIN"],
                    "location_id": [8, "WH/Stok"],
                    "quantity": 5.0,
                    "reserved_quantity": 0.0,
                },
                {
                    "id": 2,
                    "product_id": [999, "TANPA MASTER"],
                    "location_id": [8, "WH/Stok"],
                    "quantity": 3.0,
                    "reserved_quantity": 0.0,
                },
            ],
        )

        with _patch_transport(transport):
            body = self.get().json()

        self.assertEqual(mapped.odoo_id, 101)
        self.assertEqual(body["stock"]["total_qty"], 5.0)
        self.assertEqual(body["stock"]["unmapped_product_count"], 1)
        self.assertIn("1 produk tanpa odoo_id", body["alerts"])

    def test_alert_baris_tanpa_cost_price(self):
        self.seed_order(
            "SO-NOCOST", created_at=CURRENT_START, product=self.zero, qty=5, price_unit="200.00"
        )

        body = self.get().json()

        self.assertEqual(body["cogs"]["rows_with_missing_cost"], 1)
        self.assertIn("1 baris OrderLine tanpa cost_price", body["alerts"])
        # Alert = list[str] murni (beda dari B2 yang objek code/message/severity).
        self.assertTrue(all(isinstance(item, str) for item in body["alerts"]))

    def test_fail_safe_stock_odoo_down_section_lain_tetap(self):
        self.seed_order("SO-DOWN", created_at=CURRENT_START, qty=10, price_unit="100.00")
        transport = MagicMock()
        transport.fetch_internal_locations.side_effect = RuntimeError("odoo down")

        with _patch_transport(transport):
            response = self.get()

        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(body["stock"])
        self.assertIn("Stok tidak terbaca dari Odoo", body["alerts"])
        # Fail-safe PARTIAL: section lain tetap terisi.
        self.assertEqual(body["sales"]["total_amount"], 1000.0)
        self.assertEqual(body["cogs"]["total_cogs"], 400.0)
        self.assertEqual(body["pnl"]["revenue"], 1000.0)
        self.assertEqual(set(body["production"].keys()), PRODUCTION_KEYS)
        self.assertEqual(set(body["purchases"].keys()), PURCHASES_KEYS)

    def test_stock_null_saat_lokasi_internal_kosong(self):
        self.seed_order("SO-EMPTY", created_at=CURRENT_START, qty=10, price_unit="100.00")

        with _patch_transport(_mock_transport([], [])):
            body = self.get().json()

        self.assertIsNone(body["stock"])
        self.assertIn("Stok tidak terbaca dari Odoo", body["alerts"])
        self.assertEqual(body["sales"]["total_amount"], 1000.0)

class ExecutiveDashboardBudgetTests(ExecutiveDashboardBase):
    """Budget query + cache 300 dtk (keputusan H4.7: ≤ 15 query DB)."""

    def test_query_budget_maksimum_15(self):
        self.seed_order("SO-BUD", created_at=CURRENT_START, qty=10, price_unit="100.00")
        transport = _mock_transport([{"id": 8, "complete_name": "WH/Stok"}], [])

        with _patch_transport(transport):
            with CaptureQueriesContext(connection) as ctx:
                response = self.get()

        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(
            len(ctx),
            EXEC_QUERY_BUDGET,
            f"dashboard eksekutif memakai {len(ctx)} query DB (budget {EXEC_QUERY_BUDGET}).",
        )

    def test_cache_hit_dan_nocache(self):
        self.seed_order("SO-C", created_at=CURRENT_START, qty=10, price_unit="100.00")

        with CaptureQueriesContext(connection) as ctx_first:
            first = self.get().json()
        self.assertFalse(first["cached"])
        self.assertGreater(len(ctx_first), 0)

        # Cache hit: payload di-copy + `cached = True` -> **0 query**.
        with CaptureQueriesContext(connection) as ctx_hit:
            hit = self.get().json()
        self.assertTrue(hit["cached"])
        self.assertEqual(len(ctx_hit), 0)
        self.assertEqual(hit["sales"]["total_amount"], first["sales"]["total_amount"])
        self.assertEqual(hit["period"], first["period"])

        # `?_nocache=1` membaca data terbaru dan **tidak** menimpa cache.
        self.seed_order("SO-C2", created_at=CURRENT_START, qty=10, price_unit="100.00")
        fresh = self.get("_nocache=1").json()
        self.assertFalse(fresh["cached"])
        self.assertEqual(fresh["sales"]["total_amount"], 2000.0)

        with CaptureQueriesContext(connection) as ctx_restore:
            restored = self.get().json()
        self.assertEqual(len(ctx_restore), 0)
        self.assertEqual(restored["sales"]["total_amount"], 1000.0)

    def test_filters_echo_dan_meta(self):
        self.seed_order("SO-META", created_at=CURRENT_START, qty=10, price_unit="100.00")

        body = self.get(f"period={CURRENT_MONTH}&_nocache=1").json()

        self.assertEqual(body["filters"]["period"], CURRENT_MONTH)
        self.assertIsNone(body["filters"]["date_from"])
        self.assertIsNone(body["filters"]["to"])
        self.assertTrue(body["filters"]["nocache"])
        self.assertEqual(body["filters"]["resolved_from"], body["period"]["from"])
        self.assertEqual(body["filters"]["resolved_to"], body["period"]["to"])
        self.assertFalse(body["cached"])
        generated = datetime.fromisoformat(body["generated_at"])
        start = datetime.fromisoformat(body["period"]["from"])
        self.assertGreaterEqual(generated, start)
        self.assertEqual(start.strftime("%Y-%m"), CURRENT_MONTH)


class ExecutiveDashboardNonBreakingTests(ExecutiveDashboardBase):
    """H4.7 paralel: B2 ``/dashboard/summary/`` + H4.1–H4.6 tetap terdaftar & 200."""

    def test_non_breaking_b2_dan_h4(self):
        self.seed_order("SO-NB", created_at=CURRENT_START, qty=10, price_unit="100.00")
        routes = {
            "/api/v1/dashboard/summary/": "dashboard_summary",
            EXEC_URL: "dashboard_executive",
            SALES_URL: "reports_sales",
            "/api/v1/reports/purchases/": "reports_purchases",
            STOCK_URL: "reports_stock",
            COGS_URL: "reports_cogs",
            PNL_URL: "reports_pnl",
            PRODUCTION_URL: "reports_production",
        }
        for url, name in routes.items():
            self.assertEqual(resolve(url).url_name, name, url)

        summary = self.api.get("/api/v1/dashboard/summary/")
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(
            set(summary.json()),
            {
                "bundles",
                "wip_qty",
                "fg_qty",
                "orders",
                "scrap_qty_today",
                "alerts",
                "line_efficiency",
                "trend",
                "generated_at",
            },
        )

        for url in (
            SALES_URL,
            "/api/v1/reports/purchases/",
            STOCK_URL,
            COGS_URL,
            PNL_URL,
            PRODUCTION_URL,
        ):
            cache.clear()
            self.assertEqual(self.api.get(url).status_code, 200, url)