"""Test chart di agent loop + memori L3 + history tanpa resolve_followup."""

from __future__ import annotations

import pytest

from integrations.ai_agent.agent.loop import run_agent
from integrations.ai_agent.agent.memory import SUMMARY_PREFIX, summarize_history
from integrations.ai_agent.llm_wrapper.base import LLMResponse


class FakeProvider:
    def __init__(self, responses, summary="Ringkasan: user membahas produk."):
        self.responses = responses
        self.summary = summary
        self.calls = 0
        self.summary_calls = 0

    def chat(self, messages, tools=None, max_tokens=1000):
        index = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        self.last_messages = list(messages)
        return self.responses[index]

    def complete(self, system_prompt, user_prompt, max_tokens=1000):
        self.summary_calls += 1
        return LLMResponse(
            text=self.summary, prompt_tokens=10, completion_tokens=5,
            total_cost_usd=0.0, model="fake", latency_ms=1, raw={},
        )


def _response(text="", tool_calls=None):
    return LLMResponse(
        text=text, prompt_tokens=5, completion_tokens=5, total_cost_usd=0.0,
        model="fake", latency_ms=1, raw={}, tool_calls=tool_calls or [],
    )


def _messages(text="Berapa order?"):
    return [{"role": "system", "content": "s"}, {"role": "user", "content": text}]


def test_summarize_history_15_turn_menjadi_ringkasan_plus_10():
    history = [
        {"role": "user" if index % 2 == 0 else "assistant", "content": f"turn-{index}"}
        for index in range(15)
    ]
    provider = FakeProvider([_response("ok")])
    result = summarize_history(history, max_turns=10, provider=provider)
    assert result[0]["role"] == "system"
    assert result[0]["content"].startswith(SUMMARY_PREFIX)
    assert len(result) == 11  # 1 ringkasan + 10 turn terakhir
    assert result[-1]["content"] == "turn-14"
    assert provider.summary_calls == 1


def test_summarize_history_pendek_tidak_berubah():
    history = [{"role": "user", "content": "halo"}]
    assert summarize_history(history, max_turns=10) == history


@pytest.mark.django_db
def test_history_dikirim_tanpa_merge_followup():
    provider = FakeProvider([_response("Halo")])
    history = [
        {"role": "user", "content": "produk termahal?"},
        {"role": "assistant", "content": "Jaket Bomber Rp250.000"},
    ]
    run_agent(_messages("yang kedua?"), "SUPERVISOR", config={"provider": provider}, history=history)
    contents = [item.get("content") or "" for item in provider.last_messages]
    assert "produk termahal?" in contents
    assert "Jaket Bomber Rp250.000" in contents
    assert all("(follow-up:" not in text for text in contents)
    assert contents[-1] == "yang kedua?"


@pytest.mark.django_db
def test_chart_dibuat_dari_series_get_metric():
    from unittest.mock import patch

    from integrations.ai_agent.tools.base import ToolResult

    fake = ToolResult.success(
        {
            "metric": "garment.lead_time",
            "series": [
                {"key": "2026-10-19", "label": "19 Okt", "value": 0.38},
                {"key": "2026-10-20", "label": "20 Okt", "value": 81.48},
                {"key": "2026-10-21", "label": "21 Okt", "value": 191.86},
            ],
            "stats": {"avg": 91.24, "count": 3},
        },
        row_count=3,
        metadata={
            "metric": "garment.lead_time",
            "dimension": "period",
            "definition": "lead time harian",
            "period": "2026-10-19..2026-10-23",
            "source": "MES",
        },
    )
    provider = FakeProvider(
        [
            _response(
                tool_calls=[
                    {
                        "id": "c1",
                        "name": "get_metric",
                        "arguments": {
                            "name": "garment.lead_time",
                            "range": {"from": "2026-10-19", "to": "2026-10-23"},
                        },
                    }
                ]
            ),
            _response("Rata-rata lead time 91,24 jam."),
        ]
    )
    with patch("integrations.ai_agent.agent.loop.execute_tool", return_value=fake):
        result = run_agent(
            _messages("tren lead time minggu ini?"),
            "SUPERVISOR",
            config={"provider": provider},
        )
    assert result.chart_data is not None
    assert len(result.chart_data.get("data") or []) == 3
