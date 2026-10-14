"""Test endpoint dashboard summary (F1 / B1) — `GET /api/v1/dashboard/summary/`.

Read-only, agregat DB murni (tanpa Odoo). Endpoint ``IsAuthenticated`` → anonim
**403**.

Cakupan:
  * bentuk (shape) response lengkap — kunci persis tidak lebih/kurang;
  * DB kosong tetap **200** dengan nilai 0;
  * agregat benar dengan data (bundle per state, WIP/FG, scrap hari ini);
  * order open/overdue;
  * alert muncul saat queue WC > ambang **10** (via `BottleneckDetector`).

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_dashboard_summary.py -q
"""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps_industry.garment.models import BundleEvent, WorkCenter
from apps_industry.garment.tests.factories import (
    make_bundle,
    make_order,
    make_routing,
    make_scrap_accumulator,
    make_step,
    make_work_center,
    make_work_order,
)
from core.auth.models import User

DASHBOARD_URL = "/api/v1/dashboard/summary/"

TOP_KEYS = {
    "bundles",
    "wip_qty",
    "fg_qty",
    "orders",
    "scrap_qty_today",
    "alerts",
    "line_efficiency",
    "trend",
    "generated_at",
}
BUNDLE_KEYS = {"draft", "cutting", "sewing", "qc", "done"}
ORDER_KEYS = {"open", "overdue"}
ALERT_KEYS = {"code", "message", "severity"}


class DashboardSummaryAuthTests(TestCase):
    """Endpoint butuh login (konsisten endpoint monitoring/sync lain)."""

    def test_anonim_403(self):
        self.assertEqual(APIClient().get(DASHBOARD_URL).status_code, 403)


class DashboardSummaryShapeTests(TestCase):
    """Bentuk response & kasus DB kosong."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="dash-shape", password="x")

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def test_shape_lengkap(self):
        response = self.api.get(DASHBOARD_URL)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), TOP_KEYS)
        self.assertEqual(set(body["bundles"]), BUNDLE_KEYS)
        self.assertEqual(set(body["orders"]), ORDER_KEYS)
        self.assertIsInstance(body["alerts"], list)
        self.assertIsInstance(body["wip_qty"], int)
        self.assertIsInstance(body["fg_qty"], int)
        self.assertIsInstance(body["scrap_qty_today"], int)
        self.assertIn("T", body["generated_at"])  # ISO-8601

    def test_db_kosong_200_dengan_nol(self):
        response = self.api.get(DASHBOARD_URL)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            body["bundles"],
            {"draft": 0, "cutting": 0, "sewing": 0, "qc": 0, "done": 0},
        )
        self.assertEqual(body["wip_qty"], 0)
        self.assertEqual(body["fg_qty"], 0)
        self.assertEqual(body["orders"], {"open": 0, "overdue": 0})
        self.assertEqual(body["scrap_qty_today"], 0)
        self.assertEqual(body["alerts"], [])


class DashboardSummaryAggregateTests(TestCase):
    """Agregat dengan data: bundle per state, WIP/FG, scrap hari ini."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="dash-agg", password="x")
        # Routing: SEWING (non-terminal) -> PACKING (terminal = FG).
        cls.wc_sewing = make_work_center(code="SEWING-1")
        cls.wc_packing = make_work_center(code="PACKING-1")
        cls.routing = make_routing(code="ROUTE-DASH")
        make_step(cls.routing, "SEWING", 10, is_initial=True, work_center=cls.wc_sewing)
        make_step(cls.routing, "PACKING", 20, is_terminal=True, work_center=cls.wc_packing)

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def test_bundles_wip_fg_scrap(self):
        # Satu work order dipakai bersama supaya tidak menambah order liar.
        work_order = make_work_order()
        make_bundle(
            work_order=work_order,
            code="B-WIP",
            qty=10,
            state="SEWING",
            current_work_center=self.wc_sewing,
        )
        make_bundle(
            work_order=work_order,
            code="B-FG",
            qty=8,
            qty_done=6,
            state="DONE",
            current_work_center=self.wc_packing,
        )
        make_bundle(work_order=work_order, code="B-DRAFT", state="DRAFT")
        make_scrap_accumulator(work_center=self.wc_packing, qty=5)

        body = self.api.get(DASHBOARD_URL).json()

        self.assertEqual(
            body["bundles"],
            {"draft": 1, "cutting": 0, "sewing": 1, "qc": 0, "done": 1},
        )
        self.assertEqual(body["wip_qty"], 10)  # SEWING non-terminal -> qty
        self.assertEqual(body["fg_qty"], 6)  # PACKING terminal -> qty_done
        self.assertEqual(body["scrap_qty_today"], 5)

    def test_orders_open_overdue(self):
        # Tanpa bundle (tidak ada order liar dari factory bundle).
        make_order(
            code="SO-OPEN", state="DRAFT", deadline=timezone.now() + timedelta(days=2)
        )
        make_order(
            code="SO-OVERDUE",
            state="DRAFT",
            deadline=timezone.now() - timedelta(days=2),
        )
        make_order(code="SO-DONE", state="DONE")

        body = self.api.get(DASHBOARD_URL).json()

        self.assertEqual(body["orders"], {"open": 2, "overdue": 1})


