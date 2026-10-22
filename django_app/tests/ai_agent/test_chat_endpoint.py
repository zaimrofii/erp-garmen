"""Test endpoint chat AI (D.5) — 15 skenario."""

from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.auth.models import Role, User
from integrations.ai_agent.api.handlers.llm_pipeline import build_cache_scope
from integrations.ai_agent.memory import semantic_cache
from integrations.ai_agent.models import AIDecisionLog

URL = "/api/v1/ai/chat"

ANALYTICS_ENABLED = (
    "integrations.analytics.services.analytics_config_services.analytics_enabled"
)


class ChatEndpointTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.supervisor = User.objects.create_user(
            username="sup-ai",
            password="rahasia123",
            role=Role.objects.get(code=Role.Code.SUPERVISOR),
        )
        cls.operator = User.objects.create_user(
            username="op-ai",
            password="rahasia123",
            role=Role.objects.get(code=Role.Code.OPERATOR),
        )

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.supervisor)

        # G.5 — mock seluruh jalur LLM supaya test tidak pernah memanggil API nyata.
        self.intent_patch = patch(
            "integrations.ai_agent.api.views.intent_classifier.classify",
            return_value={"intent": "GENERAL_CHAT", "confidence": 0.8, "tokens": 7},
        )
        self.builder_patch = patch(
            "integrations.ai_agent.api.views.context_builder.build_context",
            return_value={
                "intent": "GENERAL_CHAT",
                "message": "uji",
                "context": {},
                "tools": [],
                "metrics": [],
            },
        )
        self.synth_patch = patch(
            "integrations.ai_agent.api.views.response_synthesizer.synthesize",
            return_value={
                "ok": True,
                "answer": "Jawaban uji dari LLM.",
                "tokens": {
                    "prompt": 120,
                    "completion": 30,
                    "total_cost_usd": 0.0000252,
                },
                "model": "mock-llm",
                "latency_ms": 5,
            },
        )
        self.mock_intent = self.intent_patch.start()
        self.mock_builder = self.builder_patch.start()
        self.mock_synth = self.synth_patch.start()
        self.addCleanup(self.intent_patch.stop)
        self.addCleanup(self.builder_patch.stop)
        self.addCleanup(self.synth_patch.stop)

    def post(self, payload, user=None):
        client = APIClient()
        client.force_authenticate(user or self.supervisor)
        return client.post(URL, payload, format="json")

    def test_history_dikirim_ke_context_builder(self):
        history = [
            {"role": "user", "content": "produk paling mahal?"},
            {"role": "assistant", "content": "Jaket."},
        ]
        with override_settings(AI_AGENT_ENABLED=True), patch(
            ANALYTICS_ENABLED, return_value=True
        ):
            response = self.post(
                {"message": "peringkat kedua?", "history": history}
            )

        self.assertEqual(response.status_code, 200)
        self.mock_builder.assert_called_once()
        self.assertEqual(
            self.mock_builder.call_args.kwargs["history"], history
        )

    def test_anonim_403(self):
        with override_settings(AI_AGENT_ENABLED=True):
            response = APIClient().post(URL, {"message": "halo"}, format="json")

        self.assertEqual(response.status_code, 403)

    def test_message_kosong_400(self):
        with override_settings(AI_AGENT_ENABLED=True):
            response = self.post({"message": ""})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "bad_request")

    def test_message_lebih_2000_400(self):
        with override_settings(AI_AGENT_ENABLED=True):
            response = self.post({"message": "x" * 2001})

        self.assertEqual(response.status_code, 400)

    def test_history_lebih_10_400(self):
        history = [{"role": "user", "content": "halo"} for _ in range(11)]
        with override_settings(AI_AGENT_ENABLED=True):
            response = self.post({"message": "halo", "history": history})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "bad_request")

    def test_context_detail_resource_id_none_400(self):
        with override_settings(AI_AGENT_ENABLED=True):
            response = self.post(
                {
                    "message": "halo",
                    "context": {
                        "page_type": "detail",
                        "resource_type": "product",
                        "resource_id": None,
                    },
                }
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "bad_context")

    def test_context_list_resource_type_tanpa_id_ok(self):
        with override_settings(AI_AGENT_ENABLED=True), patch(
            ANALYTICS_ENABLED, return_value=True
        ):
            response = self.post(
                {
                    "message": "jelaskan halaman ini",
                    "context": {"page_type": "list", "resource_type": "product"},
                }
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["decision_gate_result"], "LLM_NEEDED")
        self.assertTrue(response.json()["ok"])

    def test_rule_hit_analytics_off(self):
        with override_settings(AI_AGENT_ENABLED=True), patch(
            ANALYTICS_ENABLED, return_value=False
        ):
            response = self.post({"message": "analitik belum aktif?"})

        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["decision_gate_result"], "RULE_HIT")
        self.assertIn("Analitik belum aktif", body["answer"])
        self.assertEqual(body["tokens"]["prompt"], 0)
        self.assertEqual(body["tokens"]["completion"], 0)

    def test_llm_needed_generic(self):
        with override_settings(AI_AGENT_ENABLED=True), patch(
            ANALYTICS_ENABLED, return_value=True
        ):
            response = self.post({"message": "kenapa scrap naik?"})

        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["decision_gate_result"], "LLM_NEEDED")
        self.assertEqual(body["answer"], "Jawaban uji dari LLM.")
        self.assertNotIn("reason", body)

    def test_forbidden_context_operator(self):
        with override_settings(AI_AGENT_ENABLED=True):
            response = self.post(
                {
                    "message": "jelaskan produk ini",
                    "context": {
                        "page_type": "detail",
                        "resource_type": "product",
                        "resource_id": "123",
                    },
                },
                user=self.operator,
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["ok"])
        self.assertEqual(response.json()["error"], "forbidden_context")

    def test_decision_log_tercatat_satu_baris(self):
        with override_settings(AI_AGENT_ENABLED=True), patch(
            ANALYTICS_ENABLED, return_value=False
        ):
            self.post({"message": "analitik belum aktif?"})

        self.assertEqual(AIDecisionLog.objects.count(), 1)
        self.assertEqual(AIDecisionLog.objects.get().decision_gate_result, "RULE_HIT")

    def test_flag_false_stub_lama(self):
        with override_settings(AI_AGENT_ENABLED=False):
            response = self.post({"message": "halo"})

        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(body["ok"])
        self.assertEqual(body["reason"], "not_implemented")
        self.assertEqual(body["schema_version"], "1.0")

    def test_flag_true_endpoint_baru_rule_hit(self):
        with override_settings(AI_AGENT_ENABLED=True), patch(
            ANALYTICS_ENABLED, return_value=False
        ):
            response = self.post({"message": "analytics off?"})

        self.assertEqual(response.json()["decision_gate_result"], "RULE_HIT")

    def test_channel_invalid_400(self):
        with override_settings(AI_AGENT_ENABLED=True):
            response = self.post({"message": "halo", "channel": "EMAIL"})

        self.assertEqual(response.status_code, 400)

    def test_resource_id_tanpa_type_400(self):
        with override_settings(AI_AGENT_ENABLED=True):
            response = self.post(
                {
                    "message": "halo",
                    "context": {"page_type": "detail", "resource_id": "123"},
                }
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "bad_context")

    def test_analytics_disabled_saat_butuh(self):
        with override_settings(AI_AGENT_ENABLED=True), patch(
            ANALYTICS_ENABLED, return_value=False
        ):
            response = self.post({"message": "berapa scrap rate minggu ini?"})

        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["error"], "analytics_disabled")
        self.assertEqual(body["decision_gate_result"], "LLM_NEEDED")

    def test_rule_hit_tidak_memanggil_llm(self):
        with override_settings(AI_AGENT_ENABLED=True), patch(
            ANALYTICS_ENABLED, return_value=False
        ):
            response = self.post({"message": "analytics disabled sekarang?"})

        self.assertEqual(response.json()["decision_gate_result"], "RULE_HIT")
        self.mock_intent.assert_not_called()
        self.mock_builder.assert_not_called()
        self.mock_synth.assert_not_called()

    def test_blocked_tidak_memanggil_llm(self):
        with override_settings(AI_AGENT_ENABLED=True):
            response = self.post(
                {
                    "message": "jelaskan produk ini",
                    "context": {
                        "page_type": "detail",
                        "resource_type": "product",
                        "resource_id": "123",
                    },
                },
                user=self.operator,
            )

        self.assertEqual(response.json()["error"], "forbidden_context")
        self.mock_intent.assert_not_called()
        self.mock_builder.assert_not_called()
        self.mock_synth.assert_not_called()

    def test_llm_success_shape_kontrak(self):
        with override_settings(AI_AGENT_ENABLED=True), patch(
            ANALYTICS_ENABLED, return_value=True
        ):
            response = self.post({"message": "kenapa scrap naik pada shift ini?"})

        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["answer"], "Jawaban uji dari LLM.")
        self.assertEqual(body["decision_gate_result"], "LLM_NEEDED")
        self.assertEqual(body["confidence_score"], 0.8)
        self.assertEqual(body["impact_score"], "LOW")
        self.assertFalse(body["hitl_required"])
        self.assertIsNone(body["hitl_request_id"])
        self.assertFalse(body["cache_hit"])
        self.assertIsInstance(body["tool_calls"], list)
        self.assertGreater(body["latency_ms"], 0)
        self.assertEqual(
            set(body),
            {
                "ok",
                "answer",
                "tool_calls",
                "confidence_score",
                "impact_score",
                "hitl_required",
                "hitl_request_id",
                "decision_gate_result",
                "tokens",
                "cache_hit",
                "latency_ms",
            },
        )

    def test_llm_success_mencatat_token_cost_dan_tool(self):
        self.mock_intent.return_value = {
            "intent": "GENERAL_CHAT",
            "confidence": 0.8,
            "tokens": 7,
            "cost_usd": 0.0001,
        }
        with override_settings(AI_AGENT_ENABLED=True), patch(
            ANALYTICS_ENABLED, return_value=True
        ), patch(
            "integrations.ai_agent.api.views.cost_tracker.record_cost"
        ) as record_cost:
            response = self.post({"message": "analisis scrap cutting minggu ini"})

        self.assertTrue(response.json()["ok"])
        self.assertEqual(response.json()["tokens"]["prompt"], 120)
        log = AIDecisionLog.objects.order_by("-id").first()
        self.assertEqual(log.decision_gate_result, "LLM_NEEDED")
        self.assertEqual(log.intent, "GENERAL_CHAT")
        self.assertEqual(log.prompt_tokens, 120)
        self.assertEqual(log.completion_tokens, 30)
        # Biaya synthesizer + classifier (0.0000252 + 0.0001).
        self.assertAlmostEqual(float(log.total_cost_usd), 0.0001252, places=6)
        self.assertEqual(log.model_used, "mock-llm")
        self.assertFalse(log.cache_hit)
        record_cost.assert_called_once_with(log)

    def test_llm_gagal_tetap_200_dan_error_rapi(self):
        self.mock_synth.return_value = {
            "ok": False,
            "error": "llm_failed",
            "detail": "LLM timeout",
            "tokens": {"prompt": 0, "completion": 0, "total_cost_usd": 0},
        }
        with override_settings(AI_AGENT_ENABLED=True), patch(
            ANALYTICS_ENABLED, return_value=True
        ):
            response = self.post({"message": "kenapa rework naik di sewing?"})

        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"], "llm_failed")
        self.assertEqual(body["detail"], "LLM timeout")
        self.assertEqual(body["tokens"]["prompt"], 0)
        self.assertEqual(body["decision_gate_result"], "LLM_NEEDED")
        log = AIDecisionLog.objects.order_by("-id").first()
        self.assertEqual(log.prompt_tokens, 0)
        self.assertIn("llm_failed", log.response_text)

    def test_budget_exceeded_llm_needed_429(self):
        with override_settings(AI_AGENT_ENABLED=True), patch(
            ANALYTICS_ENABLED, return_value=True
        ), patch(
            "integrations.ai_agent.api.views.cost_tracker.check_budget",
            return_value={"exceeded": True},
        ):
            response = self.post({"message": "halo, budget saya masih ada?"})

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["error"], "budget_exceeded")
        self.mock_intent.assert_not_called()
        self.mock_synth.assert_not_called()

    def test_intent_analytics_memilih_tool_analytics(self):
        self.mock_intent.return_value = {
            "intent": "ANALYTICS_QUERY",
            "confidence": 0.8,
            "tokens": 7,
        }
        self.mock_builder.return_value = {
            "intent": "ANALYTICS_QUERY",
            "message": "berapa scrap rate?",
            "context": {},
            "tools": ["mcp-analytics"],
            "metrics": [
                {"metric_id": "garment.scrap_rate", "unit": "%", "rows": []}
            ],
        }
        with override_settings(AI_AGENT_ENABLED=True), patch(
            ANALYTICS_ENABLED, return_value=True
        ):
            response = self.post({"message": "berapa scrap rate minggu ini?"})

        tool_calls = response.json()["tool_calls"]
        self.assertEqual([call["tool"] for call in tool_calls], ["mcp-analytics"])
        self.assertEqual(tool_calls[0]["input"]["metrics"], ["garment.scrap_rate"])
        self.assertIn("scrap_rate", tool_calls[0]["output_summary"])
        self.mock_intent.assert_called_once_with("berapa scrap rate minggu ini?")
        self.mock_builder.assert_called_once()
        self.assertIs(
            self.mock_builder.call_args.kwargs["user"], self.supervisor
        )

    def test_context_product_menambah_tool_postgres(self):
        self.mock_intent.return_value = {
            "intent": "DATA_LOOKUP",
            "confidence": 0.8,
            "tokens": 7,
        }
        self.mock_builder.return_value = {
            "intent": "DATA_LOOKUP",
            "message": "produk ini apa?",
            "context": {"resource_type": "product", "resource_id": "123"},
            "tools": ["mcp-postgres-query"],
            "resource": [{"id": "123", "code": "PRD-1"}],
        }
        with override_settings(AI_AGENT_ENABLED=True), patch(
            ANALYTICS_ENABLED, return_value=True
        ):
            response = self.post(
                {
                    "message": "produk ini apa?",
                    "context": {
                        "page_type": "detail",
                        "resource_type": "product",
                        "resource_id": "123",
                    },
                }
            )

        self.assertTrue(response.json()["ok"])
        tool_calls = response.json()["tool_calls"]
        self.assertEqual(
            [call["tool"] for call in tool_calls], ["mcp-postgres-query"]
        )
        self.assertEqual(tool_calls[0]["input"]["resource_id"], "123")
        self.assertIn("1 baris", tool_calls[0]["output_summary"])

    def test_cache_hit_tokens_nol_tanpa_memanggil_llm(self):
        message = "pesan cache llm unik"
        cached = {
            "ok": True,
            "answer": "Jawaban dari cache.",
            "tool_calls": [],
            "confidence_score": 0.8,
            "impact_score": "LOW",
            "hitl_required": False,
            "hitl_request_id": None,
            "decision_gate_result": "LLM_NEEDED",
            "tokens": {"prompt": 99, "completion": 9, "total_cost_usd": 0.01},
            "cache_hit": False,
            "latency_ms": 10,
        }
        semantic_cache.set(
            build_cache_scope("SUPERVISOR", "DESKTOP", message, {}), cached
        )

        with override_settings(AI_AGENT_ENABLED=True), patch(
            ANALYTICS_ENABLED, return_value=True
        ):
            response = self.post({"message": message})

        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(body["cache_hit"])
        self.assertEqual(
            body["tokens"], {"prompt": 0, "completion": 0, "total_cost_usd": 0}
        )
        self.assertTrue(body["ok"])
        self.mock_intent.assert_not_called()
        self.mock_builder.assert_not_called()
        self.mock_synth.assert_not_called()
        self.assertTrue(AIDecisionLog.objects.order_by("-id").first().cache_hit)

    def test_synth_menerima_konteks_hasil_builder(self):
        self.mock_builder.return_value = {
            "intent": "GENERAL_CHAT",
            "message": "halo konteks",
            "context": {"page_type": "list"},
            "tools": [],
            "metrics": [],
        }
        with override_settings(AI_AGENT_ENABLED=True), patch(
            ANALYTICS_ENABLED, return_value=True
        ):
            self.post({"message": "halo konteks"})

        args, _ = self.mock_synth.call_args
        self.assertEqual(args[0], "halo konteks")
        self.assertIs(args[1], self.mock_builder.return_value)

    def test_jawaban_llm_kosong_dianggap_gagal(self):
        self.mock_synth.return_value = {
            "ok": True,
            "answer": "   ",
            "tokens": {"prompt": 10, "completion": 0, "total_cost_usd": 0.001},
            "model": "mock-llm",
            "latency_ms": 1,
        }
        message = "pertanyaan jawaban kosong unik"
        with override_settings(AI_AGENT_ENABLED=True), patch(
            ANALYTICS_ENABLED, return_value=True
        ):
            response = self.post({"message": message})

        body = response.json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"], "llm_failed")
        self.assertEqual(body["detail"], "Jawaban LLM kosong.")
        self.assertEqual(body["tokens"]["prompt"], 0)
        self.assertIsNone(
            semantic_cache.get(f"SUPERVISOR|DESKTOP|{message}")
        )



