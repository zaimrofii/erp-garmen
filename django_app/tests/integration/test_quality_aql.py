"""Test endpoint AQL (F3A.3 / B5) — ``GET /api/v1/quality/aql/``.

Sumber = `BundleEvent`: ``BUNDLE_FINISH`` (sampel) + event scrap
(``BUNDLE_SCRAP``/``SCRAP`` → ``payload.scrap_qty``); severity:
``<=1.5`` pass · ``<=4.0`` warn · ``>4.0`` fail. ``IsAuthenticated`` → 403.

Jalankan (SERIAL):

    docker compose exec django python -m pytest tests/integration/test_quality_aql.py -q
"""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps_industry.garment.models import BundleEvent, WorkCenter
from apps_industry.garment.tests.factories import make_bundle, make_work_order
from core.auth.models import User

URL = "/api/v1/quality/aql/"

TOP_KEYS = {"rows", "generated_at", "period"}
ROW_KEYS = {"wc_code", "wc_name", "sample_qty", "defect_qty", "aql_pct", "severity"}


def _event(bundle, event_type, ts, payload=None):
    """Buat `BundleEvent` lalu paksa `ts` (ts = auto_now_add)."""
    event = BundleEvent.objects.create(
        bundle=bundle, event_type=event_type, payload=payload or {}
    )
    BundleEvent.objects.filter(pk=event.pk).update(ts=ts)
    return event


class QualityAqlAuthTests(TestCase):
    def test_anonim_403(self):
        self.assertEqual(APIClient().get(URL).status_code, 403)


class QualityAqlTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="q-aql", password="x")

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    @staticmethod
    def _seed_wc(code, samples, defect_qty, when=None):
        """WC + `samples` bundle dengan FINISH (+1 event scrap bila defect_qty>0)."""
        when = when or timezone.now()
        work_center = WorkCenter.objects.create(code=code, name=f"WC {code}")
        work_order = make_work_order()
        for index in range(samples):
            bundle = make_bundle(
                work_order=work_order,
                code=f"{code}-B{index}",
                state="DONE",
                current_work_center=work_center,
            )
            _event(bundle, "BUNDLE_FINISH", when)
        if defect_qty:
            bundle = make_bundle(
                work_order=work_order,
                code=f"{code}-SCRAP",
                state="DONE",
                current_work_center=work_center,
            )
            _event(
                bundle,
                "BUNDLE_SCRAP",
                when,
                {"defect_type": "jahitan", "scrap_qty": defect_qty, "reason": "meleset"},
            )
        return work_center

    def test_shape_lengkap(self):
        self._seed_wc("WC-01", samples=1, defect_qty=0)

        body = self.api.get(URL).json()

        self.assertEqual(set(body), TOP_KEYS)
        self.assertEqual(set(body["period"]), {"from", "to"})
        self.assertIn("T", body["generated_at"])
        self.assertEqual(set(body["rows"][0]), ROW_KEYS)

    def test_kosong(self):
        body = self.api.get(URL).json()

        self.assertEqual(body["rows"], [])
        self.assertIn("generated_at", body)

    def test_satu_wc_pass(self):
        self._seed_wc("WC-01", samples=4, defect_qty=0)

        row = self.api.get(URL).json()["rows"][0]

        self.assertEqual(row["wc_code"], "WC-01")
        self.assertEqual(row["sample_qty"], 4)
        self.assertEqual(row["defect_qty"], 0)
        self.assertEqual(row["aql_pct"], 0.0)
        self.assertEqual(row["severity"], "pass")

    def test_satu_wc_fail(self):
        self._seed_wc("WC-02", samples=4, defect_qty=1)

        row = self.api.get(URL).json()["rows"][0]

        self.assertEqual(row["sample_qty"], 4)
        self.assertEqual(row["defect_qty"], 1)
        self.assertEqual(row["aql_pct"], 25.0)  # 1/4 * 100
        self.assertEqual(row["severity"], "fail")

    def test_severity_warn(self):
        # 1 defect / 40 sampel = 2.5% -> warn (1.5 < aql_pct <= 4.0)
        self._seed_wc("WC-03", samples=40, defect_qty=1)

        row = self.api.get(URL).json()["rows"][0]

        self.assertEqual(row["aql_pct"], 2.5)
        self.assertEqual(row["severity"], "warn")

    def test_period_filter(self):
        lama = timezone.now() - timedelta(days=30)
        self._seed_wc("WC-01", samples=4, defect_qty=0)
        self._seed_wc("WC-02", samples=4, defect_qty=3, when=lama)

        # Rentang default 7 hari -> hanya WC-01 (WC-02 defect/sampel di luar rentang).
        default_rows = {row["wc_code"]: row for row in self.api.get(URL).json()["rows"]}
        self.assertIn("WC-01", default_rows)
        self.assertNotIn("WC-02", default_rows)

        # Rentang 60 hari -> WC-02 muncul dengan defect 3 (75% -> fail).
        body = self.api.get(
            URL,
            {
                "from": (timezone.now() - timedelta(days=60)).isoformat(),
                "to": timezone.now().isoformat(),
            },
        ).json()
        per_code = {row["wc_code"]: row for row in body["rows"]}
        self.assertEqual(per_code["WC-02"]["defect_qty"], 3)
        self.assertEqual(per_code["WC-02"]["severity"], "fail")
