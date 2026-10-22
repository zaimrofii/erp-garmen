"""Stream alert `garment.buffer_overflow` (S.6) — queue WC melebihi ambang.

Buffer = bundle belum selesai dengan `current_work_center = WC` (WCQueue).
"""

from __future__ import annotations

from typing import Any

from django.utils import timezone

ALERT_ID = "garment.buffer_overflow"
DEFAULT_THRESHOLD = 20


def check_buffer_overflow(
    event: dict[str, Any] | None = None,
    threshold: int | None = None,
    user=None,
) -> dict[str, Any] | None:
    """Alert HIGH bila ada WC dengan buffer_length > threshold (default 20)."""
    del event, user

    limit = int(threshold if threshold is not None else DEFAULT_THRESHOLD)

    from apps_industry.garment.models import WorkCenter
    from apps_industry.garment.services.wc_queue import WCQueue

    queue = WCQueue()
    overflows: list[dict[str, Any]] = []

    for wc in WorkCenter.objects.filter(is_active=True).only("id", "code", "name"):
        try:
            length = queue.count(wc)
        except Exception:  # noqa: BLE001 - alert tidak boleh menggagalkan operator
            continue
        if length > limit:
            overflows.append(
                {
                    "work_center_id": wc.pk,
                    "work_center": wc.code,
                    "buffer_length": length,
                    "threshold": limit,
                }
            )

    if not overflows:
        return None

    names = ", ".join(item["work_center"] for item in overflows)
    return {
        "alert_id": ALERT_ID,
        "metric_id": ALERT_ID,
        "severity": "HIGH",
        "value": max(item["buffer_length"] for item in overflows),
        "threshold": limit,
        "work_centers": overflows,
        "detected_at": timezone.now().isoformat(),
        "message": f"Buffer overflow (> {limit}): {names}",
    }


__all__ = ("ALERT_ID", "DEFAULT_THRESHOLD", "check_buffer_overflow")
