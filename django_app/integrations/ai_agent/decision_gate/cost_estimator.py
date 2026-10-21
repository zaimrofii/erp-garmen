"""Estimasi biaya query tanpa memanggil LLM (D.2)."""

from __future__ import annotations

from typing import Any

from ..config import AI_CONFIG

#: Harga aproksimasi Gemini Flash (USD per token).
PROMPT_COST_PER_TOKEN = 0.0000015
COMPLETION_COST_PER_TOKEN = 0.000002
DEFAULT_COMPLETION_TOKENS = 200


def _context_size(context: dict | None) -> int:
    """Perkiraan token konteks: karakter/4 + 5 token per key."""
    if not context:
        return 0

    chars = sum(len(str(value)) for value in context.values())
    return chars // 4 + len(context) * 5


def estimate(message: str, context: dict | None = None) -> dict[str, Any]:
    """Estimasi token & biaya (underestimate lebih aman)."""
    words = len((message or "").split())
    prompt_tokens = int(words * 1.3 + _context_size(context))
    completion_tokens = DEFAULT_COMPLETION_TOKENS

    total_cost = (
        prompt_tokens * PROMPT_COST_PER_TOKEN
        + completion_tokens * COMPLETION_COST_PER_TOKEN
    )
    budget = float(AI_CONFIG["decision_gate"]["cost_budget_usd_per_query"])

    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_cost_usd": round(total_cost, 8),
        "exceeds_budget": total_cost > budget,
    }


__all__ = ("estimate",)
