"""Drift detector intent AI (F.4.2) — window vs baseline (set-based)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.db.models import Count
from django.utils import timezone

from ..config import AI_CONFIG
from ..models import AIDecisionLog


def _distribution(queryset) -> tuple[list[dict[str, Any]], int]:
    rows = (
        queryset.exclude(intent="")
        .values("intent")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    total = sum(int(row["count"]) for row in rows)

    return (
        [
            {
                "intent": row["intent"],
                "count": int(row["count"]),
                "pct": round(int(row["count"]) / total * 100, 2) if total else 0.0,
            }
            for row in rows
        ],
        total,
    )


def detect_drift(window_days: int = 7) -> dict[str, Any]:
    """Deteksi pergeseran distribusi intent (ambang config, default 20 poin)."""
    now = timezone.now()
    window_start = now - timedelta(days=window_days)
    baseline_days = int(AI_CONFIG["observability"]["drift_baseline_days"])
    baseline_start = window_start - timedelta(days=baseline_days)

    current, _ = _distribution(
        AIDecisionLog.objects.filter(timestamp__gte=window_start, timestamp__lte=now)
    )
    baseline, _ = _distribution(
        AIDecisionLog.objects.filter(
            timestamp__gte=baseline_start, timestamp__lt=window_start
        )
    )

    current_pct = {row["intent"]: row["pct"] for row in current}
    baseline_pct = {row["intent"]: row["pct"] for row in baseline}
    intents = sorted(set(current_pct) | set(baseline_pct))
    delta_pct = {
        intent: round(current_pct.get(intent, 0.0) - baseline_pct.get(intent, 0.0), 2)
        for intent in intents
    }

    threshold = float(AI_CONFIG["observability"]["drift_threshold_pct"])
    drifted = any(abs(delta) > threshold for delta in delta_pct.values())

    return {
        "drifted": drifted,
        "intents_current": current,
        "intents_baseline": baseline,
        "delta_pct": delta_pct,
        "threshold_pct": threshold,
        "computed_at": now.isoformat(),
    }


__all__ = ("detect_drift",)
