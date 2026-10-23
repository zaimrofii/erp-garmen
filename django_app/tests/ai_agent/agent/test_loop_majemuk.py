"""Test Perbaikan #2: pertanyaan majemuk tidak langsung jatuh ke fallback."""

from __future__ import annotations

import pytest

from integrations.ai_agent.agent import loop as loop_module
from integrations.ai_agent.agent.loop import run_agent
from integrations.ai_agent.llm_wrapper.base import LLMResponse
from integrations.ai_agent.tools.base import ToolResult


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
    return [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "Total order aktif dan order paling lambat?"},
    ]


@pytest.mark.django_db
def test_empat_filter_berbeda_tidak_fallback(monkeypatch):
    # Batas same_tool_limit = 5 -> 4 filter berbeda masih boleh lanjut menjawab.
    filters = ["ACTIVE", "DRAFT", "CONFIRMED", "IN_PROGRESS"]
    responses = [
        _response(tool_calls=[_list_call(index, {"state": state})])
        for index, state in enumerate(filters)
    ] + [_response("Order aktif dan order paling lambat sudah saya rangkum.")]
    provider = FakeProvider(responses)
    result = run_agent(
        _messages(), "SUPERVISOR", config={"provider": provider, "max_iterations": 8}
    )
    assert result.blocked_reason is None
    assert "sudah saya rangkum" in result.answer
    assert len(result.tool_calls) == 4


def test_dua_filter_data_sama_paksa_jawab(monkeypatch):
    # Model berputar: filter beda, data identik -> berhenti dengan jawaban parsial.
    monkeypatch.setattr(
        loop_module,
        "execute_tool",
        lambda name, args, role, user=None: ToolResult(
            data={"rows": [{"id": 1}], "total": 1}, row_count=1
        ),
    )
    responses = [
        _response(tool_calls=[_list_call(1, {"state": "ACTIVE"})]),
        _response(tool_calls=[_list_call(2, {"state": "DRAFT"})]),
        _response("seharusnya tidak dipakai"),
    ]
    provider = FakeProvider(responses)
    result = run_agent(
        _messages(), "SUPERVISOR", config={"provider": provider, "max_iterations": 8}
    )
    assert result.blocked_reason == "duplicate_tool_result"
    assert "beberapa bagian" in result.answer
    assert provider.calls == 2


def test_lima_filter_data_beda_fallback_pesan_bagian(monkeypatch):
    # Data terus berbeda -> kena same_tool_limit dengan pesan parsial.
    counter = {"n": 0}

    def _fake_execute(name, args, role, user=None):
        counter["n"] += 1
        return ToolResult(data={"rows": [counter["n"]]}, row_count=counter["n"])

    monkeypatch.setattr(loop_module, "execute_tool", _fake_execute)
    states = ["ACTIVE", "DRAFT", "CONFIRMED", "IN_PROGRESS", "DONE"]
    responses = [
        _response(tool_calls=[_list_call(index, {"state": state})])
        for index, state in enumerate(states)
    ]
    provider = FakeProvider(responses)
    result = run_agent(
        _messages(), "SUPERVISOR", config={"provider": provider, "max_iterations": 8}
    )
    assert result.blocked_reason == "same_tool_limit"
    assert "beberapa bagian" in result.answer
    assert provider.calls == 5
