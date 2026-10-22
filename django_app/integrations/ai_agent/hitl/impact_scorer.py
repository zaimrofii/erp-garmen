"""Impact scorer HITL (F.1) — PURE."""

from __future__ import annotations

import json
from typing import Any

_MUTATING_ACTIONS = {"create", "update", "delete", "state_transition", "transition", "write"}
_HIGH_RISK_KEYWORDS = (
    "finance",
    "invoice",
    "payment",
    "stock",
    "inventory",
    "journal",
    "account",
    "payroll",
)
_LEVELS = ("LOW", "MEDIUM", "HIGH")


def _bump(level: str) -> str:
    index = min(_LEVELS.index(level) + 1, len(_LEVELS) - 1)
    return _LEVELS[index]


def score(
    intent: str,
    tool_calls: list[dict] | None = None,
    proposed_action: dict | None = None,
) -> str:
    """Klasifikasi dampak aksi: LOW (read-only) / MEDIUM / HIGH."""
    del tool_calls  # Sprint F: sinyal utama = proposed_action

    if not proposed_action:
        return "LOW"

    intent_code = str(intent or "").strip().upper()

    action = str(proposed_action.get("action") or proposed_action.get("type") or "").lower()
    is_mutating = action in _MUTATING_ACTIONS or bool(
        proposed_action.get("resource") and action
    )

    serialized = json.dumps(proposed_action, default=str).lower()
    touches_high_risk = any(keyword in serialized for keyword in _HIGH_RISK_KEYWORDS)

    if touches_high_risk:
        level = "HIGH"
    elif intent_code == "SUGGEST_ACTION":
        # S.1 — usulan aksi selalu butuh persetujuan manusia (minimal MEDIUM).
        level = "MEDIUM"
    elif is_mutating:
        level = "MEDIUM"
    else:
        level = "LOW"

    items: Any = proposed_action.get("items")
    batch_size = len(items) if isinstance(items, list) else int(proposed_action.get("count") or 0)
    if batch_size > 10:
        level = _bump(level)

    return level


__all__ = ("score",)

