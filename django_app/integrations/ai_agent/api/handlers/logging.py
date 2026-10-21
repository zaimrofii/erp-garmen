"""Finalisasi audit log + biaya chat (R-1)."""

from __future__ import annotations

from ...observability import cost_tracker
from ...observability.decision_logger import log_decision
from .common import tokens


def finalize(
    request,
    body,
    result: dict,
    *,
    intent: str = "",
    model_used: str = "",
    audit_text: str = "",
    classifier_cost: float = 0.0,
) -> None:
    """Catat satu keputusan AI + biaya (perilaku sama dengan versi lama)."""
    values = result.get("tokens") or tokens()
    log_row = log_decision(
        user=request.user,
        channel=body.channel,
        query_text=body.message,
        decision_gate_result=result["decision_gate_result"],
        intent=intent,
        confidence_score=result["confidence_score"],
        impact_score=result["impact_score"],
        tools_called=result["tool_calls"],
        prompt_tokens=int(values.get("prompt") or 0),
        completion_tokens=int(values.get("completion") or 0),
        total_cost_usd=(values.get("total_cost_usd") or 0) + classifier_cost,
        cache_hit=result["cache_hit"],
        hitl_required=False,
        response_text=audit_text or result["answer"],
        model_used=model_used,
        latency_ms=result["latency_ms"],
    )
    cost_tracker.record_cost(log_row)


__all__ = ("finalize",)
