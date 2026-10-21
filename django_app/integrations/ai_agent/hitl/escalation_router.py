"""Escalation router HITL (F.1.4) — orkestrasi 3 scorer → AIHitlQueue."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from django.utils import timezone

from ..config import AI_CONFIG
from ..models import AIHitlQueue
from . import confidence_scorer, hitl_services, impact_scorer, policy_checker

logger = logging.getLogger(__name__)


def route(response: dict[str, Any], user) -> dict[str, Any]:
    """Putuskan apakah respons AI butuh persetujuan manusia (HITL)."""
    data = response or {}
    proposed_action = data.get("proposed_action") or None
    risk_level = impact_scorer.score(
        str(data.get("intent") or ""),
        data.get("tool_calls") or [],
        proposed_action,
    )
    confidence = confidence_scorer.score(data)
    policy = policy_checker.check(risk_level, hitl_services.user_role(user))

    now = timezone.now()
    expires_at = now + timedelta(hours=int(AI_CONFIG["hitl"]["auto_expire_hours"]))
    warnings: list[str] = []

    base = {
        "risk_level": risk_level,
        "required_approver_role": policy["required_role"],
        "channel": hitl_services.default_channel(policy["required_role"]),
        "expires_at": expires_at,
        "warnings": warnings,
        "confidence_score": confidence,
        "allowed": policy["allowed"],
    }

    if confidence < 0.6:
        warnings.append("confidence Rendah (<0.60): jawaban wajib menyebut ketidakpastian.")

    # Read-only / tidak ada aksi → tidak perlu persetujuan.
    if proposed_action is None or risk_level == "LOW":
        return {**base, "hitl_required": False, "hitl_request_id": None}

    # Operator/QC tidak boleh mengajukan write sama sekali.
    if not policy["allowed"]:
        warnings.append("operator_tidak_boleh_write")
        return {**base, "hitl_required": False, "hitl_request_id": None}

    decision_log = None
    log_id = data.get("decision_log_id")
    if log_id is not None:
        from ..models import AIDecisionLog

        decision_log = AIDecisionLog.objects.filter(pk=log_id).first()
    if decision_log is None:
        decision_log = hitl_services.make_decision_log(data)

    decision_log.impact_score = risk_level
    decision_log.confidence_score = confidence
    decision_log.hitl_required = True
    decision_log.save(
        update_fields=["impact_score", "confidence_score", "hitl_required"]
    )

    hitl = AIHitlQueue.objects.create(
        decision_log=decision_log,
        risk_level=risk_level,
        proposed_action=proposed_action or {},
        required_approver_role=policy["required_role"] or "SUPERVISOR",
        channel=base["channel"],
        status="PENDING",
        expires_at=expires_at,
    )

    if hitl.channel == "WA":
        try:
            from integrations.wa_bot import hitl_messages

            result = hitl_messages.send_hitl_notification(hitl)
            if not result.get("ok", False):
                warnings.append("wa_notification_failed")
        except Exception:  # noqa: BLE001 - notifikasi tidak boleh menggagalkan pengajuan
            logger.exception("hitl: gagal kirim notifikasi WA (diabaikan).")
            warnings.append("wa_notification_failed")

    return {**base, "hitl_required": True, "hitl_request_id": hitl.pk}


__all__ = ("route",)
