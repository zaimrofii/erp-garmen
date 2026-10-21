"""Entry point plugin garment — registrasi 3 metrik (B.6).

Kontrak formula: docs/analytics/CONTRACT.md §8.

`register()` dipanggil autodiscover SETIAP kali (bukan hanya saat import),
supaya `_reset_for_tests()` + `discover_metrics()` tetap menemukan metrik
walau modul plugin sudah ter-cache Python.
"""

from __future__ import annotations

from ...core.registry import is_registered, register_metric

from .metrics import (
    bottleneck,
    lead_time,
    line_balance,
    rework_rate,
    scrap_rate,
)

METRICS = (
    scrap_rate.METRIC,
    rework_rate.METRIC,
    lead_time.METRIC,
    line_balance.METRIC,
    bottleneck.METRIC,
)


def register() -> None:
    """Daftarkan metrik yang belum ada (idempoten)."""
    for metric in METRICS:
        if not is_registered(metric.metric_id):
            register_metric(metric)


__all__ = ("METRICS", "register")


