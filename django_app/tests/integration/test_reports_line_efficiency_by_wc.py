"""Test endpoint reports line-efficiency/by-wc (F3A.1 / B18).

``GET /api/v1/reports/line-efficiency/by-wc/`` — read-only dari `BundleEvent`
(``BUNDLE_START``/``BUNDLE_FINISH``) + ``Bundle.current_work_center``.

Jalankan (di dalam container, SERIAL):

    docker compose exec django python -m pytest tests/integration/test_reports_line_efficiency_by_wc.py -q
"""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps_industry.garment.models import BundleEvent, WorkCenter
from apps_industry.garment.tests.factories import make_bundle, make_work_order
from core.auth.models import User

URL = "/api/v1/reports/line-efficiency/by-wc/"

TOP_KEYS = {"rows", "generated_at", "period"}
ROW_KEYS = {
    "wc_code",
    "wc_name",
    "bundles_done",
    "avg_min_per_bundle",
    "efficiency_pct",
    "pct_delta_vs_prev",
}


def _event(bundle, event_type, ts):
    """Buat `BundleEvent` lalu paksa `ts` (ts = auto_now_add)."""
    event = BundleEvent.objects.create(bundle=bundle, event_type=event_type, payload={})
    BundleEvent.objects.filter(pk=event.pk).update(ts=ts)
    return event


class LineEfficiencyByWcAuthTests(TestCase):
    def test_anonim_403(self):
        self.assertEqual(APIClient().get(URL).status_code, 403)


class LineEfficiencyByWcTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="eff-bywc", password="x")

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def test_shape_lengkap(self):
        WorkCenter.objects.create(code="SEW-01", name="Sewing 1")

        body = self.api.get(URL).json()

        self.assertEqual(set(body), TOP_KEYS)
        self.assertEqual(set(body["period"]), {"from", "to"})
        self.assertIn("T", body["generated_at"])
        self.assertEqual(set(body["rows"][0]), ROW_KEYS)

    def test_kosong_tanpa_wc(self):
        body = self.api.get(URL).json()

        self.assertEqual(body["rows"], [])
        self.assertIn("generated_at", body)

    def test_dua_wc_bundles_done_dan_delta(self):
        wc1 = WorkCenter.objects.create(
            code="SEW-01", name="Sewing 1", config={"target_per_day": 1}
        )
        WorkCenter.objects.create(
            code="SEW-02", name="Sewing 2", config={"target_per_day": 1}
        )
        work_order = make_work_order()
        now = timezone.now()
        bundle = make_bundle(
            work_order=work_order, code="B-1", state="DONE", current_work_center=wc1
        )
        _event(bundle, "BUNDLE_START", now - timedelta(minutes=10))
        _event(bundle, "BUNDLE_FINISH", now)

        body = self.api.get(
            URL,
            {"from": (now - timedelta(hours=1)).isoformat(), "to": now.isoformat()},
        ).json()

        self.assertEqual(len(body["rows"]), 2)
        per_code = {row["wc_code"]: row for row in body["rows"]}
        self.assertEqual(per_code["SEW-01"]["bundles_done"], 1)
        self.assertAlmostEqual(per_code["SEW-01"]["avg_min_per_bundle"], 10.0, delta=0.5)
        # kapasitas = target 1/hari x 1 hari -> 100%
        self.assertEqual(per_code["SEW-01"]["efficiency_pct"], 100.0)
        # periode sebelumnya tidak ada bundle selesai -> delta = +100
        self.assertEqual(per_code["SEW-01"]["pct_delta_vs_prev"], 100.0)
        self.assertEqual(per_code["SEW-02"]["bundles_done"], 0)

    def test_filter_tanggal_period(self):
        body = self.api.get(
            URL,
            {"from": "2026-10-01T00:00:00+07:00", "to": "2026-10-02T00:00:00+07:00"},
        ).json()

        self.assertTrue(body["period"]["from"].startswith("2026-10-01"))
        self.assertTrue(body["period"]["to"].startswith("2026-10-02"))
