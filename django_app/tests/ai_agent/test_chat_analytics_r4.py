"""Test integrasi chat → metrik line_balance/bottleneck (R.4)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from integrations.ai_agent.orchestrator import context_builder, tool_selector
from integrations.ai_agent.orchestrator.text_normalizer import normalize

METRIC_HANDLER = "integrations.ai_agent.orchestrator.context_builder.mcp_analytics.handle_request"
DIMENSION = "integrations.ai_agent.orchestrator.context_builder._collect_dimension_metrics"

USER = SimpleNamespace(role=SimpleNamespace(code="ADMIN"))


class ChatAnalyticsR4Tests(SimpleTestCase):
    def test_keyword_line_seimbang_pilih_mcp_analytics(self):
        for message in (
            "line mana yang tidak seimbang?",
            "line balance minggu ini?",
        ):
            with self.subTest(message=message):
                tools = tool_selector.select_tools("GENERAL_CHAT", {}, message)
                self.assertIn("mcp-analytics", tools)

    def test_keyword_bottleneck_pilih_mcp_analytics(self):
        for message in ("bottleneck di mana?", "WC mana yang menumpuk?"):
            with self.subTest(message=message):
                tools = tool_selector.select_tools("GENERAL_CHAT", {}, message)
                self.assertIn("mcp-analytics", tools)

    def test_context_builder_menambah_metrik_r4(self):
        handler = patch(
            METRIC_HANDLER,
            return_value={"ok": True, "metric_id": "garment.line_balance", "rows": []},
        )
        with handler as handle, patch(DIMENSION, return_value=([], [])):
            line_data, _ = context_builder._auto_detect_keywords(
                normalize("line tidak seimbang?"), USER, {}, {}
            )
            bottleneck_data, _ = context_builder._auto_detect_keywords(
                normalize("bottleneck di mana?"), USER, {}, {}
            )

        self.assertIn("line_balance", line_data)
        self.assertIn("bottleneck", bottleneck_data)
        self.assertGreaterEqual(handle.call_count, 2)
