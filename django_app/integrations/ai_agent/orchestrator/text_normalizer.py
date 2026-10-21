"""Normalisasi teks pesan — PURE function, tanpa DB/state.

Layer 1: lowercase, trim, buang noise, dan ganti sinonim dengan kata
kanonik. Frasa multi-kata dicocokkan lebih dulu agar "work order" tidak
dipecah menjadi "work" + "order".
"""

from __future__ import annotations

import re

from .synonym_registry import REVERSE_MAP, get_canonical

_PUNCTUATION = ".,!?;:()[]{}\"'`"
# Frasa terpanjang lebih dulu: "manufacturing order" sebelum "order".
_ALIASES = sorted(REVERSE_MAP, key=lambda value: (-len(value.split()), -len(value)))
_ALIAS_PATTERN = re.compile(
    r"(?<!\w)(?:" + "|".join(re.escape(alias) for alias in _ALIASES) + r")(?!\w)",
    re.IGNORECASE,
)
_SPACE_PATTERN = re.compile(r"\s+")


def _display(canonical: str) -> str:
    """Kata kanonik untuk teks yang tetap enak dibaca regex/prompt."""
    return canonical.replace("_", " ")


def _normalize_text(raw: str) -> tuple[str, list[str]]:
    canonicals: list[str] = []

    def _replace(match: re.Match) -> str:
        canonical = REVERSE_MAP.get(match.group(0).lower())
        if canonical is None:
            return match.group(0)
        canonicals.append(canonical)
        return _display(canonical)

    text = _ALIAS_PATTERN.sub(_replace, raw.lower())
    return _SPACE_PATTERN.sub(" ", text).strip(), canonicals


def _clean_token(token: str) -> str:
    return token.strip(_PUNCTUATION)


def normalize(message: str) -> dict:
    """Return `{raw, normalized, canonicals, tokens}`.

    `canonicals` berisi kata kanonik unik sesuai urutan kemunculan;
    `tokens` adalah teks hasil normalisasi yang sudah dibersihkan.
    """
    raw = str(message or "").strip()
    if not raw:
        return {"raw": "", "normalized": "", "canonicals": [], "tokens": []}

    normalized, canonicals = _normalize_text(raw)
    tokens = [
        token
        for token in (_clean_token(part) for part in normalized.split())
        if token
    ]

    return {
        "raw": raw,
        "normalized": normalized,
        "canonicals": list(dict.fromkeys(canonicals)),
        "tokens": tokens,
    }


__all__ = ("normalize",)
