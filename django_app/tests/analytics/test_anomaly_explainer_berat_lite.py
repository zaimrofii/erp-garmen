"""Test Fase Berat-Lite — rule-based anomaly explainer (TEMPORARY)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps_industry.garment.models import BundleEvent
from apps_industry.garment.tests.factories import (
    make_bundle,
    make_scrap_accumulator,
    make_work_center,
)
from core.auth.models import Role, User
from integrations.analytics.plugins.garment.anomaly import anomaly_explainer

DAY = timezone.make_aware(datetime(2026, 10, 10, 9, 0))
MODULE = "integrations.analytics.plugins.garment.anomaly.anomaly_explainer"


class ScrapExplainerTests(TestCase):
    def test_scrap_menjelaskan_wc_dan_operator(self):
        wc = make_work_center("SEWING-2")
        bundle = make_bundle(qty=100, current_work_center=wc)
        make_scrap_accumulator(bundle=bundle, work_center=wc, qty=8)
        operator = User.objects.create_user(
            username="explain-op",
            password="x",
            role=Role.objects.get(code=Role.Code.OPERATOR),
        )
        for _index in range(3):
            BundleEvent.objects.create(
                bundle=bundle, event_type="SCRAP", actor=operator
            )

        result = anomaly_explainer.explain_scrap_spike(DAY.date())

        self.assertTrue(result["found"])
        self.assertIn("SEWING-2", result["narrative"])
        self.assertIn("explain-op", result["narrative"])
        self.assertIn("shift", result["narrative"])

    def test_tanpa_data_scrap(self):
        result = anomaly_explainer.explain_scrap_spike(DAY.date())

        self.assertFalse(result["found"])
        self.assertIn("belum lengkap", result["narrative"])


class LeadTimeExplainerTests(TestCase):
    def _fake_rows(self, metric_id, group_by, start, end):
        if metric_id == "garment.lead_time":
            return [{"value": 12.5}]
        if metric_id == "garment.bottleneck":
            return [
                {
                    "label": "SEWING-1",
                    "value": 100,
                    "buffer_length": 25,
                    "avg_wait_hours": 4.0,
                }
            ]
        return []

    def test_lead_time_menjelaskan_bottleneck(self):
        with patch(f"{MODULE}._metric_rows", side_effect=self._fake_rows):
            result = anomaly_explainer.explain_lead_time_spike(DAY.date())

        self.assertTrue(result["found"])
        self.assertIn("12.5", result["narrative"])
        self.assertIn("SEWING-1", result["narrative"])
        self.assertIn("buffer 25", result["narrative"])

    def test_lead_time_tanpa_data(self):
        with patch(f"{MODULE}._metric_rows", return_value=[]):
            result = anomaly_explainer.explain_lead_time_spike(DAY.date())

        self.assertFalse(result["found"])


class OeeExplainerTests(TestCase):
    def test_oee_menjelaskan_komponen_terlemah(self):
        rows = [
            {
                "label": "SEWING-2",
                "value": 18.0,
                "availability": 0.5,
                "performance": 0.4,
                "quality": 0.9,
            }
        ]
        with patch(f"{MODULE}._metric_rows", return_value=rows):
            result = anomaly_explainer.explain_oee_drop(DAY.date())

        self.assertTrue(result["found"])
        self.assertIn("SEWING-2", result["narrative"])
        self.assertIn("performance", result["narrative"])
        self.assertIn("Cek output", result["narrative"])

    def test_oee_tanpa_data(self):
        with patch(f"{MODULE}._metric_rows", return_value=[]):
            result = anomaly_explainer.explain_oee_drop(DAY.date())

        self.assertFalse(result["found"])
