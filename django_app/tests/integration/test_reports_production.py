"""Test laporan produksi (H4.6) — ``GET /api/v1/reports/production/``.

Read-only DB murni: **superset** B13/B16/B18–B21 dengan **dimensi periode** —
output (FINISH `BundleEvent.ts`), scrap (`ScrapAccumulator.created_at`), efisiensi
(rumus identik B13), OTD (pola B20, order-level). Cache 300 dtk; ``?nocache=1`` bypass.

Cakupan: default bulan berjalan, prioritas ``?period`` > ``?date_from``/``?date_to``
> ``?from``/``?to``, ``group_by=period|work_center|line``, filter ``?work_center_id``/
``?line_id`` (pk MES), union bucket output ∪ scrap, formulat output/scrap_pct/efisiensi/
OTD, ``rework``/``end_loss`` terpisah, bundle ``CANCELLED`` dibuang, cache hit = **0 query**,
400, dan **non-breaking** B13/B16/B18–B21 + H2.3/H2.4 + H4.1–H4.5.

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_reports_production.py -q
"""

from __future__ import annotations

from datetime import timedelta, timezone as dt_timezone

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

PRODUCTION_URL = "/api/v1/reports/production/"
LINE_EFFICIENCY_URL = "/api/v1/reports/line-efficiency/"
LINE_EFFICIENCY_BY_WC_URL = "/api/v1/reports/line-efficiency/by-wc/"
WIP_URL = "/api/v1/reports/wip/"
WIP_BY_WC_URL = "/api/v1/reports/wip/by-wc/"
LEAD_TIME_URL = "/api/v1/reports/lead-time/"
OTD_URL = "/api/v1/reports/on-time-delivery/"
SALES_URL = "/api/v1/reports/sales/"
PNL_URL = "/api/v1/reports/pnl/"
BUNDLES_URL = "/api/v1/garmen/bundles/"

TOP_KEYS = {"rows", "summary", "group_by", "filters", "period", "generated_at", "cached"}
SUMMARY_KEYS = {
    "total_output_pcs",
    "total_scrap_pcs",
    "total_rework_pcs",
    "total_end_loss_pcs",
    "scrap_pct",
    "avg_efficiency_pct",
    "otd_pct",
    "total_bundles",
    "total_work_orders",
}
ROW_BASE_KEYS = {"key", "label", "output_pcs", "scrap_pcs", "scrap_pct", "efficiency_pct", "otd_pct"}

#: Anchor waktu: bulan berjalan & bulan sebelumnya (jam 10:00 lokal, tz-aware).
_now = timezone.localtime(timezone.now())
CURRENT_START = _now.replace(day=1, hour=10, minute=0, second=0, microsecond=0)
NEXT_DAY = CURRENT_START + timedelta(days=1)
PREVIOUS_START = (CURRENT_START - timedelta(days=1)).replace(day=1)
CURRENT_MONTH = CURRENT_START.strftime("%Y-%m")
PREVIOUS_MONTH = PREVIOUS_START.strftime("%Y-%m")
PREVIOUS_LAST_DAY = (CURRENT_START - timedelta(days=1)).date()
CURRENT_FIRST_DAY = CURRENT_START.date()


