"""Test history asli + klarifikasi find_entity ambigu (Fase 2)."""

from __future__ import annotations

import pytest

from apps_industry.garment.models import WorkCenter
from core.auth.models import Role, User
from integrations.ai_agent.agent.loop import run_agent
from integrations.ai_agent.llm_wrapper.base import LLMResponse


class FakeProvider:
    def __init__(self, responses: list[LLMResponse]):
        self.responses = responses
        self.calls: list[dict] = []

    def chat(self, messages, tools=None, max_tokens=1000):
        self.calls.append({"messages": list(messages), "tools": tools})
        index = min(len(self.calls) - 1, len(self.responses) - 1)
        return self.responses[index]


def _response(text: str = "", tool_calls: list | None = None) -> LLMResponse:
    return LLMResponse(
        text=text,
        prompt_tokens=10,
        completion_tokens=5,
        total_cost_usd=0.0001,
        model="fake",
        latency_ms=1,
        raw={},
        tool_calls=tool_calls or [],
    )


def _messages(text: str = "Berapa order?") -> list[dict]:
    return [
        {"role": "system", "content": "system"},
        {"role": "user", "content": text},
    ]


@pytest.mark.django_db
def test_history_lima_turn_dikirim_ke_llm():
    history = []
    for turn in range(5):
        history.append({"role": "user", "content": f"pertanyaan {turn}"})
        history.append({"role": "assistant", "content": f"jawaban {turn}"})
    provider = FakeProvider([_response("Halo, ada yang bisa dibantu?")])
    run_agent(_messages(), "SUPERVISOR", config={"provider": provider}, history=history)

    sent = provider.calls[0]["messages"]
    assert sent[0]["role"] == "system"
    contents = [item["content"] for item in sent]
    for turn in range(5):
        assert f"pertanyaan {turn}" in contents
        assert f"jawaban {turn}" in contents
    assert contents.index("pertanyaan 0") < contents.index("pertanyaan 4")
    assert sent[-1]["content"] == "Berapa order?"


@pytest.mark.django_db
def test_history_maksimal_sepuluh_turn():
    history = [
        {"role": "user" if index % 2 == 0 else "assistant", "content": f"turn-{index}"}
        for index in range(14)
    ]
    provider = FakeProvider([_response("Halo")])
    run_agent(_messages(), "SUPERVISOR", config={"provider": provider}, history=history)
    contents = [item["content"] for item in provider.calls[0]["messages"]]
    assert "turn-0" not in contents
    assert "turn-13" in contents


@pytest.mark.django_db
def test_find_entity_ambigu_memicu_klarifikasi_tanpa_tool_lain():
    WorkCenter.objects.create(code="SEWING-1", name="Sewing 1")
    WorkCenter.objects.create(code="SEWING-2", name="Sewing 2")
    provider = FakeProvider(
        [
            _response(
                tool_calls=[
                    {"id": "c1", "name": "find_entity", "arguments": {"entity": "work_center", "text": "SEWING"}}
                ]
            )
        ]
    )
    result = run_agent(
        _messages("bundle di sewing berapa?"),
        "SUPERVISOR",
        config={"provider": provider},
        history=[],
    )
    assert result.clarification is not None
    assert len(result.clarification["matches"]) == 2
    assert "2 kandidat" in result.answer
    assert len(provider.calls) == 1
    assert len(result.tool_calls) == 1


@pytest.mark.django_db
def test_user_jawab_yang_pertama_melanjutkan():
    WorkCenter.objects.create(code="SEWING-1", name="Sewing 1")
    WorkCenter.objects.create(code="SEWING-2", name="Sewing 2")
    user = User.objects.create_user(
        username="sup-clarify", password="x", role=Role.objects.get(code=Role.Code.SUPERVISOR)
    )
    config = {"user_id": user.pk, "session_id": "sess-klarifikasi"}

    first = FakeProvider(
        [
            _response(
                tool_calls=[
                    {"id": "c1", "name": "find_entity", "arguments": {"entity": "work_center", "text": "SEWING"}}
                ]
            )
        ]
    )
    run_agent(
        _messages("bundle di sewing berapa?"),
        "SUPERVISOR",
        user,
        config={"provider": first, **config},
    )

    second = FakeProvider([_response("Halo, ada yang bisa dibantu?")])
    run_agent(
        _messages("yang pertama"),
        "SUPERVISOR",
        user,
        config={"provider": second, **config},
    )
    contents = [item["content"] for item in second.calls[0]["messages"]]
    assert any("Pengguna memilih kandidat" in content for content in contents)
