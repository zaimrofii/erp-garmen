"""Test `EventConsumer` (Fase E) — connect/subscribe/event/disconnect via ASGI.

Dipakai `WebsocketCommunicator` dari Channels sehingga yang diuji adalah jalur
**ASGI sungguhan** (`config.asgi.application`) dengan layer in-memory (mode test,
tidak butuh Redis): koneksi, query param `?resource=&id=`, subscribe, penerusan
event, unsubscribe, dan pembersihan group saat klien hilang.
"""

from __future__ import annotations

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.test import TestCase

from config.asgi import application
from core.event_bus import consumers, signals, websocket

BUNDLE_EVENT = {
    "id": "c0ffee00-0000-4000-8000-000000000002",
    "actor": {"id": "system", "name": "System"},
    "type": "BUNDLE_QC",
    "summary": "BUNDLE_QC → QC",
    "payload": {"state": "QC"},
    "created_at": "2026-01-01T00:00:00+00:00",
}


async def send_to_group(group: str, message: dict) -> None:
    """Kirim pesan secara async ke group (mensimulasikan publisher -> broadcast).

    Harus async + di-`await` dari dalam test: memanggil `async_to_sync` di thread
    yang sama dengan event loop aktif dilarang asgiref.
    """
    await get_channel_layer().group_send(group, message)


def auth_user(username: str = "ws-user"):
    """User untuk koneksi WS terautentikasi (FASE 4.1)."""
    return get_user_model().objects.create_user(username=username, password="x")


class UserScopedApp:
    """Bungkus ASGI app: sisipkan ``scope["user"]`` yang sudah tersimpan.

    FASE 4.1: consumer menolak anonim, jadi test butuh scope ber-user. Alih-alih
    mengirim cookie sesi (yang membuat `AuthMiddlewareStack` memuat sesi dari DB
    **di dalam event loop ASGI** → meninggalkan koneksi sinkron test tertutup),
    user disuntikkan ke scope: `channels.auth.get_user` memakai `scope["user"]`
    kalau sudah ada, jadi jalur sesi/DB tidak disentuh sama sekali.
    """

    def __init__(self, user) -> None:
        self.user = user

    async def __call__(self, scope, receive, send):
        scope["user"] = self.user
        return await application(scope, receive, send)


class ConsumerPureTests(TestCase):
    """Helper murni consumer (tanpa koneksi)."""

    def test_parse_query_menerima_bytes_dan_str(self):
        self.assertEqual(
            consumers.parse_query(b"resource=bundles&id=7"),
            {"resource": "bundles", "id": "7"},
        )
        self.assertEqual(consumers.parse_query("resource=bundles&id=7")["id"], "7")
        self.assertEqual(consumers.parse_query(None), {})
        self.assertEqual(consumers.parse_query(b""), {})

    def test_subscription_group(self):
        self.assertEqual(consumers.subscription_group(b"?resource=bundles&id=7"), "bundle.7")
        self.assertEqual(
            consumers.subscription_group(b"?resource=work-orders&id=3"), "work_order.3"
        )
        self.assertIsNone(consumers.subscription_group(b"resource=bundles"))  # id hilang
        self.assertIsNone(consumers.subscription_group(b"resource=orders&id=1"))

    def test_public_payload_whitelist(self):
        payload = consumers.public_payload(
            {
                "type": "bundle_event",
                "resource": "bundles",
                "id": "1",
                "event_name": "BUNDLE_STATE_CHANGED",
                "occurred_at": "2026-01-01T00:00:00+00:00",
                "event": BUNDLE_EVENT,
                "rahasia_internal": "jangan dikirim",
            }
        )

        self.assertNotIn("rahasia_internal", payload)
        self.assertEqual(payload["event"], BUNDLE_EVENT)


