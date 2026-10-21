"""Pipeline decision gate → LLM (R-1) — perilaku sama dengan versi lama."""

from __future__ import annotations

import hashlib

from rest_framework.response import Response

from integrations.analytics.services import analytics_config_services

from ...decision_gate import rule_evaluator
from ...memory import semantic_cache
from ...observability import cost_tracker
from ...observability.decision_logger import log_decision
from ...orchestrator import (
    context_builder,
    intent_classifier,
    response_synthesizer,
    tool_selector,
)
from .common import elapsed_ms, response, role_code, tokens, tool_calls

_ANALYTICS_HINTS = ("scrap", "rework", "lead time", "analitik", "analytics")


def run_pipeline(request, body, context, *, session_id, started) -> dict:
    """Jalankan decision gate + LLM.

    Return ``{"response": Response}`` untuk jalur dini (cache/budget),
    atau metadata hasil untuk di-log oleh `handlers.logging.finalize`.
    """

    def latency() -> int:
        return elapsed_ms(started)

    role = role_code(request.user)
    history = [item.model_dump() for item in body.history]
    decision = rule_evaluator.evaluate(body.message, context, request.user)

    history_key = ""
    if history:
        transcript = "|".join(
            f"{item['role']}:{item['content']}" for item in history
        )
        digest = hashlib.sha256(transcript.encode("utf-8")).hexdigest()[:12]
        history_key = f"|history:{digest}"
    cache_scope = f"{role}|{body.channel}|{body.message}{history_key}"

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
                if synth.get("cacheable", True):
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

    return {
        "result": result,
        "intent": intent,
        "model_used": model_used,
        "audit_text": audit_text,
        "classifier_cost": classifier_cost,
    }


__all__ = ("run_pipeline",)

