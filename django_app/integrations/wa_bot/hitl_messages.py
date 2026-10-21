"""Pesan WhatsApp untuk approval HITL (F.2.1)."""

from __future__ import annotations

import json
import logging
from typing import Any

from django.conf import settings

from integrations.wa_bot.services import get_wa_gateway

logger = logging.getLogger(__name__)


def _summary(action: dict[str, Any]) -> str:
    if not action:
        return "-"

    summary = action.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()

    kind = action.get("action") or action.get("type") or "aksi"
    resource = action.get("resource") or ""
    label = f"{kind} {resource}".strip()
    return label if label else json.dumps(action, default=str)[:200]


def format_hitl_message(hitl) -> str:
    """Format pesan WA: aksi, risiko, cara membalas."""
    action = hitl.proposed_action if isinstance(hitl.proposed_action, dict) else {}
    return (
        "🔔 Persetujuan AI dibutuhkan\n"
        f"Aksi: {_summary(action)}\n"
        f"Risiko: {hitl.risk_level}\n"
        f"Balas: APPROVE {hitl.pk} atau REJECT {hitl.pk} alasan"
    )


def _recipient() -> str:
    raw = getattr(settings, "AI_HITL_WA_TO", None) or getattr(
        settings, "HITL_ALERT_WA_TO", None
    )
    if isinstance(raw, (list, tuple)):
        return str(raw[0]).strip() if raw else ""
    return str(raw or "").strip()


def send_hitl_notification(hitl) -> dict[str, Any]:
    """Kirim notifikasi WA (mock di dev). Tidak pernah throw."""
    to = _recipient()
    if not to:
        logger.info("hitl: AI_HITL_WA_TO kosong → notifikasi WA dilewati.")
        return {"ok": False, "error": "no_recipient", "message_id": None}

    try:
        result = get_wa_gateway().send_message(to, format_hitl_message(hitl))
    except Exception as exc:  # noqa: BLE001 - notifikasi tidak boleh memblokir HITL
        logger.exception("hitl: gagal mengirim WA.")
        return {"ok": False, "error": str(exc), "message_id": None}

    if not result.ok:
        logger.warning("hitl: WA gagal (%s).", result.error)

    return {
        "ok": bool(result.ok),
        "error": result.error,
        "message_id": result.message_id,
    }


__all__ = ("format_hitl_message", "send_hitl_notification")
