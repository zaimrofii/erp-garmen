"""AppConfig Analytics — mendaftarkan metrik saat Django siap.

Pola mengikuti `integrations/erp_sync/apps.py`:
- `ready()` melakukan registrasi sekali saat app loading;
- listener event bus (B.3) akan didaftarkan di sini juga;
- import berat dilakukan DI DALAM ready() supaya aman saat app loading.
"""

from __future__ import annotations

import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class AnalyticsConfig(AppConfig):
    """App analytics: registry metrik (B.1) + listener (B.3)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations.analytics"
    verbose_name = "Analytics"

    def ready(self) -> None:
        """Autodiscover plugin metrik + daftarkan listener event bus."""
        from .config import ANALYTICS_CONFIG
        from .core import event_listener, registry

        # Sprint F (bugfix PRA-0B.1): task agregasi didefinisikan di
        # `plugins/garment/tasks.py` (bukan `integrations/analytics/tasks.py`),
        # sehingga `app.autodiscover_tasks()` tidak menemukannya dan worker
        # membuang pesan "unregistered task" (analytics.aggregate_hourly/daily,
        # analytics.cleanup_cache). Import eksplisit agar @shared_task terdaftar.
        from .plugins.garment import tasks as _garment_tasks  # noqa: F401

        count = registry.discover_metrics()
        logger.info("analytics: %d metrik terdaftar (autodiscover).", count)

        if ANALYTICS_CONFIG.get("event_bus_listener", True):
            event_listener.register_all()
