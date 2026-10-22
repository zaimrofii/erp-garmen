"""Test context builder (G.2) — mock MCP, tanpa DB/LLM."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import TestCase

from integrations.ai_agent.orchestrator import context_builder

MODULE = "integrations.ai_agent.orchestrator.context_builder"


def _user():
    return SimpleNamespace(role=SimpleNamespace(code="SUPERVISOR"))


class ContextBuilderTests(TestCase):
    def test_analytics_mengisi_metrics_dan_membatasi_rows(self):
        rows = [{"period": f"2026-10-{day:02d}", "value": day} for day in range(1, 8)]
        handler = Mock(
            return_value={
                "ok": True,
                "metric_id": "garment.scrap_rate",
                "unit": "%",
                "rows": rows,
            }
        )
        user = _user()
        with patch(f"{MODULE}.mcp_analytics.handle_request", handler):
            data = context_builder.build_context(
                "ANALYTICS_QUERY",
                ["mcp-analytics"],
                "berapa scrap?",
                {},
                user=user,
            )

        self.assertEqual(len(data["metrics"]), 5)
        self.assertEqual(len(data["metrics"][0]["rows"]), 5)
        self.assertEqual(data["metrics"][0]["rows"][0]["period"], "2026-10-03")
        self.assertEqual(data["metrics"][0]["unit"], "%")
        self.assertEqual(handler.call_count, 5)
        self.assertIs(handler.call_args.kwargs["user"], user)

    def test_analytics_error_dicatat_tanpa_raise(self):
        handler = Mock(return_value={"ok": False, "error": "analytics_disabled"})
        with patch(f"{MODULE}.mcp_analytics.handle_request", handler):
            data = context_builder.build_context(
                "ANALYTICS_QUERY", ["mcp-analytics"], "scrap?", {}
            )

        self.assertEqual(data["metrics"], [])
        self.assertEqual(data["errors"][0]["error"], "analytics_disabled")

    def test_analytics_exception_ditangkap(self):
        with patch(
            f"{MODULE}.mcp_analytics.handle_request", side_effect=RuntimeError("boom")
        ):
            data = context_builder.build_context(
                "ANALYTICS_QUERY", ["mcp-analytics"], "scrap?", {}
            )

        self.assertEqual(data["metrics"], [])
        self.assertTrue(data["errors"])

    def test_resource_order_memakai_allowlist_dan_limit(self):
        handler = Mock(return_value={"ok": True, "rows": [{"id": 42, "code": "ORD-1"}]})
        with patch(f"{MODULE}.mcp_postgres_query.handle", handler):
            data = context_builder.build_context(
                "DATA_LOOKUP",
                ["mcp-postgres-query"],
                "order 42?",
                {"resource_type": "order", "resource_id": 42},
            )

        self.assertEqual(data["resource"], [{"id": 42, "code": "ORD-1"}])
        payload = handler.call_args.args[0]
        self.assertEqual(payload["table"], "garment_order")
        self.assertEqual(payload["filters"], {"id": 42})
        self.assertEqual(payload["limit"], 5)

    def test_resource_tidak_didukung_dilewati(self):
        handler = Mock(return_value={"ok": True, "rows": [{"id": 1}]})
        with patch(f"{MODULE}.mcp_postgres_query.handle", handler):
            data = context_builder.build_context(
                "DATA_LOOKUP",
                ["mcp-postgres-query"],
                "produk?",
                {"resource_type": "product", "resource_id": 1},
            )

        self.assertNotIn("resource", data)
        handler.assert_not_called()

    def test_bundle_mengisi_events(self):
        handler = Mock(return_value={"ok": True, "events": [{"event_type": "SCRAP"}]})
        with patch(f"{MODULE}.mcp_event_log.handle", handler):
            data = context_builder.build_context(
                "DIAGNOSTIC",
                ["mcp-analytics", "mcp-event-log"],
                "kenapa scrap?",
                {"resource_type": "bundle", "resource_id": 7},
            )

        self.assertEqual(data["events"], [{"event_type": "SCRAP"}])
        self.assertEqual(handler.call_args.args[0]["bundle_id"], 7)

    def test_tanpa_tool_data_minimal(self):
        data = context_builder.build_context("GENERAL_CHAT", [], "halo", {})

        self.assertEqual(data["intent"], "GENERAL_CHAT")
        self.assertEqual(data["message"], "halo")
        self.assertEqual(data["tools"], [])
        self.assertNotIn("metrics", data)
        self.assertNotIn("resource", data)
        self.assertNotIn("events", data)

    def test_resource_error_dicatat(self):
        handler = Mock(return_value={"ok": False, "error": "table_not_allowed"})
        with patch(f"{MODULE}.mcp_postgres_query.handle", handler):
            data = context_builder.build_context(
                "DATA_LOOKUP",
                ["mcp-postgres-query"],
                "order?",
                {"resource_type": "order", "resource_id": 1},
            )

        self.assertNotIn("resource", data)
        self.assertEqual(data["errors"][0]["error"], "table_not_allowed")

    def test_bundle_lead_time_untuk_pertanyaan_paling_lambat(self):
        postgres = Mock(
            return_value={
                "ok": True,
                "rows": [
                    {"id": 1, "code": "BND-LATE", "qty": 10, "state": "DONE"}
                ],
            }
        )
        events = Mock(
            return_value={
                "ok": True,
                "events": [
                    {"ts": "2026-10-14T08:00:00+00:00", "event_type": "BUNDLE_START"},
                    {"ts": "2026-10-19T08:00:00+00:00", "event_type": "BUNDLE_FINISH"},
                ],
            }
        )
        with patch(f"{MODULE}.mcp_postgres_query.handle", postgres), patch(
            f"{MODULE}.mcp_event_log.handle", events
        ):
            data = context_builder.build_context(
                "DATA_LOOKUP",
                ["mcp-postgres-query"],
                "bundle mana paling lambat?",
                {},
            )

        self.assertEqual(data["bundles"][0]["code"], "BND-LATE")
        self.assertEqual(data["bundles"][0]["lead_time_hours"], 120.0)
        self.assertEqual(postgres.call_args.args[0]["table"], "garment_bundle")

