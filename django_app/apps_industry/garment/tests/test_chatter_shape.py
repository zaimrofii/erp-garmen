"""Test bentuk response chatter endpoint (Fase B.2) — kontrak `ChatterPage` §8.

Frontend memvalidasi response ini dengan `ChatterPageSchema`
(`frontend_app/src/lib/schemas/chatter.schema.ts`):

    {preview: [...maks 5...], total_count, has_more, next_cursor}
    event = {id, actor:{id,name}, type, summary, payload, created_at}
"""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.models import BundleEvent
from apps_industry.garment.tests.factories import make_bundle, make_work_order

CHATTER_KEYS = {"preview", "total_count", "has_more", "next_cursor"}
EVENT_KEYS = {"id", "actor", "type", "summary", "payload", "created_at"}


class ChatterEndpointShapeTests(TestCase):
    """Bundle 7 event + 1 bundle lain tanpa event."""

    @classmethod
    def setUpTestData(cls):
        cls.work_order = make_work_order(code="WO-001")
        cls.bundle = make_bundle(work_order=cls.work_order, code="BND-001")
        cls.bundle_kosong = make_bundle(code="BND-002")
        for index in range(7):
            BundleEvent.objects.create(
                bundle=cls.bundle,
                event_type=f"EVENT_{index}",
                text=f"event {index}",
                payload={"index": index},
            )

    def setUp(self):
        self.client = APIClient()

    def _url(self):
        return f"/api/v1/chatter/bundles/{self.bundle.pk}"

    def test_empat_kunci_kontrak_tanpa_events(self):
        body = self.client.get(self._url()).json()

        self.assertEqual(set(body), CHATTER_KEYS)
        self.assertNotIn("events", body)  # bentuk lama sudah dihapus (B.2)

    def test_total_count_seluruh_event_bukan_hanya_halaman(self):
        body = self.client.get(self._url(), {"limit": 5}).json()

        self.assertEqual(len(body["preview"]), 5)
        self.assertEqual(body["total_count"], 7)
        self.assertTrue(body["has_more"])
        self.assertIsNotNone(body["next_cursor"])

    def test_bentuk_event_kontrak(self):
        event = self.client.get(self._url(), {"limit": 1}).json()["preview"][0]

        self.assertEqual(set(event), EVENT_KEYS)
        self.assertEqual(event["type"], "EVENT_6")
        self.assertEqual(event["summary"], "event 6")
        self.assertEqual(event["payload"], {"index": 6})
        self.assertEqual(event["actor"], {"id": "system", "name": "System"})
        self.assertTrue(event["created_at"])

    def test_halaman_kedua_lewat_cursor(self):
        pertama = self.client.get(self._url(), {"limit": 5}).json()
        kedua = self.client.get(
            self._url(), {"limit": 5, "cursor": pertama["next_cursor"]}
        ).json()

        self.assertEqual([event["type"] for event in kedua["preview"]], ["EVENT_1", "EVENT_0"])
        self.assertEqual(kedua["total_count"], 7)  # total tetap, bukan per halaman
        self.assertFalse(kedua["has_more"])
        self.assertIsNone(kedua["next_cursor"])

    def test_alias_root_dan_trailing_slash_bentuk_sama(self):
        variasi = (
            f"/api/v1/chatter/bundles/{self.bundle.pk}",
            f"/api/v1/chatter/bundles/{self.bundle.pk}/",
            f"/api/chatter/bundles/{self.bundle.pk}",
        )

        for path in variasi:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(set(response.json()), CHATTER_KEYS)

    def test_bundle_tanpa_event_kontrak_kosong(self):
        body = self.client.get(
            f"/api/v1/chatter/bundles/{self.bundle_kosong.pk}"
        ).json()

        self.assertEqual(
            body,
            {"preview": [], "total_count": 0, "has_more": False, "next_cursor": None},
        )

    def test_work_order_menggabungkan_event_semua_bundlenya(self):
        body = self.client.get(
            f"/api/v1/chatter/work-orders/{self.work_order.pk}", {"limit": 20}
        ).json()

        self.assertEqual(body["total_count"], 7)
        self.assertEqual(len(body["preview"]), 7)