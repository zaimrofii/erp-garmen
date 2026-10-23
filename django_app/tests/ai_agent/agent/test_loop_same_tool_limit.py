"""Test batas tool yang sama (same_tool_limit) untuk Q8."""

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


def _list_call(index: int, filters: dict) -> dict:
    return {
        "id": f"c{index}",
        "name": "list_records",
        "arguments": {"entity": "order", "filters": filters},
    }


def _messages():
    return [{"role": "system", "content": "s"}, {"role": "user", "content": "Order mana paling telat?"}]


@pytest.mark.django_db
def test_tool_sama_tiga_kali_berhenti():
    responses = [
        _response(tool_calls=[_list_call(index, {"state": state})])
        for index, state in enumerate(["CONFIRMED", "IN_PROGRESS", "DRAFT", "DONE"])
    ]
    provider = FakeProvider(responses)
    result = run_agent(_messages(), "SUPERVISOR", config={"provider": provider, "max_iterations": 8})
    assert result.blocked_reason == "same_tool_limit"
    assert "beberapa filter" in result.answer
    assert provider.calls == 3


@pytest.mark.django_db
def test_dua_kali_lalu_jawab_tidak_kena_limit():
    responses = [
        _response(tool_calls=[_list_call(1, {"state": "CONFIRMED"})]),
        _response(tool_calls=[_list_call(2, {"state": "IN_PROGRESS"})]),
        _response("Tidak ada order yang telat."),
    ]
    provider = FakeProvider(responses)
    result = run_agent(_messages(), "SUPERVISOR", config={"provider": provider, "max_iterations": 8})
    assert result.blocked_reason is None
    assert result.answer == "Tidak ada order yang telat."