def _iso_z(moment) -> str:
    """ISO-8601 UTC berakhiran ``Z`` — ``+`` mentah di query string jadi spasi."""
    return moment.astimezone(dt_timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ProductionReportBase(TestCase):
    """Fixture: user + 2 WC (target 10/20) + 1 line + Order ber-deadline."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="rep-prod", password="x")
        cls.product = make_product(code="PRD-PROD", name="Kaos Produksi")
        cls.wc_cut = make_work_center(code="WC-CUT", config={"target_per_day": 10})
        cls.wc_sew = make_work_center(code="WC-SEW", config={"target_per_day": 20})
        cls.line_hot = make_line(code="LINE-HOT", work_centers=[cls.wc_cut, cls.wc_sew])
        # Order on-time (deadline jauh) & order terlambat (deadline lewat).
        cls.order_ok = make_order(code="SO-PROD-OK", deadline=CURRENT_START + timedelta(days=5))
        cls.order_late = make_order(code="SO-PROD-LATE", deadline=PREVIOUS_START)
        cls.ol_ok = make_order_line(order=cls.order_ok, product=cls.product, qty=10)
        cls.ol_late = make_order_line(order=cls.order_late, product=cls.product, qty=10)

    def setUp(self):
        cache.clear()
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def get(self, query: str = ""):
        """GET laporan produksi (query string tanpa tanda tanya)."""
        url = f"{PRODUCTION_URL}?{query}" if query else PRODUCTION_URL
        return self.api.get(url)

    def seed_work_order(self, code: str, *, order_line, state: str = "IN_PROGRESS"):
        """WorkOrder + OrderLine yang sudah punya Order (untuk OTD)."""
        from apps_industry.garment.models import WorkOrder

        return WorkOrder.objects.create(code=code, order_line=order_line, state=state)

    def seed_bundle(
        self,
        code: str,
        *,
        work_order,
        qty_done: int = 5,
        state: str = "DONE",
        work_center=None,
        line=None,
        start_at=None,
        finish_at=None,
    ):
        """Bundle (+ event START/FINISH dengan ``ts`` yang dikontrol)."""
        bundle = Bundle.objects.create(
            code=code,
            work_order=work_order,
            qty=qty_done,
            qty_done=qty_done,
            state=state,
            current_work_center=work_center,
            production_line=line,
        )
        for event_type, moment in (("BUNDLE_START", start_at), ("BUNDLE_FINISH", finish_at)):
            if moment is None:
                continue
            event = BundleEvent.objects.create(bundle=bundle, event_type=event_type)
            BundleEvent.objects.filter(pk=event.pk).update(ts=moment)
        return bundle

    def seed_scrap(self, *, work_center, at, qty: int = 0, rework: int = 0, end_loss: int = 0, bundle=None):
        """ScrapAccumulator dengan ``created_at`` yang dikontrol."""
        scrap = ScrapAccumulator.objects.create(
            work_center=work_center,
            bundle=bundle,
            qty=qty,
            rework_qty=rework,
            end_loss_qty=end_loss,
        )
        ScrapAccumulator.objects.filter(pk=scrap.pk).update(created_at=at)
        return scrap

class ProductionReportAuthTests(TestCase):
    """Izin endpoint: anonim 403 (IsAuthenticated)."""

    def test_anonim_403(self):
        self.assertEqual(APIClient().get(PRODUCTION_URL).status_code, 403)


class ProductionReportRangeTests(ProductionReportBase):
    """Default bulan berjalan + prioritas period > date_from/date_to > from/to."""

    def test_default_bulan_berjalan(self):
        work_order = self.seed_work_order("WO-1", order_line=self.ol_ok, state="DONE")
        self.seed_bundle(
            "BND-1", work_order=work_order, qty_done=5,
            work_center=self.wc_cut, line=self.line_hot, finish_at=CURRENT_START,
        )
        self.seed_scrap(work_center=self.wc_cut, at=CURRENT_START, qty=2, rework=1, end_loss=3)

        response = self.get()
        body = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(body.keys()), TOP_KEYS)
        self.assertEqual(set(body["summary"].keys()), SUMMARY_KEYS)
        self.assertEqual(body["group_by"], "period")
        self.assertFalse(body["cached"])
        self.assertEqual(
            body["filters"]["basis"],
            {"output": "bundle_event.ts", "efficiency": "bundle_event.ts", "otd": "bundle_event.ts", "scrap": "scrap_accumulator.created_at"},
        )

        summary = body["summary"]
        self.assertEqual(summary["total_output_pcs"], 5)
        self.assertEqual(summary["total_scrap_pcs"], 2)
        self.assertEqual(summary["total_rework_pcs"], 1)
        self.assertEqual(summary["total_end_loss_pcs"], 3)
        # scrap_pct = 2 / (5 + 2) x 100 = 28.57
        self.assertEqual(summary["scrap_pct"], 28.57)
        # Tanpa event START -> efisiensi B13 = 0.0.
        self.assertEqual(summary["avg_efficiency_pct"], 0.0)
        # WO DONE, FINISH = awal bulan <= deadline (+5 hari) -> on-time 100%.
        self.assertEqual(summary["otd_pct"], 100.0)
        self.assertEqual(summary["total_bundles"], 1)
        self.assertEqual(summary["total_work_orders"], 1)
        self.assertNotIn("currency", summary)

        self.assertEqual(len(body["rows"]), 1)
        row = body["rows"][0]
        self.assertEqual(
            set(row.keys()),
            ROW_BASE_KEYS | {"period", "bundle_count", "wo_count", "rework_pcs", "end_loss_pcs"},
        )
        self.assertEqual(row["key"], CURRENT_MONTH)
        self.assertEqual(row["period"], CURRENT_MONTH)
        self.assertEqual(row["output_pcs"], 5)
        self.assertEqual(row["scrap_pcs"], 2)
        self.assertEqual(row["bundle_count"], 1)
        self.assertEqual(row["wo_count"], 1)
        self.assertEqual(row["otd_pct"], 100.0)

    def test_parameter_period(self):
        work_order = self.seed_work_order("WO-1", order_line=self.ol_ok)
        self.seed_bundle("BND-PREV", work_order=work_order, qty_done=3, work_center=self.wc_cut, finish_at=PREVIOUS_START)
        self.seed_bundle("BND-CUR", work_order=work_order, qty_done=7, work_center=self.wc_cut, finish_at=CURRENT_START)

        body = self.get(f"period={PREVIOUS_MONTH}").json()

        self.assertEqual(body["summary"]["total_output_pcs"], 3)
        self.assertEqual(body["summary"]["total_bundles"], 1)
        self.assertEqual([row["key"] for row in body["rows"]], [PREVIOUS_MONTH])

    def test_parameter_date_from_date_to(self):
        work_order = self.seed_work_order("WO-1", order_line=self.ol_ok)
        self.seed_bundle("BND-A", work_order=work_order, qty_done=4, work_center=self.wc_cut, finish_at=CURRENT_START)
        self.seed_bundle("BND-B", work_order=work_order, qty_done=9, work_center=self.wc_cut, finish_at=PREVIOUS_START)

        body = self.get(
            f"date_from={CURRENT_FIRST_DAY.isoformat()}"
            f"&date_to={CURRENT_FIRST_DAY.isoformat()}"
        ).json()

        self.assertEqual(body["summary"]["total_output_pcs"], 4)
        self.assertEqual(body["summary"]["total_bundles"], 1)

    def test_alias_from_to(self):
        work_order = self.seed_work_order("WO-1", order_line=self.ol_ok)
        self.seed_bundle("BND-A", work_order=work_order, qty_done=6, work_center=self.wc_cut, finish_at=CURRENT_START)

        body = self.get(f"from={_iso_z(CURRENT_START)}&to={_iso_z(NEXT_DAY)}").json()

        self.assertEqual(body["summary"]["total_output_pcs"], 6)
        self.assertEqual(body["filters"]["from"], _iso_z(CURRENT_START))

    def test_param_tidak_valid_400(self):
        for query, key in (
            ("group_by=nope", "group_by"),
            ("period=2026-13", "period"),
            ("date_from=kemarin", "tanggal"),
            ("work_center_id=abc", "work_center_id"),
            ("line_id=0", "line_id"),
        ):
            with self.subTest(query=query):
                response = self.get(query)
                self.assertEqual(response.status_code, 400)
                self.assertIn(key, response.json()["detail"])

        terbalik = self.get(
            f"date_from={CURRENT_FIRST_DAY.isoformat()}"
            f"&date_to={PREVIOUS_LAST_DAY.isoformat()}"
        )
        self.assertEqual(terbalik.status_code, 400)
        self.assertIn("tidak boleh lebih besar", terbalik.json()["detail"])


class ProductionReportGroupTests(ProductionReportBase):
    """``?group_by=period|work_center|line`` — bucket, union, urutan."""

    def test_group_by_period_union_bucket(self):
        work_order = self.seed_work_order("WO-1", order_line=self.ol_ok)
        self.seed_bundle("BND-CUR", work_order=work_order, qty_done=8, work_center=self.wc_cut, finish_at=CURRENT_START)
        # Bulan sebelumnya: ADA scrap, TANPA output -> bucket tetap muncul (union).
        self.seed_scrap(work_center=self.wc_cut, at=PREVIOUS_START, qty=9)

        body = self.get(
            f"group_by=period&date_from={PREVIOUS_START.date().isoformat()}"
            f"&date_to={CURRENT_FIRST_DAY.isoformat()}"
        ).json()
        rows = body["rows"]

        self.assertEqual([row["key"] for row in rows], [PREVIOUS_MONTH, CURRENT_MONTH])
        self.assertEqual(rows[0]["output_pcs"], 0)
        self.assertEqual(rows[0]["scrap_pcs"], 9)
        self.assertEqual(rows[0]["scrap_pct"], 100.0)
        self.assertEqual(rows[1]["output_pcs"], 8)
        # Sigma baris == summary.
        self.assertEqual(sum(row["output_pcs"] for row in rows), body["summary"]["total_output_pcs"])
        self.assertEqual(sum(row["scrap_pcs"] for row in rows), body["summary"]["total_scrap_pcs"])

    def test_group_by_work_center(self):
        work_order = self.seed_work_order("WO-1", order_line=self.ol_ok)
        self.seed_bundle("BND-CUT", work_order=work_order, qty_done=5, work_center=self.wc_cut, line=self.line_hot, finish_at=CURRENT_START)
        self.seed_bundle("BND-SEW", work_order=work_order, qty_done=4, work_center=self.wc_sew, line=self.line_hot, finish_at=CURRENT_START)
        self.seed_scrap(work_center=self.wc_sew, at=CURRENT_START, qty=1)

        body = self.get("group_by=work_center").json()
        rows = body["rows"]

        self.assertEqual(body["group_by"], "work_center")
        self.assertEqual(
            set(rows[0].keys()),
            ROW_BASE_KEYS | {"wc_id", "wc_code", "wc_name", "bundle_count"},
        )
        self.assertEqual([row["wc_code"] for row in rows], ["WC-CUT", "WC-SEW"])
        self.assertEqual(rows[0]["output_pcs"], 5)
        self.assertEqual(rows[1]["output_pcs"], 4)
        self.assertEqual(rows[1]["scrap_pcs"], 1)
        self.assertEqual(rows[1]["bundle_count"], 1)
        # OTD = metrik order-level -> null di baris WC.
        self.assertIsNone(rows[0]["otd_pct"])
        self.assertNotIn("rework_pcs", rows[0])

    def test_group_by_line_dan_tanpa_line(self):
        work_order = self.seed_work_order("WO-1", order_line=self.ol_ok)
        self.seed_bundle("BND-1", work_order=work_order, qty_done=5, work_center=self.wc_cut, line=self.line_hot, finish_at=CURRENT_START)
        self.seed_bundle("BND-2", work_order=work_order, qty_done=2, work_center=self.wc_cut, line=None, finish_at=CURRENT_START)

        body = self.get("group_by=line").json()
        rows = body["rows"]

        self.assertEqual(
            set(rows[0].keys()),
            ROW_BASE_KEYS | {"line_id", "line_code", "line_name", "bundle_count"},
        )
        self.assertEqual([row["key"] for row in rows], ["LINE-HOT", ""])
        self.assertEqual(rows[0]["output_pcs"], 5)
        self.assertEqual(rows[1]["label"], "(tanpa line)")
        self.assertEqual(rows[1]["output_pcs"], 2)
        self.assertIsNone(rows[1]["otd_pct"])


class ProductionReportFilterTests(ProductionReportBase):
    """Filter ``?work_center_id=`` / ``?line_id=`` (pk MES)."""

    def test_filter_work_center_id(self):
        work_order = self.seed_work_order("WO-1", order_line=self.ol_ok)
        self.seed_bundle("BND-CUT", work_order=work_order, qty_done=5, work_center=self.wc_cut, line=self.line_hot, finish_at=CURRENT_START)
        self.seed_bundle("BND-SEW", work_order=work_order, qty_done=4, work_center=self.wc_sew, line=self.line_hot, finish_at=CURRENT_START)
        self.seed_scrap(work_center=self.wc_sew, at=CURRENT_START, qty=3)

        body = self.get(f"work_center_id={self.wc_sew.pk}").json()

        self.assertEqual(body["filters"]["work_center_id"], self.wc_sew.pk)
        self.assertEqual(body["summary"]["total_output_pcs"], 4)
        self.assertEqual(body["summary"]["total_scrap_pcs"], 3)
        self.assertEqual(body["summary"]["total_bundles"], 1)

    def test_filter_line_id(self):
        work_order = self.seed_work_order("WO-1", order_line=self.ol_ok)
        self.seed_bundle("BND-HOT", work_order=work_order, qty_done=5, work_center=self.wc_cut, line=self.line_hot, finish_at=CURRENT_START)
        self.seed_bundle("BND-NONE", work_order=work_order, qty_done=2, work_center=self.wc_cut, line=None, finish_at=CURRENT_START)

        body = self.get(f"line_id={self.line_hot.pk}").json()

        self.assertEqual(body["filters"]["line_id"], self.line_hot.pk)
        self.assertEqual(body["summary"]["total_output_pcs"], 5)
        self.assertEqual(body["summary"]["total_bundles"], 1)

class ProductionReportFormulaTests(ProductionReportBase):
    """Formula output/scrap/efisiensi/OTD + penanda khusus."""

    def test_output_formula_dan_cancelled_dibuang(self):
        work_order = self.seed_work_order("WO-1", order_line=self.ol_ok)
        self.seed_bundle("BND-OK", work_order=work_order, qty_done=5, work_center=self.wc_cut, finish_at=CURRENT_START)
        self.seed_bundle(
            "BND-DEL", work_order=work_order, qty_done=100,
            state="CANCELLED", work_center=self.wc_cut, finish_at=CURRENT_START,
        )

        summary = self.get().json()["summary"]

        self.assertEqual(summary["total_output_pcs"], 5)
        self.assertEqual(summary["total_bundles"], 1)

    def test_rework_dan_end_loss_terpisah_dari_scrap(self):
        work_order = self.seed_work_order("WO-1", order_line=self.ol_ok)
        self.seed_bundle("BND-1", work_order=work_order, qty_done=10, work_center=self.wc_cut, finish_at=CURRENT_START)
        self.seed_scrap(work_center=self.wc_cut, at=CURRENT_START, qty=2, rework=7, end_loss=11)

        body = self.get().json()
        summary = body["summary"]
        row = body["rows"][0]

        self.assertEqual(summary["total_scrap_pcs"], 2)
        self.assertEqual(summary["total_rework_pcs"], 7)
        self.assertEqual(summary["total_end_loss_pcs"], 11)
        # scrap_pct HANYA memakai qty scrap (rework/end-loss tidak dicampur).
        self.assertEqual(summary["scrap_pct"], 16.67)
        self.assertEqual(row["rework_pcs"], 7)
        self.assertEqual(row["end_loss_pcs"], 11)

    def test_scrap_pct_denominator_nol(self):
        work_order = self.seed_work_order("WO-1", order_line=self.ol_ok)
        self.seed_bundle("BND-1", work_order=work_order, qty_done=5, work_center=self.wc_cut, finish_at=CURRENT_START)

        hanya_output = self.get().json()["summary"]
        self.assertEqual(hanya_output["scrap_pct"], 0.0)

        Bundle.objects.all().delete()
        cache.clear()
        self.seed_scrap(work_center=self.wc_cut, at=CURRENT_START, qty=4)

        hanya_scrap = self.get().json()["summary"]
        self.assertEqual(hanya_scrap["total_output_pcs"], 0)
        self.assertEqual(hanya_scrap["total_scrap_pcs"], 4)
        self.assertEqual(hanya_scrap["scrap_pct"], 100.0)

    def test_efisiensi_per_period_rumus_b13(self):
        work_order = self.seed_work_order("WO-1", order_line=self.ol_ok)
        self.seed_bundle(
            "BND-1", work_order=work_order, qty_done=5, work_center=self.wc_cut,
            start_at=CURRENT_START, finish_at=CURRENT_START,
        )

        body = self.get(
            f"date_from={CURRENT_FIRST_DAY.isoformat()}"
            f"&date_to={CURRENT_FIRST_DAY.isoformat()}"
        ).json()

        # target_per_day WC-CUT = 10, 1 bundle selesai dalam 1 hari -> 10.0%.
        self.assertEqual(body["summary"]["avg_efficiency_pct"], 10.0)
        self.assertEqual(body["rows"][0]["efficiency_pct"], 10.0)

    def test_efisiensi_per_work_center(self):
        work_order = self.seed_work_order("WO-1", order_line=self.ol_ok)
        self.seed_bundle(
            "BND-CUT", work_order=work_order, qty_done=5, work_center=self.wc_cut,
            start_at=CURRENT_START, finish_at=CURRENT_START,
        )
        self.seed_bundle(
            "BND-SEW", work_order=work_order, qty_done=4, work_center=self.wc_sew,
            start_at=CURRENT_START, finish_at=CURRENT_START,
        )

        body = self.get(
            f"group_by=work_center&date_from={CURRENT_FIRST_DAY.isoformat()}"
            f"&date_to={CURRENT_FIRST_DAY.isoformat()}"
        ).json()
        rows = {row["wc_code"]: row for row in body["rows"]}

        # WC-CUT target 10/hari -> 10.0%; WC-SEW target 20/hari -> 5.0%.
        self.assertEqual(rows["WC-CUT"]["efficiency_pct"], 10.0)
        self.assertEqual(rows["WC-SEW"]["efficiency_pct"], 5.0)

    def test_otd_order_level_dan_null_di_wc_line(self):
        wo_ok = self.seed_work_order("WO-OK", order_line=self.ol_ok, state="DONE")
        wo_late = self.seed_work_order("WO-LATE", order_line=self.ol_late, state="DONE")
        self.seed_bundle("BND-OK", work_order=wo_ok, qty_done=5, work_center=self.wc_cut, line=self.line_hot, finish_at=CURRENT_START)
        self.seed_bundle("BND-LATE", work_order=wo_late, qty_done=3, work_center=self.wc_cut, line=self.line_hot, finish_at=CURRENT_START)

        by_period = self.get("group_by=period").json()
        self.assertEqual(by_period["summary"]["otd_pct"], 50.0)
        self.assertEqual(by_period["rows"][0]["otd_pct"], 50.0)

        cache.clear()
        by_wc = self.get("group_by=work_center").json()
        self.assertEqual(by_wc["rows"][0]["otd_pct"], None)
        # OTD tetap dihitung di summary walau baris WC bernilai null.
        self.assertEqual(by_wc["summary"]["otd_pct"], 50.0)

    def test_bundle_count_dan_wo_count(self):
        wo_a = self.seed_work_order("WO-A", order_line=self.ol_ok)
        wo_b = self.seed_work_order("WO-B", order_line=self.ol_late)
        self.seed_bundle("BND-1", work_order=wo_a, qty_done=5, work_center=self.wc_cut, finish_at=CURRENT_START)
        self.seed_bundle("BND-2", work_order=wo_a, qty_done=2, work_center=self.wc_cut, finish_at=CURRENT_START)
        self.seed_bundle("BND-3", work_order=wo_b, qty_done=1, work_center=self.wc_cut, finish_at=CURRENT_START)

        body = self.get("group_by=period").json()
        row = body["rows"][0]

        self.assertEqual(row["bundle_count"], 3)
        self.assertEqual(row["wo_count"], 2)
        self.assertEqual(body["summary"]["total_bundles"], 3)
        self.assertEqual(body["summary"]["total_work_orders"], 2)


class ProductionReportCacheTests(ProductionReportBase):
    """Cache 300 dtk: hit = **0 query DB** + ``?_nocache=1`` (tidak baca & tidak tulis)."""

    def test_cache_hit_nol_query_dan_key_per_filter(self):
        work_order = self.seed_work_order("WO-1", order_line=self.ol_ok)
        self.seed_bundle("BND-1", work_order=work_order, qty_done=5, work_center=self.wc_cut, finish_at=CURRENT_START)
        self.seed_scrap(work_center=self.wc_cut, at=CURRENT_START, qty=1)

        with CaptureQueriesContext(connection) as pertama:
            response1 = self.get()
        self.assertFalse(response1.json()["cached"])
        self.assertGreater(len(pertama), 0)

        with CaptureQueriesContext(connection) as kedua:
            response2 = self.get()
        self.assertTrue(response2.json()["cached"])
        self.assertEqual(len(kedua), 0)
        self.assertEqual(response2.json()["rows"], response1.json()["rows"])
        self.assertEqual(response2.json()["generated_at"], response1.json()["generated_at"])

        bypass = self.get("_nocache=1").json()
        self.assertFalse(bypass["cached"])
        self.assertTrue(self.get().json()["cached"])

        self.assertFalse(self.get("group_by=work_center").json()["cached"])
        self.assertTrue(self.get("group_by=work_center").json()["cached"])


class ProductionReportNonBreakingTests(ProductionReportBase):
    """B13/B16/B18–B21 + H2.3/H2.4 + H4.1–H4.5 tetap hijau & route baru terdaftar."""

    def test_non_breaking(self):
        self.assertEqual(resolve(PRODUCTION_URL).url_name, "reports_production")
        self.assertEqual(resolve(LINE_EFFICIENCY_URL).url_name, "reports_line_efficiency")
        self.assertEqual(resolve(LINE_EFFICIENCY_BY_WC_URL).url_name, "reports_line_efficiency_by_wc")
        self.assertEqual(resolve(WIP_URL).url_name, "reports_wip")
        self.assertEqual(resolve(WIP_BY_WC_URL).url_name, "reports_wip_by_wc")
        self.assertEqual(resolve(LEAD_TIME_URL).url_name, "reports_lead_time")
        self.assertEqual(resolve(OTD_URL).url_name, "reports_on_time_delivery")
        self.assertEqual(resolve(SALES_URL).url_name, "reports_sales")
        self.assertEqual(resolve(PNL_URL).url_name, "reports_pnl")

        for url in (LINE_EFFICIENCY_URL, WIP_URL, LEAD_TIME_URL, OTD_URL, SALES_URL, PNL_URL):
            with self.subTest(url=url):
                response = self.api.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertIsInstance(response.json(), dict)

        # H2.4 — daftar bundle MES tetap jalan (read-only, tidak diubah H4.6).
        bundles = self.api.get(BUNDLES_URL)
        self.assertEqual(bundles.status_code, 200)
