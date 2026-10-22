"""Stream alert `garment.wc_idle` (S.6) — work center tanpa event > 2 jam kerja.

Best-effort: fungsi ini hanya mendeteksi; pengiriman WA dilakukan listener
(`integrations.analytics.core.event_listener`) dan kegagalan WA ditelan.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone

ALERT_ID = "garment.wc_idle"
IDLE_HOURS = 2.0
WORK_START_HOUR = 8
WORK_END_HOUR = 17
LOOKBACK_DAYS = 7


def _as_local(value: datetime) -> datetime:
    return timezone.localtime(value) if timezone.is_aware(value) else value


def _is_working_time(moment: datetime) -> bool:
    return moment.weekday() < 5 and WORK_START_HOUR <= moment.hour < WORK_END_HOUR


def _wc_id(row: dict) -> int | None:
    payload = row.get("payload") or {}
    if isinstance(payload, dict) and payload.get("work_center_id") not in (None, ""):
        try:
            return int(payload["work_center_id"])
        except (TypeError, ValueError):
            return None
    value = row.get("bundle__current_work_center_id")
    return int(value) if value is not None else None


def check_wc_idle(
    event: dict[str, Any] | None = None,
    now: datetime | None = None,
    user=None,
) -> dict[str, Any] | None:
    """Alert bila WC aktif terakhir menerima event > 2 jam lalu (jam kerja)."""
    del event, user

    moment = _as_local(now or timezone.now())
    if not _is_working_time(moment):
        return None

    from apps_industry.garment.models import BundleEvent, WorkCenter

    since = moment - timedelta(days=LOOKBACK_DAYS)
    rows = BundleEvent.objects.filter(ts__gte=since).values(
        "ts",
        "bundle__current_work_center_id",
        "payload",
    )

    latest: dict[int, datetime] = {}
    for row in rows:
        wc_id = _wc_id(row)
        ts = row.get("ts")
        if wc_id is None or ts is None:
            continue
        if wc_id not in latest or ts > latest[wc_id]:
            latest[wc_id] = ts

    if not latest:
        return None

    idle: list[dict[str, Any]] = []
    for wc in WorkCenter.objects.filter(pk__in=list(latest), is_active=True).only(
        "id", "code", "name"
    ):
        last = latest[wc.pk]
        hours = (moment - _as_local(last)).total_seconds() / 3600
        if hours >= IDLE_HOURS:
            idle.append(
                {
                    "work_center_id": wc.pk,
                    "work_center": wc.code,
                    "idle_hours": round(hours, 1),
                    "last_event": _as_local(last).isoformat(),
                }
            )

    if not idle:
        return None

    names = ", ".join(item["work_center"] for item in idle)
    return {
        "alert_id": ALERT_ID,
        "metric_id": ALERT_ID,
        "severity": "MEDIUM",
        "value": max(item["idle_hours"] for item in idle),
        "threshold": IDLE_HOURS,
        "work_centers": idle,
        "detected_at": moment.isoformat(),
        "message": f"Work center idle > {IDLE_HOURS:.0f} jam: {names}",
    }


__all__ = (
    "ALERT_ID",
    "IDLE_HOURS",
    "LOOKBACK_DAYS",
    "WORK_END_HOUR",
    "WORK_START_HOUR",
    "check_wc_idle",
)
