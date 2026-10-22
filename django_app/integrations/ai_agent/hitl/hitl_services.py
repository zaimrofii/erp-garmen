"""Service HITL (F.1.7) — antrean approval AI + audit."""

from __future__ import annotations

from typing import Any

from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from core.audit.services import AuditLogger

from ..config import AI_CONFIG
from ..models import AIDecisionLog, AIHitlQueue

audit_logger = AuditLogger()

#: role → required role yang boleh diputuskan.
AUTHORITY: dict[str, set[str]] = {
    "ADMIN": {"SUPERVISOR", "OWNER"},
    "OWNER": {"SUPERVISOR", "OWNER"},
    "SUPERVISOR": {"SUPERVISOR"},
}


class HitlNotFound(LookupError):
    """HITL id tidak ditemukan."""


class HitlConflict(RuntimeError):
    """Status bukan PENDING."""

    def __init__(self, status: str) -> None:
        super().__init__(f"Permintaan sudah {status}.")
        self.status = status


def user_role(user) -> str:
    if user is None:
        return ""
    if getattr(user, "is_superuser", False):
        return "ADMIN"
    role = getattr(user, "role", None)
    return str(getattr(role, "code", "") or "").strip().upper()


def can_decide(user, required_role: str) -> bool:
    role = user_role(user)
    if role == "ADMIN" or getattr(user, "is_superuser", False):
        return True
    return required_role.upper() in AUTHORITY.get(role, set())


def serialize(row: AIHitlQueue) -> dict[str, Any]:
    log = row.decision_log

    return {
        "id": row.pk,
        "decision_log_id": row.decision_log_id,
        "risk_level": row.risk_level,
        "proposed_action": row.proposed_action or {},
        "required_approver_role": row.required_approver_role,
        "channel": row.channel,
        "status": row.status,
        "query_text": log.query_text if log is not None else "",
        "intent": log.intent if log is not None else "",
        "confidence_score": log.confidence_score if log is not None else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "decided_by": row.decided_by.get_username() if row.decided_by_id else None,
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
        "rejection_reason": row.rejection_reason,
    }


