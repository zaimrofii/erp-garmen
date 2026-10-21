"""Regression PRA-0B.1 — task analytics harus terdaftar di Celery.

Bug asli: task didefinisikan di `integrations/analytics/plugins/garment/tasks.py`
tetapi tidak pernah diimpor, sehingga worker membuang pesan sebagai
*unregistered* dan `MetricSnapshot` tidak pernah terisi.
"""

from __future__ import annotations

from django.conf import settings
from django.test import SimpleTestCase

from config.celery import app

ANALYTICS_TASKS = [
    "analytics.aggregate_hourly",
    "analytics.aggregate_daily",
    "analytics.cleanup_cache",
]


class AnalyticsTaskRegistrationTests(SimpleTestCase):
    def test_semua_task_analytics_terdaftar(self):
        missing = [name for name in ANALYTICS_TASKS if name not in app.tasks]

        self.assertEqual(missing, [], f"Task belum terdaftar: {missing}")

    def test_aggregate_hourly_terdaftar(self):
        self.assertIn("analytics.aggregate_hourly", app.tasks)

    def test_beat_schedule_menunjuk_task_yang_sama(self):
        keys = {
            "analytics-aggregate-hourly": "analytics.aggregate_hourly",
            "analytics-aggregate-daily": "analytics.aggregate_daily",
            "analytics-cleanup-cache": "analytics.cleanup_cache",
        }

        for key, task_name in keys.items():
            self.assertEqual(settings.CELERY_BEAT_SCHEDULE[key]["task"], task_name)
