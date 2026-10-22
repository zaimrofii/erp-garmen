"""Rule-based anomaly explainer (TEMPORARY — nanti mcp-anomaly-explainer/KG).

Menjelaskan PENYEBAB anomali dari data SQL yang ada, bukan menebak.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from django.utils import timezone

__all__ = ("explain_lead_time_spike", "explain_oee_drop", "explain_scrap_spike")


def _bounds(day: date | None) -> tuple[date, datetime, datetime]:
    target = day or timezone.localdate()
    start = timezone.make_aware(datetime.combine(target, time.min))
    return target, start, start + timedelta(days=1)


def explain_scrap_spike(day: date | None = None) -> dict[str, Any]:
    """Cari WC/operator/shift penyumbang scrap tertinggi."""
    from integrations.ai_agent.data_access.metrics import MetricsRepository

    target, _start, _end = _bounds(day)
    repo = MetricsRepository()
    by_wc = repo.quality_by_wc()
    by_operator = repo.quality_by_operator()
    by_shift = repo.quality_by_shift()

    top_wc = max(by_wc, key=lambda row: row["scrap_qty"], default=None)
    top_operator = max(by_operator, key=lambda row: row["scrap_events"], default=None)
    top_shift = max(by_shift, key=lambda row: row["scrap_qty"], default=None)

    if not top_wc or top_wc["scrap_qty"] <= 0:
        return {
            "type": "scrap_spike",
            "date": target.isoformat(),
            "found": False,
            "narrative": "Data scrap belum lengkap untuk dijelaskan.",
            "evidence": {},
        }

    total = sum(row["scrap_qty"] for row in by_wc) or 1
    share = top_wc["scrap_qty"] / total
    operator_text = (
        f", operator {top_operator['operator']} ({top_operator['scrap_events']} event scrap)"
        if top_operator and top_operator["scrap_events"] > 0
        else ""
    )
    shift_text = (
        f", shift {top_shift['shift']}" if top_shift and top_shift["scrap_qty"] > 0 else ""
    )
    narrative = (
        f"Scrap naik karena {top_wc['work_center']} ({share:.0%} scrap)"
        f"{operator_text}{shift_text}."
    )

    return {
        "type": "scrap_spike",
        "date": target.isoformat(),
        "found": True,
        "narrative": narrative,
        "evidence": {
            "top_work_center": top_wc,
            "top_operator": top_operator,
            "top_shift": top_shift,
            "share": round(share, 4),
            "by_wc": by_wc,
        },
    }


def _metric_rows(metric_id: str, group_by: str, start: datetime, end: datetime) -> list[dict]:
    from integrations.analytics.core.registry import get_metric

    try:
        metric = get_metric(metric_id)
        return list(
            metric.compute(
                {
                    "granularity": "day",
                    "group_by": group_by,
                    "date_from": start,
                    "date_to": end,
                }
            )
        )
    except Exception:  # noqa: BLE001 - explainer tidak boleh crash chat
        return []


def explain_lead_time_spike(day: date | None = None) -> dict[str, Any]:
    """Lead time melonjak → cek bottleneck WC + buffer."""
    target, start, end = _bounds(day)
    lead_rows = _metric_rows("garment.lead_time", "period", start, end)
    bottleneck_rows = _metric_rows("garment.bottleneck", "work_center", start, end)

    lead_value = max(
        (float(row.get("value") or 0) for row in lead_rows), default=0.0
    )
    top = max(
        bottleneck_rows,
        key=lambda row: float(row.get("value") or 0),
        default=None,
    )

    if not lead_rows and not bottleneck_rows:
        return {
            "type": "lead_time_spike",
            "date": target.isoformat(),
            "found": False,
            "narrative": "Data lead time/bottleneck belum lengkap.",
            "evidence": {},
        }

    narrative = f"Lead time {lead_value:.1f} jam."
    if top and float(top.get("value") or 0) > 0:
        narrative += (
            f" Bottleneck utama {top.get('label') or top.get('key')}: "
            f"buffer {top.get('buffer_length', 0)} bundle, "
            f"tunggu {top.get('avg_wait_hours', 0):.1f} jam."
        )

    return {
        "type": "lead_time_spike",
        "date": target.isoformat(),
        "found": True,
        "narrative": narrative,
        "evidence": {
            "lead_time": lead_value,
            "bottleneck": bottleneck_rows[:5],
        },
    }


def explain_oee_drop(day: date | None = None) -> dict[str, Any]:
    """OEE turun → jelaskan komponen A/P/Q terendah per WC."""
    target, start, end = _bounds(day)
    rows = _metric_rows("garment.oee", "work_center", start, end)

    if not rows:
        return {
            "type": "oee_drop",
            "date": target.isoformat(),
            "found": False,
            "narrative": "Data OEE belum lengkap untuk dijelaskan.",
            "evidence": {},
        }

    lowest = min(rows, key=lambda row: float(row.get("value") or 0))
    components = {
        "availability": float(lowest.get("availability") or 0),
        "performance": float(lowest.get("performance") or 0),
        "quality": float(lowest.get("quality") or 0),
    }
    weakest = min(components, key=components.get)
    label = lowest.get("label") or lowest.get("key")
    narrative = (
        f"OEE {label} turun ke {float(lowest.get('value') or 0):.1f}%. "
        f"Komponen terlemah: {weakest} ({components[weakest]:.0%})."
    )
    if weakest == "quality":
        narrative += " Cek scrap/rework terakhir."
    elif weakest == "availability":
        narrative += " Cek WC idle dan downtime."
    else:
        narrative += " Cek output vs kapasitas."

    return {
        "type": "oee_drop",
        "date": target.isoformat(),
        "found": True,
        "narrative": narrative,
        "evidence": {
            "lowest": lowest,
            "components": components,
            "weakest": weakest,
            "rows": rows[:5],
        },
    }
