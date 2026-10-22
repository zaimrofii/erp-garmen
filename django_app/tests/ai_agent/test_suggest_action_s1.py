"""Test S.1/S.2 — intent SUGGEST_ACTION, prompt, guardrail, HITL."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from core.auth.models import Role, User
from integrations.ai_agent.hitl import impact_scorer
from integrations.ai_agent.models import AIHitlQueue
from integrations.ai_agent.orchestrator import (
    intent_classifier,
    response_synthesizer,
    tool_selector,
)

PROVIDER = "integrations.ai_agent.orchestrator.response_synthesizer.get_llm_provider"
INTENT_PROVIDER = "integrations.ai_agent.orchestrator.intent_classifier.get_llm_provider"

URL = "/api/v1/ai/chat"
VIEW_INTENT = "integrations.ai_agent.api.views.intent_classifier.classify"
VIEW_TOOLS = "integrations.ai_agent.api.views.tool_selector.select_tools"
VIEW_BUILD = "integrations.ai_agent.api.views.context_builder.build_context"
WA_SEND = "integrations.wa_bot.hitl_messages.send_hitl_notification"


def _llm(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        text=text,
        prompt_tokens=20,
        completion_tokens=40,
        total_cost_usd=0.001,
        model="deepseek-chat",
        latency_ms=15,
    )


SUGGEST_JSON = json.dumps(
    {
        "problem": "scrap SEWING-2 8.4%",
        "proposed_actions": [
            {
                "action": "rework BND-A-12",
                "impact": "MEDIUM",
                "confidence": 0.82,
                "reason": "3.2% scrap",
            },
            {
                "action": "pindah BND-A-14 ke SEWING-1",
                "impact": "MEDIUM",
                "confidence": 0.75,
                "reason": "2.8% scrap",
            },
        ],
    }
)


class IntentSuggestTests(SimpleTestCase):
    def test_classify_suggest_action(self):
        provider = SimpleNamespace(complete=lambda **kwargs: _llm("SUGGEST_ACTION"))
        with patch(INTENT_PROVIDER, return_value=provider):
            result = intent_classifier.classify("apa yang harus saya lakukan?")

        self.assertEqual(result["intent"], "SUGGEST_ACTION")

    def test_classify_diagnostic(self):
        provider = SimpleNamespace(complete=lambda **kwargs: _llm("DIAGNOSTIC"))
        with patch(INTENT_PROVIDER, return_value=provider):
            result = intent_classifier.classify("kenapa scrap naik?")

        self.assertEqual(result["intent"], "DIAGNOSTIC")

    def test_is_suggest_action_helper(self):
        self.assertTrue(intent_classifier.is_suggest_action("suggest_action"))
        self.assertFalse(intent_classifier.is_suggest_action("DIAGNOSTIC"))


class ToolSelectorSuggestTests(SimpleTestCase):
    def test_suggest_action_tools(self):
        tools = tool_selector.select_tools(
            "SUGGEST_ACTION", {}, "apa yang harus saya lakukan?"
        )

        self.assertIn("mcp-analytics", tools)
        self.assertIn("mcp-rule-engine", tools)
        self.assertIn("mcp-aggregator", tools)

    def test_intent_lain_tidak_dapat_rule_engine(self):
        tools = tool_selector.select_tools("DATA_LOOKUP", {}, "produk kaos?")

        self.assertNotIn("mcp-rule-engine", tools)

class SuggestSynthesizerTests(SimpleTestCase):
    def _synthesize(self, text: str) -> dict:
        provider = SimpleNamespace(complete=lambda **kwargs: _llm(text))
        with patch(PROVIDER, return_value=provider):
            return response_synthesizer.synthesize(
                "apa yang harus saya lakukan?",
                {"message": "uji", "context": {}, "metrics": []},
                intent="SUGGEST_ACTION",
            )

    def test_json_valid_menghasilkan_proposed_actions(self):
        result = self._synthesize(SUGGEST_JSON)

        self.assertTrue(result["ok"])
        self.assertEqual(len(result["proposed_actions"]), 2)
        self.assertTrue(result["hitl_required"])
        self.assertFalse(result["cacheable"])
        self.assertEqual(result["proposed_actions"][0]["action"], "rework BND-A-12")

    def test_json_code_fence_diparse(self):
        result = self._synthesize(f"```json\n{SUGGEST_JSON}\n```")

        self.assertEqual(len(result.get("proposed_actions", [])), 2)

    def test_answer_menyebut_menunggu_persetujuan(self):
        result = self._synthesize(SUGGEST_JSON)

        self.assertIn("persetujuan manusia", result["answer"])

    def test_json_rusak_fallback_teks(self):
        result = self._synthesize("Bukan JSON, hanya teks biasa.")

        self.assertTrue(result["ok"])
        self.assertNotIn("proposed_actions", result)
        self.assertIn("teks biasa", result["answer"])

    def test_semua_aksi_berbahaya_fallback(self):
        payload = json.dumps(
            {
                "problem": "x",
                "proposed_actions": [
                    {"action": "hapus semua order", "confidence": 0.9}
                ],
            }
        )

        result = self._synthesize(payload)

        self.assertNotIn("proposed_actions", result)


class ActionGuardrailTests(SimpleTestCase):
    def test_aksi_berbahaya_difilter(self):
        actions = response_synthesizer._validate_proposed_actions(
            [{"action": "hapus semua order", "confidence": 0.9}]
        )

        self.assertEqual(actions, [])

    def test_aksi_spesifik_valid(self):
        actions = response_synthesizer._validate_proposed_actions(
            [{"action": "rework bundle BND-A-1", "confidence": 0.8}]
        )

        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["action"], "rework bundle BND-A-1")

    def test_default_impact_dan_confidence(self):
        actions = response_synthesizer._validate_proposed_actions(
            [{"action": "pindah bundle BND-1 ke SEWING-1"}]
        )

        self.assertEqual(actions[0]["impact"], "LOW")
        self.assertEqual(actions[0]["confidence"], 0.5)

    def test_maksimal_tiga_aksi_sorted(self):
        raw = [
            {"action": f"rework bundle BND-{index}", "confidence": index / 10}
            for index in range(1, 7)
        ]

        actions = response_synthesizer._validate_proposed_actions(raw)

        self.assertEqual(len(actions), 3)
        self.assertEqual([item["confidence"] for item in actions], [0.6, 0.5, 0.4])

    def test_aksi_kurang_dari_dua_kata_difilter(self):
        actions = response_synthesizer._validate_proposed_actions(
            [{"action": "rework", "confidence": 0.9}]
        )

        self.assertEqual(actions, [])

    def test_confidence_diklamp(self):
        actions = response_synthesizer._validate_proposed_actions(
            [
                {"action": "rework bundle A", "confidence": 5},
                {"action": "pindah bundle B", "confidence": -2},
            ]
        )

        self.assertEqual(actions[0]["confidence"], 1.0)
        self.assertEqual(actions[1]["confidence"], 0.0)

class ImpactScorerSuggestTests(SimpleTestCase):
    def test_suggest_action_minimal_medium(self):
        level = impact_scorer.score(
            "SUGGEST_ACTION",
            [],
            {"type": "suggest_actions", "actions": [{"action": "rework bundle A"}]},
        )

        self.assertEqual(level, "MEDIUM")

    def test_suggest_action_high_jika_finance(self):
        level = impact_scorer.score(
            "SUGGEST_ACTION",
            [],
            {"actions": [{"action": "update invoice INV-1"}]},
        )

        self.assertEqual(level, "HIGH")

    def test_tanpa_aksi_low(self):
        self.assertEqual(impact_scorer.score("SUGGEST_ACTION", [], None), "LOW")


@override_settings(AI_AGENT_ENABLED=True)
class SuggestHitlIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.role = Role.objects.get(code=Role.Code.SUPERVISOR)

    def setUp(self):
        super().setUp()
        cache.clear()
        self.user = User.objects.create_user(
            username="suggest-hitl", password="x", role=self.role
        )
        self.api = APIClient()
        self.api.force_authenticate(self.user)

        self.patches = [
            patch(
                VIEW_INTENT,
                return_value={
                    "intent": "SUGGEST_ACTION",
                    "confidence": 0.9,
                    "cost_usd": 0,
                },
            ),
            patch(VIEW_TOOLS, return_value=["mcp-analytics"]),
            patch(
                VIEW_BUILD,
                return_value={
                    "intent": "SUGGEST_ACTION",
                    "message": "uji",
                    "context": {},
                    "tools": ["mcp-analytics"],
                    "metrics": [],
                },
            ),
            patch(WA_SEND, return_value={"ok": True}),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_membuat_antrean_hitl_dan_id_di_response(self):
        provider = SimpleNamespace(complete=lambda **kwargs: _llm(SUGGEST_JSON))
        with patch(PROVIDER, return_value=provider):
            response = self.api.post(
                URL, {"message": "apa yang harus saya lakukan?"}, format="json"
            )

        body = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(body["hitl_required"])
        self.assertIsInstance(body["hitl_request_id"], int)
        self.assertEqual(body["risk_level"], "MEDIUM")

        queue = AIHitlQueue.objects.get(pk=body["hitl_request_id"])
        self.assertEqual(queue.status, "PENDING")
        self.assertEqual(queue.risk_level, "MEDIUM")
        self.assertEqual(len(queue.proposed_action["actions"]), 2)
        self.assertEqual(queue.decision_log.hitl_required, True)


