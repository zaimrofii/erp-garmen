"""Test jejak event aksi (Fase E): action endpoint -> `BundleEvent` + event bus.

Membuktikan dua hal sekaligus tanpa mengubah kontrak response aksi (B.2/C):
  1. POST aksi menulis satu baris `BundleEvent` (sumber chatter §8);
  2. `publisher.publish` dipanggil dengan `bundle_id` + `event` bentuk chatter,
     sehingga `core.event_bus.websocket.broadcast` bisa mengirimnya ke group
     `bundle.<id>` (dibuktikan lewat group_send yang ditangkap layer palsu).
"""

from __future__ import annotations

from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.models import BundleEvent
from apps_industry.garment.tests.auth import authenticate
from apps_industry.garment.tests.factories import make_bundle
from core.event_bus import signals, websocket


class ActionEventPublishTests(TestCase):
    """Aksi pertama yang sah dari metadata harus muncul di chatter + event bus."""

    def setUp(self):
        # Cache channel layer di-reset supaya patch `get_channel_layer` benar-benar dipakai.
        websocket.reset_channel_layer_cache()
        self.client = APIClient()
        # FASE 4.1: ActionView kini `IsAuthenticated`.
        authenticate(self.client)
        self.bundle = make_bundle(code="BND-EVT-001")
        # Jalur metadata kontrak §3 (sama seperti frontend `loadResourceMetadata`).
        metadata = self.client.get(f"/api/v1/metadata/bundles/?id={self.bundle.pk}").json()
        self.actions = metadata["state_machine"]["allowed_actions"]
        self.assertNotEqual(self.actions, [], "bundle uji harus punya aksi sah")

    def tearDown(self):
        websocket.reset_channel_layer_cache()

    def post_action(self, action_id: str):
        """POST aksi lewat endpoint dari metadata (bukan path tebakan)."""
        return self.client.post(
            f"/api/v1/garmen/bundles/{self.bundle.pk}/{action_id}/",
            {},
            format="json",
        )

    def test_aksi_menulis_bundle_event(self):
        action_id = self.actions[0]["id"]
        sebelum = BundleEvent.objects.filter(bundle=self.bundle).count()

        response = self.post_action(action_id)

        self.assertEqual(response.status_code, 200)
        events = BundleEvent.objects.filter(bundle=self.bundle)
        self.assertEqual(events.count(), sebelum + 1)

        event = events.order_by("-ts", "-id").first()
        self.assertEqual(event.event_type, action_id)
        self.assertEqual(event.payload["state"], response.json()["state"])

    def test_aksi_memublikasikan_event_bus_dengan_bentuk_chatter(self):
        action_id = self.actions[0]["id"]

        with mock.patch("core.event_bus.publisher.publish") as publish:
            response = self.post_action(action_id)

        self.assertEqual(response.status_code, 200)
        publish.assert_called_once()
        event_name, payload = publish.call_args.args
        self.assertEqual(event_name, signals.BUNDLE_STATE_CHANGED)
        self.assertEqual(payload["bundle_id"], self.bundle.pk)
        self.assertEqual(payload["state"], response.json()["state"])

        # Bentuk `event` = chatter §8 (kontrak yang sama dengan metadata/chatter).
        event = payload["event"]
        self.assertEqual(set(event), {"id", "actor", "type", "summary", "payload", "created_at"})
        self.assertEqual(event["type"], action_id)
        self.assertEqual(event["payload"]["state"], response.json()["state"])

    def test_event_masuk_group_websocket_bundle(self):
        """publish() nyata -> group_send ke `bundle.<id>` (menutup rantai end-to-end)."""
        action_id = self.actions[0]["id"]
        sent: list[tuple[str, dict]] = []

        class FakeLayer:
            async def group_send(self, group, message):
                sent.append((group, message))

        with mock.patch("channels.layers.get_channel_layer", return_value=FakeLayer()):
            response = self.post_action(action_id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual([group for group, _ in sent], [f"bundle.{self.bundle.pk}"])
        message = sent[0][1]
        self.assertEqual(message["type"], "bundle_event")
        self.assertEqual(message["resource"], "bundles")
        self.assertEqual(message["id"], str(self.bundle.pk))
        self.assertEqual(message["event"]["type"], action_id)

    def test_aksi_tidak_sah_tidak_memublikasikan_event(self):
        with mock.patch("core.event_bus.publisher.publish") as publish:
            response = self.post_action("AKSI_TIDAK_ADA")

        self.assertEqual(response.status_code, 400)
        publish.assert_not_called()

    def test_chatter_metadata_ikut_menampilkan_event_aksi(self):
        """Metadata bundle (blok chatter) memuat event aksi terbaru → UI ikut hidup."""
        action_id = self.actions[0]["id"]
        self.post_action(action_id)

        metadata = self.client.get(f"/api/v1/metadata/bundles/?id={self.bundle.pk}").json()
        types = [event["type"] for event in metadata["chatter"]["preview"]]

        self.assertIn(action_id, types)
