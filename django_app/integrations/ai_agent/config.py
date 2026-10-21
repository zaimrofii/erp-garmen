"""Konfigurasi AI Agent (Sprint D)."""

from __future__ import annotations

import os

_TRUE = {"1", "true", "yes", "y", "on"}


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in _TRUE


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


AI_CONFIG: dict = {
    # Master switch; default OFF → stub lama `integrations/ai/` tetap dipakai.
    "enabled": _env_bool("AI_AGENT_ENABLED", False),
    # Sprint G.1 — LLM provider (read-only, context injection).
    "llm": {
        "provider": os.getenv("AI_LLM_PROVIDER", "deepseek").strip().lower() or "deepseek",
        "model": os.getenv("AI_LLM_MODEL", "deepseek-chat").strip() or "deepseek-chat",
        "timeout_seconds": _env_int("AI_LLM_TIMEOUT_SECONDS", 30),
        "max_tokens": _env_int("AI_LLM_MAX_TOKENS", 1000),
        "temperature": _env_float("AI_LLM_TEMPERATURE", 0.3),
        "cost_per_1k_prompt_usd": _env_float("AI_LLM_COST_PROMPT", 0.00014),
        "cost_per_1k_completion_usd": _env_float("AI_LLM_COST_COMPLETION", 0.00028),
    },
    "decision_gate": {
        "rule_hit_max_tokens": 0,  # RULE_HIT = 0 token
        "cost_budget_usd_per_query": 0.05,
    },
    "semantic_cache": {
        "ttl_seconds": 300,
        "similarity_threshold": 0.92,
    },
    "hitl": {
        "auto_expire_hours": 24,
        "default_channel": "WA",
    },
    "mcp": {
        "timeout_seconds": 5,
        "total_timeout_seconds": 15,
        "max_rows_to_llm": 50,
        # Allowlist tabel untuk mcp-postgres-query (Sprint D).
        "allowlist": [
            "garment_order",
            "garment_workorder",
            "garment_bundle",
            "erp_sync_syncrecord",
        ],
    },
    # Sprint F — observability & budget.
    "observability": {
        "user_monthly_budget_usd": 5.0,
        "dashboard_cache_seconds": 60,
        "drift_window_days": 7,
        "drift_baseline_days": 30,
        "drift_threshold_pct": 20.0,
    },
}

__all__ = ("AI_CONFIG",)