def get_queue(
    role: str | None = None,
    status: str = "PENDING",
    risk: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Daftar antrean HITL (filter status/risk + offset) untuk UI S.3."""
    queryset = AIHitlQueue.objects.select_related("decision_log", "decided_by")

    status_norm = str(status or "PENDING").strip().upper()
    if status_norm != "ALL":
        queryset = queryset.filter(status=status_norm)

    risk_norm = str(risk or "").strip().upper()
    if risk_norm and risk_norm != "ALL":
        queryset = queryset.filter(risk_level=risk_norm)

    normalized = str(role or "").strip().upper()
    if normalized == "SUPERVISOR":
        queryset = queryset.filter(required_approver_role="SUPERVISOR")
    elif normalized not in ("ADMIN", "OWNER", ""):
        queryset = queryset.none()

    total = queryset.count()
    rows = [
        serialize(row)
        for row in queryset.order_by("-created_at")[offset : offset + max(1, limit)]
    ]
    return rows, total


def get_pending(role: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """Daftar PENDING; role supervisor hanya melihat antrean SUPERVISOR."""
    rows, _total = get_queue(role, "PENDING", None, limit, 0)
    return rows


def default_channel(required_role: str | None) -> str:
    configured = str(AI_CONFIG["hitl"].get("default_channel", "WA")).upper()
    if configured == "WA" and required_role in ("SUPERVISOR", "OWNER"):
        return "WA"
    return "DESKTOP"


def make_decision_log(response: dict[str, Any]) -> AIDecisionLog:
    return AIDecisionLog.objects.create(
        query_text=str(response.get("query_text") or ""),
        decision_gate_result=str(response.get("decision_gate_result") or "LLM_NEEDED"),
        intent=str(response.get("intent") or ""),
        confidence_score=response.get("confidence_score"),
    )


def _load(hitl_id: int) -> AIHitlQueue:
    row = (
        AIHitlQueue.objects.select_related("decision_log", "decided_by")
        .filter(pk=hitl_id)
        .first()
    )
    if row is None:
        raise HitlNotFound(f"HITL request {hitl_id} tidak ditemukan.")
    return row


def approve(hitl_id: int, user, note: str | None = None) -> dict[str, Any]:
    """Setujui pengajuan (hanya PENDING + role berwenang)."""
    row = _load(hitl_id)
    if row.status != "PENDING":
        raise HitlConflict(row.status)
    if not can_decide(user, row.required_approver_role):
        raise PermissionDenied("Role Anda tidak berwenang menyetujui pengajuan ini.")

    now = timezone.now()
    row.status = "APPROVED"
    row.decided_by = user if getattr(user, "pk", None) is not None else None
    row.decided_at = now
    row.rejection_reason = ""
    row.save(update_fields=["status", "decided_by", "decided_at", "rejection_reason"])

    log = row.decision_log
    if log is not None:
        log.hitl_decision = "APPROVED"
        log.hitl_approver = row.decided_by
        log.hitl_latency_seconds = max(0, int((now - row.created_at).total_seconds()))
        log.save(
            update_fields=["hitl_decision", "hitl_approver", "hitl_latency_seconds"]
        )

    audit_logger.log(
        user=user,
        action="ai.hitl_approve",
        resource="ai_hitl_queue",
        resource_id=row.pk,
        payload={"note": note or "", "required_role": row.required_approver_role},
    )

    # S.5 — setelah disetujui manusia, executor LOG-ONLY dijalankan.
    from . import action_executor

    execution = action_executor.execute(row.pk)

    return {**serialize(row), "hitl_id": row.pk, "execution": execution}


def reject(hitl_id: int, user, reason: str) -> dict[str, Any]:
    """Tolak pengajuan; alasan WAJIB (audit)."""
    clean_reason = str(reason or "").strip()
    if not clean_reason:
        raise ValidationError("Field 'reason' wajib diisi untuk reject.")

    row = _load(hitl_id)
    if row.status != "PENDING":
        raise HitlConflict(row.status)
    if not can_decide(user, row.required_approver_role):
        raise PermissionDenied("Role Anda tidak berwenang menolak pengajuan ini.")

    now = timezone.now()
    row.status = "REJECTED"
    row.decided_by = user if getattr(user, "pk", None) is not None else None
    row.decided_at = now
    row.rejection_reason = clean_reason
    row.save(update_fields=["status", "decided_by", "decided_at", "rejection_reason"])

    log = row.decision_log
    if log is not None:
        log.hitl_decision = "REJECTED"
        log.hitl_approver = row.decided_by
        log.hitl_latency_seconds = max(0, int((now - row.created_at).total_seconds()))
        log.save(
            update_fields=["hitl_decision", "hitl_approver", "hitl_latency_seconds"]
        )

    audit_logger.log(
        user=user,
        action="ai.hitl_reject",
        resource="ai_hitl_queue",
        resource_id=row.pk,
        payload={"reason": clean_reason},
    )
    return serialize(row)


def expire_pending() -> int:
    """Tandai PENDING yang lewat `expires_at` menjadi EXPIRED (Celery)."""
    now = timezone.now()
    queryset = AIHitlQueue.objects.filter(status="PENDING", expires_at__lt=now)
    count = queryset.count()
    if count == 0:
        return 0

    queryset.update(status="EXPIRED", decided_at=now)
    audit_logger.log(
        user=None,
        action="ai.hitl_expire",
        resource="ai_hitl_queue",
        resource_id="batch",
        payload={"count": count, "expires_before": now.isoformat()},
    )
    return count


__all__ = (
    "HitlConflict",
    "HitlNotFound",
    "approve",
    "can_decide",
    "default_channel",
    "expire_pending",
    "get_pending",
    "get_queue",
    "make_decision_log",
    "reject",
    "serialize",
    "user_role",
)