class EventConsumerTests(TestCase):
    """Jalur ASGI nyata (`ws/events/`) dengan layer in-memory.

    FASE 4.1: consumer menolak anonim → tiap test membawa sesi Django yang sah.
    """

    @classmethod
    def setUpTestData(cls):
        # FASE 4.1: user dibuat SEKALI per kelas, sebelum koneksi ASGI mana pun
        # berjalan — supaya `setUp` tiap test tidak menyentuh DB (kerja WS
        # meninggalkan koneksi sinkron test dalam keadaan tertutup).
        cls.user = auth_user()

    def communicator(self, path: str = "/ws/events/") -> WebsocketCommunicator:
        """`WebsocketCommunicator` dengan scope ber-user (BUKAN anonim)."""
        return WebsocketCommunicator(UserScopedApp(self.user), path)

    def test_connect_tanpa_query_masuk_group_default(self):
        async_to_sync(self._connect_default)()

    async def _connect_default(self):
        communicator = self.communicator("/ws/events/")
        connected, _ = await communicator.connect()

        self.assertTrue(connected)
        self.assertEqual(
            await communicator.receive_json_from(),
            {"type": "connected", "groups": [websocket.DEFAULT_GROUP]},
        )
        await communicator.disconnect()

    def test_connect_dengan_query_param_masuk_group_bundle(self):
        async_to_sync(self._connect_with_query)()

    async def _connect_with_query(self):
        communicator = self.communicator("/ws/events/?resource=bundles&id=42")
        connected, _ = await communicator.connect()

        self.assertTrue(connected)
        hello = await communicator.receive_json_from()
        self.assertEqual(hello["groups"], [websocket.DEFAULT_GROUP, "bundle.42"])
        await communicator.disconnect()

    def test_query_param_tidak_valid_hanya_group_default(self):
        async_to_sync(self._connect_invalid_query)()

    async def _connect_invalid_query(self):
        communicator = self.communicator("/ws/events/?resource=orders&id=1")
        connected, _ = await communicator.connect()

        self.assertTrue(connected)
        hello = await communicator.receive_json_from()
        self.assertEqual(hello["groups"], [websocket.DEFAULT_GROUP])
        await communicator.disconnect()

    def test_subscribe_dan_terima_event_bundle(self):
        async_to_sync(self._subscribe_and_receive)()

    async def _subscribe_and_receive(self):
        communicator = self.communicator("/ws/events/")
        await communicator.connect()
        await communicator.receive_json_from()  # hello

        await communicator.send_json_to({"type": "subscribe", "resource": "bundles", "id": 42})
        self.assertEqual(
            await communicator.receive_json_from(),
            {"type": "subscribed", "group": "bundle.42"},
        )

        # Publisher -> group_send (bentuk dari `websocket.channel_message`).
        _, message = websocket.route(
            signals.BUNDLE_STATE_CHANGED, {"bundle_id": 42, "event": BUNDLE_EVENT}
        )
        await send_to_group("bundle.42", message)

        delivered = await communicator.receive_json_from()
        self.assertEqual(delivered["type"], "bundle_event")
        self.assertEqual(delivered["resource"], "bundles")
        self.assertEqual(delivered["id"], "42")
        self.assertEqual(delivered["event_name"], "BUNDLE_STATE_CHANGED")
        self.assertEqual(delivered["event"], BUNDLE_EVENT)
        await communicator.disconnect()

    def test_subscribe_tanpa_id_masuk_group_default(self):
        async_to_sync(self._subscribe_default)()

    async def _subscribe_default(self):
        communicator = self.communicator("/ws/events/")
        await communicator.connect()
        await communicator.receive_json_from()

        await communicator.send_json_to({"type": "subscribe"})
        self.assertEqual(
            await communicator.receive_json_from(),
            {"type": "subscribed", "group": websocket.DEFAULT_GROUP},
        )
        await communicator.disconnect()

    def test_subscribe_tidak_valid_dibalas_error(self):
        async_to_sync(self._subscribe_invalid)()

    async def _subscribe_invalid(self):
        communicator = self.communicator("/ws/events/")
        await communicator.connect()
        await communicator.receive_json_from()

        await communicator.send_json_to({"type": "subscribe", "resource": "bundles"})
        reply = await communicator.receive_json_from()

        self.assertEqual(reply["type"], "error")
        self.assertEqual(reply["reason"], "invalid_subscription")
        await communicator.disconnect()

    def test_event_work_order_diteruskan(self):
        async_to_sync(self._receive_work_order)()

    async def _receive_work_order(self):
        communicator = self.communicator("/ws/events/?resource=work-orders&id=3")
        await communicator.connect()
        await communicator.receive_json_from()

        _, message = websocket.route(signals.WORK_ORDER_STATE_CHANGED, {"wo_id": 3})
        await send_to_group("work_order.3", message)

        delivered = await communicator.receive_json_from()
        self.assertEqual(delivered["type"], "work_order_event")
        self.assertEqual(delivered["resource"], "work-orders")
        await communicator.disconnect()

    def test_ping_pong_dan_tipe_asing(self):
        async_to_sync(self._ping_and_unknown)()

    async def _ping_and_unknown(self):
        communicator = self.communicator("/ws/events/")
        await communicator.connect()
        await communicator.receive_json_from()

        await communicator.send_json_to({"type": "ping"})
        self.assertEqual(await communicator.receive_json_from(), {"type": "pong"})

        await communicator.send_json_to({"type": "apa_pun"})
        self.assertEqual(
            await communicator.receive_json_from(),
            {"type": "error", "reason": "unknown_message_type"},
        )

        # Kirim JSON rusak: dijawab error, koneksi TETAP hidup.
        await communicator.send_to(text_data="{bukan json}")
        self.assertEqual(
            await communicator.receive_json_from(),
            {"type": "error", "reason": "invalid_json"},
        )

        await communicator.send_json_to({"type": "ping"})
        self.assertEqual(await communicator.receive_json_from(), {"type": "pong"})
        await communicator.disconnect()

    def test_unsubscribe_stop_penerimaan_event(self):
        async_to_sync(self._unsubscribe)()

    async def _unsubscribe(self):
        communicator = self.communicator("/ws/events/?resource=bundles&id=5")
        await communicator.connect()
        await communicator.receive_json_from()

        await communicator.send_json_to({"type": "unsubscribe", "group": "bundle.5"})
        self.assertEqual(
            await communicator.receive_json_from(),
            {"type": "unsubscribed", "group": "bundle.5"},
        )

        _, message = websocket.route(signals.BUNDLE_STATE_CHANGED, {"bundle_id": 5})
        await send_to_group("bundle.5", message)

        self.assertTrue(await communicator.receive_nothing(timeout=0.2))
        await communicator.disconnect()

    def test_unsubscribe_group_yang_tidak_diikuti_dibalas_error(self):
        async_to_sync(self._unsubscribe_unknown)()

    async def _unsubscribe_unknown(self):
        communicator = self.communicator("/ws/events/")
        await communicator.connect()
        await communicator.receive_json_from()

        await communicator.send_json_to({"type": "unsubscribe", "group": "bundle.404"})
        reply = await communicator.receive_json_from()

        self.assertEqual(reply["type"], "error")
        self.assertEqual(reply["reason"], "not_subscribed")
        await communicator.disconnect()

    def test_disconnect_membersihkan_semua_group(self):
        async_to_sync(self._disconnect_clears_groups)()

    async def _disconnect_clears_groups(self):
        channel_layer = get_channel_layer()
        communicator = self.communicator("/ws/events/?resource=bundles&id=77")
        await communicator.connect()
        await communicator.receive_json_from()

        await communicator.disconnect()

        registry = getattr(channel_layer, "_groups", {})
        self.assertEqual(set(registry.get("bundle.77", set())), set())
        self.assertEqual(set(registry.get(websocket.DEFAULT_GROUP, set())), set())

    # ------------------------------------------------------------ FASE 4.1 auth
    def test_connect_anonim_ditolak_4401(self):
        """Koneksi tanpa sesi → ditutup `4401`, tidak masuk group mana pun."""
        async_to_sync(self._connect_anonymous)()

    async def _connect_anonymous(self):
        communicator = WebsocketCommunicator(application, "/ws/events/")

        connected, close_code = await communicator.connect()

        self.assertFalse(connected)
        self.assertEqual(close_code, consumers.WS_CLOSE_UNAUTHORIZED)
        self.assertEqual(consumers.WS_CLOSE_UNAUTHORIZED, 4401)
