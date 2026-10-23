"""Test fallback loop (demo-ready): max_iterations & repeated tool call."""

from __future__ import annotations

import pytest

from integrations.ai_agent.agent.loop import run_agent
from integrations.ai_agent.llm_wrapper.base import LLMResponse


class FakeProvider:
    def __init__(self, responses):
        self.responses = responses
        self.calls = 0

    def chat(self, messages, tools=None, max_tokens=1000):
        index = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        return self.responses[index]


def _response(text="", tool_calls=None):
    return LLMResponse(
        text=text, prompt_tokens=5, completion_tokens=5, total_cost_usd=0.0,
        model="fake", latency_ms=1, raw={}, tool_calls=tool_calls or [],
    )


def _call(name="count_records", args=None, call_id="c"):
    return {"id": call_id, "name": name, "arguments": args or {"entity": "order"}}


def _messages(text="Berapa order?"):
    return [{"role": "system", "content": "s"}, {"role": "user", "content": text}]


@pytest.mark.django_db
def test_max_iterations_memberi_fallback_bukan_empty():
    # Argumen berbeda tiap putaran agar tidak memicu deteksi repeated_tool_call.
    responses = [
        _response(tool_calls=[_call(args={"entity": entity}, call_id=f"c{index}")])
        for index, entity in enumerate(["order", "bundle", "product", "customer"])
    ]
    provider = FakeProvider(responses)
    result = run_agent(_messages(), "SUPERVISOR", config={"provider": provider, "max_iterations": 3})
    assert result.error == "max_iterations"
    assert result.blocked_reason == "max_iterations"
    assert result.answer.strip() != ""
    assert "belum bisa menyimpulkan" in result.answer
    assert "count_records" in result.answer


@pytest.mark.django_db
def test_tool_sama_tiga_kali_break_dengan_fallback():
    same = _response(tool_calls=[_call(args={"entity": "order"})])
    provider = FakeProvider([same])
    result = run_agent(_messages(), "SUPERVISOR", config={"provider": provider, "max_iterations": 8})
    assert result.blocked_reason == "repeated_tool_call"
    assert result.answer.strip() != ""
    assert provider.calls == 3
