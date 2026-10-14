"""Test paginator chatter: encode/decode cursor + paginate_events (Kontrak §8)."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps_industry.garment.api.chatter.paginator import (
    decode_cursor,
    encode_cursor,
    paginate_events,
)
from apps_industry.garment.models import BundleEvent
from apps_industry.garment.tests.factories import make_bundle


class CursorTests(TestCase):
    """Cursor = base64 dari `<ts ISO>|<id>`."""

    def test_encode_decode_round_trip(self):
        ts = timezone.now().replace(microsecond=123456)
        cursor = encode_cursor(ts, "abc-123")

        decoded = decode_cursor(cursor)

        self.assertIsNotNone(decoded)
        self.assertEqual(decoded[0], ts)
        self.assertEqual(decoded[1], "abc-123")

    def test_decode_cursor_kosong_atau_invalid(self):
        self.assertIsNone(decode_cursor(None))
        self.assertIsNone(decode_cursor(""))
        self.assertIsNone(decode_cursor("bukan-base64!!"))
        self.assertIsNone(decode_cursor("dGFuZ2dhbC10YW5wYS1waXBl"))  # tanpa pemisah "|"
        self.assertIsNone(decode_cursor(encode_cursor(timezone.now(), "")))


class PaginateEventsTests(TestCase):
    """Urutan terbaru dulu, halaman berikutnya lewat cursor."""

    @classmethod
    def setUpTestData(cls):
        cls.bundle = make_bundle(code="BND-001")
        for index in range(7):
            BundleEvent.objects.create(
                bundle=cls.bundle, event_type=f"EVENT_{index}", text=f"event {index}"
            )

    def _events(self):
        return BundleEvent.objects.filter(bundle=self.bundle)

    def test_halaman_pertama_terbaru_dulu(self):
        page = paginate_events(self._events(), limit=5)

        self.assertEqual(len(page["preview"]), 5)
        self.assertTrue(page["has_more"])
        self.assertIsNotNone(page["next_cursor"])
        self.assertEqual(page["preview"][0]["type"], "EVENT_6")
        self.assertEqual(page["preview"][-1]["type"], "EVENT_2")

    def test_halaman_berikutnya_lewat_cursor(self):
        pertama = paginate_events(self._events(), limit=5)

        kedua = paginate_events(self._events(), limit=5, cursor=pertama["next_cursor"])

        self.assertEqual(
            [event["type"] for event in kedua["preview"]], ["EVENT_1", "EVENT_0"]
        )
        self.assertFalse(kedua["has_more"])
        self.assertIsNone(kedua["next_cursor"])

    def test_cursor_invalid_dianggap_halaman_pertama(self):
        page = paginate_events(self._events(), limit=5, cursor="cursor-ngawur")

        self.assertEqual(page["preview"][0]["type"], "EVENT_6")
        self.assertTrue(page["has_more"])

    def test_tanpa_event(self):
        bundle_lain = make_bundle(code="BND-002")

        page = paginate_events(BundleEvent.objects.filter(bundle=bundle_lain))

        self.assertEqual(page, {"preview": [], "has_more": False, "next_cursor": None})

    def test_shape_event_kontrak_dan_actor_system(self):
        """Fase B.2: event = `{id, actor:{id,name}, type, summary, payload, created_at}`."""
        BundleEvent.objects.filter(bundle=self.bundle).delete()
        event = BundleEvent.objects.create(
            bundle=self.bundle, event_type="SCRAP", text="scrap 2 pcs", payload={"qty": 2}
        )

        page = paginate_events(self._events())
        event_payload = page["preview"][0]

        self.assertEqual(len(page["preview"]), 1)
        self.assertEqual(
            set(event_payload),
            {"id", "actor", "type", "summary", "payload", "created_at"},
        )
        self.assertEqual(event_payload["id"], str(event.pk))
        self.assertEqual(event_payload["actor"], {"id": "system", "name": "System"})
        self.assertEqual(event_payload["type"], "SCRAP")
        self.assertEqual(event_payload["summary"], "scrap 2 pcs")
        self.assertEqual(event_payload["payload"], {"qty": 2})
        self.assertEqual(event_payload["created_at"], event.ts.isoformat())

    def test_actor_diambil_dari_user(self):
        user = get_user_model().objects.create_user(
            username="operator1", password="rahasia123"
        )
        BundleEvent.objects.create(
            bundle=self.bundle, event_type="BUNDLE_START", actor=user
        )

        page = paginate_events(self._events(), limit=1)

        self.assertEqual(
            page["preview"][0]["actor"], {"id": str(user.pk), "name": "operator1"}
        )
