"""Test row_count masuk ke metadata trace (fix Q1 '5 produk')."""

from __future__ import annotations

import pytest

from integrations.ai_agent.agent.loop import run_agent
from integrations.ai_agent.agent.validator import validate_answer
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


@pytest.mark.django_db
def test_row_count_ada_di_metadata_trace():
    provider = FakeProvider(
        [
            _response(
                tool_calls=[
                    {"id": "c1", "name": "list_records", "arguments": {"entity": "product", "limit": 5}}
                ]
            ),
            _response("5 produk termahal: 1. Jaket Bomber Rp250.000"),
        ]
    )
    result = run_agent(
        [{"role": "system", "content": "s"}, {"role": "user", "content": "Produk termahal apa?"}],
        "SUPERVISOR",
        config={"provider": provider},
    )
    assert result.tool_calls
    assert result.tool_calls[0]["metadata"]["row_count"] == result.tool_calls[0]["row_count"]


def test_jawaban_jumlah_produk_lulus():
    trace = [
        {
            "tool": "list_records",
            "row_count": 5,
            "result": {"rows": [{"sale_price": "250000.00"}] * 5},
            "metadata": {
                "metric": "rows",
                "dimension": "product",
                "definition": "daftar produk",
                "period": "all-time",
                "source": "MES",
                "row_count": 5,
            },
        }
    ]
    assert validate_answer("5 produk termahal: 1. Jaket Bomber Rp250.000", trace)["ok"] is True
