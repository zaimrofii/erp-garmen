"""Test endpoint reports WIP (F1 / B16) — `GET /api/v1/reports/wip/`.

Read-only dari `Bundle` (state != DONE). ``IsAuthenticated`` → 403.

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_reports_wip.py -q
"""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.models import WorkCenter
from apps_industry.garment.tests.factories import make_bundle, make_work_order
from core.auth.models import User

WIP_URL = "/api/v1/reports/wip/"

TOP_KEYS_WC = {"rows", "total_wip", "group_by", "generated_at"}
TOP_KEYS_NONE = {"total_wip", "group_by", "generated_at"}
ROW_KEYS = {"wc_code", "wc_name", "wip_qty", "queue_depth", "label", "unit", "trend", "series"}


class ReportsWipAuthTests(TestCase):
    def test_anonim_403(self):
        self.assertEqual(APIClient().get(WIP_URL).status_code, 403)


class ReportsWipTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="rep-wip", password="x")

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    @staticmethod
    def _seed():
        wc1 = WorkCenter.objects.create(code="SEW-01", name="Sewing 1")
        wc2 = WorkCenter.objects.create(code="SEW-02", name="Sewing 2")
        work_order = make_work_order()
        make_bundle(work_order=work_order, code="B1", qty=10, state="SEWING", current_work_center=wc1)
        make_bundle(work_order=work_order, code="B2", qty=5, state="CUTTING", current_work_center=wc1)
        make_bundle(work_order=work_order, code="B3", qty=7, state="SEWING", current_work_center=wc2)
        # DONE -> tidak dihitung WIP.
        make_bundle(work_order=work_order, code="B4", qty=99, state="DONE", current_work_center=wc1)

    def test_shape_group_by_wc(self):
        self._seed()

        body = self.api.get(WIP_URL).json()

        self.assertEqual(set(body), TOP_KEYS_WC)
        self.assertEqual(body["group_by"], "wc")
        self.assertIn("T", body["generated_at"])
        self.assertEqual(len(body["rows"]), 2)
        self.assertEqual(set(body["rows"][0]), ROW_KEYS)

    def test_shape_group_by_none_tanpa_rows(self):
        self._seed()

        body = self.api.get(WIP_URL, {"group_by": "none"}).json()

        self.assertEqual(set(body), TOP_KEYS_NONE)
        self.assertNotIn("rows", body)
        self.assertEqual(body["group_by"], "none")

    def test_kosong(self):
        body = self.api.get(WIP_URL).json()

        self.assertEqual(body["total_wip"], 0)
        self.assertEqual(body["rows"], [])

    def test_wip_qty_dan_queue_depth_per_wc(self):
        self._seed()

        body = self.api.get(WIP_URL).json()

        per_code = {row["wc_code"]: row for row in body["rows"]}
        self.assertEqual(per_code["SEW-01"]["wip_qty"], 15)  # 10 + 5 (DONE dikecualikan)
        self.assertEqual(per_code["SEW-01"]["queue_depth"], 2)
        self.assertEqual(per_code["SEW-02"]["wip_qty"], 7)
        self.assertEqual(per_code["SEW-02"]["queue_depth"], 1)
        self.assertEqual(body["total_wip"], 22)

    def test_total_wip_group_by_none(self):
        self._seed()

        body = self.api.get(WIP_URL, {"group_by": "none"}).json()

        self.assertEqual(body["total_wip"], 22)

    def test_group_by_invalid_400(self):
        self.assertEqual(
            self.api.get(WIP_URL, {"group_by": "line"}).status_code, 400
        )


class ReportsWipGapTests(TestCase):
    """G4 (aditif) — label / unit / trend / series."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="wip-gap", password="x")

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    @staticmethod
    def _seed():
        work_center = WorkCenter.objects.create(code="SEW-01", name="Sewing 1")
        work_order = make_work_order()
        make_bundle(
            work_order=work_order, code="B1", qty=10, state="SEWING", current_work_center=work_center
        )
        make_bundle(
            work_order=work_order, code="B2", qty=5, state="CUTTING", current_work_center=work_center
        )
        return work_center

    def test_row_field_baru_aditif(self):
        self._seed()

        row = self.api.get(WIP_URL).json()["rows"][0]

        self.assertEqual(row["label"], row["wc_name"])
        self.assertEqual(row["unit"], "pcs")
        self.assertEqual(len(row["trend"]), 7)
        self.assertEqual(len(row["series"]), 7)
        self.assertEqual(
            row["series"][0],
            {"x": row["trend"][0]["date"], "y": row["trend"][0]["value"]},
        )
        dates = [point["date"] for point in row["trend"]]
        self.assertEqual(dates, sorted(dates))

    def test_trend_hari_ini_sama_wip_qty(self):
        self._seed()

        row = self.api.get(WIP_URL).json()["rows"][0]

        self.assertEqual(row["trend"][-1]["value"], row["wip_qty"])

