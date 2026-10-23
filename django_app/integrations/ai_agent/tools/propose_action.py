"""Tool `propose_action` — usulan tindakan ke HITL (TIDAK mengeksekusi apa pun)."""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from .base import ToolResult, fn_schema

NAME = "propose_action"
SUPERVISOR_PLUS = frozenset({"SUPERVISOR", "ADMIN", "OWNER"})
ACTION_TYPES = ("rework", "move_wc", "audit", "stop", "other")
SCHEMA = fn_schema(
    NAME,
    "Usulkan tindakan produksi untuk disetujui manusia (status PENDING di HITL)."
    " TIDAK mengeksekusi/mengubah data. Kembalikan {hitl_id, status, message}."
    " Panggil HANYA bila user meminta usulan tindakan.",
    {
        "action_type": {
            "type": "string",
            "enum": list(ACTION_TYPES),
            "description": "rework / move_wc / audit / stop / other.",
        },
        "entity_type": {
            "type": "string",
            "description": "Jenis objek, mis. 'bundle', 'work_order', 'work_center'.",
        },
        "entity_id": {"type": "string", "description": "ID/kode objek."},
        "reason": {"type": "string", "description": "Alasan usulan (data pendukung)."},
        "confidence": {"type": "number", "description": "Keyakinan 0-1 (opsional)."},
    },
    ["action_type", "entity_type", "entity_id"],
)


def run(
    action_type: str,
    entity_type: str,
    entity_id: str,
    reason: str = "",
    confidence: float = 0.5,
    requested_by=None,
) -> ToolResult:
    from integrations.ai_agent.models import AIHitlQueue
    from integrations.ai_agent.observability.decision_logger import log_decision

    action = str(action_type or "").strip().lower()
    if action not in ACTION_TYPES:
        raise ValueError(f"action_type tidak dikenal: {action_type!r}")
    entity = str(entity_type or "").strip().lower()
    identifier = str(entity_id or "").strip()
    if not entity or not identifier:
        raise ValueError("entity_type dan entity_id wajib diisi")
    try:
        score = float(confidence)
    except (TypeError, ValueError):
        raise ValueError("confidence harus angka 0-1") from None
    score = max(0.0, min(score, 1.0))

    proposed = {
        "action_type": action,
        "entity_type": entity,
        "entity_id": identifier,
        "reason": str(reason or "")[:1000],
        "confidence": score,
    }
    log = log_decision(
        user=requested_by if getattr(requested_by, "pk", None) else None,
        channel="DESKTOP",
        query_text=f"propose_action:{action}:{entity}:{identifier}"[:500],
        decision_gate_result="PROPOSE_ACTION",
        impact_score="MEDIUM",
        tools_called=[{"tool": NAME, "args": {k: v for k, v in proposed.items() if k != "reason"}}],
        response_text="usulan tindakan dikirim ke HITL (menunggu persetujuan)",
        latency_ms=1,
    )
    queue = AIHitlQueue.objects.create(
        decision_log=log,
        risk_level="MEDIUM",
        proposed_action=proposed,
        required_approver_role="SUPERVISOR",
        channel="DESKTOP",
        status="PENDING",
        expires_at=timezone.now() + timedelta(hours=24),
    )
    return ToolResult.success(
        {
            "hitl_id": queue.pk,
            "status": queue.status,
            "message": (
                f"Usulan {action} untuk {entity} {identifier} dikirim ke HITL "
                f"(id={queue.pk}); menunggu persetujuan supervisor."
            ),
            "proposed_action": proposed,
        },
        row_count=1,
        filters_applied={"action_type": action, "entity_type": entity, "entity_id": identifier},
    )


__all__ = ("ACTION_TYPES", "NAME", "SCHEMA", "SUPERVISOR_PLUS", "run")
