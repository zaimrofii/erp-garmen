"""Test Fix #18 — render natural SUGGEST_ACTION, prompt sederhana, chart_data."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from core.auth.models import Role, User
from integrations.ai_agent.orchestrator import chart_builder, response_synthesizer

PROVIDER = "integrations.ai_agent.orchestrator.response_synthesizer.get_llm_provider"

SUGGEST_JSON = json.dumps(
    {
        "problem": "Scrap SEWING-2 naik ke 21%",
        "proposed_actions": [
            {
                "action": "rework BND-A-12",
                "impact": "MEDIUM",
                "confidence": 0.82,
                "reason": "3,2% scrap",
            },
            {
                "action": "pindah BND-A-14 ke SEWING-1",
                "impact": "LOW",
                "confidence": 0.6,
                "reason": "beban tidak seimbang",
            },
        ],
    }
)

METRICS = [
    {
        "metric_id": "garment.scrap_rate",
        "dimension": "period",
        "unit": "%",
        "rows": [
            {"label": "2026-10-18", "value": 1.6},
            {"label": "2026-10-19", "value": 5.2},
            {"label": "2026-10-20", "value": 21.0},
        ],
    }
]


def _llm(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        text=text,
        prompt_tokens=10,
        completion_tokens=20,
        total_cost_usd=0.0,
        model="mock",
        latency_ms=5,
    )


def _synth(
    text: str,
    intent: str = "SUGGEST_ACTION",
    context: dict | None = None,
    message: str = "apa yang harus saya lakukan?",
) -> dict:
    provider = SimpleNamespace(complete=lambda **kwargs: _llm(text))
    with patch(PROVIDER, return_value=provider):
        return response_synthesizer.synthesize(
            message,
            {
                "message": "uji",
                "context": {},
                "metrics": (context or {}).get("metrics", []),
            },
            intent=intent,
        )


def _assert_bukan_json(answer: str) -> None:
    stripped = answer.strip()
    assert not stripped.startswith("{"), answer
    assert "proposed_actions" not in answer, answer
    assert '"action"' not in answer, answer


class SuggestNaturalRenderTests(SimpleTestCase):
    def test_json_valid_render_natural_bukan_json(self):
        result = _synth(SUGGEST_JSON)

        _assert_bukan_json(result["answer"])
        self.assertIn("**Masalah:**", result["answer"])
        self.assertIn("**Usulan aksi:**", result["answer"])
        self.assertIn("rework BND-A-12", result["answer"])
        self.assertIn("82%", result["answer"])
        self.assertNotIn("0.82", result["answer"])

    def test_json_dengan_preamble_dan_fence(self):
        text = f"Berikut usulan saya:\n```json\n{SUGGEST_JSON}\n```\nSemoga membantu."
        result = _synth(text)

        _assert_bukan_json(result["answer"])
        self.assertEqual(len(result["proposed_actions"]), 2)

    def test_json_rusak_dislamatkan_tanpa_json_mentah(self):
        broken = (
            '{"problem": "Bottleneck QC-1", "proposed_actions": ['
            '{"action": "pindah BND-QC-4 ke QC-2", "impact": "HIGH",'
            ' "confidence": 0.9, "reason": "antrean menumpuk"}'
        )

        result = _synth(broken)

        _assert_bukan_json(result["answer"])
        self.assertIn("pindah BND-QC-4 ke QC-2", result["answer"])
        self.assertIn("90%", result["answer"])

    def test_json_tidak_bisa_dislamatkan_tetap_bukan_json(self):
        result = _synth('{"proposed_actions": [')

        _assert_bukan_json(result["answer"])
        self.assertIn("format jawabannya belum bisa dibaca", result["answer"])

    def test_intent_lain_yang_membalas_json_tidak_ditampilkan_mentah(self):
        result = _synth(SUGGEST_JSON, intent="ANALYTICS_QUERY")

        _assert_bukan_json(result["answer"])
        self.assertIn("rework BND-A-12", result["answer"])

    def test_prompt_bahasa_sederhana(self):
        prompt = response_synthesizer.SYSTEM_PROMPT

        self.assertIn("Bahasa Indonesia sederhana", prompt)
        self.assertIn('"21%" (bukan "21.0%")', prompt)
        self.assertIn("JANGAN tampilkan tabel mentah atau JSON", prompt)
        self.assertIn("JANGAN menyarankan write", prompt)  # guardrail lama tetap

    def test_prompt_suggest_hanya_json(self):
        prompt = response_synthesizer.SUGGEST_SYSTEM_PROMPT

        self.assertIn("HANYA JSON valid", prompt)
        self.assertIn("JANGAN eksekusi aksi", prompt)

class ChartDataTests(SimpleTestCase):
    def test_metrics_period_menghasilkan_line_chart(self):
        result = _synth(
            "kenapa scrap naik?",
            intent="ANALYTICS_QUERY",
            context={"metrics": METRICS},
            message="kenapa scrap naik?",
        )

        chart = result["chart_data"]

        self.assertEqual(chart["type"], "line")
        self.assertEqual(chart["title"], "Tren Scrap")
        self.assertEqual(chart["unit"], "%")
        self.assertEqual(chart["data"][0], {"label": "18 Okt", "value": 1.6})
        self.assertEqual(len(chart["data"]), 3)

    def test_kurang_dari_dua_titik_tidak_ada_chart(self):
        metrics = [{**METRICS[0], "rows": METRICS[0]["rows"][:1]}]

        result = _synth(
            "scrap?", intent="ANALYTICS_QUERY", context={"metrics": metrics}, message="scrap?"
        )

        self.assertNotIn("chart_data", result)

    def test_intent_lain_tidak_dapat_chart(self):
        self.assertIsNone(
            chart_builder.build_chart_data({"metrics": METRICS}, "DATA_LOOKUP")
        )


URL = "/api/v1/ai/chat"


@override_settings(AI_AGENT_ENABLED=True)
class ChartPipelineTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.role = Role.objects.get(code=Role.Code.SUPERVISOR)

    def setUp(self):
        super().setUp()
        cache.clear()
        self.user = User.objects.create_user(
            username="chart-pipe", password="x", role=self.role
        )
        self.api = APIClient()
        self.api.force_authenticate(self.user)

        self.patches = [
            patch(
                "integrations.ai_agent.api.views.rule_evaluator.evaluate",
                return_value={"result": "LLM_NEEDED", "answer": None},
            ),
            patch(
                "integrations.analytics.services.analytics_config_services.analytics_enabled",
                return_value=True,
            ),
            patch(
                "integrations.ai_agent.api.views.intent_classifier.classify",
                return_value={
                    "intent": "ANALYTICS_QUERY",
                    "confidence": 0.9,
                    "cost_usd": 0,
                },
            ),
            patch(
                "integrations.ai_agent.api.views.tool_selector.select_tools",
                return_value=["mcp-analytics"],
            ),
            patch(
                "integrations.ai_agent.api.views.context_builder.build_context",
                return_value={
                    "intent": "ANALYTICS_QUERY",
                    "message": "scrap?",
                    "context": {},
                    "tools": ["mcp-analytics"],
                    "metrics": METRICS,
                },
            ),
            patch(
                "integrations.ai_agent.api.views.response_synthesizer.synthesize",
                return_value={
                    "ok": True,
                    "answer": "Scrap naik tajam jadi 21%.",
                    "chart_data": {
                        "type": "line",
                        "title": "Tren Scrap",
                        "unit": "%",
                        "data": [
                            {"label": "18 Okt", "value": 1.6},
                            {"label": "20 Okt", "value": 21.0},
                        ],
                    },
                    "tokens": {"prompt": 1, "completion": 1, "total_cost_usd": 0},
                    "model": "mock",
                    "latency_ms": 1,
                },
            ),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_chart_data_diteruskan_ke_response_api(self):
        response = self.api.post(
            URL, {"message": "kenapa scrap naik?"}, format="json"
        )

        body = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["chart_data"]["title"], "Tren Scrap")
        self.assertEqual(len(body["chart_data"]["data"]), 2)

