"""Test response synthesizer (G.3) — mock LLM, tanpa API nyata."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from integrations.ai_agent.llm_wrapper.base import LLMError
from integrations.ai_agent.orchestrator import response_synthesizer

MODULE = "integrations.ai_agent.orchestrator.response_synthesizer"


class _FakeProvider:
    def __init__(self, text="Scrap naik 2% dibanding minggu lalu.", error=None):
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
            prompt_tokens=120,
            completion_tokens=30,
            total_cost_usd=0.0000252,
            model="deepseek-chat",
            latency_ms=850,
            raw={},
        )


def _context_data():
    return {
        "intent": "ANALYTICS_QUERY",
        "message": "kenapa scrap naik?",
        "context": {"page_type": "dashboard"},
        "tools": ["mcp-analytics"],
        "metrics": [
            {
                "metric_id": "garment.scrap_rate",
                "unit": "%",
                "rows": [{"period": "2026-10-19", "value": 4.2}],
            }
        ],
    }


class ResponseSynthesizerTests(SimpleTestCase):
    def test_success_mengembalikan_answer_dan_token(self):
        provider = _FakeProvider()
        with patch(f"{MODULE}.get_llm_provider", return_value=provider):
            result = response_synthesizer.synthesize("kenapa scrap naik?", _context_data())

        self.assertTrue(result["ok"])
        self.assertEqual(result["answer"], "Scrap naik 2% dibanding minggu lalu.")
        self.assertEqual(
            result["tokens"],
            {"prompt": 120, "completion": 30, "total_cost_usd": 0.0000252},
        )
        self.assertEqual(result["model"], "deepseek-chat")
        self.assertEqual(result["latency_ms"], 850)

    def test_context_injection_masuk_prompt(self):
        provider = _FakeProvider()
        with patch(f"{MODULE}.get_llm_provider", return_value=provider):
            response_synthesizer.synthesize("kenapa scrap naik?", _context_data())

        prompt = provider.last_kwargs["user_prompt"]
        self.assertIn("kenapa scrap naik?", prompt)
        self.assertIn("DATA DARI SISTEM", prompt)
        self.assertIn("garment.scrap_rate", prompt)
        self.assertIn("4.2", prompt)
        self.assertIn("dashboard", prompt)
        self.assertNotIn('"tools"', prompt)
        self.assertEqual(provider.last_kwargs["max_tokens"], 500)

    def test_system_prompt_read_only(self):
        provider = _FakeProvider()
        with patch(f"{MODULE}.get_llm_provider", return_value=provider):
            response_synthesizer.synthesize("halo", _context_data())

        system_prompt = provider.last_kwargs["system_prompt"]
        self.assertIn("JANGAN menyarankan write action", system_prompt)
        self.assertIn("JANGAN mengarang data", system_prompt)

    def test_llm_error_rapi(self):
        provider = _FakeProvider(error=LLMError("LLM timeout", "timeout"))
        with patch(f"{MODULE}.get_llm_provider", return_value=provider):
            result = response_synthesizer.synthesize("scrap?", _context_data())

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "llm_failed")
        self.assertEqual(result["code"], "timeout")
        self.assertEqual(result["detail"], "LLM timeout")
        self.assertEqual(
            result["tokens"], {"prompt": 0, "completion": 0, "total_cost_usd": 0}
        )

    def test_exception_generik_rapi(self):
        provider = _FakeProvider(error=RuntimeError("boom"))
        with patch(f"{MODULE}.get_llm_provider", return_value=provider):
            result = response_synthesizer.synthesize("scrap?", _context_data())

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "llm_failed")
        self.assertEqual(result["code"], "llm_error")
        self.assertEqual(result["detail"], "boom")

    def test_message_kosong_tidak_memanggil_llm(self):
        provider = _FakeProvider()
        with patch(f"{MODULE}.get_llm_provider", return_value=provider):
            result = response_synthesizer.synthesize("   ", _context_data())

        self.assertEqual(result["error"], "empty_message")
        self.assertIsNone(provider.last_kwargs)

    def test_context_none_ditolak(self):
        provider = _FakeProvider()
        with patch(f"{MODULE}.get_llm_provider", return_value=provider):
            result = response_synthesizer.synthesize("scrap?", None)

        self.assertEqual(result["error"], "empty_context")
        self.assertIsNone(provider.last_kwargs)

    def test_context_tanpa_message_ditolak(self):
        provider = _FakeProvider()
        with patch(f"{MODULE}.get_llm_provider", return_value=provider):
            result = response_synthesizer.synthesize("scrap?", {"intent": "UNKNOWN"})

        self.assertEqual(result["error"], "empty_context")
        self.assertIsNone(provider.last_kwargs)

    def test_token_none_dinormalisasi_nol(self):
        provider = _FakeProvider()
        provider.complete = lambda **kwargs: SimpleNamespace(
            text="ok",
            prompt_tokens=None,
            completion_tokens=None,
            total_cost_usd=None,
            model="mock",
            latency_ms=None,
            raw={},
        )
        with patch(f"{MODULE}.get_llm_provider", return_value=provider):
            result = response_synthesizer.synthesize("scrap?", _context_data())

        self.assertEqual(
            result["tokens"], {"prompt": 0, "completion": 0, "total_cost_usd": 0.0}
        )
        self.assertEqual(result["latency_ms"], 0)
