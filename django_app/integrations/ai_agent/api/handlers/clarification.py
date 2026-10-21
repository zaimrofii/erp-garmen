"""Handler klarifikasi pending (R-1) — deterministik, tanpa LLM."""

from __future__ import annotations

from rest_framework.response import Response

from ...clarification import pending_state, resolver, templates
from ...clarification.pending_state import MAX_TURNS
from .common import clarification_response, elapsed_ms, looks_like_new_question


def handle_pending_clarification(
    request,
    message: str,
    *,
    channel: str = "DESKTOP",
    context: dict | None = None,
    session_id: str,
    started: float,
) -> Response | None:
    """Tangani jawaban klarifikasi; `None` = lanjut ke pipeline normal."""
    user_id = request.user.pk
    pending = pending_state.load(user_id, session_id)

    # Fix #17A — pesan pertanyaan baru = ganti topik (state dibuang).
    if pending and looks_like_new_question(message):
        pending_state.clear(user_id, session_id)
        pending = None

    if not pending:
        return None

    candidates = list(pending.get("candidates") or [])
    resolution = resolver.resolve(
        message,
        candidates,
        turn_count=int(pending.get("turn_count", 0) or 0),
    )
    resolved_types = {
        resolver.ResolutionType.RANK,
        resolver.ResolutionType.FUZZY,
    }

    def latency() -> int:
        return elapsed_ms(started)

    if resolution.type in resolved_types and resolution.candidate:
        if context is not None:
            context["_resolved_candidate"] = resolution.candidate
        # Fix #17A — state tetap hidup sampai TTL/batas turn.
        if pending_state.increment_turn(user_id, session_id) >= MAX_TURNS:
            pending_state.clear(user_id, session_id)
        return None

    if resolution.type is resolver.ResolutionType.CANCEL:
        pending_state.clear(user_id, session_id)
        return clarification_response(
            request, message, channel, "Baik, saya lupakan. Ada yang lain?", latency()
        )

    if resolution.type is resolver.ResolutionType.ESCALATE:
        pending_state.clear(user_id, session_id)
        return clarification_response(
            request,
            message,
            channel,
            templates.escalation_response(candidates),
            latency(),
        )

    if resolution.type is resolver.ResolutionType.ALL:
        pending_state.clear(user_id, session_id)
        return clarification_response(
            request, message, channel, templates.all_response(candidates), latency()
        )

    turn = pending_state.increment_turn(user_id, session_id)
    if turn >= MAX_TURNS:
        pending_state.clear(user_id, session_id)
        return clarification_response(
            request,
            message,
            channel,
            templates.escalation_response(candidates),
            latency(),
        )
    return clarification_response(
        request,
        message,
        channel,
        templates.ambiguous_question(candidates),
        latency(),
    )


__all__ = ("handle_pending_clarification",)
