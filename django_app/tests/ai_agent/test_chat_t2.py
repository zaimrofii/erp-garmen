"""Test integrasi chat T2 — rule/aggregator/time-series via endpoint (mock LLM)."""

from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.auth.models import Role, User

URL = "/api/v1/ai/chat"
ANALYTICS_ENABLED = (
    "integrations.analytics.services.analytics_config_services.analytics_enabled"
)


class ChatT2IntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="sup-t2",
            password="x",
            role=Role.objects.get(code=Role.Code.SUPERVISOR),
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.intent = patch(
            "integrations.ai_agent.api.views.intent_classifier.classify",
            return_value={
                "intent": "DIAGNOSTIC",
                "confidence": 0.8,
                "tokens": 1,
            },
        )
        self.builder = patch(
            "integrations.ai_agent.api.views.context_builder.build_context",
            return_value={
                "intent": "DIAGNOSTIC",
                "message": "x",
                "context": {},
                "tools": [],
            },
        )
        self.synth = patch(
            "integrations.ai_agent.api.views.response_synthesizer.synthesize",
            return_value={
                "ok": True,
                "answer": "Jawaban uji T2.",
                "tokens": {"prompt": 1, "completion": 1, "total_cost_usd": 0},
                "model": "mock",
                "latency_ms": 1,
            },
        )
        self.mock_intent = self.intent.start()
        self.builder.start()
        self.synth.start()
        self.addCleanup(self.intent.stop)
        self.addCleanup(self.builder.stop)
        self.addCleanup(self.synth.stop)

    def _post(self, message):
        with patch(ANALYTICS_ENABLED, return_value=True):
            return self.client.post(URL, {"message": message}, format="json")

    def test_order_boleh_lanjut_memilih_rule_engine(self):
        self.mock_intent.return_value = {
            "intent": "DIAGNOSTIC",
            "confidence": 0.8,
            "tokens": 1,
        }

        response = self._post("order ini boleh lanjut?")

        self.assertTrue(response.json()["ok"])
        self.assertIn(
            "mcp-rule-engine",
            [call["tool"] for call in response.json()["tool_calls"]],
        )

    def test_total_produksi_memilih_aggregator(self):
        self.mock_intent.return_value = {
            "intent": "ANALYTICS_QUERY",
            "confidence": 0.8,
            "tokens": 1,
        }

        response = self._post("total produksi minggu ini?")

        self.assertTrue(response.json()["ok"])
        self.assertIn(
            "mcp-aggregator",
            [call["tool"] for call in response.json()["tool_calls"]],
        )

    def test_tren_scrap_memilih_time_series(self):
        self.mock_intent.return_value = {
            "intent": "ANALYTICS_QUERY",
            "confidence": 0.8,
            "tokens": 1,
        }

        response = self._post("tren scrap 30 hari?")

        self.assertTrue(response.json()["ok"])
        self.assertIn(
            "mcp-time-series",
            [call["tool"] for call in response.json()["tool_calls"]],
        )

    def test_stok_cukup_memilih_rule_engine(self):
        self.mock_intent.return_value = {
            "intent": "DIAGNOSTIC",
            "confidence": 0.8,
            "tokens": 1,
        }

        response = self._post("stok cukup untuk order ini?")

        self.assertIn(
            "mcp-rule-engine",
            [call["tool"] for call in response.json()["tool_calls"]],
        )

    def test_rata_rata_memilih_aggregator(self):
        self.mock_intent.return_value = {
            "intent": "ANALYTICS_QUERY",
            "confidence": 0.8,
            "tokens": 1,
        }

        response = self._post("rata-rata scrap per work center?")

        self.assertIn(
            "mcp-aggregator",
            [call["tool"] for call in response.json()["tool_calls"]],
        )

    def test_historis_memilih_time_series(self):
        self.mock_intent.return_value = {
            "intent": "ANALYTICS_QUERY",
            "confidence": 0.8,
            "tokens": 1,
        }

        response = self._post("historis rework 30 hari?")

        self.assertIn(
            "mcp-time-series",
            [call["tool"] for call in response.json()["tool_calls"]],
        )

