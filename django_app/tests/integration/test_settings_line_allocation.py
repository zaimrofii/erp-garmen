"""Test endpoint settings line-allocation (F3A.2 / B25) — model BARU ``LineAllocationRule``.

``GET|POST /api/v1/settings/line-allocation/`` (migrasi ``0010_lineallocationrule``).
``IsAuthenticated`` untuk GET & POST → anonim 403.

Jalankan (SERIAL):

    docker compose exec django python -m pytest tests/integration/test_settings_line_allocation.py -q
"""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.models import LineAllocationRule
from apps_industry.garment.tests.factories import make_line
from core.auth.models import User

URL = "/api/v1/settings/line-allocation/"

TOP_KEYS = {"rows", "total_count", "has_more", "next_cursor"}
ROW_KEYS = {
    "id",
    "name",
    "wc_type",
    "line_id",
    "line_code",
    "priority",
    "is_active",
    "config",
    "created_at",
    "updated_at",
}


class SettingsLineAllocationAuthTests(TestCase):
    def test_anonim_get_403(self):
        self.assertEqual(APIClient().get(URL).status_code, 403)

    def test_anonim_post_403(self):
        response = APIClient().post(URL, {"name": "X"}, format="json")

        self.assertEqual(response.status_code, 403)


class SettingsLineAllocationGetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="set-alloc-get", password="x")

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    @staticmethod
    def _seed():
        line = make_line(code="LINE-1")
        LineAllocationRule.objects.create(
            name="Sewing Rendah", wc_type="SEWING", line=line, priority=1
        )
        LineAllocationRule.objects.create(
            name="Sewing Tinggi", wc_type="SEWING", line=line, priority=9
        )
        LineAllocationRule.objects.create(name="Cutting", wc_type="CUTTING", line=line)
        return line

    def test_shape_listpage_kosong(self):
        body = self.api.get(URL).json()

        self.assertEqual(set(body), TOP_KEYS)
        self.assertEqual(body["rows"], [])
        self.assertEqual(body["total_count"], 0)

    def test_list_shape_dan_line_code(self):
        line = self._seed()

        body = self.api.get(URL).json()

        self.assertEqual(body["total_count"], 3)
        row = body["rows"][0]
        self.assertEqual(set(row), ROW_KEYS)
        self.assertEqual(row["line_id"], line.pk)
        self.assertEqual(row["line_code"], "LINE-1")

    def test_urut_priority_desc(self):
        self._seed()

        rows = self.api.get(URL).json()["rows"]

        sewings = [row["priority"] for row in rows if row["wc_type"] == "SEWING"]
        self.assertEqual(sewings, [9, 1])

    def test_filter_wc_type_case_insensitive(self):
        self._seed()

        body = self.api.get(URL, {"wc_type": "sewing"}).json()

        self.assertEqual(body["total_count"], 2)
        self.assertTrue(all(row["wc_type"] == "SEWING" for row in body["rows"]))

    def test_limit_invalid_400(self):
        self.assertEqual(self.api.get(URL, {"limit": "abc"}).status_code, 400)


class SettingsLineAllocationPostTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="set-alloc-post", password="x")

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def test_post_sukses_201_dan_persist(self):
        line = make_line(code="LINE-A")
        payload = {
            "name": "Alokasi Sewing",
            "wc_type": "SEWING",
            "line_id": line.pk,
            "priority": 5,
            "config": {"kapasitas": 120},
        }

        response = self.api.post(URL, payload, format="json")

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(set(body), ROW_KEYS)
        self.assertEqual(body["wc_type"], "SEWING")
        self.assertEqual(body["line_id"], line.pk)
        self.assertEqual(body["line_code"], "LINE-A")
        self.assertEqual(body["priority"], 5)
        self.assertEqual(body["config"], {"kapasitas": 120})

        rule = LineAllocationRule.objects.get(pk=body["id"])
        self.assertEqual(rule.line_id, line.pk)
        self.assertTrue(rule.is_active)

    def test_post_line_id_tidak_ada_404(self):
        response = self.api.post(
            URL, {"name": "X", "wc_type": "SEWING", "line_id": 999999}, format="json"
        )

        self.assertEqual(response.status_code, 404)

    def test_post_default_priority_dan_config(self):
        line = make_line(code="LINE-B")

        body = self.api.post(
            URL,
            {"name": "Default", "wc_type": "QC", "line_id": line.pk},
            format="json",
        ).json()

        self.assertEqual(body["priority"], 0)
        self.assertEqual(body["config"], {})

    def test_post_tampil_di_list(self):
        line = make_line(code="LINE-C")
        self.api.post(
            URL,
            {"name": "Muncul", "wc_type": "CUTTING", "line_id": line.pk},
            format="json",
        )

        self.assertEqual(self.api.get(URL).json()["total_count"], 1)


class SettingsLineAllocationValidationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="set-alloc-val", password="x")

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)
        self.line = make_line(code="LINE-V")

    def test_name_kosong_400(self):
        response = self.api.post(
            URL,
            {"name": " ", "wc_type": "SEWING", "line_id": self.line.pk},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_wc_type_kosong_400(self):
        response = self.api.post(
            URL,
            {"name": "X", "wc_type": "  ", "line_id": self.line.pk},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_line_id_non_integer_400(self):
        response = self.api.post(
            URL, {"name": "X", "wc_type": "SEWING", "line_id": "abc"}, format="json"
        )

        self.assertEqual(response.status_code, 400)

    def test_config_bukan_objek_400(self):
        response = self.api.post(
            URL,
            {"name": "X", "wc_type": "SEWING", "line_id": self.line.pk, "config": [1]},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

