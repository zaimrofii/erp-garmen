"""Test agent loop (Fase 1) — provider palsu, tanpa panggilan LLM nyata."""

from __future__ import annotations

import pytest

from integrations.ai_agent.agent.loop import run_agent
from integrations.ai_agent.llm_wrapper.base import LLMResponse


class FakeProvider:
    """Provider skrip: setiap `chat` mengembalikan respons berikutnya."""

    def __init__(self, responses: list[LLMResponse]):
        self.responses = responses
        self.calls: list[dict] = []

    def chat(self, messages, tools=None, max_tokens=1000):
        self.calls.append({"messages": list(messages), "tools": tools, "max_tokens": max_tokens})
        index = min(len(self.calls) - 1, len(self.responses) - 1)
        return self.responses[index]


def _response(text: str = "", tool_calls: list | None = None, cost: float = 0.0001) -> LLMResponse:
    return LLMResponse(
        text=text,
        prompt_tokens=100,
        completion_tokens=20,
        total_cost_usd=cost,
        model="fake",
        latency_ms=1,
        raw={},
        tool_calls=tool_calls or [],
    )


def _call(name: str, call_id: str, arguments: dict) -> dict:
    return {"id": call_id, "name": name, "arguments": arguments}


def _messages() -> list[dict]:
    return [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "Berapa jumlah order?"},
    ]


@pytest.mark.django_db
def test_loop_jawab_langsung_satu_iterasi():
    provider = FakeProvider([_response("Halo, ada yang bisa dibantu?")])
    result = run_agent(_messages(), "SUPERVISOR", config={"provider": provider})
    assert result.error is None
    assert result.iterations == 1
    assert result.tool_calls == []
    assert result.answer == "Halo, ada yang bisa dibantu?"
    assert len(provider.calls) == 1
    assert provider.calls[0]["tools"], "tool schema harus dikirim ke LLM"


@pytest.mark.django_db
def test_loop_dua_tool_lalu_jawab():
    provider = FakeProvider(
        [
            _response(tool_calls=[_call("count_records", "c1", {"entity": "order"})]),
            _response(tool_calls=[_call("count_records", "c2", {"entity": "order"})]),
            _response("Jumlahnya 0 order."),
        ]
    )
    result = run_agent(_messages(), "SUPERVISOR", config={"provider": provider})
    assert result.error is None
    assert result.iterations == 3
    assert len(result.tool_calls) == 2
    assert all(call["tool"] == "count_records" for call in result.tool_calls)
    assert all(call["executed"] for call in result.tool_calls)
    assert result.tokens["prompt"] == 300
    assert result.cost_usd > 0


@pytest.mark.django_db
def test_loop_max_iterations():
    looping = _response(tool_calls=[_call("count_records", "c", {"entity": "order"})])
    provider = FakeProvider([looping])
    result = run_agent(
        _messages(), "SUPERVISOR", config={"provider": provider, "max_iterations": 5}
    )
    assert result.error == "max_iterations"
    assert result.iterations == 5
    assert result.answer == ""
    assert len(provider.calls) == 5


@pytest.mark.django_db
def test_loop_role_operator_tidak_dapat_tool_metric():
    provider = FakeProvider([_response("ok")])
    run_agent(_messages(), "OPERATOR", config={"provider": provider})
    names = {item["function"]["name"] for item in provider.calls[0]["tools"]}
    assert "get_metric" not in names


@pytest.mark.django_db
def test_loop_validator_memblokir_angka_asing():
    provider = FakeProvider(
        [
            _response(tool_calls=[_call("count_records", "c1", {"entity": "order"})]),
            _response("Ada 999 order."),
        ]
    )
    result = run_agent(_messages(), "SUPERVISOR", config={"provider": provider})
    assert result.validator["ok"] is False
    assert "tidak konsisten" in result.answer
