"""Test endpoint settings bundling (F3A.2 / B24) — model BARU ``BundlingRule``.

``GET|POST /api/v1/settings/bundling/`` (migrasi ``0009_bundlingrule``).
``IsAuthenticated`` untuk GET & POST → anonim 403.

Jalankan (SERIAL):

    docker compose exec django python -m pytest tests/integration/test_settings_bundling.py -q
"""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.models import BundlingRule
from core.auth.models import User

URL = "/api/v1/settings/bundling/"

TOP_KEYS = {"rows", "total_count", "has_more", "next_cursor"}
ROW_KEYS = {
    "id",
    "name",
    "size_matrix",
    "bundle_size_default",
    "is_active",
    "created_at",
    "updated_at",
}


class SettingsBundlingAuthTests(TestCase):
    def test_anonim_get_403(self):
        self.assertEqual(APIClient().get(URL).status_code, 403)

    def test_anonim_post_403(self):
        response = APIClient().post(URL, {"name": "X"}, format="json")

        self.assertEqual(response.status_code, 403)


class SettingsBundlingGetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="set-bnd-get", password="x")

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def test_shape_listpage_kosong(self):
        body = self.api.get(URL).json()

        self.assertEqual(set(body), TOP_KEYS)
        self.assertEqual(body["rows"], [])
        self.assertEqual(body["total_count"], 0)
        self.assertIsNone(body["next_cursor"])

    def test_list_dua_rule_urut_nama(self):
        BundlingRule.objects.create(name="B-Rule", size_matrix={"S": 10})
        BundlingRule.objects.create(name="A-Rule", bundle_size_default=12)

        body = self.api.get(URL).json()

        self.assertEqual(body["total_count"], 2)
        self.assertEqual([row["name"] for row in body["rows"]], ["A-Rule", "B-Rule"])
        self.assertEqual(set(body["rows"][0]), ROW_KEYS)
        self.assertEqual(body["rows"][1]["size_matrix"], {"S": 10})
        self.assertTrue(body["rows"][1]["is_active"])

    def test_pagination_limit(self):
        BundlingRule.objects.create(name="A")
        BundlingRule.objects.create(name="B")

        page1 = self.api.get(URL, {"limit": 1}).json()

        self.assertTrue(page1["has_more"])
        self.assertEqual(page1["next_cursor"], 1)

        page2 = self.api.get(URL, {"limit": 1, "cursor": 1}).json()

        self.assertFalse(page2["has_more"])

    def test_limit_invalid_400(self):
        self.assertEqual(self.api.get(URL, {"limit": "abc"}).status_code, 400)


class SettingsBundlingPostTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="set-bnd-post", password="x")

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def test_post_sukses_201_dan_persist(self):
        payload = {
            "name": "Rule Kaos",
            "size_matrix": {"S": 10, "M": 12},
            "bundle_size_default": 12,
        }

        response = self.api.post(URL, payload, format="json")

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(set(body), ROW_KEYS)
        self.assertEqual(body["name"], "Rule Kaos")
        self.assertEqual(body["size_matrix"], {"S": 10, "M": 12})
        self.assertEqual(body["bundle_size_default"], 12)

        rule = BundlingRule.objects.get(pk=body["id"])
        self.assertEqual(rule.size_matrix, {"S": 10, "M": 12})
        self.assertTrue(rule.is_active)

    def test_post_default_size_matrix_kosong(self):
        body = self.api.post(URL, {"name": "Default"}, format="json").json()

        self.assertEqual(body["size_matrix"], {})
        self.assertEqual(body["bundle_size_default"], 0)

    def test_post_dua_rule_total_dua(self):
        self.api.post(URL, {"name": "A"}, format="json")
        self.api.post(URL, {"name": "B"}, format="json")

        self.assertEqual(self.api.get(URL).json()["total_count"], 2)


class SettingsBundlingValidationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="set-bnd-val", password="x")

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def test_name_kosong_400(self):
        self.assertEqual(
            self.api.post(URL, {"name": "   "}, format="json").status_code, 400
        )

    def test_size_matrix_bukan_objek_400(self):
        response = self.api.post(
            URL, {"name": "X", "size_matrix": [1, 2]}, format="json"
        )

        self.assertEqual(response.status_code, 400)

    def test_bundle_size_default_negatif_400(self):
        response = self.api.post(
            URL, {"name": "X", "bundle_size_default": -1}, format="json"
        )

        self.assertEqual(response.status_code, 400)
