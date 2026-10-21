"""Active learning HITL (F.1.5) — feedback loop; refinement di Sprint G."""

from __future__ import annotations

import logging
from typing import Any

from core.audit.services import AuditLogger

logger = logging.getLogger(__name__)

audit_logger = AuditLogger()


def record_feedback(hitl_id: int, decision: str, reason: str = "", user=None) -> Any:
    """Catat feedback keputusan HITL ke AuditLog `ai.hitl_feedback`."""
    return audit_logger.log(
        user=user,
        action="ai.hitl_feedback",
        resource="ai_hitl_queue",
        resource_id=hitl_id,
        payload={"decision": str(decision).upper(), "reason": reason},
    )


__all__ = ("record_feedback",)
