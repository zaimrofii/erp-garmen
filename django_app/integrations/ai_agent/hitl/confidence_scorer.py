"""Confidence scorer HITL (F.1) — PURE."""

from __future__ import annotations


def score(response: dict) -> float:
    """Skor keyakinan agent 0.0–1.0 (default Sprint F)."""
    gate = str((response or {}).get("decision_gate_result") or "").upper()

    if gate == "RULE_HIT":
        return 0.95
    if gate == "BLOCKED":
        return 0.0

    raw = (response or {}).get("confidence_score")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return max(0.0, min(1.0, float(raw)))

    return 0.7


__all__ = ("score",)

