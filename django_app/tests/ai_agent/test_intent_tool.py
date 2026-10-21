"""Test intent classifier + tool selector (G.2) — mock provider, tanpa API."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from integrations.ai_agent.orchestrator import intent_classifier, tool_selector


class _FakeProvider:
    def __init__(self, text="ANALYTICS_QUERY", error: Exception | None = None):
        self.text = text
        self.error = error
        self.last_kwargs = None

    def complete(self, system_prompt, user_prompt, max_tokens=1000):
        self.last_kwargs = {
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "max_tokens": max_tokens,
        }
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            text=self.text,
            prompt_tokens=5,
            completion_tokens=2,
            total_cost_usd=0.0001,
            model="mock",
            latency_ms=1,
            raw={},
        )


class IntentClassifierTests(SimpleTestCase):
    def test_intent_valid_dan_token(self):
        provider = _FakeProvider("ANALYTICS_QUERY")
        with patch(
            "integrations.ai_agent.orchestrator.intent_classifier.get_llm_provider",
            return_value=provider,
        ):
            result = intent_classifier.classify("berapa scrap rate?")

        self.assertEqual(
            result,
            {
                "intent": "ANALYTICS_QUERY",
                "confidence": 0.8,
                "tokens": 7,
                "cost_usd": 0.0001,
            },
        )
        self.assertEqual(provider.last_kwargs["max_tokens"], 10)
        self.assertIn("berapa scrap rate?", provider.last_kwargs["user_prompt"])

    def test_output_lowercase_bertitik(self):
        provider = _FakeProvider("diagnostic.")
        with patch(
            "integrations.ai_agent.orchestrator.intent_classifier.get_llm_provider",
            return_value=provider,
        ):
            result = intent_classifier.classify("kenapa scrap naik?")

        self.assertEqual(result["intent"], "DIAGNOSTIC")
        self.assertEqual(result["confidence"], 0.8)

    def test_intent_tidak_valid_jadi_unknown(self):
        provider = _FakeProvider("bla-bla")
        with patch(
            "integrations.ai_agent.orchestrator.intent_classifier.get_llm_provider",
            return_value=provider,
        ):
            result = intent_classifier.classify("halo")

        self.assertEqual(result["intent"], "UNKNOWN")
        self.assertEqual(result["confidence"], 0.0)

    def test_output_kosong_jadi_unknown(self):
        provider = _FakeProvider("")
        with patch(
            "integrations.ai_agent.orchestrator.intent_classifier.get_llm_provider",
            return_value=provider,
        ):
            result = intent_classifier.classify("halo")

        self.assertEqual(result["intent"], "UNKNOWN")

    def test_provider_error_tidak_raise(self):
        provider = _FakeProvider(error=RuntimeError("boom"))
        with patch(
            "integrations.ai_agent.orchestrator.intent_classifier.get_llm_provider",
            return_value=provider,
        ):
            result = intent_classifier.classify("halo")

        self.assertEqual(result, {"intent": "UNKNOWN", "confidence": 0.0, "tokens": 0})


class ToolSelectorTests(SimpleTestCase):
    def test_analytics_query(self):
        self.assertEqual(
            tool_selector.select_tools("ANALYTICS_QUERY", {}), ["mcp-analytics"]
        )

    def test_diagnostic_dua_tool(self):
        self.assertEqual(
            tool_selector.select_tools("DIAGNOSTIC", {}),
            ["mcp-analytics", "mcp-event-log"],
        )

    def test_general_dan_unknown_kosong(self):
        for intent in ("GENERAL_CHAT", "UNKNOWN", "", "tidak-dikenal"):
            with self.subTest(intent=intent):
                self.assertEqual(tool_selector.select_tools(intent, {}), [])

    def test_resource_menambah_postgres(self):
        self.assertEqual(
            tool_selector.select_tools("ANALYTICS_QUERY", {"resource_type": "product"}),
            ["mcp-analytics", "mcp-postgres-query"],
        )

    def test_postgres_tidak_duplikat(self):
        self.assertEqual(
            tool_selector.select_tools("DATA_LOOKUP", {"resource_type": "order"}),
            ["mcp-postgres-query"],
        )

    def test_llm_return_unknown_tetap_unknown(self):
        provider = _FakeProvider("UNKNOWN")
        with patch(
            "integrations.ai_agent.orchestrator.intent_classifier.get_llm_provider",
            return_value=provider,
        ):
            result = intent_classifier.classify("halo")

        self.assertEqual(result["intent"], "UNKNOWN")
        self.assertEqual(result["confidence"], 0.0)
        self.assertEqual(result["tokens"], 7)

    def test_llm_return_invalid_jadi_unknown(self):
        provider = _FakeProvider("TOO_LONG_INTENT_NAME")
        with patch(
            "integrations.ai_agent.orchestrator.intent_classifier.get_llm_provider",
            return_value=provider,
        ):
            result = intent_classifier.classify("halo")

        self.assertEqual(result["intent"], "UNKNOWN")
        self.assertEqual(result["confidence"], 0.0)

    def test_tool_selector_unknown_kosong(self):
        self.assertEqual(tool_selector.select_tools("UNKNOWN", {}), [])

    def test_tool_selector_diagnostic_dengan_product(self):
        self.assertEqual(
            tool_selector.select_tools("DIAGNOSTIC", {"resource_type": "product"}),
            ["mcp-analytics", "mcp-event-log", "mcp-postgres-query"],
        )

    def test_data_lookup_stok_odoo_menambah_odoo_rpc(self):
        self.assertEqual(
            tool_selector.select_tools(
                "DATA_LOOKUP", {}, "berapa stok produk Kaos di Odoo?"
            ),
            ["mcp-postgres-query", "mcp-odoo-rpc"],
        )

    def test_unknown_stok_odoo_menambah_odoo_rpc(self):
        self.assertEqual(
            tool_selector.select_tools("UNKNOWN", {}, "stok odoo?"),
            ["mcp-odoo-rpc"],
        )

    def test_keyword_po_dan_so(self):
        for message in ("status PO terakhir?", "status SO minggu ini?"):
            with self.subTest(message=message):
                self.assertIn(
                    "mcp-odoo-rpc",
                    tool_selector.select_tools("DATA_LOOKUP", {}, message),
                )

    def test_diagnostic_keyword_boleh_menambah_rule_engine(self):
        self.assertEqual(
            tool_selector.select_tools("DIAGNOSTIC", {}, "order ini boleh lanjut?"),
            ["mcp-analytics", "mcp-event-log", "mcp-postgres-query", "mcp-rule-engine"],
        )

    def test_analytics_total_menambah_aggregator(self):
        self.assertEqual(
            tool_selector.select_tools("ANALYTICS_QUERY", {}, "total produksi minggu ini?"),
            ["mcp-analytics", "mcp-aggregator"],
        )

    def test_analytics_tren_menambah_time_series(self):
        self.assertEqual(
            tool_selector.select_tools("ANALYTICS_QUERY", {}, "tren scrap 30 hari?"),
            ["mcp-analytics", "mcp-time-series"],
        )



