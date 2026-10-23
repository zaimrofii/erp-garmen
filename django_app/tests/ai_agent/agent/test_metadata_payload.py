"""Test bugfix: metadata hanya di final (tidak dikirim ke LLM) + validator metadata."""

from __future__ import annotations

import json

import pytest

from integrations.ai_agent.agent.loop import run_agent
from integrations.ai_agent.agent.validator import validate_answer
from integrations.ai_agent.llm_wrapper.base import LLMResponse
from integrations.ai_agent.tools.base import ToolResult


class FakeProvider:
    def __init__(self, responses):
        self.responses = responses
        self.calls = 0
        self.tool_messages: list[str] = []

    def chat(self, messages, tools=None, max_tokens=1000):
        for item in messages:
            if item.get("role") == "tool":
                self.tool_messages.append(item.get("content") or "")
        index = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        return self.responses[index]


def _response(text="", tool_calls=None):
    return LLMResponse(
        text=text, prompt_tokens=5, completion_tokens=5, total_cost_usd=0.0,
        model="fake", latency_ms=1, raw={}, tool_calls=tool_calls or [],
    )


def _messages(text="Berapa order?"):
    return [{"role": "system", "content": "s"}, {"role": "user", "content": text}]


def _tool_call(index: int):
    return {"id": f"c{index}", "name": "count_records", "arguments": {"entity": "order"}}


@pytest.mark.django_db
def test_metadata_tidak_dikirim_ke_llm():
    provider = FakeProvider(
        [
            _response(tool_calls=[_tool_call(1)]),
            _response(tool_calls=[_tool_call(2)]),
            _response("Ada 0 order."),
        ]
    )
    result = run_agent(_messages(), "SUPERVISOR", config={"provider": provider})
    assert provider.tool_messages
    for content in provider.tool_messages:
        assert "metadata" not in content
    assert result.tool_metadata and result.tool_metadata[0].get("source") == "MES"


@pytest.mark.django_db
def test_payload_lebih_kecil_40_persen():
    heavy = ToolResult.success(
        {"rows": [{"value": 1}] * 3},
        row_count=3,
        metadata={
            "metric": "count",
            "dimension": "order",
            "definition": "jumlah baris order pada periode ini",
            "period": "all-time",
            "source": "MES",
        },
    )
    old = json.dumps(heavy.to_dict(), default=str)
    new = json.dumps(
        {
            "ok": True,
            "error": None,
            "data": heavy.data,
            "row_count": heavy.row_count,
            "warnings": heavy.warnings,
        },
        default=str,
    )
    assert len(new) <= len(old) * 0.6


def test_validator_terima_angka_metadata():
    trace = [
        {
            "tool": "list_records",
            "row_count": 5,
            "result": {"rows": []},
            "metadata": {
                "metric": "rows",
                "dimension": "order",
                "definition": "daftar order",
                "period": "all-time",
                "source": "MES",
                "row_count": 5,
            },
        }
    ]
    assert validate_answer("5 bundle", trace)["ok"] is True
