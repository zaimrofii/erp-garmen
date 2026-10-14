"""Jembatan event bus -> WebSocket group (Fase E).

**Satu-satunya** tempat yang tahu pemetaan nama event domain ke group Channels
beserta bentuk pesan yang diterima klien:

    ==========================  ==========================  ==================
    event_name                  group                        resource (REST)
    ==========================  ==========================  ==================
    BUNDLE_STATE_CHANGED        ``bundle.<bundle_id>``       ``bundles``
    SCRAP_RECORDED              ``bundle.<bundle_id>``       ``bundles``
    WORK_ORDER_STATE_CHANGED    ``work_order.<wo_id>``       ``work-orders``
    ==========================  ==========================  ==================

Pesan group = JSON yang diteruskan consumer apa adanya ke klien::

    {
      "type": "bundle_event",      # nama handler di EventConsumer (Channels)
      "resource": "bundles",
      "id": 42,
      "event_name": "BUNDLE_STATE_CHANGED",
      "occurred_at": "<ISO-8601>",
      "event": {"id": "...", "actor": {...}, "type": "...", "summary": "...",
                "payload": {}, "created_at": "..."}
    }

Field ``event`` memakai bentuk chatter kontrak §8 (`chatter_event_payload`) —
sama dengan yang dipakai metadata/chatter, sehingga frontend memvalidasinya
dengan `ChatterEventSchema` yang sama (tidak ada bentuk event kedua).

**Fail-safe**: tanpa Channels/Redis (mode test tanpa layer, container tanpa
Redis, server dijalankan via WSGI) `broadcast()` mencatat warning dan
mengembalikan ``False`` — event bus tidak boleh mati hanya karena real-time
belum siap. Nama group divalidasi (`[A-Za-z0-9_.-]{1,100}`) supaya id aneh tidak
pernah sampai ke channel layer.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from django.utils import timezone

logger = logging.getLogger(__name__)

__all__ = (
    "BUNDLE_EVENT_TYPE",
    "DEFAULT_GROUP",
    "RESOURCE_GROUP_PREFIXES",
    "WORK_ORDER_EVENT_TYPE",
    "broadcast",
    "channel_message",
    "group_for",
    "reset_channel_layer_cache",
    "resource_group",
    "route",
)

#: Group default (semua event) — di-join consumer tanpa query param.
DEFAULT_GROUP = "events"

#: Nama handler di `EventConsumer` (= key `type` pada pesan Channels).
BUNDLE_EVENT_TYPE = "bundle_event"
WORK_ORDER_EVENT_TYPE = "work_order_event"

#: Prefix nama group per resource REST.
RESOURCE_GROUP_PREFIXES: dict[str, str] = {
    "bundles": "bundle",
    "work-orders": "work_order",
}

#: Nama group harus aman untuk channel layer (ASCII, tanpa spasi).
GROUP_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")

#: Kandidat key id di payload event (urut prioritas).
BUNDLE_ID_KEYS = ("bundle_id", "bundle", "id")
WORK_ORDER_ID_KEYS = ("wo_id", "work_order_id", "work_order", "id")

#: Cache channel layer (None = belum pernah dicoba; False = tidak tersedia).
_layer_cache: Any = None
_layer_checked = False
_unavailable_warned = False


def resource_group(resource: str, instance_id: Any) -> str | None:
    """PURE — nama group untuk resource REST + id; `None` kalau tidak valid.

    Contoh: ``resource_group("bundles", 42)`` -> ``"bundle.42"``. Id kosong atau
    nama hasilnya tidak aman -> ``None`` (event di-skip, bukan dikirim ke group
    yang salah).
    """
    prefix = RESOURCE_GROUP_PREFIXES.get(str(resource or "").strip().lower())
    if prefix is None:
        return None

    identifier = _identifier(instance_id)
    if identifier is None:
        return None

    name = f"{prefix}.{identifier}"
    return name if GROUP_NAME_PATTERN.match(name) else None


def group_for(event_name: str, payload: dict | None = None) -> str | None:
    """PURE — group tujuan satu event (``None`` = event tidak di-broadcast)."""
    data = dict(payload or {})
    name = str(event_name or "").strip().upper()

    if name in ("BUNDLE_STATE_CHANGED", "SCRAP_RECORDED"):
        return resource_group("bundles", _first_key(data, BUNDLE_ID_KEYS))
    if name == "WORK_ORDER_STATE_CHANGED":
        return resource_group("work-orders", _first_key(data, WORK_ORDER_ID_KEYS))
    return None


def channel_message(event_name: str, payload: dict | None = None) -> dict | None:
    """PURE — pesan JSON untuk klien WS (bentuk di docstring modul)."""
    group = group_for(event_name, payload)
    if group is None:
        return None

    data = dict(payload or {})
    name = str(event_name or "").strip().upper()
    is_work_order = name == "WORK_ORDER_STATE_CHANGED"
    resource = "work-orders" if is_work_order else "bundles"
    identifier = _first_key(data, WORK_ORDER_ID_KEYS if is_work_order else BUNDLE_ID_KEYS)
    raw_event = data.get("event")

    return {
        "type": WORK_ORDER_EVENT_TYPE if is_work_order else BUNDLE_EVENT_TYPE,
        "resource": resource,
        "id": _identifier(identifier),
        "event_name": name,
        "occurred_at": timezone.now().isoformat(),
        "event": raw_event if isinstance(raw_event, dict) else {},
    }


def route(event_name: str, payload: dict | None = None) -> tuple[str, dict] | None:
    """PURE — `(group, message)` untuk satu event; `None` kalau tidak dirutekan."""
    group = group_for(event_name, payload)
    message = channel_message(event_name, payload)
    if group is None or message is None:
        return None
    return group, message


def broadcast(event_name: str, payload: dict | None = None) -> bool:
    """Kirim satu event ke group WebSocket; ``False`` kalau real-time tidak siap.

    Tidak pernah melempar exception: layer hilang, Redis down, atau dipanggil
    dari konteks async hanya menghasilkan warning + ``False``.
    """
    target = route(event_name, payload)
    if target is None:
        logger.debug("event '%s' tidak dipetakan ke group WebSocket.", event_name)
        return False

    layer = _get_layer()
    if layer is None:
        _warn_unavailable()
        return False

    group, message = target
    try:
        # Import lokal: modul ini tetap ringan untuk dipakai di test murni.
        from asgiref.sync import async_to_sync

        async_to_sync(layer.group_send)(group, message)
    except Exception:  # noqa: BLE001 - real-time tidak boleh mematikan alur utama
        logger.warning(
            "gagal mengirim event '%s' ke group '%s' (real-time dilewati).",
            event_name,
            group,
            exc_info=True,
        )
        return False

    logger.debug("event '%s' dikirim ke group WS '%s'.", event_name, group)
    return True


def reset_channel_layer_cache() -> None:
    """Test seam: lupakan cache channel layer (mis. setelah `override_settings`)."""
    global _layer_cache, _layer_checked, _unavailable_warned
    _layer_cache = None
    _layer_checked = False
    _unavailable_warned = False


# ---------------------------------------------------------------- internal
def _get_layer() -> Any:
    """Channel layer aktif, atau `None` kalau Channels/Redis tidak tersedia."""
    global _layer_cache, _layer_checked
    if _layer_checked:
        return _layer_cache

    _layer_checked = True
    try:
        from channels.layers import get_channel_layer

        _layer_cache = get_channel_layer()
    except Exception:  # noqa: BLE001 - channels belum terpasang / CHANNEL_LAYERS rusak
        logger.warning("channel layer tidak bisa dimuat (real-time dilewati).", exc_info=True)
        _layer_cache = None
    return _layer_cache


def _warn_unavailable() -> None:
    """Warn sekali saja (hindari spam log kalau real-time memang dimatikan)."""
    global _unavailable_warned
    if _unavailable_warned:
        return
    _unavailable_warned = True
    logger.warning(
        "channel layer tidak tersedia -> event domain tidak dikirim ke WebSocket "
        "(cek CHANNEL_LAYERS/Redis)."
    )


def _first_key(data: dict, keys: tuple[str, ...]) -> Any:
    """Nilai pertama yang ada di `data` untuk daftar key (urut prioritas)."""
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return None


def _identifier(value: Any) -> str | None:
    """PURE — id -> string aman (huruf/angka/`-`/`_`/`.`); selain itu `None`."""
    if value is None or isinstance(value, bool):
        return None

    text = str(value).strip()
    if text == "":
        return None
    return text if re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", text) else None
