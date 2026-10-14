"""Consumer WebSocket event bus (Fase E) — `ws/events/`.

Kontrak klien (frontend `useWebSocket.ts`):

  1. **connect** — opsional query param ``?resource=bundles&id=42``. Tanpa query,
     klien otomatis masuk group default ``events`` (semua event domain).
     Balasan::

        {"type": "connected", "groups": ["events", "bundle.42"]}

  2. **subscribe** — ``{"type":"subscribe","resource":"bundles","id":42}``
     (atau tanpa argumen -> group default). Balasan::

        {"type": "subscribed", "group": "bundle.42"}

  3. **unsubscribe** — ``{"type":"unsubscribe","group":"bundle.42"}``.
  4. **ping** -> ``{"type":"pong"}`` (keep-alive manual; tidak ada timer di server).
  5. pesan lain -> ``{"type":"error","reason":"unknown_message_type"}`` — klien
     tidak pernah diputus hanya karena mengirim JSON yang tidak dikenal.

Event masuk dari publisher (`core.event_bus.publisher` -> `broadcast()`) dengan
key ``type`` = ``bundle_event`` / ``work_order_event`` (lihat
`core.event_bus.websocket.channel_message`) dan diteruskan **apa adanya** ke
klien lewat `public_payload()`.

Catatan Fase G: `AuthMiddlewareStack` sudah dipasang (session user tersedia di
`self.scope["user"]`).

FASE 4.1 (hardening): koneksi **wajib terautentikasi** — `connect()` menolak
`AnonymousUser` dengan close code **4401** (unauthenticated) sebelum `accept()`,
jadi tidak ada group yang pernah dimasuki klien anonim. `?resource=&id=` tetap
diperlakukan seperti sebelumnya (belum ada filter kepemilikan per-bundle; cukup
require auth dulu).
"""

from __future__ import annotations

import logging
from urllib.parse import parse_qs

from channels.generic.websocket import AsyncJsonWebsocketConsumer

from . import websocket

logger = logging.getLogger(__name__)

#: Key pesan yang boleh dilihat klien (whitelist — payload internal tidak bocor).
PUBLIC_KEYS = ("type", "resource", "id", "event_name", "occurred_at", "event")

#: Sentinell internal: penanda JSON rusak dari klien (lihat `decode_json`).
INVALID_JSON = "__invalid_json__"

#: Close code WebSocket untuk koneksi anonim (FASE 4.1). Rentang 4000-4999 =
#: "application specific" (RFC 6455) → aman dipakai aplikasi.
WS_CLOSE_UNAUTHORIZED = 4401



def parse_query(query_string: bytes | str | None) -> dict[str, str]:
    """PURE — query string -> dict nilai pertama (decode aman, tanpa exception).

    `?` di depan diabaikan supaya helper ini juga ramah dipakai manual/test
    (`scope["query_string"]` dari ASGI memang tanpa `?`).
    """
    if isinstance(query_string, bytes):
        raw = query_string.decode("utf-8", errors="replace")
    else:
        raw = str(query_string or "")

    raw = raw.lstrip("?")
    if raw.strip() == "":
        return {}

    parsed = parse_qs(raw, keep_blank_values=False)
    return {key: values[0] for key, values in parsed.items() if values}


def subscription_group(query_string: bytes | str | None) -> str | None:
    """PURE — group dari query param `?resource=&id=` (``None`` kalau tidak ada)."""
    params = parse_query(query_string)
    resource = params.get("resource")
    identifier = params.get("id")
    if resource is None or identifier is None:
        return None
    return websocket.resource_group(resource, identifier)


def public_payload(message: dict) -> dict:
    """PURE — potong pesan Channels ke key yang boleh dilihat klien."""
    return {key: message[key] for key in PUBLIC_KEYS if key in message}


