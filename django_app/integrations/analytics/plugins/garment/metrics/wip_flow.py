"""Metrik `garment.wip_flow` (S.6) — arus masuk−keluar bundle per WC per jam.

Nilai positif = menumpuk, negatif = mengalir keluar. Sumber: satu query
`BundleEvent` dalam rentang; arah ditentukan `payload.direction` (in/out) atau
tipe event (START/RECEIVE/MOVE_IN = masuk, FINISH/SEND/MOVE_OUT = keluar).
"""

from __future__ import annotations

from typing import Any

from django.db.models.functions import TruncHour

from ....core.metric import MetricDefinition
from ._common import range_kwargs

METRIC_ID = "garment.wip_flow"
IN_TYPES = {"BUNDLE_START", "BUNDLE_RECEIVE", "BUNDLE_MOVE_IN", "BUNDLE_QUEUE_IN"}
OUT_TYPES = {"BUNDLE_FINISH", "BUNDLE_SEND", "BUNDLE_MOVE_OUT"}


def _direction(row: dict) -> str | None:
    payload = row.get("payload") or {}
    if isinstance(payload, dict):
        value = str(payload.get("direction") or "").lower()
        if value in {"in", "out"}:
            return value
    event_type = str(row.get("event_type") or "").upper()
    if event_type in IN_TYPES:
        return "in"
    if event_type in OUT_TYPES:
        return "out"
    return None


def _wc_id(row: dict) -> int | None:
    payload = row.get("payload") or {}
    if isinstance(payload, dict) and payload.get("work_center_id") not in (None, ""):
        try:
            return int(payload["work_center_id"])
        except (TypeError, ValueError):
            return None
    value = row.get("bundle__current_work_center_id")
    return int(value) if value is not None else None


def _compute_wip_flow(filters: dict[str, Any]) -> list[dict]:
    """Hitung (in − out) per jam/per work center dari event bundle."""
    from apps_industry.garment.models import BundleEvent, WorkCenter

    group_by = filters.get("group_by") or "period"
    events = BundleEvent.objects.filter(**range_kwargs(filters, "ts"))

    if filters.get("work_center_id"):
        events = events.filter(
            bundle__current_work_center_id=filters["work_center_id"]
        )
    if filters.get("line_id"):
        events = events.filter(bundle__production_line_id=filters["line_id"])

    rows = list(
        events.annotate(hour=TruncHour("ts")).values(
            "hour",
            "event_type",
            "payload",
            "bundle__current_work_center_id",
        )
    )
    if not rows:
        return []

    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        direction = _direction(row)
        if direction is None:
            continue
        wc_id = _wc_id(row)
        if wc_id is None:
            continue

        if group_by == "work_center":
            key = str(wc_id)
        else:
            key = row["hour"].isoformat()

        entry = grouped.setdefault(key, {"key": key, "in": 0, "out": 0})
        entry[direction] += 1

    if group_by == "work_center":
        wc_map = {
            wc.pk: wc
            for wc in WorkCenter.objects.filter(pk__in=[int(k) for k in grouped]).only(
                "id", "code", "name"
            )
        }
    else:
        wc_map = {}

    result: list[dict] = []
    for key, entry in grouped.items():
        value = entry["in"] - entry["out"]
        if group_by == "work_center":
            wc = wc_map.get(int(key))
            label = (getattr(wc, "code", None) or key) if wc else key
        else:
            label = key
        result.append(
            {
                "key": key,
                "label": label,
                "value": value,
                "in": entry["in"],
                "out": entry["out"],
            }
        )

    return sorted(result, key=lambda item: item["key"])


METRIC = MetricDefinition(
    metric_id=METRIC_ID,
    domain="garment",
    label="WIP Flow",
    unit="bundle/jam",
    granularities=["hour"],
    dimensions=["period", "work_center"],
    source_models=["garment.BundleEvent", "garment.WorkCenter"],
    formula_version="1.0",
    compute=_compute_wip_flow,
    null_policy="no_active_returns_empty",
)


__all__ = ("IN_TYPES", "METRIC", "METRIC_ID", "OUT_TYPES")
