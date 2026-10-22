"""Metrik `garment.wc_idle_status` (Fix #20) — status idle per work center.

Baris per WC aktif: ``status`` ACTIVE/IDLE/NO_EVENT, ``last_event_at``,
``idle_hours``. IDLE bila event terakhir ≥ 2 jam (tanpa kalender shift).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.utils import timezone

from ....core.metric import MetricDefinition

METRIC_ID = "garment.wc_idle_status"
IDLE_HOURS = 2.0
LOOKBACK_DAYS = 7


def _wc_id(row: dict) -> int | None:
    payload = row.get("payload") or {}
    if isinstance(payload, dict) and payload.get("work_center_id") not in (None, ""):
        try:
            return int(payload["work_center_id"])
        except (TypeError, ValueError):
            return None
    value = row.get("bundle__current_work_center_id")
    return int(value) if value is not None else None


def _compute_wc_idle_status(filters: dict[str, Any]) -> list[dict]:
    from apps_industry.garment.models import BundleEvent, WorkCenter

    now = timezone.now()
    raw_now = filters.get("now")
    if raw_now:
        from django.utils.dateparse import parse_datetime

        parsed = parse_datetime(str(raw_now))
        if parsed is not None:
            now = parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed)

    since = now - timedelta(days=LOOKBACK_DAYS)
    rows = BundleEvent.objects.filter(ts__gte=since).values(
        "ts", "payload", "bundle__current_work_center_id"
    )

    latest: dict[int, Any] = {}
    for row in rows:
        wc_id = _wc_id(row)
        if wc_id is None:
            continue
        if wc_id not in latest or row["ts"] > latest[wc_id]:
            latest[wc_id] = row["ts"]

    result: list[dict] = []
    for wc in WorkCenter.objects.filter(is_active=True).only("id", "code", "name"):
        last = latest.get(wc.pk)
        if last is None:
            result.append(
                {
                    "key": str(wc.pk),
                    "label": wc.code,
                    "value": 0.0,
                    "status": "NO_EVENT",
                    "last_event_at": None,
                    "idle_hours": None,
                }
            )
            continue

        idle_hours = max(0.0, (now - last).total_seconds() / 3600)
        result.append(
            {
                "key": str(wc.pk),
                "label": wc.code,
                "value": round(idle_hours, 2),
                "status": "IDLE" if idle_hours >= IDLE_HOURS else "ACTIVE",
                "last_event_at": timezone.localtime(last).isoformat(),
                "idle_hours": round(idle_hours, 2),
            }
        )

    return sorted(result, key=lambda item: -item["value"])


METRIC = MetricDefinition(
    metric_id=METRIC_ID,
    domain="garment",
    label="WC Idle Status",
    unit="jam",
    granularities=["hour"],
    dimensions=["work_center"],
    source_models=["garment.BundleEvent", "garment.WorkCenter"],
    formula_version="1.0",
    compute=_compute_wc_idle_status,
    null_policy="no_active_returns_empty",
)


__all__ = ("IDLE_HOURS", "LOOKBACK_DAYS", "METRIC", "METRIC_ID")
