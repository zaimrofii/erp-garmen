"""Test cache ringkasan L3 (perbaikan 2b)."""

from __future__ import annotations

from django.core.cache import cache

from integrations.ai_agent.agent.memory import SUMMARY_PREFIX, summarize_history
from integrations.ai_agent.llm_wrapper.base import LLMResponse


class FakeProvider:
    def __init__(self, summary: str = "Ringkasan: user membahas produk."):
        self.summary = summary
        self.summary_calls = 0

    def complete(self, system_prompt, user_prompt, max_tokens=1000):
        self.summary_calls += 1
        return LLMResponse(
            text=self.summary, prompt_tokens=10, completion_tokens=5,
            total_cost_usd=0.0, model="fake", latency_ms=1, raw={},
        )


def _history(turns: int) -> list[dict]:
    return [
        {"role": "user" if index % 2 == 0 else "assistant", "content": f"turn-{index}"}
        for index in range(turns)
    ]


def test_history_sama_dipanggil_dua_kali_cache_hit():
    cache.clear()
    provider = FakeProvider()
    first = summarize_history(_history(15), provider=provider, conversation_id="conv-a")
    second = summarize_history(_history(15), provider=provider, conversation_id="conv-a")
    assert provider.summary_calls == 1
    assert first[0]["content"].startswith(SUMMARY_PREFIX)
    assert first == second
    assert len(second) == 11


def test_history_berubah_meringkas_ulang():
    cache.clear()
    provider = FakeProvider()
    summarize_history(_history(15), provider=provider, conversation_id="conv-b")
    summarize_history(_history(16), provider=provider, conversation_id="conv-b")
    assert provider.summary_calls == 2


def test_conversation_berbeda_tidak_berbagi_cache():
    cache.clear()
    provider = FakeProvider()
    summarize_history(_history(15), provider=provider, conversation_id="conv-c")
    summarize_history(_history(15), provider=provider, conversation_id="conv-d")
    assert provider.summary_calls == 2
