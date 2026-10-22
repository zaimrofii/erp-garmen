"""Metrik `garment.buffer_status` (Fix #20) — buffer per work center.

Baris per WC aktif: ``buffer_length`` (WCQueue), ``threshold`` (default 20),
``overflow``, ``status`` OVERFLOW/OK.
"""

from __future__ import annotations

from typing import Any

from ....core.metric import MetricDefinition

METRIC_ID = "garment.buffer_status"
DEFAULT_THRESHOLD = 20


def _compute_buffer_status(filters: dict[str, Any]) -> list[dict]:
    from apps_industry.garment.models import WorkCenter
    from apps_industry.garment.services.wc_queue import WCQueue

    try:
        threshold = int(filters.get("threshold") or DEFAULT_THRESHOLD)
    except (TypeError, ValueError):
        threshold = DEFAULT_THRESHOLD

    queue = WCQueue()
    result: list[dict] = []
    for wc in WorkCenter.objects.filter(is_active=True).only("id", "code", "name"):
        try:
            length = queue.count(wc)
        except Exception:  # noqa: BLE001 - status tidak boleh menggagalkan metrik
            continue
        overflow = length > threshold
        result.append(
            {
                "key": str(wc.pk),
                "label": wc.code,
                "value": length,
                "buffer_length": length,
                "threshold": threshold,
                "overflow": overflow,
                "status": "OVERFLOW" if overflow else "OK",
            }
        )

    return sorted(result, key=lambda item: -item["value"])


METRIC = MetricDefinition(
    metric_id=METRIC_ID,
    domain="garment",
    label="Buffer Status",
    unit="bundle",
    granularities=["hour"],
    dimensions=["work_center"],
    source_models=["garment.Bundle", "garment.WorkCenter"],
    formula_version="1.0",
    compute=_compute_buffer_status,
    null_policy="no_active_returns_empty",
)


__all__ = ("DEFAULT_THRESHOLD", "METRIC", "METRIC_ID")
