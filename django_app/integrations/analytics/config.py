"""Konstanta analytics (bukan setting Django — nilai domain-spesifik).

Nilai cache & jadwal mengikuti kontrak Sprint A:
- cache 60 detik: docs/analytics/CONTRACT.md §5
- anomaly z-score 3.0: docs/analytics/CONTRACT.md §8.4
"""

from __future__ import annotations

ANALYTICS_CONFIG: dict = {
    "active_domains": ["garment"],
    "cache_ttl_seconds": 60,  # sesuai CONTRACT.md §5
    "stream_window_default": "15m",
    "anomaly_threshold_zscore": 3.0,
    "storage_backend_default": "django_orm",
    "event_bus_listener": True,  # subscribe core.event_bus (B.3)
    "batch_schedule": {
        "hourly": "0 * * * *",
        "daily": "5 0 * * *",
        "anomaly_check": "*/15 * * * *",
    },
}

__all__ = ("ANALYTICS_CONFIG",)
