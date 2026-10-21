"""Test MCP time-series T2.3 — snapshot + fallback compute."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from integrations.ai_agent.mcp_servers import mcp_time_series
from integrations.analytics.plugins.garment.models import MetricSnapshot


def _user(role="SUPERVISOR"):
    return SimpleNamespace(role=SimpleNamespace(code=role))


def _snapshot(metric_id, granularity, period_start, value):
    return MetricSnapshot.objects.create(
        metric_id=metric_id,
        granularity=granularity,
        dimension_key="",
        period_start=period_start,
        period_end=period_start + timedelta(hours=1 if granularity == "hour" else 24),
        value=Decimal(str(value)),
    )


class TimeSeriesTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.start = self.now - timedelta(days=3)

    def test_day_series(self):
        _snapshot("garment.scrap_rate", "day", self.start, "4.2")
        _snapshot("garment.scrap_rate", "day", self.start + timedelta(days=1), "5.1")

        result = mcp_time_series.handle(
            "get_metric_series",
            {
                "metric_id": "garment.scrap_rate",
                "granularity": "day",
                "period_from": self.start.isoformat(),
                "period_to": self.now.isoformat(),
            },
            _user(),
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["series"][0]["value"], 4.2)
        self.assertFalse(result["fallback_live"])

    def test_hour_series(self):
        _snapshot("garment.rework_rate", "hour", self.start, "2.0")

        result = mcp_time_series.handle(
            "get_metric_series",
            {
                "metric_id": "garment.rework_rate",
                "granularity": "hour",
                "period_from": self.start.isoformat(),
                "period_to": self.now.isoformat(),
            },
            _user(),
        )

        self.assertEqual(result["granularity"], "hour")
        self.assertEqual(result["count"], 1)

    def test_metric_invalid(self):
        result = mcp_time_series.handle(
            "get_metric_series", {"metric_id": "output_pcs"}, _user()
        )

        self.assertEqual(result["error"], "metric_id_tidak_dikenal")

    def test_snapshot_kosong_fallback_compute(self):
        class _Metric:
            def compute(self, filters):
                return [
                    {"key": "2026-10-20", "value": 7.5},
                    {"key": "2026-10-21", "value": 8.0},
                ]

        with patch(
            f"{mcp_time_series.__name__}.registry.get_metric", return_value=_Metric()
        ):
            result = mcp_time_series.handle(
                "get_metric_series",
                {
                    "metric_id": "garment.scrap_rate",
                    "granularity": "day",
                    "period_from": self.start.isoformat(),
                    "period_to": self.now.isoformat(),
                },
                _user(),
            )

        self.assertTrue(result["ok"])
        self.assertTrue(result["fallback_live"])
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["series"][0]["value"], 7.5)

    def test_granularity_invalid(self):
        result = mcp_time_series.handle(
            "get_metric_series",
            {"metric_id": "garment.scrap_rate", "granularity": "week"},
            _user(),
        )

        self.assertEqual(result["error"], "granularity_invalid")

    def test_period_invalid(self):
        result = mcp_time_series.handle(
            "get_metric_series",
            {
                "metric_id": "garment.scrap_rate",
                "period_from": "2026-10-20T00:00:00+00:00",
                "period_to": "2026-10-01T00:00:00+00:00",
            },
            _user(),
        )

        self.assertEqual(result["error"], "period_invalid")

    def test_role_operator_forbidden(self):
        result = mcp_time_series.handle(
            "get_metric_series",
            {"metric_id": "garment.scrap_rate"},
            _user("OPERATOR"),
        )

        self.assertEqual(result["error"], "forbidden")
