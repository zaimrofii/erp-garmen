"""Test endpoint reports lead-time (F3A.1 / B19 & B19b).

* ``GET /api/v1/reports/lead-time/``          -> ListPage + ``avg_hours`` (per bundle, dengan ``stages``)
* ``GET /api/v1/reports/lead-time/bundles/``  -> ListPage FLAT (``wc_count``, urut ``hours_total`` DESC)

Jalankan (SERIAL):

    docker compose exec django python -m pytest tests/integration/test_reports_lead_time.py -q
"""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps_industry.garment.models import Bundle, BundleEvent, WorkCenter
from apps_industry.garment.tests.factories import make_bundle, make_work_order
from core.auth.models import User

URL = "/api/v1/reports/lead-time/"
URL_FLAT = "/api/v1/reports/lead-time/bundles/"

TOP_KEYS = {"rows", "total_count", "has_more", "next_cursor", "avg_hours"}
ROW_KEYS = {"bundle_code", "created_at", "finished_at", "hours_total", "stages"}
STAGE_KEYS = {"wc_code", "minutes"}
FLAT_TOP_KEYS = {"rows", "total_count", "has_more", "next_cursor"}
FLAT_ROW_KEYS = {"bundle_code", "hours_total", "wc_count", "done_at"}


def _event(bundle, event_type, ts):
    """Buat `BundleEvent` lalu paksa `ts` (ts = auto_now_add)."""
    event = BundleEvent.objects.create(bundle=bundle, event_type=event_type, payload={})
    BundleEvent.objects.filter(pk=event.pk).update(ts=ts)
    return event


def _make_bundle(work_order, code, work_center, created_hours_ago):
    """Bundle dengan ``created_at`` yang dipaksa (auto_now_add)."""
    bundle = make_bundle(
        work_order=work_order, code=code, state="DONE", current_work_center=work_center
    )
    Bundle.objects.filter(pk=bundle.pk).update(
        created_at=timezone.now() - timedelta(hours=created_hours_ago)
    )
    bundle.refresh_from_db()
    return bundle


class LeadTimeAuthTests(TestCase):
    def test_anonim_403(self):
        self.assertEqual(APIClient().get(URL).status_code, 403)

    def test_anonim_flat_403(self):
        self.assertEqual(APIClient().get(URL_FLAT).status_code, 403)


class LeadTimeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="rep-lead", password="x")

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def test_shape_lengkap(self):
        WorkCenter.objects.create(code="SEW-01", name="Sewing 1")

        body = self.api.get(URL).json()

        self.assertEqual(set(body), TOP_KEYS)
        self.assertEqual(body["rows"], [])
        self.assertEqual(body["avg_hours"], 0.0)

    def test_kosong(self):
        body = self.api.get(URL).json()

        self.assertEqual(body["total_count"], 0)
        self.assertIsNone(body["next_cursor"])
        self.assertFalse(body["has_more"])

    def test_satu_bundle_tiga_stage(self):
        work_center = WorkCenter.objects.create(code="SEW-01", name="Sewing 1")
        work_order = make_work_order()
        now = timezone.now()
        bundle = _make_bundle(work_order, "B-3ST", work_center, created_hours_ago=6)
        for start_ago, finish_ago in ((350, 300), (240, 180), (120, 60)):
            _event(bundle, "BUNDLE_START", now - timedelta(minutes=start_ago))
            _event(bundle, "BUNDLE_FINISH", now - timedelta(minutes=finish_ago))

        body = self.api.get(URL).json()

        row = body["rows"][0]
        self.assertEqual(set(row), ROW_KEYS)
        self.assertEqual(row["bundle_code"], "B-3ST")
        self.assertEqual(len(row["stages"]), 3)
        self.assertEqual(set(row["stages"][0]), STAGE_KEYS)
        self.assertEqual(row["stages"][0]["wc_code"], "SEW-01")
        self.assertAlmostEqual(row["stages"][0]["minutes"], 50.0, delta=0.5)
        self.assertAlmostEqual(row["hours_total"], 5.0, delta=0.1)

    def test_avg_hours_seluruh_baris(self):
        work_center = WorkCenter.objects.create(code="SEW-01", name="Sewing 1")
        work_order = make_work_order()
        now = timezone.now()
        for code, created_ago, finish_ago in (("B-A", 4, 60), ("B-B", 2, 30)):
            bundle = _make_bundle(work_order, code, work_center, created_ago)
            _event(bundle, "BUNDLE_START", now - timedelta(minutes=finish_ago + 10))
            _event(bundle, "BUNDLE_FINISH", now - timedelta(minutes=finish_ago))

        body = self.api.get(URL).json()

        self.assertEqual(body["total_count"], 2)
        # (3.0 jam + 1.5 jam) / 2 = 2.25
        self.assertAlmostEqual(body["avg_hours"], 2.25, delta=0.1)

    def test_filter_tanggal_hanya_yang_dalam_rentang(self):
        work_center = WorkCenter.objects.create(code="SEW-01", name="Sewing 1")
        work_order = make_work_order()
        now = timezone.now()
        lama = _make_bundle(work_order, "B-LAMA", work_center, created_hours_ago=30)
        _event(lama, "BUNDLE_START", now - timedelta(hours=29))
        _event(lama, "BUNDLE_FINISH", now - timedelta(hours=28))
        baru = _make_bundle(work_order, "B-BARU", work_center, created_hours_ago=2)
        _event(baru, "BUNDLE_START", now - timedelta(hours=1, minutes=30))
        _event(baru, "BUNDLE_FINISH", now - timedelta(hours=1))

        body = self.api.get(
            URL,
            {"from": (now - timedelta(hours=3)).isoformat(), "to": now.isoformat()},
        ).json()

class LeadTimeFlatTests(TestCase):
    """B19b — lead-time FLAT per bundle (untuk list view)."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="rep-lead-flat", password="x")

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    @staticmethod
    def _seed_two():
        work_center = WorkCenter.objects.create(code="SEW-01", name="Sewing 1")
        work_order = make_work_order()
        now = timezone.now()
        for code, created_ago, finish_ago in (("B-A", 4, 60), ("B-B", 2, 30)):
            bundle = _make_bundle(work_order, code, work_center, created_ago)
            _event(bundle, "BUNDLE_START", now - timedelta(minutes=finish_ago + 10))
            _event(bundle, "BUNDLE_FINISH", now - timedelta(minutes=finish_ago))

    def test_shape_listpage(self):
        self._seed_two()

        body = self.api.get(URL_FLAT).json()

        self.assertEqual(set(body), FLAT_TOP_KEYS)
        self.assertEqual(set(body["rows"][0]), FLAT_ROW_KEYS)

    def test_kosong(self):
        body = self.api.get(URL_FLAT).json()

        self.assertEqual(body["rows"], [])
        self.assertEqual(body["total_count"], 0)
        self.assertIsNone(body["next_cursor"])

    def test_dua_bundle_wc_count(self):
        self._seed_two()

        body = self.api.get(URL_FLAT).json()

        self.assertEqual(body["total_count"], 2)
        self.assertEqual(body["rows"][0]["wc_count"], 1)
        self.assertIsNotNone(body["rows"][0]["done_at"])

    def test_sorting_hours_desc(self):
        self._seed_two()

        body = self.api.get(URL_FLAT).json()

        self.assertEqual([row["bundle_code"] for row in body["rows"]], ["B-A", "B-B"])
        self.assertGreater(body["rows"][0]["hours_total"], body["rows"][1]["hours_total"])