class DashboardSummaryAlertTests(TestCase):
    """Alert bottleneck: muncul saat queue WC > ambang (10)."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="dash-alert", password="x")

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    @staticmethod
    def _queue(work_center, jumlah):
        """Isi queue WC dengan `jumlah` bundle (state non-terminal, WC terisi)."""
        work_order = make_work_order()
        for index in range(jumlah):
            make_bundle(
                work_order=work_order,
                code=f"{work_center.code}-Q{index}",
                state="SEWING",
                current_work_center=work_center,
            )

    def test_alert_muncul_saat_queue_gt_10(self):
        work_center = make_work_center(code="SEWING-9")
        self._queue(work_center, 11)  # ambang 10 -> 11 > 10

        body = self.api.get(DASHBOARD_URL).json()

        self.assertTrue(body["alerts"])
        alert = next(a for a in body["alerts"] if a["code"] == "BOTTLENECK_SEWING-9")
        self.assertEqual(set(alert), ALERT_KEYS)
        self.assertEqual(alert["severity"], "medium")
        self.assertIn("11", alert["message"])

    def test_tanpa_alert_kalau_queue_tidak_melebihi_ambang(self):
        work_center = make_work_center(code="SEWING-10")
        self._queue(work_center, 10)  # == ambang, bukan > ambang

        body = self.api.get(DASHBOARD_URL).json()

        self.assertEqual(body["alerts"], [])

    def test_alert_high_kalau_queue_jauh_di_atas_ambang(self):
        work_center = make_work_center(code="SEWING-11")
        self._queue(work_center, 20)  # >= 2x ambang -> high

        body = self.api.get(DASHBOARD_URL).json()

        alert = next(a for a in body["alerts"] if a["code"] == "BOTTLENECK_SEWING-11")
        self.assertEqual(alert["severity"], "high")


class DashboardSummaryGapTests(TestCase):
    """G1 (aditif) — `line_efficiency` + `trend` (field lama tidak dihapus)."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="dash-gap", password="x")

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    @staticmethod
    def _event(bundle, event_type, ts):
        event = BundleEvent.objects.create(
            bundle=bundle, event_type=event_type, payload={}
        )
        BundleEvent.objects.filter(pk=event.pk).update(ts=ts)
        return event

    def test_line_efficiency_ada_di_response(self):
        body = self.api.get(DASHBOARD_URL).json()

        self.assertIn("line_efficiency", body)
        self.assertIsInstance(body["line_efficiency"]["pct"], float)
        self.assertIsInstance(body["line_efficiency"]["delta"], float)

    def test_trend_7_hari_terakhir_ascending(self):
        body = self.api.get(DASHBOARD_URL).json()

        trend = body["trend"]
        self.assertEqual(len(trend), 7)
        dates = [row["date"] for row in trend]
        self.assertEqual(dates, sorted(dates))
        for row in trend:
            self.assertIsInstance(row["wip"], int)
            self.assertIsInstance(row["fg"], int)

    def test_line_efficiency_delta_negatif_saat_pct_turun(self):
        work_center = WorkCenter.objects.create(
            code="WC-EFF", name="Eff", config={"target_per_day": 1}
        )
        work_order = make_work_order()
        now = timezone.now()
        bundle = make_bundle(
            work_order=work_order,
            code="B-PREV",
            qty=5,
            qty_done=5,
            state="DONE",
            current_work_center=work_center,
        )
        # Selesai di jendela 7 hari SEBELUMNYA; hari ini tidak ada -> delta < 0.
        self._event(bundle, "BUNDLE_START", now - timedelta(days=8))
        self._event(bundle, "BUNDLE_FINISH", now - timedelta(days=7, hours=1))

        body = self.api.get(DASHBOARD_URL).json()

        self.assertLess(body["line_efficiency"]["delta"], 0)

