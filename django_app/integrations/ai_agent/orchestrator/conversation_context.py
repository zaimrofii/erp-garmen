"""Resolusi follow-up percakapan — Layer 2 (tanpa DB/LLM).

Contoh:
  history: [{user: "produk paling mahal?"}, {assistant: "Jaket..."}]
  message: "peringkat kedua?"
  → target_rank=2, previous_query="produk paling mahal?",
    resolved_message="produk paling mahal? (follow-up: peringkat kedua?)"

Modul ini hanya membaca history; retrieval data tetap tanggung jawab
context builder.
"""

from __future__ import annotations

from typing import Any

from .synonym_registry import (
    ENTITY_CANONICALS,
    FOLLOWUP_CANONICALS,
    RANK_CANONICALS,
)
from .text_normalizer import normalize


def _field(item: Any, key: str) -> str:
    """Ambil field dari dict maupun objek Pydantic."""
    if isinstance(item, dict):
        value = item.get(key)
    else:
        value = getattr(item, key, None)
    return str(value or "").strip()


def _last_turn(history: list[Any]) -> tuple[str | None, str | None]:
    """Ambil user terakhir dan assistant sesudahnya (urutan kronologis)."""
    previous_user: str | None = None
    previous_assistant: str | None = None

    for item in reversed(history or []):
        role = _field(item, "role").lower()
        content = _field(item, "content")
        if role == "assistant" and previous_assistant is None:
            previous_assistant = content
        elif role == "user" and previous_user is None:
            previous_user = content
            break

    return previous_user, previous_assistant


def is_followup(message: str) -> bool:
    """True bila pesan mengandung penanda lanjutan (rank/waktu/lagi)."""
    norm = normalize(message)
    return bool(set(norm["canonicals"]) & FOLLOWUP_CANONICALS)


def _target_rank(canonicals: list[str]) -> int | None:
    found = set(canonicals)
    for rank, canonical in RANK_CANONICALS.items():
        if canonical in found:
            return rank
    return None


def _target_entity(*canonical_lists: list[str]) -> str | None:
    for canonicals in canonical_lists:
        for canonical in canonicals:
            entity = ENTITY_CANONICALS.get(canonical)
            if entity:
                return entity
    return None


def _empty(message: str) -> dict:
    return {
        "is_followup": False,
        "resolved_message": message,
        "previous_query": None,
        "previous_answer": None,
        "target_rank": None,
        "target_entity": None,
        "topic": None,
    }


def resolve_followup(message: str, history: list[Any]) -> dict:
    """Resolve pesan follow-up ke query sebelumnya.

    Follow-up tanpa history diperlakukan sebagai pesan biasa agar tidak
    menebak konteks yang tidak ada.
    """
    if not is_followup(message) or not history:
        return _empty(message)

    previous_query, previous_answer = _last_turn(history)
    if not previous_query:
        return _empty(message)

    current_norm = normalize(message)
    previous_norm = normalize(previous_query)
    target_rank = _target_rank(current_norm["canonicals"])
    target_entity = _target_entity(
        previous_norm["canonicals"], current_norm["canonicals"]
    )

    topic = None
    if target_entity and target_rank is not None:
        topic = f"{target_entity}_ranking"
    elif target_entity:
        topic = f"{target_entity}_followup"

    return {
        "is_followup": True,
        "resolved_message": f"{previous_query} (follow-up: {message})",
        "previous_query": previous_query,
        "previous_answer": previous_answer,
        "target_rank": target_rank,
        "target_entity": target_entity,
        "topic": topic,
    }


__all__ = ("is_followup", "resolve_followup")
