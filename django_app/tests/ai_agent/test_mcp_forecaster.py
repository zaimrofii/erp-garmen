"""Test MCP forecaster T3.2 — mock series + order fixture."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps_industry.garment.tests.factories import (
    make_bundle,
    make_order,
    make_order_line,
    make_work_order,
)
from integrations.ai_agent.mcp_servers import mcp_forecaster

MODULE = "integrations.ai_agent.mcp_servers.mcp_forecaster"


def _user(role="SUPERVISOR"):
    return SimpleNamespace(role=SimpleNamespace(code=role))


def _series(count=10):
    start = timezone.localdate() - timedelta(days=count - 1)
    return {
        "ok": True,
        "series": [
            {
                "period": (start + timedelta(days=index)).isoformat(),
                "value": 10.0 + index,
            }
            for index in range(count)
        ],
    }


class ForecastMetricTests(TestCase):
    def test_ma_horizon_1(self):
        with patch(f"{MODULE}.mcp_time_series.handle", return_value=_series()):
            result = mcp_forecaster.handle(
                "forecast_metric",
                {"metric_id": "garment.scrap_rate", "horizon_days": 1, "method": "ma"},
                _user(),
            )

        self.assertTrue(result["ok"])
        self.assertEqual(len(result["forecast"]), 1)
        self.assertGreaterEqual(result["forecast"][0]["value_high"], result["forecast"][0]["value_low"])

    def test_linear_horizon_7(self):
        with patch(f"{MODULE}.mcp_time_series.handle", return_value=_series()):
            result = mcp_forecaster.handle(
                "forecast_metric",
                {"metric_id": "garment.scrap_rate", "horizon_days": 7, "method": "linear"},
                _user(),
            )

        self.assertTrue(result["ok"])
        self.assertEqual(len(result["forecast"]), 7)
        self.assertGreater(result["forecast"][1]["value_mid"], result["forecast"][0]["value_mid"])

    def test_insufficient_data(self):
        with patch(f"{MODULE}.mcp_time_series.handle", return_value=_series(3)):
            result = mcp_forecaster.handle(
                "forecast_metric",
                {"metric_id": "garment.scrap_rate", "horizon_days": 1},
                _user(),
            )

        self.assertEqual(result["error"], "insufficient_data")

    def test_horizon_di_luar_batas(self):
        result = mcp_forecaster.handle(
            "forecast_metric",
            {"metric_id": "garment.scrap_rate", "horizon_days": 31},
            _user(),
        )

        self.assertEqual(result["error"], "horizon_invalid")

    def test_metric_invalid(self):
        result = mcp_forecaster.handle(
            "forecast_metric", {"metric_id": "output_pcs"}, _user()
        )

        self.assertEqual(result["error"], "metric_id_tidak_dikenal")

    def test_operator_forbidden(self):
        result = mcp_forecaster.handle(
            "forecast_metric",
            {"metric_id": "garment.scrap_rate"},
            _user("OPERATOR"),
        )

        self.assertEqual(result["error"], "forbidden")


class PredictCompletionTests(TestCase):
    def test_order_done(self):
        order = make_order(state="DONE")
        line = make_order_line(order=order, qty=10, price_unit=1)
        wo = make_work_order(order_line=line, qty_planned=10, qty_done=10)
        make_bundle(work_order=wo, qty=10, qty_done=10)

        result = mcp_forecaster.handle(
            "predict_completion", {"order_id": order.pk}, _user()
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["days_remaining"], 0)
        self.assertEqual(result["estimated_completion_date"], timezone.localdate().isoformat())

    def test_order_in_progress(self):
        order = make_order(state="IN_PROGRESS")
        line = make_order_line(order=order, qty=10, price_unit=1)
        wo = make_work_order(order_line=line, qty_planned=10, qty_done=5)
        make_bundle(work_order=wo, qty=10, qty_done=5)

        result = mcp_forecaster.handle(
            "predict_completion", {"order_id": order.code}, _user()
        )

        self.assertTrue(result["ok"])
        self.assertGreater(result["days_remaining"], 0)
        self.assertGreater(
            result["estimated_completion_date"], timezone.localdate().isoformat()
        )

    def test_order_tidak_ada(self):
        result = mcp_forecaster.handle(
            "predict_completion", {"order_id": "TIDAK-ADA"}, _user()
        )

        self.assertEqual(result["error"], "not_found")
