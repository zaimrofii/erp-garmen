"""Endpoint chat AI Agent (D.5/G.5) — decision gate → LLM dengan context injection."""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

from pydantic import ValidationError
from django.core.cache import cache
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from integrations.analytics.services import analytics_config_services

from ..clarification import pending_state, resolver, templates
from ..clarification.pending_state import MAX_TURNS
from ..decision_gate import rule_evaluator
from ..memory import semantic_cache
from ..observability import cost_tracker
from ..observability.decision_logger import log_decision
from ..orchestrator import (
    context_builder,
    intent_classifier,
    response_synthesizer,
    tool_selector,
)
from .schemas import ChatRequest, validate_context, validate_history

logger = logging.getLogger(__name__)

_ANALYTICS_HINTS = ("scrap", "rework", "lead time", "analitik", "analytics")
_FORBIDDEN_CONTEXT_ROLES = {"OPERATOR", "QC"}
_MASTER_RESOURCES = {"product", "partner"}
#: Kata tanya → pesan baru dianggap ganti topik (bukan jawaban klarifikasi).
_NEW_QUESTION_HINTS = (
    "apa",
    "berapa",
    "kenapa",
    "mengapa",
    "bagaimana",
    "gimana",
    "kapan",
    "siapa",
    "tampilkan",
    "sebutkan",
    "jelaskan",
)
RATE_LIMIT_PER_MINUTE = 60
_RATE_LIMIT_TTL_SECONDS = 120


