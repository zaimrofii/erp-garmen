"""Test Fase Berat-Lite — DailySummary L2/L3 (TEMPORARY)."""

from __future__ import annotations

from datetime import datetime

from django.test import TestCase
from django.utils import timezone

from apps_industry.garment.models import BundleEvent, ScrapAccumulator
from apps_industry.garment.tests.factories import (
    make_bundle,
    make_scrap_accumulator,
    make_work_center,
)
from core.auth.models import Role, User
from integrations.analytics import summary
from integrations.analytics.models import DailySummary

DAY = timezone.make_aware(datetime(2026, 10, 10, 9, 0))


class SummaryTestBase(TestCase):
    def _seed(self):
        wc = make_work_center("SEWING-2")
        bundle = make_bundle(qty=10, current_work_center=wc)
        operator = User.objects.create_user(
            username="summary-op",
            password="x",
            role=Role.objects.get(code=Role.Code.OPERATOR),
        )
        event = BundleEvent.objects.create(
            bundle=bundle, event_type="BUNDLE_FINISH", actor=operator
        )
        BundleEvent.objects.filter(pk=event.pk).update(ts=DAY)
        scrap = make_scrap_accumulator(
            bundle=bundle, work_center=wc, qty=3, rework_qty=1
        )
        ScrapAccumulator.objects.filter(pk=scrap.pk).update(created_at=DAY)
        return wc, bundle


class AggregateSummaryTests(SummaryTestBase):
    def test_aggregate_output_scrap_rework(self):
        self._seed()

        result = summary.aggregate_daily_summary(DAY.date())

        self.assertEqual(result["date"], DAY.date().isoformat())
        self.assertEqual(result["total_output"], 10.0)
        self.assertEqual(result["total_scrap"], 3.0)
        self.assertEqual(result["total_rework"], 1.0)

    def test_top_wc_dan_operator(self):
        self._seed()

        result = summary.aggregate_daily_summary(DAY.date())

        self.assertEqual(result["top_wc"], "SEWING-2")
        self.assertEqual(result["top_operator"], "summary-op")

    def test_idempoten_satu_baris(self):
        self._seed()

        summary.aggregate_daily_summary(DAY.date())
        summary.aggregate_daily_summary(DAY.date())

        self.assertEqual(DailySummary.objects.filter(date=DAY.date()).count(), 1)

    def test_hari_tanpa_data_tetap_baris_nol(self):
        result = summary.aggregate_daily_summary(DAY.date())

        self.assertEqual(result["total_output"], 0.0)
        self.assertEqual(result["top_wc"], "")


class GetSummaryTests(SummaryTestBase):
    def test_get_summary_sebelum_agregasi_none(self):
        self.assertIsNone(summary.get_summary(DAY.date()))

    def test_get_summary_setelah_agregasi(self):
        self._seed()
        summary.aggregate_daily_summary(DAY.date())

        result = summary.get_summary(DAY.date())

        self.assertIsNotNone(result)
        self.assertEqual(result["oee"] >= 0, True)
        self.assertIn("avg_lead_time", result)
