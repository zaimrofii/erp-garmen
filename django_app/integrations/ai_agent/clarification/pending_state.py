"""Pending clarification state (R.1) — cache/Redis dengan TTL, BUKAN history chat.

State hanya hidup selama klarifikasi berlangsung (default 10 menit). RANK yang
berhasil tidak menghabiskan kuota; hanya kegagalan klarifikasi yang dibatasi
`MAX_TURNS` sebelum eskalasi.
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


def failed_clarification_count(state: dict[str, Any]) -> int:
    """Jumlah kegagalan klarifikasi; state lama memakai turn_count."""
    return int(
        state.get("failed_clarification_count", state.get("turn_count", 0)) or 0
    )


def record_success(
    user_id: int,
    session_id: str,
    candidate: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Catat RANK/FUZZY berhasil tanpa menghapus state.

    `turn_count` tetap naik untuk informasi/TTL, tetapi penghitung kegagalan
    di-reset sehingga RANK berikutnya tidak terkena MAX_TURNS.
    """
    state = load(user_id, session_id)
    if not state:
        return None

    state["turn_count"] = int(state.get("turn_count", 0) or 0) + 1
    state["successful_rank_count"] = int(
        state.get("successful_rank_count", 0) or 0
    ) + 1
    state["failed_clarification_count"] = 0
    if candidate:
        state["selected_id"] = candidate.get("id")
        state["selected_label"] = candidate.get("label")
        state["selected_entity"] = candidate.get("entity") or state.get("entity")
    save(user_id, session_id, state)
    return state


def record_failure(user_id: int, session_id: str) -> int:
    """Catat UNRESOLVED/AMBIGU; return jumlah kegagalan setelah increment."""
    state = load(user_id, session_id)
    if not state:
        return 0

    prior_turn = int(state.get("turn_count", 0) or 0)
    prior_failed = int(
        state.get("failed_clarification_count", prior_turn) or 0
    )
    state["turn_count"] = prior_turn + 1
    state["failed_clarification_count"] = prior_failed + 1
    save(user_id, session_id, state)
    return state["failed_clarification_count"]


def is_expired_by_failures(state: dict[str, Any]) -> bool:
    """True bila kegagalan klarifikasi sudah mencapai ambang."""
    return failed_clarification_count(state) >= MAX_TURNS


def is_expired_by_turns(state: dict[str, Any]) -> bool:
    """True bila sudah mencapai batas turn (dipakai state lama)."""
    return int(state.get("turn_count", 0) or 0) >= MAX_TURNS


__all__ = (
    "MAX_TURNS",
    "TTL_SECONDS",
    "clear",
    "failed_clarification_count",
    "increment_turn",
    "is_expired_by_failures",
    "is_expired_by_turns",
    "load",
    "record_failure",
    "record_success",
    "save",
)
