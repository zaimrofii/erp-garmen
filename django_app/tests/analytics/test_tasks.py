"""Test task Celery analytics (B.8) — 6 skenario."""

from __future__ import annotations

import itertools
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import TestCase
from django.utils import timezone

from apps_industry.garment.models import BundleEvent, ScrapAccumulator
from apps_industry.garment.tests.factories import (
    make_bundle,
    make_order_line,
    make_scrap_accumulator,
    make_work_center,
    make_work_order,
)
from integrations.analytics.plugins.garment import tasks
from integrations.analytics.plugins.garment.models import MetricSnapshot
from master.models import Product

_ODOO = itertools.count(1)
GET_STORAGE = "integrations.analytics.plugins.garment.tasks.get_storage_for_metric"
LIST_METRICS = "integrations.analytics.plugins.garment.tasks.registry.list_metrics"


def _fake_metric(metric_id: str, granularities=("hour", "day")):
    return SimpleNamespace(
        metric_id=metric_id,
        granularities=list(granularities),
        compute=lambda filters: [{"key": "2026-10-18", "value": 1.0}],
    )


class AggregateMockTests(TestCase):
    def test_aggregate_hourly_menyimpan_dua_metrik(self):
        metrics = [
            _fake_metric("garment.scrap_rate"),
            _fake_metric("garment.rework_rate"),
            _fake_metric("garment.lead_time", granularities=("day",)),
        ]
        storage = MagicMock()
        storage.save.return_value = 1

        with patch(LIST_METRICS, return_value=metrics), patch(
            GET_STORAGE, return_value=storage
        ):
            result = tasks.aggregate_hourly()

        self.assertEqual(set(result), {"garment.scrap_rate", "garment.rework_rate"})
        self.assertEqual(storage.save.call_count, 2)  # lead_time tidak support hour

    def test_aggregate_daily_menyimpan_tiga_metrik(self):
        metrics = [_fake_metric(name) for name in (
            "garment.scrap_rate",
            "garment.rework_rate",
            "garment.lead_time",
        )]
        storage = MagicMock()
        storage.save.return_value = 1

        with patch(LIST_METRICS, return_value=metrics), patch(
            GET_STORAGE, return_value=storage
        ):
            result = tasks.aggregate_daily()

        self.assertEqual(len(result), 3)
        self.assertEqual(storage.save.call_count, 3)


class AggregateRealTests(TestCase):
    def _seed_yesterday(self):
        now = timezone.localdate()
        yesterday = timezone.make_aware(
            datetime.combine(now - timedelta(days=1), datetime.min.time())
        ) + timedelta(hours=12)

        product = Product.objects.create(
            code=f"P-{uuid.uuid4().hex[:8]}", name="Produk", odoo_id=next(_ODOO)
        )
        work_order = make_work_order(
            order_line=make_order_line(product=product), qty_planned=1000
        )
        bundle = make_bundle(work_order=work_order, qty=10)

        start_event = BundleEvent.objects.create(
            bundle=bundle, event_type="BUNDLE_START"
        )
        finish_event = BundleEvent.objects.create(
            bundle=bundle, event_type="BUNDLE_FINISH"
        )
        BundleEvent.objects.filter(pk=start_event.pk).update(
            ts=yesterday - timedelta(hours=2)
        )
        BundleEvent.objects.filter(pk=finish_event.pk).update(ts=yesterday)

        accumulator = make_scrap_accumulator(
            bundle=bundle, work_center=make_work_center(), qty=1
        )
        ScrapAccumulator.objects.filter(pk=accumulator.pk).update(created_at=yesterday)

    def test_aggregate_daily_idempoten(self):
        self._seed_yesterday()

        tasks.aggregate_daily()
        first = MetricSnapshot.objects.count()
        tasks.aggregate_daily()

        self.assertGreater(first, 0)
        self.assertEqual(MetricSnapshot.objects.count(), first)


class CleanupAndScheduleTests(TestCase):
    def test_cleanup_cache_memanggil_invalidate(self):
        with patch(
            "integrations.analytics.plugins.garment.tasks.invalidate_cache"
        ) as invalidate:
            result = tasks.cleanup_cache()

        self.assertTrue(result)
        invalidate.assert_called_once()

    def test_beat_schedule_19_entry(self):
        # Sprint F menambah ai-hitl-expire + ai-detect-drift (17 → 19).
        self.assertEqual(len(settings.CELERY_BEAT_SCHEDULE), 19)
        self.assertIn("analytics-aggregate-hourly", settings.CELERY_BEAT_SCHEDULE)

    def test_task_name_eksplisit(self):
        self.assertEqual(tasks.aggregate_hourly.name, "analytics.aggregate_hourly")
        self.assertEqual(tasks.aggregate_daily.name, "analytics.aggregate_daily")
        self.assertEqual(tasks.cleanup_cache.name, "analytics.cleanup_cache")
