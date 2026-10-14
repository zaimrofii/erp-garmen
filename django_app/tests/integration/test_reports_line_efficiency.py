"""Test endpoint reports line efficiency (F1 / B13).

`GET /api/v1/reports/line-efficiency/` — read-only dari `BundleEvent`
(``BUNDLE_START``/``BUNDLE_FINISH``). ``IsAuthenticated`` → 403.

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_reports_line_efficiency.py -q
"""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps_industry.garment.models import BundleEvent, WorkCenter
from apps_industry.garment.tests.factories import make_bundle, make_work_order
from core.auth.models import User

EFFICIENCY_URL = "/api/v1/reports/line-efficiency/"

TOP_KEYS = {"rows", "generated_at", "period"}
ROW_KEYS = {"wc_code", "wc_name", "bundles_done", "avg_min_per_bundle", "efficiency_pct", "label", "unit", "trend", "series"}


def _event(bundle, event_type, ts):
    """Buat `BundleEvent` lalu paksa `ts` (ts = auto_now_add)."""
    event = BundleEvent.objects.create(bundle=bundle, event_type=event_type, payload={})
    BundleEvent.objects.filter(pk=event.pk).update(ts=ts)
    return event


class ReportsLineEfficiencyAuthTests(TestCase):
    def test_anonim_403(self):
        self.assertEqual(APIClient().get(EFFICIENCY_URL).status_code, 403)


class ReportsLineEfficiencyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="rep-eff", password="x")

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def test_shape_lengkap(self):
        WorkCenter.objects.create(code="SEW-01", name="Sewing Line 1")

        body = self.api.get(EFFICIENCY_URL).json()

        self.assertEqual(set(body), TOP_KEYS)
        self.assertEqual(set(body["period"]), {"from", "to"})
        self.assertIn("T", body["generated_at"])
        row = body["rows"][0]
        self.assertEqual(set(row), ROW_KEYS)
        self.assertEqual(row["wc_code"], "SEW-01")
        self.assertEqual(row["wc_name"], "Sewing Line 1")
        # WC tanpa bundle selesai tetap tampil dengan nilai 0.
        self.assertEqual(row["bundles_done"], 0)
        self.assertEqual(row["avg_min_per_bundle"], 0.0)
        self.assertEqual(row["efficiency_pct"], 0.0)

    def test_kosong_rows_kosong(self):
        body = self.api.get(EFFICIENCY_URL).json()

        self.assertEqual(body["rows"], [])
        self.assertIn("generated_at", body)

    def test_avg_min_per_bundle(self):
        work_center = WorkCenter.objects.create(code="SEW-01", name="Sewing Line 1")
        work_order = make_work_order()
        now = timezone.now()
        for index, durasi_menit in enumerate((10, 20)):
            bundle = make_bundle(
                work_order=work_order,
                code=f"B-{index}",
                state="DONE",
                current_work_center=work_center,
            )
            _event(bundle, "BUNDLE_START", now - timedelta(minutes=durasi_menit + 5))
            _event(bundle, "BUNDLE_FINISH", now - timedelta(minutes=5))

        body = self.api.get(EFFICIENCY_URL).json()

        row = next(r for r in body["rows"] if r["wc_code"] == "SEW-01")
        self.assertEqual(row["bundles_done"], 2)
        self.assertAlmostEqual(row["avg_min_per_bundle"], 15.0, delta=0.5)

    def test_filter_from_to_period(self):
        body = self.api.get(
            EFFICIENCY_URL,
            {"from": "2026-10-01T00:00:00+07:00", "to": "2026-10-02T00:00:00+07:00"},
        ).json()

        self.assertTrue(body["period"]["from"].startswith("2026-10-01"))
        self.assertTrue(body["period"]["to"].startswith("2026-10-02"))

    def test_from_invalid_400(self):
        self.assertEqual(
            self.api.get(EFFICIENCY_URL, {"from": "bukan-tanggal"}).status_code, 400
        )

    def test_from_lebih_besar_dari_to_400(self):
        response = self.api.get(
            EFFICIENCY_URL,
            {"from": "2026-10-05T00:00:00+07:00", "to": "2026-10-01T00:00:00+07:00"},
        )

        self.assertEqual(response.status_code, 400)


class ReportsLineEfficiencyGapTests(TestCase):
    """G4b (aditif) — label / unit / trend / series."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="eff-gap", password="x")

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def test_row_field_baru_aditif(self):
        WorkCenter.objects.create(code="SEW-01", name="Sewing Line 1")

        row = self.api.get(EFFICIENCY_URL).json()["rows"][0]

        self.assertEqual(row["label"], "Sewing Line 1")
        self.assertEqual(row["unit"], "%")
        self.assertEqual(len(row["trend"]), 7)
        self.assertEqual(len(row["series"]), 7)
        self.assertEqual(
            row["series"][0],
            {"x": row["trend"][0]["date"], "y": row["trend"][0]["value"]},
        )

    def test_trend_efisiensi_hari_ini(self):
        work_center = WorkCenter.objects.create(
            code="SEW-01", name="Sewing Line 1", config={"target_per_day": 1}
        )
        work_order = make_work_order()
        now = timezone.now()
        bundle = make_bundle(
            work_order=work_order,
            code="B-EFF",
            qty=5,
            qty_done=5,
            state="DONE",
            current_work_center=work_center,
        )
        _event(bundle, "BUNDLE_START", now - timedelta(minutes=1))
        _event(bundle, "BUNDLE_FINISH", now)

        row = self.api.get(EFFICIENCY_URL).json()["rows"][0]

        self.assertEqual(row["trend"][-1]["value"], 100.0)

