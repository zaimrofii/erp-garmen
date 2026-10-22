"""Handler klarifikasi pending (R-1) — deterministik, tanpa LLM."""

from __future__ import annotations

from rest_framework.response import Response

from ...clarification import pending_state, resolver, templates
from ...clarification.pending_state import MAX_TURNS
from ...memory import semantic_cache
from ...orchestrator.text_normalizer import normalize
from .common import clarification_response, elapsed_ms, looks_like_new_question


def _clear_and_invalidate(user_id: int, session_id: str) -> None:
    """Hapus state klarifikasi dan buang cache jawaban lama."""
    pending_state.clear(user_id, session_id)
    try:
        semantic_cache.invalidate("clarification_reset")
    except Exception:  # noqa: BLE001 - cache opsional
        pass


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

    if not pending:
        return None

    candidates = list(pending.get("candidates") or [])

    def latency() -> int:
        return elapsed_ms(started)

    original = str(pending.get("original_query") or "")
    if original and normalize(message)["tokens"] == normalize(original)["tokens"]:
        # Pertanyaan awal diulang: jangan eksekusi ulang; buang state dan
        # biarkan pipeline membangun kandidat dari data terkini.
        _clear_and_invalidate(user_id, session_id)
        return None

    failed_count = pending_state.failed_clarification_count(pending)
    resolution = resolver.resolve(
        message,
        candidates,
        turn_count=failed_count,
    )
    resolved_types = {
        resolver.ResolutionType.RANK,
        resolver.ResolutionType.FUZZY,
    }

    def is_new_topic() -> bool:
        tokens = [token.strip("?.,!") for token in str(message or "").split()]
        if len(tokens) <= 1 or not looks_like_new_question(message):
            return False
        original_tokens = normalize(original)["tokens"] if original else []
        if original_tokens and normalize(message)["tokens"] == original_tokens:
            return False
        return True

    if resolution.type in resolved_types and resolution.candidate:
        if context is not None:
            context["_resolved_candidate"] = resolution.candidate
        # Fix #17A + Fase 3A — RANK berhasil tidak menghabiskan MAX_TURNS.
        pending_state.record_success(user_id, session_id, resolution.candidate)
        return None

    if resolution.type is resolver.ResolutionType.CANCEL:
        _clear_and_invalidate(user_id, session_id)
        remainder = getattr(resolution, "remainder", None)
        if remainder:
            # Fase 3B — jalankan sisa pertanyaan setelah cancel.
            setattr(request, "_ai_remainder", remainder)
            return None
        return clarification_response(
            request, message, channel, "Baik, saya lupakan. Ada yang lain?", latency()
        )

    if is_new_topic():
        _clear_and_invalidate(user_id, session_id)
        return None

    if resolution.type is resolver.ResolutionType.ESCALATE:
        _clear_and_invalidate(user_id, session_id)
        return clarification_response(
            request,
            message,
            channel,
            templates.escalation_response(candidates),
            latency(),
        )

    if resolution.type is resolver.ResolutionType.ALL:
        _clear_and_invalidate(user_id, session_id)
        return clarification_response(
            request, message, channel, templates.all_response(candidates), latency()
        )

    failed = pending_state.record_failure(user_id, session_id)
    if failed >= MAX_TURNS:
        _clear_and_invalidate(user_id, session_id)
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
