"""Task Celery analytics garment (B.8) — agregasi snapshot + cleanup cache."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from celery import shared_task
from django.utils import timezone

from ...core import registry
from ...services.analytics_config_services import invalidate_cache
from .storage import get_storage_for_metric

logger = logging.getLogger(__name__)

_KEY_TO_BUCKET = {"key", "label", "value"}


def _parse_bucket(key: str) -> datetime:
    """Parse bucket `TruncDate` ("YYYY-MM-DD") atau `TruncHour` (datetime ISO)."""
    text = str(key)
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        value = datetime.strptime(text, "%Y-%m-%d")

    if timezone.is_naive(value):
        value = timezone.make_aware(value)
    return value


def _storage_rows(rows: list[dict], granularity: str) -> list[dict]:
    step = timedelta(hours=1) if granularity == "hour" else timedelta(days=1)
    result = []
    for row in rows:
        start = _parse_bucket(row["key"])
        result.append(
            {
                "dimension_key": "",
                "period_start": start,
                "period_end": start + step,
                "value": row.get("value"),
                "extra": {
                    key: value
                    for key, value in row.items()
                    if key not in _KEY_TO_BUCKET
                },
            }
        )
    return result


def _aggregate(granularity: str) -> dict[str, int]:
    """Hitung 3 metrik garment untuk 1 bucket terakhir lalu simpan snapshot.

    Bucket dihitung pada zona waktu lokal (WIB), bukan tengah malam UTC, agar
    konsisten dengan `timezone.localdate()` yang dipakai laporan dan test.
    """
    now = timezone.localtime(timezone.now())

    if granularity == "hour":
        end = now.replace(minute=0, second=0, microsecond=0)
        start = end - timedelta(hours=1)
    else:
        end = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start = end - timedelta(days=1)

    saved: dict[str, int] = {}
    for metric in registry.list_metrics("garment"):
        if granularity not in metric.granularities:
            continue

        rows = metric.compute(
            {
                "granularity": granularity,
                "group_by": "period",
                "date_from": start,
                "date_to": end,
            }
        )
        storage_rows = _storage_rows(rows, granularity)
        if not storage_rows:
            continue

        saved[metric.metric_id] = get_storage_for_metric(metric.metric_id).save(
            metric.metric_id, granularity, storage_rows
        )

    logger.info("analytics: agregasi %s menyimpan %s.", granularity, saved)
    return saved


@shared_task(name="analytics.aggregate_hourly")
def aggregate_hourly() -> dict[str, int]:
    """Snapshot metrik granularity `hour` untuk 1 jam terakhir (idempoten)."""
    return _aggregate("hour")


@shared_task(name="analytics.aggregate_daily")
def aggregate_daily() -> dict[str, int]:
    """Snapshot metrik granularity `day` untuk 1 hari terakhir (idempoten)."""
    return _aggregate("day")


@shared_task(name="analytics.aggregate_daily_summary")
def aggregate_daily_summary(day=None) -> dict:
    """S.5 Berat-Lite — hitung DailySummary (idempoten)."""
    from ...summary import aggregate_daily_summary as _aggregate_summary

    return _aggregate_summary(day)


@shared_task(name="analytics.cleanup_cache")
def cleanup_cache() -> bool:
    """Buang cache analytics (prefix/versi) — murah dan idempoten."""
    invalidate_cache()
    return True


__all__ = (
    "aggregate_daily",
    "aggregate_daily_summary",
    "aggregate_hourly",
    "cleanup_cache",
)

