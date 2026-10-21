"""Pending clarification state (R.1) — cache/Redis dengan TTL, BUKAN history chat.

State hanya hidup selama klarifikasi berlangsung (default 10 menit) dan
maksimal `MAX_TURNS` putaran; setelah itu AI wajib eskalasi.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from django.core.cache import cache

logger = logging.getLogger(__name__)

#: Umur state klarifikasi (detik).
TTL_SECONDS = 600
#: Setelah sekian turn tanpa resolve → eskalasi.
MAX_TURNS = 3


def _key(user_id: int, session_id: str) -> str:
    return f"clarification:{user_id}:{session_id}"


def save(user_id: int, session_id: str, state: dict[str, Any]) -> None:
    """Simpan state `{candidates, original_query, question, turn_count}`."""
    payload = dict(state)
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    cache.set(_key(user_id, session_id), json.dumps(payload), TTL_SECONDS)


def load(user_id: int, session_id: str) -> dict[str, Any] | None:
    """Ambil state; `None` bila tidak ada / kedaluwarsa / rusak."""
    raw = cache.get(_key(user_id, session_id))
    if not raw:
        return None

    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("clarification: state tersimpan bukan JSON valid; diabaikan.")
        return None

    return data if isinstance(data, dict) else None


def clear(user_id: int, session_id: str) -> None:
    cache.delete(_key(user_id, session_id))


def increment_turn(user_id: int, session_id: str) -> int:
    """Naikkan `turn_count`; 0 bila state sudah tidak ada."""
    state = load(user_id, session_id)
    if not state:
        return 0

    state["turn_count"] = int(state.get("turn_count", 0) or 0) + 1
    save(user_id, session_id, state)
    return state["turn_count"]


def is_expired_by_turns(state: dict[str, Any]) -> bool:
    """True bila sudah mencapai batas turn (perlu eskalasi)."""
    return int(state.get("turn_count", 0) or 0) >= MAX_TURNS


__all__ = (
    "MAX_TURNS",
    "TTL_SECONDS",
    "clear",
    "increment_turn",
    "is_expired_by_turns",
    "load",
    "save",
)
