"""Metrik `garment.oee` (S.6) — Availability × Performance × Quality per work center.

Definisi v1 (deterministik, tanpa kalender shift eksternal):
- Availability = jam aktif / jam terjadwal (8 jam/hari kerja data).
  Jam aktif = jumlah bucket jam yang punya BundleEvent, maksimal 8/hari.
- Performance = output / (capacity_per_hour × jam aktif), dibatasi 1.0.
  capacity 0 → performance 1.0 (tidak bisa diukur, bukan 0).
- Quality = 1 − scrap / (output + scrap); denominator 0 → 0.
- OEE = A × P × Q × 100 (persen).

Tanpa event pada rentang → row kosong (``no_active_returns_empty``).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from django.db.models import Sum
from django.db.models.functions import TruncDate

from ....core.metric import MetricDefinition
from ._common import range_kwargs

METRIC_ID = "garment.oee"
SCHEDULED_HOURS_PER_DAY = 8.0


def _week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _event_wc(row: dict) -> int | None:
    payload = row.get("payload") or {}
    if isinstance(payload, dict) and payload.get("work_center_id") not in (None, ""):
        try:
            return int(payload["work_center_id"])
        except (TypeError, ValueError):
            pass
    value = row.get("bundle__current_work_center_id")
    return int(value) if value is not None else None


def _compute_oee(filters: dict[str, Any]) -> list[dict]:
    """Hitung OEE per period/work center dari event + scrap (set-based)."""
    from apps_industry.garment.models import BundleEvent, ScrapAccumulator, WorkCenter

    group_by = filters.get("group_by") or "period"
    granularity = filters.get("granularity") or "day"

    events = BundleEvent.objects.filter(**range_kwargs(filters, "ts"))
    scrap = ScrapAccumulator.objects.filter(**range_kwargs(filters, "created_at"))

    if filters.get("work_center_id"):
        events = events.filter(
            bundle__current_work_center_id=filters["work_center_id"]
        )
        scrap = scrap.filter(work_center_id=filters["work_center_id"])
    if filters.get("line_id"):
        events = events.filter(bundle__production_line_id=filters["line_id"])
        scrap = scrap.filter(bundle__production_line_id=filters["line_id"])

    event_rows = list(
        events.annotate(day=TruncDate("ts")).values(
            "day",
            "ts",
            "event_type",
            "bundle__qty",
            "bundle__current_work_center_id",
            "payload",
        )
    )
    if not event_rows:
        return []

    scrap_rows = list(
        scrap.annotate(day=TruncDate("created_at"))
        .values("day", "work_center_id")
        .annotate(qty=Sum("qty"))
    )

    buckets: dict[tuple[date, int], dict[str, Any]] = {}
    for row in event_rows:
        wc_id = _event_wc(row)
        if wc_id is None:
            continue
        key = (row["day"], wc_id)
        entry = buckets.setdefault(key, {"hours": set(), "output": 0.0})
        entry["hours"].add(row["ts"].hour)
        if row["event_type"] in {"BUNDLE_FINISH", "BUNDLE_SEND"}:
            entry["output"] += float(row["bundle__qty"] or 0)

    if not buckets:
        return []

    scraps: dict[tuple[date, int], float] = {}
    for row in scrap_rows:
        if row.get("work_center_id") is None:
            continue
        scraps[(row["day"], int(row["work_center_id"]))] = float(row["qty"] or 0)

    wc_ids = {wc_id for (_day, wc_id) in buckets}
    wc_map = {
        wc.pk: wc
        for wc in WorkCenter.objects.filter(pk__in=wc_ids).only(
            "id", "code", "name", "capacity_per_hour"
        )
    }

    groups: dict[str, dict[str, Any]] = {}
    for (day, wc_id), entry in buckets.items():
        if group_by == "work_center":
            key = str(wc_id)
        elif granularity == "week":
            key = _week_start(day).isoformat()
        else:
            key = day.isoformat()

        group = groups.setdefault(
            key,
            {
                "key": key,
                "days": set(),
                "hours": 0.0,
                "output": 0.0,
                "scrap": 0.0,
                "capacity_hours": 0.0,
            },
        )
        active_hours = min(float(len(entry["hours"])), SCHEDULED_HOURS_PER_DAY)
        wc = wc_map.get(wc_id)
        capacity = float(getattr(wc, "capacity_per_hour", 0) or 0)
        group["days"].add(day)
        group["hours"] += active_hours
        group["output"] += entry["output"]
        group["scrap"] += scraps.get((day, wc_id), 0.0)
        group["capacity_hours"] += capacity * active_hours

    rows: list[dict] = []
    for group in groups.values():
        scheduled = SCHEDULED_HOURS_PER_DAY * max(1, len(group["days"]))
        availability = min(1.0, group["hours"] / scheduled) if scheduled else 0.0
        performance = (
            min(1.0, group["output"] / group["capacity_hours"])
            if group["capacity_hours"] > 0
            else 1.0
        )
        denominator = group["output"] + group["scrap"]
        quality = 1.0 - (group["scrap"] / denominator) if denominator > 0 else 0.0
        quality = max(0.0, min(1.0, quality))
        value = availability * performance * quality * 100

        if group_by == "work_center":
            wc = wc_map.get(int(group["key"]))
            label = (
                (getattr(wc, "code", None) or str(group["key"])) if wc else group["key"]
            )
        else:
            label = group["key"]

        rows.append(
            {
                "key": group["key"],
                "label": label,
                "value": round(value, 2),
                "availability": round(availability, 3),
                "performance": round(performance, 3),
                "quality": round(quality, 3),
                "output_qty": round(group["output"], 2),
                "scrap_qty": round(group["scrap"], 2),
            }
        )

    return sorted(rows, key=lambda item: item["key"])


METRIC = MetricDefinition(
    metric_id=METRIC_ID,
    domain="garment",
    label="OEE",
    unit="%",
    granularities=["day", "week"],
    dimensions=["period", "work_center"],
    source_models=[
        "garment.BundleEvent",
        "garment.ScrapAccumulator",
        "garment.WorkCenter",
    ],
    formula_version="1.0",
    compute=_compute_oee,
    null_policy="no_active_returns_empty",
)


__all__ = ("METRIC", "METRIC_ID", "SCHEDULED_HOURS_PER_DAY")

