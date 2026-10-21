"""Rule evaluator decision gate (D.2) — RULE_HIT/BLOCKED tanpa LLM."""

from __future__ import annotations

import logging
from typing import Any

from integrations.analytics.services import analytics_config_services

logger = logging.getLogger(__name__)

RULE_ANALYTICS_OFF = "R1"
RULE_FORBIDDEN = "R2"
RULE_BAD_CONTEXT = "R3"

ANSWER_ANALYTICS_OFF = "Analitik belum aktif. Hubungi admin untuk mengaktifkan."
ANSWER_FORBIDDEN = "Anda tidak berhak mengakses data ini."
ANSWER_BAD_CONTEXT = "Konteks tidak valid."

_ANALYTICS_HINTS = (
    "analitik belum aktif",
    "analytics belum aktif",
    "analitik off",
    "analytics off",
    "analytics disabled",
)
_PRODUCT_HINTS = ("produk", "product")
_FORBIDDEN_ROLES = {"OPERATOR", "QC"}


def _role_code(user) -> str:
    role = getattr(user, "role", None)
    return str(getattr(role, "code", "") or "").strip().upper()


def _rule_hit(rule_id: str, answer: str) -> dict[str, Any]:
    return {"result": "RULE_HIT", "answer": answer, "rule_id": rule_id, "tokens": 0}


def _blocked(rule_id: str, answer: str) -> dict[str, Any]:
    return {"result": "BLOCKED", "answer": answer, "rule_id": rule_id, "tokens": 0}


def evaluate(message: str, context: dict | None, user) -> dict[str, Any]:
    """Cek apakah request bisa dijawab RULE (tanpa LLM).

    Return ``{"result": RULE_HIT|LLM_NEEDED|BLOCKED, "answer", "rule_id", "tokens": 0}``.
    """
    text = (message or "").lower()
    data = context or {}

    # R1 — pertanyaan tentang status analitik: bisa dijawab tanpa LLM.
    if any(hint in text for hint in _ANALYTICS_HINTS):
        if not analytics_config_services.analytics_enabled():
            return _rule_hit(RULE_ANALYTICS_OFF, ANSWER_ANALYTICS_OFF)
        return {"result": "LLM_NEEDED", "answer": None, "rule_id": None, "tokens": 0}

    # R2 — role tidak berhak mengakses data produk.
    if _role_code(user) in _FORBIDDEN_ROLES and any(
        hint in text for hint in _PRODUCT_HINTS
    ):
        return _blocked(RULE_FORBIDDEN, ANSWER_FORBIDDEN)

    # R3 — konteks tidak valid (resource_type tanpa resource_id, bukan list/report).
    page_type = data.get("page_type")
    resource_type = data.get("resource_type")
    resource_id = data.get("resource_id")
    if (
        resource_type
        and not resource_id
        and page_type not in {"list", "report"}
    ):
        return _blocked(RULE_BAD_CONTEXT, ANSWER_BAD_CONTEXT)

    # Default: butuh LLM (Sprint E tool selection).
    return {"result": "LLM_NEEDED", "answer": None, "rule_id": None, "tokens": 0}


__all__ = ("evaluate",)
