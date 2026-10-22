"""Data Sanity v1 (S.7) — deteksi input operator tidak wajar.

Read-only: modul ini TIDAK mengubah data produksi. Semua fungsi mengembalikan
dict JSON-safe untuk konteks AI/observability.

Fungsi:
- ``detect_phantom_productivity`` — clustering input di akhir shift.
- ``detect_impossible_cycle_time`` — durasi siklus < standar.
- ``detect_scrap_discrepancy`` — scrap sewing > 10% dari qty cutting.
- ``compute_reliability_index`` — skor 0-100 per operator.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from django.db.models import Count, Sum
from django.utils import timezone

PHANTOM_WINDOW_MINUTES = 30
PHANTOM_MIN_EVENTS = 30
STANDARD_CYCLE_SECONDS = 45
SCRAP_THRESHOLD = 0.10
LOOKBACK_DAYS = 7
RELIABILITY_THRESHOLD = 60

START_TYPES = {"BUNDLE_START", "BUNDLE_RECEIVE", "BUNDLE_MOVE_IN"}
FINISH_TYPES = {"BUNDLE_FINISH", "BUNDLE_SEND"}


def _operator_filter(operator_id: int | str) -> dict[str, Any]:
    if isinstance(operator_id, int):
        return {"actor_id": operator_id}
    return {"actor__username": str(operator_id)}


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start = timezone.make_aware(datetime.combine(day, time.min))
    return start, start + timedelta(days=1)


def _max_events_in_window(
    timestamps: list[datetime], window_minutes: int = PHANTOM_WINDOW_MINUTES
) -> int:
    """Jumlah event maksimum dalam sliding window (menit) — PURE."""
    ordered = sorted(timestamps)
    window = timedelta(minutes=window_minutes)
    best = 0
    left = 0
    for right, current in enumerate(ordered):
        while current - ordered[left] > window:
            left += 1
        best = max(best, right - left + 1)
    return best


def detect_phantom_productivity(
    operator_id: int | str, date: date | None = None
) -> dict[str, Any]:
    """Deteksi ≥30 event dalam 30 menit (indikasi input ditumpuk)."""
    from apps_industry.garment.models import BundleEvent

    day = date or timezone.localdate()
    start, end = _day_bounds(day)
    timestamps = list(
        BundleEvent.objects.filter(
            ts__gte=start, ts__lt=end, **_operator_filter(operator_id)
        ).values_list("ts", flat=True)
    )
    peak = _max_events_in_window(timestamps)
    suspicious = peak >= PHANTOM_MIN_EVENTS

    message = (
        f"Operator {operator_id} input {peak} event dalam "
        f"{PHANTOM_WINDOW_MINUTES} menit pada {day.isoformat()} — kemungkinan ditumpuk."
        if suspicious
        else f"Input operator {operator_id} pada {day.isoformat()} wajar (puncak {peak} event/30 menit)."
    )

    return {
        "operator_id": operator_id,
        "date": day.isoformat(),
        "events": len(timestamps),
        "max_events_in_window": peak,
        "window_minutes": PHANTOM_WINDOW_MINUTES,
        "threshold": PHANTOM_MIN_EVENTS,
        "suspicious": suspicious,
        "message": message,
    }


def detect_impossible_cycle_time(bundle_id: int) -> dict[str, Any]:
    """Deteksi durasi START→FINISH < standar (45 detik)."""
    from apps_industry.garment.models import BundleEvent

    rows = list(
        BundleEvent.objects.filter(bundle_id=bundle_id)
        .order_by("ts")
        .values("event_type", "ts")
    )

    durations: list[float] = []
    pending_start: datetime | None = None
    for row in rows:
        event_type = str(row["event_type"]).upper()
        if event_type in START_TYPES:
            pending_start = row["ts"]
        elif event_type in FINISH_TYPES and pending_start is not None:
            durations.append((row["ts"] - pending_start).total_seconds())
            pending_start = None

    minimum = min(durations) if durations else None
    suspicious = minimum is not None and minimum < STANDARD_CYCLE_SECONDS

    return {
        "bundle_id": bundle_id,
        "standard_seconds": STANDARD_CYCLE_SECONDS,
        "min_cycle_seconds": round(minimum, 2) if minimum is not None else None,
        "occurrences": len(durations),
        "impossible_count": sum(
            1 for value in durations if value < STANDARD_CYCLE_SECONDS
        ),
        "suspicious": suspicious,
        "message": (
            f"Bundle {bundle_id}: siklus {minimum:.0f} detik < standar "
            f"{STANDARD_CYCLE_SECONDS} detik."
            if suspicious and minimum is not None
            else f"Bundle {bundle_id}: tidak ada siklus mustahil terdeteksi."
        ),
    }


def detect_scrap_discrepancy(order_id: int) -> dict[str, Any]:
    """Cross-check qty cutting (bundle) vs scrap sewing (> 10%)."""
    from apps_industry.garment.models import Bundle, ScrapAccumulator

    bundles = Bundle.objects.filter(work_order__order_line__order_id=order_id)
    input_qty = float(bundles.aggregate(total=Sum("qty"))["total"] or 0)
    scrap_qty = float(
        ScrapAccumulator.objects.filter(bundle__in=bundles).aggregate(
            total=Sum("qty")
        )["total"]
        or 0
    )
    ratio = (scrap_qty / input_qty) if input_qty > 0 else 0.0
    suspicious = ratio > SCRAP_THRESHOLD

    return {
        "order_id": order_id,
        "input_qty": input_qty,
        "scrap_qty": scrap_qty,
        "scrap_ratio": round(ratio, 4),
        "threshold": SCRAP_THRESHOLD,
        "suspicious": suspicious,
        "message": (
            f"Order {order_id}: scrap {ratio:.1%} dari qty cutting "
            f"(> {SCRAP_THRESHOLD:.0%}) — perlu cross-check."
            if suspicious
            else f"Order {order_id}: scrap {ratio:.1%} masih wajar."
        ),
    }

def _impossible_count_for_bundles(bundle_ids: list[int]) -> int:
    """Hitung pasangan START→FINISH < standar untuk kumpulan bundle."""
    from apps_industry.garment.models import BundleEvent

    if not bundle_ids:
        return 0

    rows = (
        BundleEvent.objects.filter(bundle_id__in=bundle_ids)
        .order_by("bundle_id", "ts")
        .values("bundle_id", "event_type", "ts")
    )
    pending: dict[int, datetime] = {}
    count = 0
    for row in rows:
        bundle_id = int(row["bundle_id"])
        event_type = str(row["event_type"]).upper()
        if event_type in START_TYPES:
            pending[bundle_id] = row["ts"]
        elif event_type in FINISH_TYPES and bundle_id in pending:
            seconds = (row["ts"] - pending.pop(bundle_id)).total_seconds()
            if seconds < STANDARD_CYCLE_SECONDS:
                count += 1
    return count


def compute_reliability_index(operator_id: int | str) -> dict[str, Any]:
    """Skor 0-100: penalti phantom, siklus mustahil, dan scrap discrepancy."""
    from apps_industry.garment.models import Bundle, BundleEvent

    since = timezone.now() - timedelta(days=LOOKBACK_DAYS)
    rows = list(
        BundleEvent.objects.filter(
            ts__gte=since, **_operator_filter(operator_id)
        ).values("ts", "bundle_id")
    )

    by_day: dict[str, list[datetime]] = {}
    for row in rows:
        key = timezone.localtime(row["ts"]).date().isoformat()
        by_day.setdefault(key, []).append(row["ts"])

    phantom_days = sum(
        1
        for timestamps in by_day.values()
        if _max_events_in_window(timestamps) >= PHANTOM_MIN_EVENTS
    )

    bundle_ids = sorted({int(row["bundle_id"]) for row in rows if row["bundle_id"]})
    impossible = _impossible_count_for_bundles(bundle_ids)

    order_ids = list(
        Bundle.objects.filter(pk__in=bundle_ids)
        .values_list("work_order__order_line__order_id", flat=True)
        .distinct()
    )
    discrepancies = sum(
        1
        for order_id in order_ids[:20]
        if order_id is not None and detect_scrap_discrepancy(int(order_id))["suspicious"]
    )

    penalty_phantom = min(40, phantom_days * 30)
    penalty_cycle = min(30, impossible * 10)
    penalty_scrap = min(20, discrepancies * 5)
    score = max(0, min(100, 100 - penalty_phantom - penalty_cycle - penalty_scrap))

    if score >= 80:
        level = "BAIK"
    elif score >= RELIABILITY_THRESHOLD:
        level = "CUKUP"
    else:
        level = "RENDAH"

    return {
        "operator_id": operator_id,
        "score": score,
        "level": level,
        "window_days": LOOKBACK_DAYS,
        "breakdown": {
            "events": len(rows),
            "phantom_days": phantom_days,
            "impossible_cycles": impossible,
            "scrap_discrepancies": discrepancies,
            "penalty_phantom": penalty_phantom,
            "penalty_cycle": penalty_cycle,
            "penalty_scrap": penalty_scrap,
        },
        "suspicious": score < RELIABILITY_THRESHOLD,
        "message": f"Reliability Index operator {operator_id}: {score}/100 ({level}).",
    }


def scan_suspicious_operators(
    days: int = LOOKBACK_DAYS, limit: int = 5
) -> list[dict[str, Any]]:
    """Operator paling aktif → reliability index, urut skor terendah."""
    from apps_industry.garment.models import BundleEvent

    since = timezone.now() - timedelta(days=max(1, days))
    actors = list(
        BundleEvent.objects.filter(ts__gte=since, actor__isnull=False)
        .values("actor_id", "actor__username")
        .annotate(events=Count("id"))
        .order_by("-events")[:10]
    )

    results: list[dict[str, Any]] = []
    for actor in actors:
        index = compute_reliability_index(int(actor["actor_id"]))
        index["username"] = actor["actor__username"]
        results.append(index)

    results.sort(key=lambda item: (item["score"], -item["breakdown"]["events"]))
    return results[: max(1, limit)]


def collect_operator_anomalies(
    message: str | None = None, user=None
) -> dict[str, Any]:
    """Ringkasan untuk context builder (dipanggil hanya saat keyword anomali)."""
    del message, user
    try:
        operators = scan_suspicious_operators()
    except Exception:  # noqa: BLE001 - data sanity tidak boleh menggagalkan chat
        operators = []

    suspicious = [item for item in operators if item.get("suspicious")]
    return {
        "operators": operators,
        "suspicious_count": len(suspicious),
        "reliability_threshold": RELIABILITY_THRESHOLD,
        "window_days": LOOKBACK_DAYS,
        "summary": (
            f"{len(suspicious)} operator dengan Reliability Index < "
            f"{RELIABILITY_THRESHOLD} dari {len(operators)} operator teraktif."
            if operators
            else "Belum ada event operator dalam 7 hari terakhir."
        ),
    }


__all__ = (
    "LOOKBACK_DAYS",
    "PHANTOM_MIN_EVENTS",
    "PHANTOM_WINDOW_MINUTES",
    "RELIABILITY_THRESHOLD",
    "SCRAP_THRESHOLD",
    "STANDARD_CYCLE_SECONDS",
    "collect_operator_anomalies",
    "compute_reliability_index",
    "detect_impossible_cycle_time",
    "detect_phantom_productivity",
    "detect_scrap_discrepancy",
    "scan_suspicious_operators",
)

