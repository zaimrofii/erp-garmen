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

import re
from typing import Any

from .synonym_registry import (
    ENTITY_CANONICALS,
    FOLLOWUP_CANONICALS,
    RANK_CANONICALS,
)
from .text_normalizer import normalize

PRONOUN_WORDS = ("itu", "tersebut", "tadi", "yang itu")
_CODE_RE = re.compile(r"\b[A-Z]{2,}(?:-[A-Z0-9]+){1,4}\b", re.IGNORECASE)
_QUESTION_WORDS = ("apa", "siapa", "berapa", "mana", "harganya")
_CODE_ENTITY = (
    ("BND", "bundle"),
    ("SO", "order"),
    ("INV", "invoice"),
    ("PO", "purchase_order"),
    ("WO", "work_order"),
    ("FG", "product"),
    ("RM", "product"),
)


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
    """True bila pesan mengandung penanda lanjutan (rank/pronoun/waktu)."""
    text = str(message or "").lower()
    if any(re.search(rf"\b{re.escape(word)}\b", text) for word in PRONOUN_WORDS):
        return True
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
        "entity_type": None,
        "entity_code": None,
        "entity_name": None,
        "topic": None,
    }


def _entity_from_code(code: str | None) -> str | None:
    if not code:
        return None
    upper = code.upper()
    for prefix, entity in _CODE_ENTITY:
        if upper.startswith(prefix) or f"-{prefix}-" in upper:
            return entity
    return None


def _extract_entity(previous_query: str, previous_answer: str | None) -> dict:
    """Ambil entity/kode/nama dari pertanyaan atau jawaban sebelumnya."""
    previous_norm = normalize(previous_query)
    entity_type = None

    code_match = _CODE_RE.search(previous_query or "")
    if code_match is None and previous_answer:
        code_match = _CODE_RE.search(previous_answer)
    entity_code = code_match.group(0) if code_match else None
    if entity_code:
        entity_type = _entity_from_code(entity_code)

    if entity_type is None:
        for canonical in previous_norm["canonicals"]:
            entity_type = ENTITY_CANONICALS.get(canonical)
            if entity_type:
                break

    entity_name = None
    if entity_type == "product":
        match = re.search(
            r"\b(?:produk|product)\s+([A-Za-z0-9][A-Za-z0-9\- ]{0,40})",
            previous_query or "",
            re.IGNORECASE,
        )
        if match:
            entity_name = match.group(1).strip(" ?.,!")

    return {
        "entity_type": entity_type,
        "entity_code": entity_code,
        "entity_name": entity_name,
    }


def _is_context_question(message: str, previous_query: str, previous_answer: str | None) -> bool:
    """Pertanyaan pendek seperti 'order apa?' setelah entity sebelumnya."""
    text = str(message or "").lower()
    tokens = [token.strip("?.,!") for token in text.split() if token.strip("?.,!")]
    if not tokens or len(tokens) > 5:
        return False
    if any(word in tokens for word in ("saja", "semua", "daftar")):
        return False
    if not any(word in tokens for word in _QUESTION_WORDS):
        return False
    entity = _extract_entity(previous_query, previous_answer)
    return bool(entity["entity_code"] or entity["entity_type"] or entity["entity_name"])


def _has_followup_signal(
    message: str, previous_query: str, previous_answer: str | None
) -> bool:
    """True hanya bila pesan memang menunjuk konteks sebelumnya."""
    text = str(message or "").lower().strip()
    if is_followup(message):
        return True
    if re.search(r"\btotal\s+(?:nilai\s+)?belanja(?:nya)?\b", text):
        return True
    return _is_context_question(message, previous_query, previous_answer)


def _infer_intent(text: str) -> str:
    """Infer intent lama dari isi query history (tanpa menyimpan metadata)."""
    norm = normalize(text)
    canonicals = set(norm["canonicals"])
    lowered = str(text or "").lower()
    if canonicals & {"scrap", "rework", "oee", "wip"} or any(
        word in lowered
        for word in (
            "scrap",
            "rework",
            "oee",
            "wip",
            "tren",
            "lead time",
            "bottleneck",
            "analitik",
            "analytics",
        )
    ):
        return "ANALYTICS_QUERY"
    if any(
        word in lowered
        for word in ("apa yang harus", "saran", "rekomendasi", "suggest")
    ):
        return "SUGGEST_ACTION"
    return "DATA_LOOKUP"


def _intent_changed(previous_query: str, intent: str | None) -> bool:
    """Intent analytics ↔ data berubah: jangan bawa query lama."""
    current = str(intent or "").strip().upper()
    if current not in {"ANALYTICS_QUERY", "DATA_LOOKUP"}:
        return False
    previous = _infer_intent(previous_query)
    if current == "ANALYTICS_QUERY":
        return previous != "ANALYTICS_QUERY"
    return previous == "ANALYTICS_QUERY"


def _entity_code_changed(
    message: str, previous_query: str, previous_answer: str | None
) -> bool:
    """Kode entity baru berbeda dari kode di history → topik baru."""
    current = _CODE_RE.search(str(message or ""))
    if current is None:
        return False
    previous = _CODE_RE.search(previous_query or "")
    if previous is None and previous_answer:
        previous = _CODE_RE.search(previous_answer)
    if previous is None:
        return False
    return current.group(0).upper() != previous.group(0).upper()


def resolve_followup(
    message: str, history: list[Any], intent: str | None = None
) -> dict:
    """Resolve pesan follow-up ke query sebelumnya.

    Follow-up tanpa history diperlakukan sebagai pesan biasa agar tidak
    menebak konteks yang tidak ada.
    """
    if not history:
        return _empty(message)

    previous_query, previous_answer = _last_turn(history)
    if not previous_query:
        return _empty(message)

    # FIX #21 — context bleeding: jangan prepend bila topik/entity/intent
    # berubah. Ini menjaga query baru seperti "tren scrap?" dan kode order
    # lain tetap independen dari percakapan sebelumnya.
    if _entity_code_changed(message, previous_query, previous_answer):
        return _empty(message)
    if _intent_changed(previous_query, intent):
        return _empty(message)
    if not _has_followup_signal(message, previous_query, previous_answer):
        return _empty(message)

    # Fase 3.6B — cancel/remainder dan count tidak boleh ditempeli query lama.
    text = str(message or "").lower().strip()
    spend_followup = bool(
        re.search(r"\btotal\s+(?:nilai\s+)?belanja(?:nya)?\b", text)
    )
    if re.match(r"^(lupakan|batal|ganti|reset|cancel)\b", text) or (
        re.search(r"\b(total|jumlah|berapa banyak|count)\b", text)
        and not spend_followup
    ):
        return _empty(message)

    if (
        not is_followup(message)
        and not _is_context_question(message, previous_query, previous_answer)
        and not spend_followup
    ):
        return _empty(message)

    current_norm = normalize(message)
    previous_norm = normalize(previous_query)
    target_rank = _target_rank(current_norm["canonicals"])
    target_entity = _target_entity(
        previous_norm["canonicals"], current_norm["canonicals"]
    )
    entity = _extract_entity(previous_query, previous_answer)
    if entity["entity_type"]:
        target_entity = entity["entity_type"]

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
        "entity_type": entity["entity_type"],
        "entity_code": entity["entity_code"],
        "entity_name": entity["entity_name"],
        "topic": topic,
    }


__all__ = ("is_followup", "resolve_followup")