class EventConsumer(AsyncJsonWebsocketConsumer):
    """Klien real-time: satu koneksi = sekumpulan group (default + per-resource)."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        #: Group yang sedang diikuti koneksi ini (dipakai saat disconnect).
        self.joined: list[str] = []

    # ---------------------------------------------------------------- lifecycle
    async def connect(self) -> None:
        """Terima koneksi **hanya untuk user terautentikasi** (FASE 4.1).

        Anonim → `close(code=4401)` SEBELUM `accept()`, jadi klien tidak pernah
        masuk group mana pun. Selain itu perilaku lama tidak berubah: masuk group
        default lalu (kalau ada) group dari query param `?resource=&id=`.
        """

        user = self.scope.get("user")
        if user is None or not getattr(user, "is_authenticated", False):
            logger.warning(
                "WS %s: koneksi anonim ditolak (close %s).",
                self.channel_name,
                WS_CLOSE_UNAUTHORIZED,
            )
            await self.close(code=WS_CLOSE_UNAUTHORIZED)
            return

        await self.accept()
        await self._join(websocket.DEFAULT_GROUP)

        requested = subscription_group(self.scope.get("query_string"))
        if requested is not None:
            await self._join(requested)

        await self.send_json({"type": "connected", "groups": list(self.joined)})

    async def disconnect(self, code) -> None:
        """Lepas semua group — tidak ada group yang tertinggal setelah klien hilang."""
        for group in list(self.joined):
            await self._leave(group)

    async def receive_json(self, content, **kwargs) -> None:
        """subscribe/unsubscribe/ping dari klien; sisanya dijawab error (tanpa putus)."""
        data = content if isinstance(content, dict) else {}
        kind = str(data.get("type") or "").strip().lower()

        if kind == INVALID_JSON:
            await self.send_json({"type": "error", "reason": "invalid_json"})
            return
        if kind == "subscribe":
            await self._subscribe(data)
            return
        if kind == "unsubscribe":
            await self._unsubscribe(data)
            return
        if kind == "ping":
            await self.send_json({"type": "pong"})
            return

        await self.send_json({"type": "error", "reason": "unknown_message_type"})

    # ------------------------------------------------------------- group handler
    async def bundle_event(self, message) -> None:
        """Event bundle dari publisher -> teruskan ke klien (payload chatter §8)."""
        await self.send_json(public_payload(message))

    async def work_order_event(self, message) -> None:
        """Event work order dari publisher -> teruskan ke klien."""
        await self.send_json(public_payload(message))

    async def decode_json(self, text_data):
        """Fail-safe (Fase E): JSON rusak **tidak** memutus koneksi.

        Default Channels melempar `JSONDecodeError` → koneksi ditutup. Untuk
        perangkat lapangan (scanner/tablet) lebih ramah menjawab
        `{"type":"error","reason":"invalid_json"}` dan membiarkan koneksi hidup,
        supaya satu pesan rusak tidak mematikan aliran event.
        """
        try:
            return await super().decode_json(text_data)
        except Exception:  # noqa: BLE001 - json.JSONDecodeError dan turunannya
            logger.warning("WS %s: JSON dari klien tidak bisa diparse (diabaikan).", self.channel_name)
            return {"type": INVALID_JSON}

    # -------------------------------------------------------------------- internal
    async def _subscribe(self, data: dict) -> None:
        """Masuk group dari `resource`+`id` (atau group default kalau kosong)."""
        group = websocket.resource_group(data.get("resource"), data.get("id"))
        if group is None and data.get("resource") in (None, ""):
            group = websocket.DEFAULT_GROUP

        if group is None:
            await self.send_json(
                {
                    "type": "error",
                    "reason": "invalid_subscription",
                    "detail": "Butuh 'resource' + 'id' yang valid (mis. bundles/42).",
                }
            )
            return

        await self._join(group)
        await self.send_json({"type": "subscribed", "group": group})

    async def _unsubscribe(self, data: dict) -> None:
        """Keluar dari group (kalau memang sedang diikuti)."""
        group = str(data.get("group") or "").strip()
        if group not in self.joined:
            await self.send_json({"type": "error", "reason": "not_subscribed", "group": group})
            return

        await self._leave(group)
        await self.send_json({"type": "unsubscribed", "group": group})

    async def _join(self, group: str) -> None:
        """group_add sekali saja (agar `disconnect` tidak meninggalkan sisa)."""
        if group in self.joined:
            return

        await self.channel_layer.group_add(group, self.channel_name)
        self.joined.append(group)
        logger.debug("WS %s join group '%s'.", self.channel_name, group)

    async def _leave(self, group: str) -> None:
        """group_discard + hapus dari daftar lokal."""
        await self.channel_layer.group_discard(group, self.channel_name)
        if group in self.joined:
            self.joined.remove(group)
        logger.debug("WS %s leave group '%s'.", self.channel_name, group)
