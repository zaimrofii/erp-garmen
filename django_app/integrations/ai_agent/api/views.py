"""Endpoint chat AI Agent (D.5/G.5) — orkestrator tipis (R-1)."""

from __future__ import annotations

import logging
import time

from pydantic import ValidationError
from django.conf import settings
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

# Modul diimpor di level modul agar patch path test lama tetap valid.
from integrations.analytics.services import (  # noqa: F401
    analytics_config_services,
)

from ..clarification import pending_state  # noqa: F401
from ..decision_gate import rule_evaluator  # noqa: F401
from ..memory import semantic_cache  # noqa: F401
from ..observability import cost_tracker  # noqa: F401
from ..observability.decision_logger import log_decision
from ..orchestrator import (  # noqa: F401
    context_builder,
    intent_classifier,
    response_synthesizer,
    tool_selector,
)
from .handlers import handle_pending_clarification, run_pipeline
from .handlers.common import (
    RATE_LIMIT_PER_MINUTE,
    elapsed_ms,
    is_rate_limited,
    rate_limit_key,
    response,
    role_code,
    session_id,
    tokens,
    tool_calls,
)
from .schemas import ChatRequest, validate_context, validate_history

logger = logging.getLogger(__name__)

_FORBIDDEN_CONTEXT_ROLES = {"OPERATOR", "QC"}
_MASTER_RESOURCES = {"product", "partner"}

# Alias kompatibilitas (nama lama dipertahankan untuk pemanggil/test).
_is_rate_limited = is_rate_limited
_rate_limit_key = rate_limit_key
_role_code = role_code
_session_id = session_id
_response = response
_tokens = tokens
_tool_calls = tool_calls


class AiChatView(APIView):
    """`POST /api/v1/ai/chat` — validasi + delegasi ke handler (R-1)."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        started = time.monotonic()

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
        role = _role_code(request.user)

        if _is_rate_limited(request.user):
            return Response(
                {"ok": False, "error": "rate_limited", "retry_after_s": 60},
                status=429,
            )

        session = _session_id(request)
        clarification = handle_pending_clarification(
            request,
            body.message,
            channel=body.channel,
            context=context,
            session_id=session,
            started=started,
        )
        if clarification is not None:
            return clarification

        # Fase 3B — CANCEL + remainder: lanjutkan pipeline dengan sisa teks.
        remainder = getattr(request, "_ai_remainder", None)
        if remainder:
            body = body.model_copy(update={"message": remainder})

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
                latency_ms=max(1, int((time.monotonic() - started) * 1000)),
            )
            return Response({"ok": False, "error": "forbidden_context"})

        if getattr(settings, "AI_AGENT_TOOLS_ENABLED", False):
            return _agent_response(request, body, role, started=started, session_id=session)

        outcome = run_pipeline(
            request,
            body,
            context,
            session_id=session,
            started=started,
        )
        if "response" in outcome:
            return outcome["response"]

        return Response(outcome["result"])


def _agent_messages(body, role: str) -> list[dict]:
    from ..agent.prompts import build_system_prompt

    return [
        {"role": "system", "content": build_system_prompt(role=role)},
        {"role": "user", "content": body.message},
    ]


def _agent_response(request, body, role: str, *, started: float, session_id: str = ""):
    """Jalur baru `/ai/chat` (flag AI_AGENT_TOOLS_ENABLED=true)."""
    from ..agent.loop import run_agent

    history = [{"role": item.role, "content": item.content} for item in (body.history or [])]
    result = run_agent(
        _agent_messages(body, role),
        role,
        request.user,
        config={
            "max_iterations": getattr(settings, "AI_AGENT_MAX_ITERATIONS", 5),
            "user_id": getattr(request.user, "pk", None),
            "session_id": session_id,
        },
        history=history,
    )
    latency_ms = elapsed_ms(started)
    trace = [
        {
            "tool": call.get("tool"),
            "input": call.get("args") or {},
            "output_summary": f"row_count={call.get('row_count')} error={call.get('error')}"[:500],
        }
        for call in result.tool_calls
    ]
    log_decision(
        user=request.user,
        channel=body.channel,
        query_text=body.message,
        decision_gate_result="AGENT_TOOLS",
        impact_score="LOW",
        tools_called=trace,
        prompt_tokens=int(result.tokens.get("prompt") or 0),
        completion_tokens=int(result.tokens.get("completion") or 0),
        total_cost_usd=result.cost_usd,
        response_text=result.answer[:500],
        latency_ms=latency_ms,
    )
    payload = _response(
        ok=result.error is None,
        answer=result.answer,
        decision_gate_result="AGENT_TOOLS",
        latency_ms=latency_ms,
        error=result.error,
        tool_calls=trace,
        tokens=result.tokens,
    )
    payload["agent_mode"] = "tools"
    payload["iterations"] = result.iterations
    payload["validator"] = result.validator
    if result.clarification:
        payload["clarification"] = result.clarification
    return Response(payload)


__all__ = ("AiChatView",)

