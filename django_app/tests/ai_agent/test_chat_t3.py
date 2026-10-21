"""Test integrasi chat T3 — comparator/forecaster (mock LLM)."""

from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.auth.models import Role, User

URL = "/api/v1/ai/chat"
ANALYTICS_ENABLED = (
    "integrations.analytics.services.analytics_config_services.analytics_enabled"
)


class ChatT3IntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="sup-t3",
            password="x",
            role=Role.objects.get(code=Role.Code.SUPERVISOR),
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.intent = patch(
            "integrations.ai_agent.api.views.intent_classifier.classify",
            return_value={"intent": "DIAGNOSTIC", "confidence": 0.8, "tokens": 1},
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
                "answer": "Jawaban uji T3.",
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

    def _tools(self, response):
        return [call["tool"] for call in response.json()["tool_calls"]]

    def test_kenapa_line_lebih_lambat_comparator(self):
        self.mock_intent.return_value = {
            "intent": "DIAGNOSTIC",
            "confidence": 0.8,
            "tokens": 1,
        }

        response = self._post("kenapa Line A lebih lambat dari Line B?")

        self.assertTrue(response.json()["ok"])
        self.assertIn("mcp-comparator", self._tools(response))

    def test_bandingkan_scrap_comparator(self):
        self.mock_intent.return_value = {
            "intent": "DIAGNOSTIC",
            "confidence": 0.8,
            "tokens": 1,
        }

        response = self._post("bandingkan scrap minggu ini vs minggu lalu")

        self.assertIn("mcp-comparator", self._tools(response))

    def test_kapan_order_selesai_forecaster(self):
        self.mock_intent.return_value = {
            "intent": "ANALYTICS_QUERY",
            "confidence": 0.8,
            "tokens": 1,
        }

        response = self._post("kapan order SO-2026-0001 selesai?")

        self.assertIn("mcp-forecaster", self._tools(response))

    def test_prediksi_scrap_forecaster(self):
        self.mock_intent.return_value = {
            "intent": "ANALYTICS_QUERY",
            "confidence": 0.8,
            "tokens": 1,
        }

        response = self._post("prediksi scrap besok?")

        self.assertIn("mcp-forecaster", self._tools(response))

    def test_comparator_tool_calls_shape(self):
        self.mock_intent.return_value = {
            "intent": "DIAGNOSTIC",
            "confidence": 0.8,
            "tokens": 1,
        }

        response = self._post("banding Line A vs Line B?")

        calls = response.json()["tool_calls"]
        self.assertTrue(any(call["tool"] == "mcp-comparator" for call in calls))
        self.assertTrue(all("output_summary" in call for call in calls))

    def test_forecaster_tool_calls_shape(self):
        self.mock_intent.return_value = {
            "intent": "ANALYTICS_QUERY",
            "confidence": 0.8,
            "tokens": 1,
        }

        response = self._post("estimasi scrap 7 hari?")

        calls = response.json()["tool_calls"]
        self.assertTrue(any(call["tool"] == "mcp-forecaster" for call in calls))
        self.assertTrue(all("output_summary" in call for call in calls))
