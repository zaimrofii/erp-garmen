"""Test kasus gagal endpoint schema + regression `/api/health/`."""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.tests.factories import make_bundle


class SchemaNotFoundTests(TestCase):
    """404 untuk resource/id yang tidak ada; 405 untuk method salah."""

    @classmethod
    def setUpTestData(cls):
        cls.bundle = make_bundle(code="BND-001")

    def setUp(self):
        self.client = APIClient()

    def test_resource_tidak_dikenal_404(self):
        # H2.1: `/garmen/orders/` kini endpoint nyata ⇒ placeholder diganti.
        response = self.client.get("/api/v1/garmen/tidak-ada/1/schema/")

        self.assertEqual(response.status_code, 404)
        self.assertIn("tidak-ada", response.json()["detail"])

    def test_id_bundle_tidak_ada_404(self):
        response = self.client.get("/api/v1/garmen/bundles/999999/schema/")

        self.assertEqual(response.status_code, 404)
        self.assertIn("999999", response.json()["detail"])

    def test_id_work_order_tidak_ada_404(self):
        response = self.client.get("/api/v1/garmen/work-orders/999999/schema/")

        self.assertEqual(response.status_code, 404)

    def test_nama_resource_case_insensitive(self):
        response = self.client.get(f"/api/v1/garmen/BUNDLES/{self.bundle.pk}/schema/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["resource"]["name"], "bundles")

    def test_method_post_tidak_diizinkan(self):
        response = self.client.post(
            f"/api/v1/garmen/bundles/{self.bundle.pk}/schema/", {}
        )

        self.assertEqual(response.status_code, 405)

    def test_health_endpoint_tetap_jalan(self):
        response = self.client.get("/api/health/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
