"""Test broadcast event bus -> group WebSocket (Fase E).

Dua lapis yang diuji:
  * **PURE** — pemetaan event -> group + pesan (`websocket.route`/`group_for`);
  * **fail-safe** — `broadcast()` tanpa channel layer / saat `group_send` error
    tidak pernah melempar exception (event bus tidak boleh mati).
"""

from __future__ import annotations

from unittest import mock

from django.test import SimpleTestCase

from core.event_bus import signals, websocket

BUNDLE_EVENT = {
    "id": "c0ffee00-0000-4000-8000-000000000001",
    "actor": {"id": "system", "name": "System"},
    "type": "BUNDLE_QC",
    "summary": "BUNDLE_QC → QC",
    "payload": {"state": "QC"},
    "created_at": "2026-01-01T00:00:00+00:00",
}


class RouteTests(SimpleTestCase):
    """Pemetaan event -> group (tanpa DB, tanpa channel layer)."""

    def test_bundle_state_changed_ke_group_bundle(self):
        group, message = websocket.route(
            signals.BUNDLE_STATE_CHANGED, {"bundle_id": 42, "event": BUNDLE_EVENT}
        )

        self.assertEqual(group, "bundle.42")
        self.assertEqual(message["type"], "bundle_event")
        self.assertEqual(message["resource"], "bundles")
        self.assertEqual(message["id"], "42")
        self.assertEqual(message["event_name"], "BUNDLE_STATE_CHANGED")
        self.assertEqual(message["event"], BUNDLE_EVENT)
        self.assertIn("occurred_at", message)

    def test_scrap_recorded_ikut_group_bundle(self):
        group, message = websocket.route(signals.SCRAP_RECORDED, {"bundle_id": 7})

        self.assertEqual(group, "bundle.7")
        self.assertEqual(message["resource"], "bundles")

    def test_work_order_state_changed_ke_group_work_order(self):
        group, message = websocket.route(signals.WORK_ORDER_STATE_CHANGED, {"wo_id": 3})

        self.assertEqual(group, "work_order.3")
        self.assertEqual(message["type"], "work_order_event")
        self.assertEqual(message["resource"], "work-orders")
        self.assertEqual(message["event"], {})  # chatter WO tidak dibuat di sini

    def test_event_tanpa_id_tidak_dirutekan(self):
        self.assertIsNone(websocket.route(signals.BUNDLE_STATE_CHANGED, {}))
        self.assertIsNone(websocket.route(signals.BUNDLE_STATE_CHANGED, {"bundle_id": ""}))

    def test_event_belum_dipetakan_tidak_dirutekan(self):
        self.assertIsNone(websocket.route(signals.ERP_SYNC_COMPLETED, {"stage": "FG"}))
        self.assertIsNone(websocket.route("EVENT_ASING", {"bundle_id": 1}))

    def test_id_aneh_ditolak(self):
        """Id dengan spasi/karakter aneh tidak pernah jadi nama group."""
        self.assertIsNone(websocket.resource_group("bundles", "a b"))
        self.assertIsNone(websocket.resource_group("bundles", None))
        self.assertIsNone(websocket.resource_group("orders", 1))
        self.assertEqual(websocket.resource_group("work-orders", 12), "work_order.12")

    def test_event_bukan_dict_diganti_dict_kosong(self):
        """Payload cacat tetap menghasilkan pesan valid (klien tidak crash)."""
        _, message = websocket.route(signals.BUNDLE_STATE_CHANGED, {"bundle_id": 1, "event": "x"})

        self.assertEqual(message["event"], {})


class BroadcastTests(SimpleTestCase):
    """`broadcast()` — jalur Redis/Channels + fail-safe."""

    def setUp(self):
        super().setUp()
        websocket.reset_channel_layer_cache()

    def tearDown(self):
        websocket.reset_channel_layer_cache()
        super().tearDown()

    def test_mengirim_ke_group_lewat_channel_layer(self):
        """group_send dipanggil dengan group + pesan yang benar (layer asli in-memory)."""
        calls: list[tuple[str, dict]] = []

        class FakeLayer:
            async def group_send(self, group, message):
                calls.append((group, message))

        with mock.patch("channels.layers.get_channel_layer", return_value=FakeLayer()):
            sent = websocket.broadcast(signals.BUNDLE_STATE_CHANGED, {"bundle_id": 5})

        self.assertTrue(sent)
        self.assertEqual(len(calls), 1)
        group, message = calls[0]
        self.assertEqual(group, "bundle.5")
        self.assertEqual(message["type"], "bundle_event")

    def test_layer_in_memory_mode_test(self):
        """Mode test memakai InMemoryChannelLayer → group_send tidak butuh Redis."""
        sent = websocket.broadcast(signals.BUNDLE_STATE_CHANGED, {"bundle_id": 9})

        self.assertTrue(sent)

    def test_tanpa_channel_layer_tidak_crash(self):
        """CHANNEL_LAYERS kosong → warning + False (fail-safe)."""
        with mock.patch("channels.layers.get_channel_layer", return_value=None):
            sent = websocket.broadcast(signals.BUNDLE_STATE_CHANGED, {"bundle_id": 5})

        self.assertFalse(sent)

    def test_group_send_error_tidak_crash(self):
        """Redis mati / error → False, bukan exception yang mematikan request."""

        class BoomLayer:
            async def group_send(self, group, message):
                raise RuntimeError("redis down")

        with mock.patch("channels.layers.get_channel_layer", return_value=BoomLayer()):
            with self.assertLogs("core.event_bus.websocket", level="WARNING"):
                sent = websocket.broadcast(signals.BUNDLE_STATE_CHANGED, {"bundle_id": 5})

        self.assertFalse(sent)

    def test_event_tidak_dirutekan_tidak_memanggil_layer(self):
        with mock.patch("channels.layers.get_channel_layer") as getter:
            sent = websocket.broadcast(signals.ERP_SYNC_COMPLETED, {"stage": "FG"})

        self.assertFalse(sent)
        getter.assert_not_called()