def _rate_limit_key(user) -> str:
    user_id = getattr(user, "pk", None) or "anon"
    window = int(time.time() // 60)
    return f"ai:rate:{user_id}:{window}"


def _is_rate_limited(user) -> bool:
    """Fixed-window 60 request/menit per user (cache/Redis counter)."""
    key = _rate_limit_key(user)
    try:
        count = cache.incr(key)
    except ValueError:
        cache.add(key, 1, timeout=_RATE_LIMIT_TTL_SECONDS)
        count = 1
    return int(count) > RATE_LIMIT_PER_MINUTE


def _role_code(user) -> str:
    role = getattr(user, "role", None)
    return str(getattr(role, "code", "") or "").strip().upper()


def _tokens() -> dict[str, Any]:
    return {"prompt": 0, "completion": 0, "total_cost_usd": 0}


def _response_tokens(tokens: dict[str, Any] | None) -> dict[str, Any]:
    """Pastikan kontrak token selalu lengkap walau LLM mengirim partial."""
    merged = _tokens()
    for key in merged:
        value = (tokens or {}).get(key)
        if value is not None:
            merged[key] = value
    return merged


def _response(
    *,
    ok: bool,
    answer: str,
    decision_gate_result: str,
    latency_ms: int,
    error: str | None = None,
    cache_hit: bool = False,
    confidence: float | None = 1.0,
    impact_score: str = "LOW",
    tool_calls: list[dict[str, Any]] | None = None,
    tokens: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": ok,
        "answer": answer,
        "tool_calls": list(tool_calls or []),
        "confidence_score": confidence,
        "impact_score": impact_score,
        "hitl_required": False,
        "hitl_request_id": None,
        "decision_gate_result": decision_gate_result,
        "tokens": _response_tokens(tokens),
        "cache_hit": cache_hit,
        "latency_ms": latency_ms,
    }
    if error:
        payload["error"] = error
    return payload


def _tool_calls(tools: list[str], context_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Ringkas tool yang dipilih (kontrak §3: output_summary ≤ 500 karakter)."""
    page_context = context_data.get("context") or {}
    metrics = context_data.get("metrics") or []
    resource = context_data.get("resource") or []
    events = context_data.get("events") or []
    calls: list[dict[str, Any]] = []

    for tool in tools:
        if tool == "mcp-analytics":
            metric_ids = list(
                dict.fromkeys(
                    str(item.get("metric_id"))
                    for item in metrics
                    if isinstance(item, dict)
                )
            )
            summary = (
                f"{len(metrics)} metrik: {', '.join(metric_ids)}"
                if metrics
                else "Tidak ada metrik yang dikembalikan."
            )
            calls.append(
                {
                    "tool": tool,
                    "input": {"metrics": metric_ids, "dimension": "period"},
                    "output_summary": summary[:500],
                }
            )
        elif tool == "mcp-postgres-query":
            bundles = context_data.get("bundles") or []
            if bundles:
                summary = f"{len(bundles)} bundle dengan lead time terpanjang."
            elif resource:
                summary = f"{len(resource)} baris data resource."
            else:
                summary = "Tidak ada data resource yang dikembalikan."
            calls.append(
                {
                    "tool": tool,
                    "input": {
                        "resource_type": page_context.get("resource_type"),
                        "resource_id": page_context.get("resource_id"),
                    },
                    "output_summary": summary[:500],
                }
            )
        elif tool == "mcp-event-log":
            summary = (
                f"{len(events)} event terbaru."
                if events
                else "Tidak ada event yang dikembalikan."
            )
            calls.append(
                {
                    "tool": tool,
                    "input": {"bundle_id": page_context.get("resource_id")},
                    "output_summary": summary[:500],
                }
            )
        elif tool in {"mcp-rule-engine", "mcp-aggregator", "mcp-time-series"}:
            calls.append(
                {
                    "tool": tool,
                    "input": {},
                    "output_summary": "Tool kalkulasi dipilih (read-only).",
                }
            )
        elif tool in {"mcp-comparator", "mcp-forecaster"}:
            calls.append(
                {
                    "tool": tool,
                    "input": {},
                    "output_summary": "Tool analisis lanjutan dipilih (read-only).",
                }
            )

    return calls


def _session_id(request) -> str:
    """ID sesi untuk pending clarification (fallback stabil per user)."""
    key = getattr(getattr(request, "session", None), "session_key", None)
    return str(key or f"user-{getattr(request.user, 'pk', 'anon')}")


def _looks_like_new_question(message: str) -> bool:
    """True bila pesan tampak pertanyaan baru (ganti topik), bukan jawaban."""
    tokens = {token.strip("?.,!") for token in str(message or "").lower().split()}
    return any(hint in tokens for hint in _NEW_QUESTION_HINTS)


def _clarification_response(request, body, answer: str, latency: int) -> Response:
    """Balasan klarifikasi deterministik (RULE_HIT, 0 token) + audit log."""
    result = _response(
        ok=True,
        answer=answer,
        decision_gate_result="RULE_HIT",
        latency_ms=latency,
    )
    log_decision(
        user=request.user,
        channel=body.channel,
        query_text=body.message,
        decision_gate_result="RULE_HIT",
        intent="CLARIFICATION",
        impact_score="LOW",
        response_text=answer,
        latency_ms=result["latency_ms"],
    )
    return Response(result)


class AiChatView(APIView):
    """`POST /api/v1/ai/chat` — RULE_HIT tanpa LLM, LLM_NEEDED ditunda Sprint E."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        started = time.monotonic()

        def latency() -> int:
            return max(1, int((time.monotonic() - started) * 1000))

        payload = request.data
        if not isinstance(payload, dict):
            return Response(
                {"ok": False, "error": "bad_request", "detail": "Body harus objek JSON."},
                status=400,
            )

        try:
            body = ChatRequest.model_validate(payload)
        except ValidationError as exc:
            return Response(
                {"ok": False, "error": "bad_request", "detail": exc.errors(include_url=False)},
                status=400,
            )

        if not body.message.strip():
            return Response(
                {"ok": False, "error": "bad_request", "detail": "message tidak boleh kosong."},
                status=400,
            )

        context_error = validate_context(body.context)
        if context_error:
            return Response(
                {"ok": False, "error": "bad_context", "detail": context_error},
                status=400,
            )

        history_error = validate_history(body.history)
        if history_error:
            return Response(
                {"ok": False, "error": "bad_request", "detail": history_error},
                status=400,
            )

        context = body.context.model_dump() if body.context else {}
        history = [item.model_dump() for item in body.history]
        role = _role_code(request.user)

        if _is_rate_limited(request.user):
            return Response(
                {"ok": False, "error": "rate_limited", "retry_after_s": 60},
                status=429,
            )

        # R.2 — lanjutkan klarifikasi yang masih pending (deterministik, 0 token).
        session_id = _session_id(request)
        pending = pending_state.load(request.user.pk, session_id)
        if pending:
            candidates = list(pending.get("candidates") or [])
            resolution = resolver.resolve(
                body.message,
                candidates,
                turn_count=int(pending.get("turn_count", 0) or 0),
            )
            resolved_types = {
                resolver.ResolutionType.RANK,
                resolver.ResolutionType.FUZZY,
            }

            if resolution.type in resolved_types and resolution.candidate:
                context["_resolved_candidate"] = resolution.candidate
                pending_state.clear(request.user.pk, session_id)
            elif resolution.type is resolver.ResolutionType.CANCEL:
                pending_state.clear(request.user.pk, session_id)
                return _clarification_response(
                    request, body, "Baik, saya lupakan. Ada yang lain?", latency()
                )
            elif resolution.type is resolver.ResolutionType.ESCALATE:
                pending_state.clear(request.user.pk, session_id)
                return _clarification_response(
                    request,
                    body,
                    templates.escalation_response(candidates),
                    latency(),
                )
            elif resolution.type is resolver.ResolutionType.ALL:
                pending_state.clear(request.user.pk, session_id)
                return _clarification_response(
                    request, body, templates.all_response(candidates), latency()
                )
            else:
                if _looks_like_new_question(body.message):
                    # Ganti topik: buang state, lanjut alur normal.
                    pending_state.clear(request.user.pk, session_id)
                else:
                    turn = pending_state.increment_turn(request.user.pk, session_id)
                    if turn >= MAX_TURNS:
                        pending_state.clear(request.user.pk, session_id)
                        return _clarification_response(
                            request,
                            body,
                            templates.escalation_response(candidates),
                            latency(),
                        )
                    return _clarification_response(
                        request,
                        body,
                        templates.ambiguous_question(candidates),
                        latency(),
                    )

        # §5 #6 — role tidak berhak melihat resource master (status 200).
        if (
            body.context
            and body.context.page_type in {"detail", "form"}
            and body.context.resource_type in _MASTER_RESOURCES
            and role in _FORBIDDEN_CONTEXT_ROLES
        ):
            log_decision(
                user=request.user,
                channel=body.channel,
                query_text=body.message,
                decision_gate_result="BLOCKED",
                impact_score="LOW",
                response_text="forbidden_context",
                latency_ms=latency(),
            )
            return Response({"ok": False, "error": "forbidden_context"})

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
            cached["tokens"] = _tokens()
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
            return Response(cached)

        intent = ""
        model_used = ""
        audit_text = ""
        classifier_cost = 0.0

        if decision["result"] == "RULE_HIT":
            result = _response(
                ok=True,
                answer=decision["answer"] or "",
                decision_gate_result="RULE_HIT",
                latency_ms=latency(),
            )
            semantic_cache.set(cache_scope, result)
        elif decision["result"] == "BLOCKED":
            result = _response(
                ok=False,
                answer=decision["answer"] or "",
                decision_gate_result="BLOCKED",
                error="blocked",
                latency_ms=latency(),
            )
        else:
            needs_analytics = any(hint in body.message.lower() for hint in _ANALYTICS_HINTS)
            analytics_off = needs_analytics and not analytics_config_services.analytics_enabled()

            if analytics_off:
                result = _response(
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
                    return Response(
                        {
                            "ok": False,
                            "error": "budget_exceeded",
                            "retry_after_s": 30,
                        },
                        status=429,
                    )

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
                tool_calls = _tool_calls(tools, context_data)

                if synth.get("ok") and str(synth.get("answer") or "").strip():
                    result = _response(
                        ok=True,
                        answer=str(synth["answer"]),
                        decision_gate_result=str(
                            synth.get("decision_gate_result") or "LLM_NEEDED"
                        ),
                        latency_ms=latency(),
                        confidence=confidence,
                        impact_score="LOW",
                        tool_calls=tool_calls,
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
                    result = _response(
                        ok=False,
                        answer="",
                        decision_gate_result="LLM_NEEDED",
                        error="llm_failed",
                        latency_ms=latency(),
                        confidence=confidence,
                        impact_score="LOW",
                        tool_calls=tool_calls,
                    )
                    result["detail"] = detail
                    audit_text = f"llm_failed: {detail}"

        tokens = result.get("tokens") or _tokens()
        log_row = log_decision(
            user=request.user,
            channel=body.channel,
            query_text=body.message,
            decision_gate_result=result["decision_gate_result"],
            intent=intent,
            confidence_score=result["confidence_score"],
            impact_score=result["impact_score"],
            tools_called=result["tool_calls"],
            prompt_tokens=int(tokens.get("prompt") or 0),
            completion_tokens=int(tokens.get("completion") or 0),
            total_cost_usd=(tokens.get("total_cost_usd") or 0) + classifier_cost,
            cache_hit=result["cache_hit"],
            hitl_required=False,
            response_text=audit_text or result["answer"],
            model_used=model_used,
            latency_ms=result["latency_ms"],
        )
        cost_tracker.record_cost(log_row)

        return Response(result)


__all__ = ("AiChatView",)

