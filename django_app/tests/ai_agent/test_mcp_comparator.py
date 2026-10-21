"""Test MCP comparator T3.1 — mock registry metric."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from integrations.ai_agent.mcp_servers import mcp_comparator

MODULE = "integrations.ai_agent.mcp_servers.mcp_comparator"


def _user(role="SUPERVISOR"):
    return SimpleNamespace(role=SimpleNamespace(code=role))


class _Metric:
    metric_id = "garment.scrap_rate"
    unit = "%"

    def __init__(self, a=20.0, b=30.0, rows=None):
        self.a = a
        self.b = b
        self.rows = rows
        self.calls = 0

    def compute(self, filters):
        self.calls += 1
        if self.rows is not None:
            return self.rows
        if self.calls == 1:
            return [{"key": "a", "value": self.a}]
        return [{"key": "b", "value": self.b}]


def _periods(metric):
    with patch(f"{MODULE}.registry.get_metric", return_value=metric):
        return mcp_comparator.handle(
            "compare_periods",
            {
                "metric_id": "garment.scrap_rate",
                "period_a": {
                    "from": "2026-10-13T00:00:00+00:00",
                    "to": "2026-10-19T00:00:00+00:00",
                },
                "period_b": {
                    "from": "2026-10-06T00:00:00+00:00",
                    "to": "2026-10-12T00:00:00+00:00",
                },
            },
            _user(),
        )


class ComparatorTests(SimpleTestCase):
    def test_compare_periods_delta_dan_trend_better(self):
        result = _periods(_Metric(a=20, b=30))
        row = result["comparison"][0]

        self.assertTrue(result["ok"])
        self.assertAlmostEqual(row["delta"], -10.0)
        self.assertAlmostEqual(row["delta_pct"], -33.3333, places=4)
        self.assertEqual(row["trend"], "better")
        self.assertEqual(result["summary"]["winner"], "A")
        self.assertTrue(result["summary"]["significant"])

    def test_trend_worse(self):
        result = _periods(_Metric(a=40, b=30))

        self.assertEqual(result["comparison"][0]["trend"], "worse")
        self.assertEqual(result["summary"]["winner"], "B")

    def test_trend_same(self):
        result = _periods(_Metric(a=30, b=30))

        self.assertEqual(result["comparison"][0]["trend"], "same")
        self.assertEqual(result["summary"]["winner"], "tie")

    def test_compare_dimensions(self):
        metric = _Metric(
            rows=[
                {"key": "1", "value": 32.5},
                {"key": "2", "value": 45.2},
            ]
        )
        with patch(f"{MODULE}.registry.get_metric", return_value=metric):
            result = mcp_comparator.handle(
                "compare_dimensions",
                {
                    "metric_id": "garment.scrap_rate",
                    "dimension_a": {"type": "line", "id": 1},
                    "dimension_b": {"type": "line", "id": 2},
                    "period_from": "2026-10-01T00:00:00+00:00",
                    "period_to": "2026-10-20T00:00:00+00:00",
                },
                _user(),
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["comparison"][0]["a_value"], 32.5)
        self.assertEqual(result["comparison"][0]["b_value"], 45.2)
        self.assertEqual(result["comparison"][0]["unit"], "%")

    def test_metric_invalid(self):
        result = mcp_comparator.handle(
            "compare_periods",
            {"metric_id": "tidak_ada", "period_a": {}, "period_b": {}},
            _user(),
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "metric_tidak_dikenal")

    def test_data_kosong(self):
        result = _periods(_Metric(rows=[]))

        self.assertEqual(result["error"], "no_data")

    def test_period_invalid(self):
        with patch(f"{MODULE}.registry.get_metric", return_value=_Metric()):
            result = mcp_comparator.handle(
                "compare_periods",
                {
                    "metric_id": "garment.scrap_rate",
                    "period_a": {"from": "x", "to": "y"},
                    "period_b": {"from": "x", "to": "y"},
                },
                _user(),
            )

        self.assertEqual(result["error"], "bad_request")

    def test_operator_forbidden(self):
        result = mcp_comparator.handle(
            "compare_periods",
            {"metric_id": "garment.scrap_rate"},
            _user("OPERATOR"),
        )

        self.assertEqual(result["error"], "forbidden")
