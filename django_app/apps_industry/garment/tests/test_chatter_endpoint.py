"""Test endpoint chatter: paginasi cursor untuk bundle & work-order (kontrak §3/§8)."""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.models import BundleEvent
from apps_industry.garment.tests.factories import make_bundle, make_work_order


class ChatterEndpointTests(TestCase):
    """Bundle A (7 event, milik WO-001) + Bundle B (1 event, WO lain)."""

    @classmethod
    def setUpTestData(cls):
        cls.work_order = make_work_order(code="WO-001")
        cls.bundle = make_bundle(work_order=cls.work_order, code="BND-001")
        cls.bundle_lain = make_bundle(code="BND-002")
        for index in range(7):
            BundleEvent.objects.create(
                bundle=cls.bundle, event_type=f"EVENT_{index}", text=f"e{index}"
            )
        BundleEvent.objects.create(bundle=cls.bundle_lain, event_type="LAIN")

    def setUp(self):
        self.client = APIClient()

    def test_chatter_bundle_dengan_limit_dan_cursor(self):
        halaman_1 = self.client.get(
            f"/api/v1/chatter/bundles/{self.bundle.pk}", {"limit": 5}
        )
        self.assertEqual(halaman_1.status_code, 200)
        body_1 = halaman_1.json()
        # Kontrak `ChatterPage` (Fase B.2).
        self.assertEqual(
            set(body_1), {"preview", "total_count", "has_more", "next_cursor"}
        )
        self.assertEqual(len(body_1["preview"]), 5)
        self.assertEqual(body_1["total_count"], 7)
        self.assertTrue(body_1["has_more"])
        self.assertIsNotNone(body_1["next_cursor"])
        self.assertEqual(body_1["preview"][0]["type"], "EVENT_6")

        halaman_2 = self.client.get(
            f"/api/v1/chatter/bundles/{self.bundle.pk}",
            {"limit": 5, "cursor": body_1["next_cursor"]},
        )
        body_2 = halaman_2.json()
        self.assertEqual(
            [event["type"] for event in body_2["preview"]], ["EVENT_1", "EVENT_0"]
        )
        self.assertEqual(body_2["total_count"], 7)  # total seluruh event, bukan halaman
        self.assertFalse(body_2["has_more"])
        self.assertIsNone(body_2["next_cursor"])

    def test_chatter_default_limit_sama_dengan_preview_kontrak(self):
        """Default = 5 (= `CHATTER_PREVIEW_LIMIT`) supaya lolos `ChatterPageSchema`."""
        response = self.client.get(f"/api/v1/chatter/bundles/{self.bundle.pk}")

        body = response.json()
        self.assertEqual(len(body["preview"]), 5)
        self.assertEqual(body["total_count"], 7)
        self.assertTrue(body["has_more"])
        self.assertIsNotNone(body["next_cursor"])

    def test_chatter_limit_besar_mengembalikan_semua_event(self):
        response = self.client.get(
            f"/api/v1/chatter/bundles/{self.bundle.pk}", {"limit": 20}
        )

        body = response.json()
        self.assertEqual(len(body["preview"]), 7)
        self.assertEqual(body["total_count"], 7)
        self.assertFalse(body["has_more"])
        self.assertIsNone(body["next_cursor"])

    def test_cursor_invalid_dianggap_halaman_pertama(self):
        response = self.client.get(
            f"/api/v1/chatter/bundles/{self.bundle.pk}",
            {"limit": 5, "cursor": "cursor-ngawur"},
        )

        body = response.json()
        self.assertEqual(body["preview"][0]["type"], "EVENT_6")
        self.assertTrue(body["has_more"])

    def test_chatter_work_order_menggabungkan_event_semua_bundlenya(self):
        response = self.client.get(
            f"/api/v1/chatter/work-orders/{self.work_order.pk}", {"limit": 20}
        )

        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(body["preview"]), 7)  # event bundle B tidak ikut
        self.assertEqual(body["total_count"], 7)
        self.assertNotIn("LAIN", [event["type"] for event in body["preview"]])

    def test_chatter_alias_v1_juga_jalan(self):
        response = self.client.get(f"/api/v1/chatter/bundles/{self.bundle.pk}")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["preview"]), 5)  # default = PAGE_SIZE
        self.assertEqual(body["total_count"], 7)

    def test_limit_di_luar_batas_400(self):
        response = self.client.get(
            f"/api/v1/chatter/bundles/{self.bundle.pk}", {"limit": 999}
        )

        self.assertEqual(response.status_code, 400)

    def test_resource_tidak_dikenal_404(self):
        response = self.client.get("/api/v1/chatter/orders/1")

        self.assertEqual(response.status_code, 404)
        self.assertIn("orders", response.json()["detail"])
