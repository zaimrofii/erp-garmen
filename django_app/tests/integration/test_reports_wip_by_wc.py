"""Test endpoint reports WIP per-WC flat (F3A.1 / B21).

``GET /api/v1/reports/wip/by-wc/`` — tabel ringkas (tanpa ``label``/``unit``/
``trend``/``series``); semantik WIP sama dengan B16 (`WCQueue.EXCLUDED_STATES`).

Jalankan (SERIAL):

    docker compose exec django python -m pytest tests/integration/test_reports_wip_by_wc.py -q
"""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps_industry.garment.models import Bundle, WorkCenter
from apps_industry.garment.tests.factories import make_bundle, make_work_order
from core.auth.models import User

URL = "/api/v1/reports/wip/by-wc/"

TOP_KEYS = {"rows", "total_wip", "generated_at"}
ROW_KEYS = {
    "wc_code",
    "wc_name",
    "wip_qty",
    "queue_depth",
    "oldest_bundle_age_hours",
}


class WipByWcAuthTests(TestCase):
    def test_anonim_403(self):
        self.assertEqual(APIClient().get(URL).status_code, 403)


class WipByWcTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="rep-wip-bywc", password="x")

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    @staticmethod
    def _seed():
        """WC-01: 2 bundle WIP (10+5) + 1 DONE; WC-02: 1 bundle WIP (7)."""
        now = timezone.now()
        wc1 = WorkCenter.objects.create(code="SEW-01", name="Sewing 1")
        wc2 = WorkCenter.objects.create(code="SEW-02", name="Sewing 2")
        work_order = make_work_order()
        tertua = make_bundle(
            work_order=work_order, code="B1", qty=10, state="SEWING", current_work_center=wc1
        )
        Bundle.objects.filter(pk=tertua.pk).update(created_at=now - timedelta(hours=3))
        make_bundle(
            work_order=work_order, code="B2", qty=5, state="CUTTING", current_work_center=wc1
        )
        make_bundle(
            work_order=work_order, code="B3", qty=7, state="SEWING", current_work_center=wc2
        )
        # DONE -> bukan WIP.
        make_bundle(
            work_order=work_order, code="B4", qty=99, state="DONE", current_work_center=wc1
        )
        return wc1, wc2

    def test_shape_lengkap(self):
        self._seed()

        body = self.api.get(URL).json()

        self.assertEqual(set(body), TOP_KEYS)
        self.assertIn("T", body["generated_at"])
        self.assertEqual(set(body["rows"][0]), ROW_KEYS)

    def test_kosong(self):
        body = self.api.get(URL).json()

        self.assertEqual(body["rows"], [])
        self.assertEqual(body["total_wip"], 0)

    def test_dua_wc_wip_qty_dan_queue_depth(self):
        self._seed()

        body = self.api.get(URL).json()

        self.assertEqual(len(body["rows"]), 2)
        per_code = {row["wc_code"]: row for row in body["rows"]}
        self.assertEqual(per_code["SEW-01"]["wip_qty"], 15)  # 10 + 5, DONE dikecualikan
        self.assertEqual(per_code["SEW-01"]["queue_depth"], 2)
        self.assertEqual(per_code["SEW-02"]["wip_qty"], 7)
        self.assertEqual(per_code["SEW-02"]["queue_depth"], 1)
        self.assertEqual(body["total_wip"], 22)

    def test_oldest_bundle_age_hours(self):
        self._seed()

        body = self.api.get(URL).json()

        per_code = {row["wc_code"]: row for row in body["rows"]}
        # bundle tertua dibuat 3 jam lalu -> ~3.0 jam
        self.assertAlmostEqual(
            per_code["SEW-01"]["oldest_bundle_age_hours"], 3.0, delta=0.5
        )
        # WC-02 baru dibuat sekarang -> jauh lebih kecil dari 1 jam
        self.assertLess(per_code["SEW-02"]["oldest_bundle_age_hours"], 1.0)
