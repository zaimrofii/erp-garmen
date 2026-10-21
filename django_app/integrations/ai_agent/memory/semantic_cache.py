"""Semantic cache exact-match (D.6) — Redis via Django cache + mirror ORM.

Embedding similarity sesungguhnya ada di Sprint G; Sprint D cukup hash exact.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

from ..config import AI_CONFIG
from ..models import AISemanticCache

logger = logging.getLogger(__name__)

_KEY_PREFIX = "ai_cache"
_VERSION_KEY = "ai_cache:version"
_DEFAULT_TTL = 300


def _ttl_seconds() -> int:
    return int(AI_CONFIG["semantic_cache"]["ttl_seconds"])


def _normalize(query_text: str) -> str:
    return " ".join((query_text or "").lower().split())


def _version() -> int:
    return int(cache.get(_VERSION_KEY, 1) or 1)


def _cache_key(normalized: str) -> str:
    digest = hashlib.sha1(f"{_version()}:{normalized}".encode("utf-8")).hexdigest()
    return f"{_KEY_PREFIX}:{digest}"


def get(query_text: str) -> dict | None:
    """Ambil response dari cache; ``None`` bila miss."""
    normalized = _normalize(query_text)
    if not normalized:
        return None

    payload = cache.get(_cache_key(normalized))
    if payload is None:
        return None

    row = (
        AISemanticCache.objects.filter(query_normalized_text=normalized)
        .order_by("-created_at")
        .first()
    )
    if row is not None:
        row.hit_count += 1
        row.save(update_fields=["hit_count"])

    return payload


def set(
    query_text: str,
    response: dict,
    tool_calls_signature: str = "",
    invalidation_trigger: str = "",
) -> None:
    """Simpan response di cache (TTL) + mirror ORM untuk audit."""
    normalized = _normalize(query_text)
    if not normalized:
        return

    ttl = _ttl_seconds()
    cache.set(_cache_key(normalized), response, timeout=ttl)

    AISemanticCache.objects.create(
        query_normalized_text=normalized,
        response_text=json.dumps(response, default=str),
        tool_calls_signature=(tool_calls_signature or "")[:64],
        expires_at=timezone.now() + timedelta(seconds=max(ttl, 0)),
        invalidation_trigger=(invalidation_trigger or "")[:50],
    )


def invalidate(trigger: str) -> int:
    """Invalidasi cache (global version bump) + tandai baris audit kedaluwarsa."""
    try:
        cache.incr(_VERSION_KEY)
    except ValueError:
        cache.set(_VERSION_KEY, 2, timeout=None)

    updated = AISemanticCache.objects.filter(invalidation_trigger=trigger).update(
        expires_at=timezone.now()
    )
    logger.info("ai_agent: cache invalidated trigger=%s rows=%d", trigger, updated)
    return updated


def _reset_for_tests() -> None:
    cache.delete(_VERSION_KEY)


__all__ = ("get", "invalidate", "set")

