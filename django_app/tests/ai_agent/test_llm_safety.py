"""Test guardrail LLM (G.6) — prompt safety, filter, validator, rate limit."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from core.auth.models import Role, User
from django.core.cache import cache

from integrations.ai_agent.api.views import RATE_LIMIT_PER_MINUTE, _rate_limit_key
from integrations.ai_agent.orchestrator import context_builder, response_synthesizer
from integrations.ai_agent.orchestrator.response_synthesizer import (
    EMPTY_ANSWER_FALLBACK,
    SYSTEM_PROMPT,
    WRITE_REJECT_ANSWER,
    validate_answer,
)

MODULE = "integrations.ai_agent.orchestrator.response_synthesizer"


def _user(role_code="SUPERVISOR"):
    return SimpleNamespace(role=SimpleNamespace(code=role_code))


class PromptSafetyTests(SimpleTestCase):
    def test_system_prompt_write_dan_hallucination(self):
        self.assertIn("JANGAN menyarankan write", SYSTEM_PROMPT)
        self.assertIn("JANGAN mengarang", SYSTEM_PROMPT)
        self.assertIn("harga/kredit/pajak", SYSTEM_PROMPT)
        self.assertIn("bagaimana cara", SYSTEM_PROMPT)
        self.assertIn("JANGAN sebut data produk yang tidak ada", SYSTEM_PROMPT)


class ContextSanitizerTests(SimpleTestCase):
    def _build(self, role_code):
        context = {
            "page_type": "detail",
            "resource_type": "partner",
            "resource_id": "7",
            "visible_fields_snapshot": {
                "name": "PT Demo",
                "password": "secret",
                "api_key": "key",
                "token": "tok",
                "npwp": "123",
                "credit_limit": 1000,
                "city": "Jakarta",
            },
        }
        return context_builder.build_context(
            "GENERAL_CHAT", [], "halo", context, user=_user(role_code)
        )

    def test_filter_field_sensitif_supervisor(self):
        data = self._build("SUPERVISOR")
        snapshot = data["context"]["visible_fields_snapshot"]

        self.assertEqual(snapshot, {"name": "PT Demo", "city": "Jakarta"})
        self.assertNotIn("password", snapshot)
        self.assertNotIn("api_key", snapshot)
        self.assertNotIn("npwp", snapshot)
        self.assertNotIn("credit_limit", snapshot)

    def test_finance_tetap_dapat_npwp_tapi_password_tetap_disaring(self):
        data = self._build("FINANCE")
        snapshot = data["context"]["visible_fields_snapshot"]

        self.assertEqual(snapshot["npwp"], "123")
        self.assertEqual(snapshot["credit_limit"], 1000)
        self.assertNotIn("password", snapshot)
        self.assertNotIn("api_key", snapshot)
        self.assertNotIn("token", snapshot)

    def test_warning_saat_ada_field_disaring(self):
        with self.assertLogs(
            "integrations.ai_agent.orchestrator.context_builder", level="WARNING"
        ) as logs:
            self._build("SUPERVISOR")

        self.assertIn("disaring", "\n".join(logs.output))


class ResponseValidatorTests(SimpleTestCase):
    def test_write_sql_ditolak(self):
        for text in (
            "UPDATE garment_bundle SET qty = 0",
            "DELETE FROM garment_bundle",
            "INSERT INTO garment_bundle VALUES (1)",
            "DROP TABLE garment_bundle",
        ):
            with self.subTest(text=text):
                self.assertEqual(validate_answer(text), WRITE_REJECT_ANSWER)

    def test_jawaban_panjang_dipotong(self):
        result = validate_answer("x" * 5001)

        self.assertEqual(len(result), 5003)
        self.assertTrue(result.endswith("..."))

    def test_jawaban_kosong_fallback(self):
        self.assertEqual(validate_answer("   "), EMPTY_ANSWER_FALLBACK)

    def test_validator_dipakai_synthesize(self):
        class _Provider:
            def complete(self, system_prompt, user_prompt, max_tokens=1000):
                return SimpleNamespace(
                    text="UPDATE bundle SET qty=0",
                    prompt_tokens=1,
                    completion_tokens=1,
                    total_cost_usd=0,
                    model="mock",
                    latency_ms=1,
                    raw={},
                )

        with patch(f"{MODULE}.get_llm_provider", return_value=_Provider()):
            result = response_synthesizer.synthesize(
                "halo",
                {"message": "halo", "context": {}, "metrics": []},
            )

        self.assertEqual(result["answer"], WRITE_REJECT_ANSWER)
        self.assertTrue(result["ok"])


@override_settings(AI_AGENT_ENABLED=True)
class RateLimitTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="rate-limit-ai",
            password="x",
            role=Role.objects.get(code=Role.Code.SUPERVISOR),
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.cache_key = _rate_limit_key(self.user)
        cache.delete(self.cache_key)
        self.addCleanup(cache.delete, self.cache_key)

        self.patches = [
            patch(
                "integrations.ai_agent.api.views.intent_classifier.classify",
                return_value={
                    "intent": "GENERAL_CHAT",
                    "confidence": 0.8,
                    "tokens": 1,
                },
            ),
            patch(
                "integrations.ai_agent.api.views.context_builder.build_context",
                return_value={
                    "intent": "GENERAL_CHAT",
                    "message": "halo",
                    "context": {},
                    "tools": [],
                    "metrics": [],
                },
            ),
            patch(
                "integrations.ai_agent.api.views.response_synthesizer.synthesize",
                return_value={
                    "ok": True,
                    "answer": "Jawaban uji.",
                    "tokens": {"prompt": 1, "completion": 1, "total_cost_usd": 0},
                    "model": "mock",
                    "latency_ms": 1,
                },
            ),
            patch(
                "integrations.analytics.services.analytics_config_services.analytics_enabled",
                return_value=True,
            ),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def _post(self):
        return self.client.post(
            "/api/v1/ai/chat", {"message": "halo rate limit"}, format="json"
        )

    def test_60_request_per_menit_200(self):
        for _ in range(RATE_LIMIT_PER_MINUTE):
            response = self._post()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(cache.get(self.cache_key), RATE_LIMIT_PER_MINUTE)

    def test_61_request_per_menit_429(self):
        for _ in range(RATE_LIMIT_PER_MINUTE):
            self._post()

        response = self._post()

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["error"], "rate_limited")
        self.assertEqual(response.json()["retry_after_s"], 60)

