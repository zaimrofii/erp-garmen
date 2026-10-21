"""Test storage backend Django ORM (B.5) — 6 skenario."""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from integrations.analytics.plugins.garment.models import MetricSnapshot
from integrations.analytics.plugins.garment.storage import get_storage_for_metric
from integrations.analytics.storage_backends.django_orm import DjangoORMStorage


def _row(index: int, start, *, dim: str = "", value: float = 1.0):
    return {
        "dimension_key": dim,
        "period_start": start + timedelta(days=index),
        "period_end": start + timedelta(days=index + 1),
        "value": value,
        "extra": {"n": index},
    }


class DjangoORMStorageTests(TestCase):
    """save bulk + query filter."""

    def setUp(self):
        self.storage = DjangoORMStorage()
        self.metric = "garment.scrap_rate"
        self.start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)

    def test_save_100_rows(self):
        rows = [_row(i, self.start) for i in range(100)]

        count = self.storage.save(self.metric, "day", rows)

        self.assertEqual(count, 100)
        self.assertEqual(MetricSnapshot.objects.count(), 100)

    def test_save_duplikat_tetap_satu_baris(self):
        rows = [_row(0, self.start)]
        self.storage.save(self.metric, "day", rows)

        self.storage.save(self.metric, "day", rows)

        self.assertEqual(MetricSnapshot.objects.count(), 1)

    def test_query_by_metric_id(self):
        self.storage.save(self.metric, "day", [_row(0, self.start)])
        self.storage.save("garment.rework_rate", "day", [_row(1, self.start)])

        result = self.storage.query(self.metric, None, "day")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["metric_id"], self.metric)

    def test_query_by_dimension(self):
        self.storage.save(
            self.metric, "day", [_row(0, self.start, dim="wc:12"), _row(1, self.start, dim="wc:13")]
        )

        result = self.storage.query(self.metric, "wc:12", "day")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["dimension_key"], "wc:12")

    def test_query_by_period_range(self):
        self.storage.save(
            self.metric, "day", [_row(i, self.start) for i in range(10)]
        )
        period_from = self.start + timedelta(days=3)
        period_to = self.start + timedelta(days=6)

        result = self.storage.query(
            self.metric, None, "day", period_from=period_from, period_to=period_to
        )

        self.assertEqual(len(result), 4)  # hari 3,4,5,6

    def test_get_storage_for_metric(self):
        storage = get_storage_for_metric("garment.lead_time")

        self.assertIsInstance(storage, DjangoORMStorage)
