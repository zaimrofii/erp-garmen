"""Stream engine analytics (B.4) — sliding window + cooldown, Redis atomic.

Kontrak: docs/analytics/CONTRACT.md §8.4 (alert spike) & §8 (granularity hour).
SEMUA operasi window dijalankan dalam SATU pipeline transaksi (MULTI/EXEC):
ZADD + ZREMRANGEBYSCORE + EXPIRE — tidak boleh ada key tanpa TTL.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone as dt_timezone
from typing import Any

from django.conf import settings

from ..config import ANALYTICS_CONFIG

logger = logging.getLogger(__name__)

KEY_PREFIX = "analytics:stream:"
ALERT_KEY_PREFIX = "analytics:alert:"
COOLDOWN_SECONDS = 30 * 60  # 1 alert / metrik / 30 menit (CONTRACT §8.4)

_WINDOW_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def _redis_client():
    """Client Redis (URL sama dengan cache/Celery) — dibuat lazy."""
    import redis

    return redis.Redis.from_url(str(settings.REDIS_URL), decode_responses=True)


def _parse_window(window: str) -> int:
    """`"15m"` → 900, `"1h"` → 3600, `"30s"` → 30, `"1d"` → 86400."""
    text = str(window).strip().lower()
    if len(text) < 2 or text[-1] not in _WINDOW_UNITS:
        raise ValueError(f"window tidak dikenal: {window!r}")

    amount = text[:-1]
    if not amount.isdigit() or int(amount) <= 0:
        raise ValueError(f"window tidak dikenal: {window!r}")

    return int(amount) * _WINDOW_UNITS[text[-1]]


def _event_ts(event: dict[str, Any]) -> float:
    """Timestamp event (epoch detik): `ts` numerik, ISO-8601, atau sekarang."""
    raw = event.get("ts")
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str) and raw:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return time.time()
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt_timezone.utc)
        return parsed.timestamp()
    return time.time()


def _event_id(event: dict[str, Any]) -> str:
    raw = event.get("id") or event.get("event_id")
    if raw:
        return str(raw)
    return f"evt-{uuid.uuid4().hex[:12]}"


def record_event(event: dict[str, Any], metric_id: str, value: float) -> None:
    """Catat nilai event ke sorted set (score=ts) dengan trim + TTL atomic."""
    now = _event_ts(event)
    window = _parse_window(
        event.get("window") or ANALYTICS_CONFIG["stream_window_default"]
    )
    key = f"{KEY_PREFIX}{metric_id}"

    client = _redis_client()
    with client.pipeline(transaction=True) as pipe:
        pipe.zadd(key, {_event_id(event): now})
        pipe.zremrangebyscore(key, "-inf", now - window)
        pipe.expire(key, window * 2)
        pipe.execute()

    logger.debug(
        "analytics: stream %s +%s (window=%ss, value=%s).",
        metric_id,
        _event_id(event),
        window,
        value,
    )


def evaluate(event: dict[str, Any], rule: dict[str, Any]) -> dict[str, Any] | None:
    """Bandingkan nilai event dengan threshold + cooldown 30 menit.

    `rule` = ``{"metric_id", "window", "baseline", "threshold"}``.
    Return alert shape CONTRACT §8.4 atau ``None``.
    """
    metric_id = str(rule["metric_id"])
    window = str(rule.get("window") or ANALYTICS_CONFIG["stream_window_default"])
    baseline = float(rule.get("baseline") or 0.0)
    threshold = float(rule.get("threshold") or 0.0)

    value = float(event.get("value") if event.get("value") is not None else 0.0)

    if value <= threshold:
        return None

    client = _redis_client()
    alert_key = f"{ALERT_KEY_PREFIX}{metric_id}"
    if not client.set(alert_key, "1", nx=True, ex=COOLDOWN_SECONDS):
        logger.debug("analytics: alert %s dalam cooldown — dilewati.", metric_id)
        return None

    return {
        "metric_id": metric_id,
        "window": window,
        "value": value,
        "baseline": baseline,
        "threshold": threshold,
        "severity": "HIGH" if value >= threshold * 2 else "MEDIUM",
        "detected_at": datetime.now(dt_timezone.utc).astimezone().isoformat(),
    }


__all__ = ("evaluate", "record_event")

