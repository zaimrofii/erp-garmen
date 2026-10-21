"""Test LLM wrapper (G.1) — mock httpx, tanpa API nyata."""

from __future__ import annotations

from unittest.mock import patch

import httpx
from django.test import SimpleTestCase, override_settings

from integrations.ai_agent.llm_wrapper.base import LLMError
from integrations.ai_agent.llm_wrapper.deepseek import DeepSeekProvider
from integrations.ai_agent.llm_wrapper.factory import get_llm_provider
from integrations.ai_agent.llm_wrapper.gemini import GeminiProvider

DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"


class _FakeResponse:
    def __init__(self, status_code: int = 200, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=httpx.Request("POST", DEEPSEEK_URL),
                response=httpx.Response(
                    self.status_code, request=httpx.Request("POST", DEEPSEEK_URL)
                ),
            )

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, response=None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.last_url = None
        self.last_headers = None
        self.last_json = None

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def post(self, url, headers=None, json=None):
        self.last_url = url
        self.last_headers = headers
        self.last_json = json
        if self.error is not None:
            raise self.error
        return self.response or _FakeResponse()


def _ok_payload(text="Scrap naik 2%.", prompt=1000, completion=500):
    return {
        "choices": [{"message": {"content": text}}],
        "usage": {"prompt_tokens": prompt, "completion_tokens": completion},
    }


@override_settings(AI_LLM_API_KEY="test-key", AI_LLM_MODEL="deepseek-chat")
class DeepSeekProviderTests(SimpleTestCase):
    def test_success_dan_payload(self):
        client = _FakeClient(_FakeResponse(payload=_ok_payload()))
        with patch(
            "integrations.ai_agent.llm_wrapper.deepseek.httpx.Client",
            return_value=client,
        ):
            result = DeepSeekProvider().complete("system", "user", max_tokens=123)

        self.assertEqual(result.text, "Scrap naik 2%.")
        self.assertEqual(result.prompt_tokens, 1000)
        self.assertEqual(result.completion_tokens, 500)
        self.assertEqual(result.model, "deepseek-chat")
        self.assertGreaterEqual(result.latency_ms, 0)
        self.assertEqual(client.last_url, DEEPSEEK_URL)
        self.assertEqual(client.last_headers["Authorization"], "Bearer test-key")
        self.assertEqual(client.last_json["max_tokens"], 123)
        self.assertEqual(client.last_json["messages"][0]["role"], "system")

    def test_cost_dihitung_benar(self):
        client = _FakeClient(
            _FakeResponse(payload=_ok_payload(prompt=1000, completion=500))
        )
        with patch(
            "integrations.ai_agent.llm_wrapper.deepseek.httpx.Client",
            return_value=client,
        ):
            result = DeepSeekProvider().complete("s", "u")

        # 1K prompt * 0.00014 + 0.5K completion * 0.00028 = 0.00028
        self.assertAlmostEqual(result.total_cost_usd, 0.00028, places=8)
        self.assertEqual(result.raw["usage"]["prompt_tokens"], 1000)

    @override_settings(AI_LLM_API_KEY="")
    def test_tanpa_api_key(self):
        with self.assertRaises(LLMError) as ctx:
            DeepSeekProvider().complete("s", "u")

        self.assertEqual(ctx.exception.code, "no_api_key")

    def test_http_401(self):
        client = _FakeClient(_FakeResponse(status_code=401))
        with patch(
            "integrations.ai_agent.llm_wrapper.deepseek.httpx.Client",
            return_value=client,
        ):
            with self.assertRaises(LLMError) as ctx:
                DeepSeekProvider().complete("s", "u")

        self.assertEqual(ctx.exception.code, "http_error")
        self.assertIn("401", ctx.exception.message)

    def test_timeout(self):
        client = _FakeClient(error=httpx.TimeoutException("timeout"))
        with patch(
            "integrations.ai_agent.llm_wrapper.deepseek.httpx.Client",
            return_value=client,
        ):
            with self.assertRaises(LLMError) as ctx:
                DeepSeekProvider().complete("s", "u")

        self.assertEqual(ctx.exception.code, "timeout")

    def test_network_error(self):
        client = _FakeClient(error=httpx.ConnectError("boom"))
        with patch(
            "integrations.ai_agent.llm_wrapper.deepseek.httpx.Client",
            return_value=client,
        ):
            with self.assertRaises(LLMError) as ctx:
                DeepSeekProvider().complete("s", "u")

        self.assertEqual(ctx.exception.code, "network_error")

    def test_respons_malformed(self):
        client = _FakeClient(_FakeResponse(payload={"choices": []}))
        with patch(
            "integrations.ai_agent.llm_wrapper.deepseek.httpx.Client",
            return_value=client,
        ):
            with self.assertRaises(LLMError) as ctx:
                DeepSeekProvider().complete("s", "u")

        self.assertEqual(ctx.exception.code, "malformed_response")


@override_settings(AI_LLM_API_KEY="test-key")
class FactoryTests(SimpleTestCase):
    @override_settings(AI_LLM_PROVIDER="deepseek")
    def test_factory_deepseek(self):
        self.assertIsInstance(get_llm_provider(), DeepSeekProvider)

    @override_settings(AI_LLM_PROVIDER="gemini")
    def test_factory_gemini(self):
        self.assertIsInstance(get_llm_provider(), GeminiProvider)

    @override_settings(AI_LLM_PROVIDER="tidak-ada")
    def test_factory_provider_tidak_dikenal(self):
        with self.assertRaises(ValueError):
            get_llm_provider()


@override_settings(AI_LLM_API_KEY="test-key", AI_LLM_MODEL="gemini-2.0-flash")
class GeminiProviderTests(SimpleTestCase):
    def test_success_dan_cost(self):
        payload = {
            "candidates": [
                {"content": {"parts": [{"text": "Jawaban "}, {"text": "Gemini"}]}}
            ],
            "usageMetadata": {"promptTokenCount": 1000, "candidatesTokenCount": 500},
        }
        client = _FakeClient(_FakeResponse(payload=payload))
        with patch(
            "integrations.ai_agent.llm_wrapper.gemini.httpx.Client",
            return_value=client,
        ):
            result = GeminiProvider().complete("system", "user", max_tokens=99)

        self.assertEqual(result.text, "Jawaban Gemini")
        self.assertEqual(result.model, "gemini-2.0-flash")
        self.assertEqual(result.prompt_tokens, 1000)
        self.assertEqual(result.completion_tokens, 500)
        self.assertAlmostEqual(result.total_cost_usd, 0.00028, places=8)
        self.assertIn("x-goog-api-key", client.last_headers)
        self.assertEqual(client.last_json["generationConfig"]["maxOutputTokens"], 99)

    @override_settings(AI_LLM_API_KEY="", AI_LLM_GEMINI_API_KEY="")
    def test_tanpa_api_key(self):
        with self.assertRaises(LLMError) as ctx:
            GeminiProvider().complete("s", "u")

        self.assertEqual(ctx.exception.code, "no_api_key")

    def test_respons_kosong(self):
        payload = {"candidates": [{"content": {"parts": [{"text": ""}]}}]}
        client = _FakeClient(_FakeResponse(payload=payload))
        with patch(
            "integrations.ai_agent.llm_wrapper.gemini.httpx.Client",
            return_value=client,
        ):
            with self.assertRaises(LLMError) as ctx:
                GeminiProvider().complete("s", "u")

        self.assertEqual(ctx.exception.code, "empty_response")
