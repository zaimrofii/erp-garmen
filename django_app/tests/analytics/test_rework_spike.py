"""Test stream alert rework spike (R.4) — deterministik, tanpa Redis/WA nyata."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from integrations.analytics.plugins.garment.streams import rework_spike

GET_METRIC = "integrations.analytics.core.registry.get_metric"


class _FakeMetric:
    """Metric palsu: baseline list harian + nilai hari ini."""

    def __init__(self, baseline: list[float], today: float):
        self.baseline = baseline
        self.today = today

    def compute(self, filters):
        if filters.get("date_from") == filters.get("date_to"):
            return [{"key": filters["date_from"], "value": self.today}]
        return [
            {"key": f"d{index}", "value": value}
            for index, value in enumerate(self.baseline)
        ]


class ReworkSpikeTests(SimpleTestCase):
    def _check(self, baseline, today):
        metric = _FakeMetric(baseline, today)
        with patch(GET_METRIC, return_value=metric):
            return rework_spike.check_rework_spike()

    def test_rework_5_persen_vs_baseline_1_persen_alert_high(self):
        alert = self._check([1.0] * 7, 5.0)

        self.assertIsNotNone(alert)
        self.assertEqual(alert["metric_id"], "garment.rework_rate")
        self.assertEqual(alert["severity"], "HIGH")
        self.assertEqual(alert["value"], 5.0)
        self.assertEqual(alert["threshold"], 3.0)
        self.assertIn("Rework spike", alert["message"])

    def test_rework_1_5_persen_tidak_spike(self):
        self.assertIsNone(self._check([1.0] * 7, 1.5))

    def test_baseline_kurang_dari_tiga_hari_none(self):
        self.assertIsNone(self._check([1.0, 1.0], 9.0))
