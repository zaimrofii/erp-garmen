"""Celery task AI Agent (Sprint F)."""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="ai_agent.hitl_expire_pending")
def hitl_expire_pending() -> int:
    """Tandai AIHitlQueue PENDING yang kedaluwarsa → EXPIRED."""
    from .hitl import hitl_services

    count = hitl_services.expire_pending()
    logger.info("ai_agent: %d HITL kedaluwarsa ditandai EXPIRED.", count)
    return count


@shared_task(name="ai_agent.detect_drift")
def detect_ai_drift() -> dict:
    """Deteksi drift intent harian; AuditLog kalau melewati ambang."""
    from core.audit.services import AuditLogger

    from .observability import drift_detector

    result = drift_detector.detect_drift()
    if result["drifted"]:
        AuditLogger().log(
            user=None,
            action="ai.drift_detected",
            resource="ai_decision_log",
            resource_id="batch",
            payload={
                "delta_pct": result["delta_pct"],
                "threshold_pct": result["threshold_pct"],
            },
        )
        logger.warning("ai_agent: drift intent terdeteksi: %s", result["delta_pct"])

    return result


__all__ = ("detect_ai_drift", "hitl_expire_pending")

