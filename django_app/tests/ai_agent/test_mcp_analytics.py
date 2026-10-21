"""Test MCP analytics (D.4) — 8 skenario, service layer WAJIB."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import TestCase

from integrations.ai_agent.mcp_servers import mcp_analytics

GET_CONFIG = (
    "integrations.ai_agent.mcp_servers.mcp_analytics."
    "analytics_config_services.get_config"
)


def _user(role_code: str):
    return SimpleNamespace(role=SimpleNamespace(code=role_code))


class McpAnalyticsTests(TestCase):
    def test_off_analytics_disabled(self):
        with patch(GET_CONFIG, return_value=SimpleNamespace(enabled=False)):
            result = mcp_analytics.handle_request(
                "list_metrics", {"domain": "garment"}, _user("SUPERVISOR")
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "analytics_disabled")
        self.assertEqual(result["reason"], "analytics_disabled")

    def test_on_supervisor_list_metrics(self):
        with patch(GET_CONFIG, return_value=SimpleNamespace(enabled=True)):
            result = mcp_analytics.handle_request(
                "list_metrics", {"domain": "garment"}, _user("SUPERVISOR")
            )

        self.assertTrue(result["ok"])
        self.assertEqual(len(result["metrics"]), 3)

    def test_on_operator_forbidden(self):
        with patch(GET_CONFIG, return_value=SimpleNamespace(enabled=True)):
            result = mcp_analytics.handle_request(
                "list_metrics", {"domain": "garment"}, _user("OPERATOR")
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "forbidden")

    def test_list_metrics_domain_garment_tiga(self):
        with patch(GET_CONFIG, return_value=SimpleNamespace(enabled=True)):
            result = mcp_analytics.handle_request(
                "list_metrics", {"domain": "garment"}, _user("OWNER")
            )

        ids = {item["metric_id"] for item in result["metrics"]}
        self.assertEqual(
            ids,
            {"garment.scrap_rate", "garment.rework_rate", "garment.lead_time"},
        )

    def test_get_metric_scrap_rate_rows(self):
        with patch(GET_CONFIG, return_value=SimpleNamespace(enabled=True)):
            result = mcp_analytics.handle_request(
                "get_metric",
                {"metric_id": "garment.scrap_rate", "dimension": "period"},
                _user("SUPERVISOR"),
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["metric_id"], "garment.scrap_rate")
        self.assertIn("rows", result)
        self.assertFalse(result["truncated"])

    def test_truncate_lebih_50_baris(self):
        fake_rows = [{"key": str(index), "value": 1} for index in range(60)]
        fake_metric = SimpleNamespace(
            metric_id="garment.scrap_rate", unit="%", compute=lambda filters: fake_rows
        )

        with patch(GET_CONFIG, return_value=SimpleNamespace(enabled=True)), patch.object(
            mcp_analytics.analytics_registry, "get_metric", return_value=fake_metric
        ):
            result = mcp_analytics.handle_request(
                "get_metric", {"metric_id": "garment.scrap_rate"}, _user("SUPERVISOR")
            )

        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["rows"]), 50)

    def test_memakai_get_config_service_layer(self):
        get_config = MagicMock(return_value=SimpleNamespace(enabled=True))

        with patch(GET_CONFIG, get_config):
            mcp_analytics.handle_request("list_metrics", {}, _user("SUPERVISOR"))

        get_config.assert_called_once()

    def test_tidak_ada_http_call(self):
        with patch(GET_CONFIG, return_value=SimpleNamespace(enabled=True)), patch(
            "urllib.request.urlopen", side_effect=AssertionError("HTTP tidak boleh")
        ) as urlopen:
            result = mcp_analytics.handle_request(
                "list_metrics", {"domain": "garment"}, _user("SUPERVISOR")
            )

        self.assertTrue(result["ok"])
        urlopen.assert_not_called()
