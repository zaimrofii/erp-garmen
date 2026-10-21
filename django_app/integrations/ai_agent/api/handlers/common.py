"""Helper respons/request chat AI — dipakai handler dan view (R-1)."""

from __future__ import annotations

import time
from typing import Any

from django.core.cache import cache
from rest_framework.response import Response

from ...observability.decision_logger import log_decision

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


def rate_limit_key(user) -> str:
    user_id = getattr(user, "pk", None) or "anon"
    window = int(time.time() // 60)
    return f"ai:rate:{user_id}:{window}"


def is_rate_limited(user) -> bool:
    """Fixed-window 60 request/menit per user (cache/Redis counter)."""
    key = rate_limit_key(user)
    try:
        count = cache.incr(key)
    except ValueError:
        cache.add(key, 1, timeout=_RATE_LIMIT_TTL_SECONDS)
        count = 1
    return int(count) > RATE_LIMIT_PER_MINUTE


def role_code(user) -> str:
    role = getattr(user, "role", None)
    return str(getattr(role, "code", "") or "").strip().upper()


def elapsed_ms(started: float) -> int:
    return max(1, int((time.monotonic() - started) * 1000))


def tokens() -> dict[str, Any]:
    return {"prompt": 0, "completion": 0, "total_cost_usd": 0}


def response_tokens(values: dict[str, Any] | None) -> dict[str, Any]:
    """Pastikan kontrak token selalu lengkap walau LLM mengirim partial."""
    merged = tokens()
    for key in merged:
        value = (values or {}).get(key)
        if value is not None:
            merged[key] = value
    return merged


def response(
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
        "tokens": response_tokens(tokens),
        "cache_hit": cache_hit,
        "latency_ms": latency_ms,
    }
    if error:
        payload["error"] = error
    return payload

def tool_calls(tools: list[str], context_data: dict[str, Any]) -> list[dict[str, Any]]:
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


def session_id(request) -> str:
    """ID sesi untuk pending clarification (fallback stabil per user)."""
    key = getattr(getattr(request, "session", None), "session_key", None)
    return str(key or f"user-{getattr(request.user, 'pk', 'anon')}")


def looks_like_new_question(message: str) -> bool:
    """True bila pesan tampak pertanyaan baru (ganti topik), bukan jawaban."""
    values = {token.strip("?.,!") for token in str(message or "").lower().split()}
    return any(hint in values for hint in _NEW_QUESTION_HINTS)


def clarification_response(
    request, message: str, channel: str, answer: str, latency_ms: int
) -> Response:
    """Balasan klarifikasi deterministik (RULE_HIT, 0 token) + audit log."""
    result = response(
        ok=True,
        answer=answer,
        decision_gate_result="RULE_HIT",
        latency_ms=latency_ms,
    )
    log_decision(
        user=request.user,
        channel=channel,
        query_text=message,
        decision_gate_result="RULE_HIT",
        intent="CLARIFICATION",
        impact_score="LOW",
        response_text=answer,
        latency_ms=result["latency_ms"],
    )
    return Response(result)


__all__ = (
    "RATE_LIMIT_PER_MINUTE",
    "clarification_response",
    "elapsed_ms",
    "is_rate_limited",
    "looks_like_new_question",
    "rate_limit_key",
    "response",
    "response_tokens",
    "role_code",
    "session_id",
    "tokens",
    "tool_calls",
)

