"""Test routing & whitelist industri (Fase A).

Yang dijaga di sini:

  * ``GET /api/v1/metadata/<resource>/`` = metadata resource (dulu path ini jatuh
    ke view list dengan ``industry="metadata"`` → 200 berisi payload salah);
  * ``industry`` tak dikenal → **404 eksplisit** (bukan 200 payload salah);
  * ``/api/v1/chatter/bundles/<id>/`` (trailing slash) = body chatter, bukan
    detail bundle;
  * path kontrak tidak boleh redirect 301.
"""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.models import BundleEvent
from apps_industry.garment.models import Bundle, BundleEvent
from apps_industry.garment.tests.auth import authenticate
from apps_industry.garment.tests.factories import make_bundle

#: Key metadata yang sudah terkunci kontrak §1 (bentuk JSON TIDAK diubah Fase A).
METADATA_KEYS_KONTRAK = {
    "resource",
    "industry",
    "view_type",
    "schema_version",
    "title",
    "version",
    "device_hint",
    "state_machine",
    "layout",
    "chatter",
}


class MetadataRouteTests(TestCase):
    """`/api/v1/metadata/<resource>/` — metadata resource tanpa id di URL."""

    @classmethod
    def setUpTestData(cls):
        cls.bundle = make_bundle(code="BND-001")

    def setUp(self):
        self.client = APIClient()

    def test_metadata_bundles_200_metadata_bukan_listpage(self):
        response = self.client.get("/api/v1/metadata/bundles/")

        self.assertEqual(response.status_code, 200)  # bukan 301, bukan 404
        body = response.json()
        self.assertEqual(set(body), METADATA_KEYS_KONTRAK)
        # Fase B.1.1: `resource` = objek (dulu string) — inilah yang bikin Zod lolos.
        self.assertEqual(body["resource"]["name"], "bundles")
        self.assertEqual(body["resource"]["id"], str(self.bundle.pk))
        self.assertEqual(body["schema_version"], "1.0")
        self.assertEqual(response["X-Schema-Version"], "1.0")
        self.assertNotIn("rows", body)  # dulu justru envelope ListPage
        self.assertNotIn("total", body)

    def test_metadata_tanpa_trailing_slash_200(self):
        """Path persis kontrak §3 (`/api/v1/metadata/{resource}`) tidak redirect."""
        response = self.client.get("/api/v1/metadata/bundles")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["resource"]["name"], "bundles")

    def test_metadata_id_eksplisit(self):
        response = self.client.get("/api/v1/metadata/bundles/", {"id": self.bundle.pk})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["title"], "Bundle #BND-001")

    def test_metadata_id_tidak_ada_404(self):
        response = self.client.get("/api/v1/metadata/bundles/", {"id": 999999})

        self.assertEqual(response.status_code, 404)
        self.assertIn("999999", response.json()["detail"])

    def test_metadata_id_bukan_angka_400(self):
        response = self.client.get("/api/v1/metadata/bundles/", {"id": "abc"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("id", response.json()["detail"])

    def test_metadata_resource_tidak_dikenal_404(self):
        response = self.client.get("/api/v1/metadata/xxx/")

        self.assertEqual(response.status_code, 404)
        self.assertIn("xxx", response.json()["detail"])

    def test_metadata_resource_tanpa_data_404(self):
        """`qc` belum punya instance di test ini → 404 (bukan 500/200 kosong)."""
        response = self.client.get("/api/v1/metadata/qc/")

        self.assertEqual(response.status_code, 404)

    def test_metadata_industri_palsu_404(self):
        response = self.client.get("/api/v1/metadata/bundles/", {"industry": "palsu"})

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "industry tidak dikenal")


class IndustryWhitelistTests(TestCase):
    """Segment `<industry>` divalidasi → 404 eksplisit (Fase A.1)."""

    @classmethod
    def setUpTestData(cls):
        cls.bundle = make_bundle(code="BND-001")

    def setUp(self):
        self.client = APIClient()
        # FASE 4.1: ActionView kini `IsAuthenticated` — POST aksi di kelas ini
        # (test 404 industri palsu) butuh auth supaya yang diuji tetap 404 (bukan 403).
        authenticate(self.client)

    def test_industri_tidak_dikenal_404_bukan_200(self):
        response = self.client.get("/api/v1/unknown-industry/bundles/")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "industry tidak dikenal")

    def test_industri_palsu_404_di_schema_detail_dan_list(self):
        for path in (
            f"/api/v1/unknown-industry/bundles/{self.bundle.pk}/schema/",
            f"/api/v1/unknown-industry/bundles/{self.bundle.pk}/",
            "/api/v1/unknown-industry/bundles/",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json()["detail"], "industry tidak dikenal")

    def test_action_industri_palsu_404_tanpa_eksekusi(self):
        response = self.client.post(
            f"/api/v1/unknown-industry/bundles/{self.bundle.pk}/BUNDLE_START/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 404)
        self.bundle.refresh_from_db()
        self.assertEqual(self.bundle.state, "DRAFT")  # tidak ada state berubah

    def test_industri_valid_uppercase_dinormalkan(self):
        response = self.client.get("/api/v1/GARMEN/work-orders/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["industry"], "garmen")

    def test_industri_valid_regresi_200(self):
        for path in (
            "/api/v1/garmen/bundles/",
            "/api/v1/garmen/qc/",
            f"/api/v1/garmen/bundles/{self.bundle.pk}/",
            f"/api/v1/garmen/bundles/{self.bundle.pk}/schema/",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)


class CoreRouteOrderTests(TestCase):
    """Route kontrak core harus menang di atas pola industri (Fase A.4)."""

    def setUp(self):
        self.client = APIClient()

    def test_devices_me_tetap_200(self):
        response = self.client.get("/api/v1/devices/me")

        self.assertEqual(response.status_code, 200)
        self.assertIn("device_profile", response.json())

    def test_chatter_trailing_slash_200_body_chatter(self):
        bundle = make_bundle(code="BND-C1")
        BundleEvent.objects.create(bundle=bundle, event_type="E1", text="e1")

        tanpa_slash = self.client.get(f"/api/v1/chatter/bundles/{bundle.pk}")
        dengan_slash = self.client.get(f"/api/v1/chatter/bundles/{bundle.pk}/")

        for response in (tanpa_slash, dengan_slash):
            with self.subTest(status=response.status_code):
                self.assertEqual(response.status_code, 200)
                body = response.json()
                self.assertEqual(len(body["preview"]), 1)
                self.assertNotIn("code", body)  # bukan payload detail bundle

    def test_chatter_alias_root_tetap_jalan(self):
        bundle = make_bundle(code="BND-C2")

        response = self.client.get(f"/api/chatter/bundles/{bundle.pk}")

        self.assertEqual(response.status_code, 200)
        self.assertIn("preview", response.json())  # bentuk ChatterPage (Fase B.2)

    def test_health_tetap_200(self):
        response = self.client.get("/api/health/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")