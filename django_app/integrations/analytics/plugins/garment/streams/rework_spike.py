"""Stream alert `garment.rework_rate` (R.4) — deteksi spike deterministik.

Aturan (docs/analytics/CONTRACT.md §8.4):
``value > max(baseline + 3σ, ambang absolut 3%)`` dengan σ minimal 0.5 poin.
Baseline = rata-rata harian 7 hari terakhir (minimal 3 hari data).
"""

from __future__ import annotations

import statistics
from datetime import date, timedelta
from typing import Any

from django.utils import timezone

METRIC_ID = "garment.rework_rate"
BASELINE_DAYS = 7
MIN_BASELINE_DAYS = 3
MIN_SIGMA = 0.5
ABSOLUTE_THRESHOLD = 3.0


def _values(rows: list[dict[str, Any]]) -> list[float]:
    values: list[float] = []
    for row in rows or []:
        value = row.get("value") if isinstance(row, dict) else None
        if value is not None:
            values.append(float(value))
    return values


def check_rework_spike(
    event: dict[str, Any] | None = None,
    today: date | None = None,
    user=None,
) -> dict[str, Any] | None:
    """Return alert dict bila rework hari ini melewati threshold, else None."""
    del event, user  # signature kompatibel listener; tidak dipakai

    try:
        from ....core.registry import get_metric

        metric = get_metric(METRIC_ID)
    except Exception:  # noqa: BLE001 - alert tidak boleh menggagalkan operator
        return None

    day = today or timezone.localdate()
    baseline_from = day - timedelta(days=BASELINE_DAYS)
    baseline_to = day - timedelta(days=1)

    try:
        baseline_rows = metric.compute(
            {
                "granularity": "day",
                "group_by": "period",
                "date_from": baseline_from.isoformat(),
                "date_to": baseline_to.isoformat(),
            }
        )
        today_rows = metric.compute(
            {
                "granularity": "day",
                "group_by": "period",
                "date_from": day.isoformat(),
                "date_to": day.isoformat(),
            }
        )
    except Exception:  # noqa: BLE001
        return None

    baseline_values = _values(baseline_rows)
    if len(baseline_values) < MIN_BASELINE_DAYS:
        return None

    today_values = _values(today_rows)
    if not today_values:
        return None

    value = max(today_values)
    baseline_mean = statistics.mean(baseline_values)
    sigma = (
        statistics.stdev(baseline_values) if len(baseline_values) > 1 else 0.0
    )
    sigma = max(sigma, MIN_SIGMA)
    threshold = max(baseline_mean + 3 * sigma, ABSOLUTE_THRESHOLD)

    if value <= threshold:
        return None

    return {
        "metric_id": METRIC_ID,
        "window": "1d",
        "value": round(value, 2),
        "baseline": round(baseline_mean, 2),
        "threshold": round(threshold, 2),
        "severity": "HIGH" if value > ABSOLUTE_THRESHOLD else "MEDIUM",
        "detected_at": timezone.now().isoformat(),
        "message": (
            f"Rework spike: {value:.2f}% "
            f"(baseline {baseline_mean:.2f}%, threshold {threshold:.2f}%)"
        ),
    }


__all__ = (
    "ABSOLUTE_THRESHOLD",
    "BASELINE_DAYS",
    "METRIC_ID",
    "MIN_BASELINE_DAYS",
    "MIN_SIGMA",
    "check_rework_spike",
)
