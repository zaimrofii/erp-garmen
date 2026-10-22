"""Pipeline decision gate → LLM (R-1) — perilaku sama dengan versi lama."""

from __future__ import annotations

import hashlib
import json
import re

from django.utils import timezone
from rest_framework.response import Response

from integrations.analytics.services import analytics_config_services

from ...decision_gate import rule_evaluator
from ...clarification import pending_state
from ...hitl import escalation_router, hitl_services
from ...memory import semantic_cache
from ...observability import cost_tracker
from ...observability.decision_logger import log_decision
from ...orchestrator import (
    context_builder,
    intent_classifier,
    response_synthesizer,
    tool_selector,
)
from ...orchestrator.conversation_context import resolve_followup
from .common import elapsed_ms, response, role_code, tokens, tool_calls
from .logging import finalize

_ANALYTICS_HINTS = ("scrap", "rework", "lead time", "analitik", "analytics")


def _data_version() -> str:
    """Versi data ringan untuk cache; berubah setelah agregasi harian."""
    try:
        from integrations.analytics.models import DailySummary

        value = (
            DailySummary.objects.order_by("-computed_at")
            .values_list("computed_at", flat=True)
            .first()
        )
        return value.isoformat() if value else "none"
    except Exception:  # noqa: BLE001 - cache tetap boleh jalan tanpa summary
        return "none"


