"""Test dukungan `tools` di LLM wrapper (Fase 1) — mock httpx, tanpa API nyata."""

from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from integrations.ai_agent.llm_wrapper.base import LLMError
from integrations.ai_agent.llm_wrapper.deepseek import DeepSeekProvider
from integrations.ai_agent.llm_wrapper.gemini import GeminiProvider

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "count_records",
            "description": "hitung baris",
            "parameters": {"type": "object", "properties": {"entity": {"type": "string"}}},
        },
    }
]


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, payload: dict):
        self.payload = payload
        self.last_json = None

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def post(self, url, headers=None, json=None):
        self.last_json = json
        return _FakeResponse(self.payload)


def _payload(message: dict, prompt: int = 100, completion: int = 50) -> dict:
    return {
        "choices": [{"message": message}],
        "usage": {"prompt_tokens": prompt, "completion_tokens": completion},
    }


@override_settings(AI_LLM_API_KEY="test-key", AI_LLM_MODEL="deepseek-chat")
class DeepSeekToolsTests(SimpleTestCase):
    def test_payload_mengirim_tools(self):
        client = _FakeClient(_payload({"content": "Halo"}))
        with patch(
            "integrations.ai_agent.llm_wrapper.deepseek.httpx.Client",
            return_value=client,
        ):
            DeepSeekProvider().chat(
                [{"role": "user", "content": "berapa order?"}], tools=TOOLS
            )
        assert client.last_json["tools"] == TOOLS
        assert client.last_json["tool_choice"] == "auto"

    def test_complete_tanpa_tools_tidak_menambah_key(self):
        client = _FakeClient(_payload({"content": "Halo"}))
        with patch(
            "integrations.ai_agent.llm_wrapper.deepseek.httpx.Client",
            return_value=client,
        ):
            DeepSeekProvider().complete("system", "user")
        assert "tools" not in client.last_json

    def test_tool_calls_diparse(self):
        message = {
            "content": None,
            "tool_calls": [
                {
                    "id": "call_abc",
                    "type": "function",
                    "function": {
                        "name": "count_records",
                        "arguments": '{"entity": "order"}',
                    },
                }
            ],
        }
        client = _FakeClient(_payload(message))
        with patch(
            "integrations.ai_agent.llm_wrapper.deepseek.httpx.Client",
            return_value=client,
        ):
            response = DeepSeekProvider().chat(
                [{"role": "user", "content": "x"}], tools=TOOLS
            )
        assert response.tool_calls == [
            {"id": "call_abc", "name": "count_records", "arguments": {"entity": "order"}}
        ]
        assert response.text == ""


@override_settings(AI_LLM_API_KEY="test-key", AI_LLM_MODEL="gemini-2.0-flash")
class GeminiToolsTests(SimpleTestCase):
    def test_gemini_tools_provider_not_supported(self):
        with self.assertRaises(LLMError) as ctx:
            GeminiProvider().chat([{"role": "user", "content": "x"}], tools=TOOLS)
        self.assertEqual(ctx.exception.code, "provider_not_supported")
