"""DailySummary L2/L3 (TEMPORARY) — ringkasan harian untuk AI.

Dihitung dari event/scrap/metrik yang sudah ada; tidak menulis data bisnis.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from django.db.models import Count, Sum
from django.utils import timezone

__all__ = ("aggregate_daily_summary", "get_summary")


def _bounds(day: date | None) -> tuple[date, datetime, datetime]:
    target = day or timezone.localdate()
    start = timezone.make_aware(datetime.combine(target, time.min))
    return target, start, start + timedelta(days=1)


def _metric_rows(metric_id: str, start: datetime, end: datetime, group_by: str) -> list[dict]:
    from integrations.analytics.core.registry import get_metric

    try:
        return list(
            get_metric(metric_id).compute(
                {
                    "granularity": "day",
                    "group_by": group_by,
                    "date_from": start,
                    "date_to": end,
                }
            )
        )
    except Exception:  # noqa: BLE001 - ringkasan tidak boleh menggagalkan task
        return []


def aggregate_daily_summary(day: date | None = None) -> dict[str, Any]:
    """Hitung + simpan DailySummary untuk satu hari (idempoten)."""
    from apps_industry.garment.models import BundleEvent, ScrapAccumulator
    from integrations.analytics.models import DailySummary

    target, start, end = _bounds(day)

    output = (
        BundleEvent.objects.filter(
            event_type__in=["BUNDLE_FINISH", "BUNDLE_SEND"],
            ts__gte=start,
            ts__lt=end,
        ).aggregate(total=Sum("bundle__qty"))["total"]
        or 0
    )
    scrap_rows = ScrapAccumulator.objects.filter(
        created_at__gte=start, created_at__lt=end
    )
    scrap = scrap_rows.aggregate(total=Sum("qty"))["total"] or 0
    rework = scrap_rows.aggregate(total=Sum("rework_qty"))["total"] or 0

    oee_rows = _metric_rows("garment.oee", start, end, "period")
    oee_value = max(
        (float(row.get("value") or 0) for row in oee_rows), default=0.0
    )
    lead_rows = _metric_rows("garment.lead_time", start, end, "period")
    lead_values = [
        float(row["value"]) for row in lead_rows if row.get("value") is not None
    ]
    avg_lead = sum(lead_values) / len(lead_values) if lead_values else 0.0

    top_wc_row = (
        scrap_rows.values("work_center__code")
        .annotate(total=Sum("qty"))
        .order_by("-total")
        .first()
    )
    top_operator_row = (
        BundleEvent.objects.filter(ts__gte=start, ts__lt=end, actor__isnull=False)
        .values("actor__username")
        .annotate(events=Count("id"))
        .order_by("-events")
        .first()
    )

    summary, _created = DailySummary.objects.update_or_create(
        date=target,
        defaults={
            "total_output": float(output or 0),
            "total_scrap": float(scrap or 0),
            "total_rework": float(rework or 0),
            "avg_lead_time": round(avg_lead, 2),
            "oee": round(oee_value, 2),
            "top_wc": (top_wc_row or {}).get("work_center__code") or "",
            "top_operator": (top_operator_row or {}).get("actor__username") or "",
        },
    )
    return get_summary(target) or {"date": target.isoformat()}


def get_summary(day: date | None = None) -> dict[str, Any] | None:
    """Ambil ringkasan harian (None bila belum dihitung)."""
    from integrations.analytics.models import DailySummary

    target = day or timezone.localdate()
    row = DailySummary.objects.filter(date=target).first()
    if row is None:
        return None
    return {
        "date": row.date.isoformat(),
        "total_output": row.total_output,
        "total_scrap": row.total_scrap,
        "total_rework": row.total_rework,
        "avg_lead_time": row.avg_lead_time,
        "oee": row.oee,
        "top_wc": row.top_wc,
        "top_operator": row.top_operator,
    }