def build_cache_scope(
    role: str,
    channel: str,
    message: str,
    context: dict | None = None,
    history: list[dict] | None = None,
    state_hash: str = "",
) -> str:
    """Cache key yang membedakan filter, page context, dan versi data."""
    from integrations.ai_agent.orchestrator.context_builder.aggregate import (
        _detect_total_query,
    )

    history_key = ""
    if history:
        transcript = "|".join(
            f"{item.get('role', '')}:{item.get('content', '')}" for item in history
        )
        digest = hashlib.sha256(transcript.encode("utf-8")).hexdigest()[:12]
        history_key = f"|history:{digest}"

    context_digest = hashlib.sha256(
        json.dumps(context or {}, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:12]
    total_query = _detect_total_query(message)
    filters = (total_query or {}).get("filters") or {}
    filter_digest = hashlib.sha256(
        json.dumps(filters, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:12]
    today = timezone.localdate()
    period = f"{today.isoformat()}-W{today.isocalendar()[1]:02d}"
    return (
        f"{role}|{channel}|{message}|ctx:{context_digest}|filters:{filter_digest}"
        f"|period:{period}|data:{_data_version()}|state:{state_hash or 'none'}"
        f"{history_key}"
    )


def should_bypass_cache(request, message, history, session_id) -> bool:
    """Cache tidak boleh dipakai saat state/follow-up masih aktif."""
    pending = (
        pending_state.load(request.user.pk, session_id) if session_id else None
    )
    followup = resolve_followup(message, history or [])
    return bool(
        pending or followup.get("is_followup") or getattr(request, "_ai_remainder", None)
    )


_APPROVE_COMMAND = re.compile(
    r"^\s*(setujui|approve|lakukan|ok|ya)\s+(aksi|itu)\b",
    re.IGNORECASE,
)


def _approve_from_chat(request, body, started) -> dict | None:
    """Rule-based chat approval — 0 token, tanpa classifier/LLM."""
    if not _APPROVE_COMMAND.match(str(body.message or "")):
        return None

    from django.core.exceptions import PermissionDenied

    from ...hitl.hitl_services import HitlConflict, HitlNotFound
    from ...models import AIHitlQueue

    pending = (
        AIHitlQueue.objects.filter(
            status="PENDING", decision_log__user=request.user
        )
        .order_by("-created_at")
        .first()
    )
    if pending is None:
        answer = "Tidak ada aksi PENDING untuk disetujui."
        hitl_approved = False
        hitl_id = None
    else:
        try:
            hitl_services.approve(pending.pk, request.user, note="via chat")
            hitl_id = pending.pk
            hitl_approved = True
            answer = f"Aksi #{pending.pk} disetujui. Status: APPROVED."
        except (PermissionDenied, HitlConflict, HitlNotFound):
            hitl_id = pending.pk
            hitl_approved = False
            answer = f"Aksi #{pending.pk} tidak dapat disetujui."

    result = response(
        ok=True,
        answer=answer,
        decision_gate_result="RULE_HIT",
        latency_ms=elapsed_ms(started),
        impact_score=pending.risk_level if pending is not None else "LOW",
        tokens=tokens(),
    )
    result["hitl_approved"] = hitl_approved
    result["hitl_request_id"] = hitl_id
    log_decision(
        user=request.user,
        channel=body.channel,
        query_text=body.message,
        decision_gate_result="RULE_HIT",
        confidence_score=1.0,
        impact_score=result["impact_score"],
        hitl_required=False,
        response_text=answer,
        latency_ms=result["latency_ms"],
    )
    return result


def run_pipeline(request, body, context, *, session_id, started) -> dict:
    """Jalankan decision gate + LLM.

    Return ``{"response": Response}`` untuk jalur dini (cache/budget),
    atau metadata hasil untuk di-log oleh `handlers.logging.finalize`.
    """

    def latency() -> int:
        return elapsed_ms(started)

    role = role_code(request.user)
    history = [item.model_dump() for item in body.history]

    approval = _approve_from_chat(request, body, started)
    if approval is not None:
        return {"response": Response(approval)}

    decision = rule_evaluator.evaluate(body.message, context, request.user)

    pending = (
        pending_state.load(request.user.pk, session_id) if session_id else None
    )
    followup = resolve_followup(body.message, history)
    bypass_cache = bool(
        pending
        or followup.get("is_followup")
        or getattr(request, "_ai_remainder", None)
    )
    state_hash = (
        hashlib.sha256(
            json.dumps(pending, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()[:12]
        if pending
        else ""
    )
    cache_scope = build_cache_scope(
        role,
        body.channel,
        body.message,
        context,
        history,
        state_hash=state_hash,
    )

    if not bypass_cache:
        cached = semantic_cache.get(cache_scope)
        if cached is not None:
            cached = dict(cached)
            cached["cache_hit"] = True
            # Cache tidak memanggil LLM → token & biaya request ini nol.
            cached["tokens"] = tokens()
            cached["latency_ms"] = latency()
            log_decision(
                user=request.user,
                channel=body.channel,
                query_text=body.message,
                decision_gate_result=cached.get("decision_gate_result", "RULE_HIT"),
                confidence_score=cached.get("confidence_score"),
                impact_score=cached.get("impact_score", "LOW"),
                cache_hit=True,
                response_text=cached.get("answer", ""),
                latency_ms=cached["latency_ms"],
            )
            return {"response": Response(cached)}

    intent = ""
    model_used = ""
    audit_text = ""
    classifier_cost = 0.0

    if decision["result"] == "RULE_HIT":
        result = response(
            ok=True,
            answer=decision["answer"] or "",
            decision_gate_result="RULE_HIT",
            latency_ms=latency(),
        )
        if not bypass_cache:
            semantic_cache.set(cache_scope, result)
    elif decision["result"] == "BLOCKED":
        result = response(
            ok=False,
            answer=decision["answer"] or "",
            decision_gate_result="BLOCKED",
            error="blocked",
            latency_ms=latency(),
        )
    else:
        needs_analytics = any(
            hint in body.message.lower() for hint in _ANALYTICS_HINTS
        )
        analytics_off = (
            needs_analytics and not analytics_config_services.analytics_enabled()
        )

        if analytics_off:
            result = response(
                ok=False,
                answer="",
                decision_gate_result="LLM_NEEDED",
                error="analytics_disabled",
                latency_ms=latency(),
                confidence=None,
            )
        else:
            # F.4.1/G.5 — budget dicek tepat sebelum memanggil LLM.
            budget = cost_tracker.check_budget(request.user)
            if budget["exceeded"]:
                return {
                    "response": Response(
                        {
                            "ok": False,
                            "error": "budget_exceeded",
                            "retry_after_s": 30,
                        },
                        status=429,
                    )
                }

            intent_result = intent_classifier.classify(body.message)
            intent = str(intent_result.get("intent") or "UNKNOWN")
            confidence = intent_result.get("confidence")
            confidence = float(confidence) if confidence is not None else 0.85
            classifier_cost = float(intent_result.get("cost_usd") or 0)

            tools = tool_selector.select_tools(intent, context, body.message)
            context_data = context_builder.build_context(
                intent,
                tools,
                body.message,
                context,
                user=request.user,
                history=history,
            )
            synth = response_synthesizer.synthesize(
                body.message,
                context_data,
                user=request.user,
                session_id=session_id,
                intent=intent,
            )
            calls = tool_calls(tools, context_data)

            if synth.get("ok") and str(synth.get("answer") or "").strip():
                result = response(
                    ok=True,
                    answer=str(synth["answer"]),
                    decision_gate_result=str(
                        synth.get("decision_gate_result") or "LLM_NEEDED"
                    ),
                    latency_ms=latency(),
                    confidence=confidence,
                    impact_score="LOW",
                    tool_calls=calls,
                    tokens=synth.get("tokens"),
                )
                model_used = str(synth.get("model") or "")
                audit_text = result["answer"]
                for key in ("proposed_actions", "problem", "chart_data"):
                    if synth.get(key):
                        result[key] = synth[key]
                if synth.get("cacheable", True) and not bypass_cache:
                    semantic_cache.set(
                        cache_scope,
                        result,
                        tool_calls_signature=",".join(tools),
                    )
            else:
                detail = str(synth.get("detail") or "Jawaban LLM kosong.")
                result = response(
                    ok=False,
                    answer="",
                    decision_gate_result="LLM_NEEDED",
                    error="llm_failed",
                    latency_ms=latency(),
                    confidence=confidence,
                    impact_score="LOW",
                    tool_calls=calls,
                )
                result["detail"] = detail
                audit_text = f"llm_failed: {detail}"

    log_row = finalize(
        request,
        body,
        result,
        intent=intent,
        model_used=model_used,
        audit_text=audit_text,
        classifier_cost=classifier_cost,
    )

    # S.1 — usulan aksi wajib masuk antrean HITL (read-only, tanpa eksekusi).
    if intent == "SUGGEST_ACTION" and result.get("proposed_actions"):
        routing = escalation_router.route(
            {
                **result,
                "intent": intent,
                "query_text": body.message,
                "proposed_action": {
                    "type": "suggest_actions",
                    "problem": result.get("problem", ""),
                    "actions": result["proposed_actions"],
                    "count": len(result["proposed_actions"]),
                },
                "decision_log_id": log_row.pk,
            },
            request.user,
        )
        result["hitl_required"] = bool(routing.get("hitl_required"))
        result["hitl_request_id"] = routing.get("hitl_request_id")
        result["risk_level"] = routing.get("risk_level")

    return {
        "result": result,
        "intent": intent,
        "model_used": model_used,
        "audit_text": audit_text,
        "classifier_cost": classifier_cost,
        "logged": True,
    }


__all__ = ("run_pipeline",)

