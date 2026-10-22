"""Resolver balasan klarifikasi (R.2) — PURE: tanpa LLM, tanpa side effect.

Input: pesan user + kandidat dari `pending_state`. Output: `Resolution`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any


class ResolutionType(str, Enum):
    RANK = "RANK"  # "yg kedua", "2", "nomor 2"
    FUZZY = "FUZZY"  # "kaos sate", "pak slamet"
    CANCEL = "CANCEL"  # "bukan itu", "lupakan"
    ALL = "ALL"  # "semua", "semuanya"
    ESCALATE = "ESCALATE"  # sudah melewati MAX_TURNS
    UNRESOLVED = "UNRESOLVED"  # tidak bisa resolve


@dataclass
class Resolution:
    type: ResolutionType
    candidate: dict[str, Any] | None = None
    reason: str | None = None
    remainder: str | None = None


#: Peta ordinal → kandidat ke-N (1-based).
ORDINAL_MAP: dict[int, tuple[str, ...]] = {
    1: (
        "pertama",
        "1",
        "satu",
        "first",
        "top",
        "no 1",
        "nomor 1",
        "ke 1",
        "yang ke 1",
        "yang pertama",
        "yg ke 1",
        "yg pertama",
    ),
    2: (
        "kedua",
        "2",
        "dua",
        "second",
        "no 2",
        "nomor 2",
        "ke 2",
        "yang ke 2",
        "yang kedua",
        "yg ke 2",
        "yg kedua",
    ),
    3: (
        "ketiga",
        "3",
        "tiga",
        "third",
        "no 3",
        "nomor 3",
        "ke 3",
        "yang ke 3",
        "yang ketiga",
        "yg ke 3",
        "yg ketiga",
    ),
    4: (
        "keempat",
        "4",
        "empat",
        "fourth",
        "no 4",
        "nomor 4",
        "ke 4",
        "yang ke 4",
        "yang keempat",
        "yg ke 4",
        "yg keempat",
    ),
    5: (
        "kelima",
        "5",
        "lima",
        "fifth",
        "no 5",
        "nomor 5",
        "ke 5",
        "yang ke 5",
        "yang kelima",
        "yg ke 5",
        "yg kelima",
    ),
}

CANCEL_WORDS = (
    "bukan",
    "salah",
    "lupakan",
    "ganti",
    "tidak",
    "no",
    "batal",
    "cancel",
    "reset",
)
ALL_WORDS = ("semua", "semuanya", "all", "both", "keduanya")

#: Hanya kata perintah cancel yang boleh membawa pertanyaan lanjutan.
_CANCEL_REMAINDER_RE = re.compile(
    r"^\s*(?:lupakan|batal|ganti|reset|cancel)\b[\s,;:\-]*(.*)$",
    re.IGNORECASE,
)

#: Ambang skor fuzzy (0–100).
FUZZY_MIN_SCORE = 70


def _has_word(text: str, word: str) -> bool:
    """Cocokkan kata/frasa dengan batas kata (`no` tidak match `nomor`)."""
    return re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text) is not None


def _cancel_remainder(message: str) -> str | None:
    """Ambil pertanyaan setelah perintah cancel, mis. 'lupakan, total order?'."""
    match = _CANCEL_REMAINDER_RE.match(message or "")
    if match is None:
        return None
    remainder = match.group(1).strip(" .,!")
    return remainder or None


def _match_score(text: str, target: str, fuzz_module) -> float:
    """Skor kemiripan; fallback substring bila rapidfuzz tidak tersedia."""
    target = (target or "").strip().lower()
    if not target:
        return 0.0
    if fuzz_module is not None:
        return float(fuzz_module.partial_ratio(text, target))
    if text in target or target in text:
        return 100.0
    return 0.0


def _fuzzy_match(
    message: str, candidates: list[dict[str, Any]]
) -> tuple[dict[str, Any], float] | None:
    try:
        from rapidfuzz import fuzz
    except ImportError:  # pragma: no cover - jalur fallback
        fuzz = None

    best_score = 0.0
    best_candidate = None
    for candidate in candidates:
        label = str(candidate.get("label") or "")
        score = _match_score(message, label, fuzz)
        for value in (candidate.get("attrs") or {}).values():
            if value:
                score = max(score, _match_score(message, str(value), fuzz))
        if score > best_score:
            best_score = score
            best_candidate = candidate

    if best_candidate is not None and best_score >= FUZZY_MIN_SCORE:
        return best_candidate, best_score
    return None


def resolve(
    message: str,
    candidates: list[dict[str, Any]],
    turn_count: int = 0,
    max_turns: int = 3,
) -> Resolution:
    """Resolve balasan user ke kandidat (deterministik).

    Urutan: ESCALATE → CANCEL → ALL → RANK → FUZZY → UNRESOLVED.
    """
    if not candidates:
        return Resolution(type=ResolutionType.CANCEL, reason="Kandidat kosong")

    if turn_count >= max_turns:
        return Resolution(
            type=ResolutionType.ESCALATE, reason=f"Sudah {turn_count} turn"
        )

    text = (message or "").lower().strip()
    if not text:
        return Resolution(type=ResolutionType.UNRESOLVED, reason="Balasan kosong")

    if any(_has_word(text, word) for word in CANCEL_WORDS):
        return Resolution(
            type=ResolutionType.CANCEL,
            reason="User batalkan",
            remainder=_cancel_remainder(text),
        )

    if any(_has_word(text, word) for word in ALL_WORDS):
        return Resolution(type=ResolutionType.ALL, reason="User pilih semua")

    for rank, words in ORDINAL_MAP.items():
        if rank > len(candidates):
            continue
        for word in words:
            if _has_word(text, word):
                return Resolution(
                    type=ResolutionType.RANK,
                    candidate=candidates[rank - 1],
                    reason=f"Ordinal {rank} ({word})",
                )

    # Angka murni hanya bermakna ordinal; jangan fuzzy ke kode (mis. "2" di SO-042).
    if text.isdigit():
        return Resolution(
            type=ResolutionType.UNRESOLVED, reason="Ordinal di luar rentang kandidat"
        )

    fuzzy = _fuzzy_match(text, candidates)
    if fuzzy is not None:
        candidate, score = fuzzy
        return Resolution(
            type=ResolutionType.FUZZY,
            candidate=candidate,
            reason=f"Fuzzy match (score={score:.0f})",
        )

    return Resolution(type=ResolutionType.UNRESOLVED, reason="Tidak bisa resolve")


__all__ = (
    "ALL_WORDS",
    "CANCEL_WORDS",
    "FUZZY_MIN_SCORE",
    "ORDINAL_MAP",
    "Resolution",
    "ResolutionType",
    "resolve",
)
