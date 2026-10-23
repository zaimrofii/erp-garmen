"""Test persist raw_answer + validator_reason di AIDecisionLog (pra-demo)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from core.auth.models import Role, User
from integrations.ai_agent.llm_wrapper.base import LLMResponse
from integrations.ai_agent.models import AIDecisionLog

URL = "/api/v1/ai/chat"


class FakeProvider:
    def __init__(self, text="Halo, ada yang bisa dibantu?"):
        self.text = text

    def chat(self, messages, tools=None, max_tokens=1000):
        return LLMResponse(
            text=self.text, prompt_tokens=5, completion_tokens=5, total_cost_usd=0.0,
            model="fake", latency_ms=1, raw={},
        )

    def complete(self, system_prompt, user_prompt, max_tokens=1000):
        return LLMResponse(
            text="ringkasan", prompt_tokens=1, completion_tokens=1, total_cost_usd=0.0,
            model="fake", latency_ms=1, raw={},
        )


@pytest.mark.django_db
def test_log_menyimpan_raw_answer_dan_reason():
    user = User.objects.create_user(
        username="log-supervisor", password="x", role=Role.objects.get(code=Role.Code.SUPERVISOR)
    )
    client = APIClient(SERVER_NAME="localhost")
    client.force_authenticate(user)
    with patch("integrations.ai_agent.agent.loop._provider", return_value=FakeProvider()):
        response = client.post(URL, {"message": "halo"}, format="json")
    assert response.status_code == 200
    log = AIDecisionLog.objects.filter(decision_gate_result="AGENT_TOOLS").latest("timestamp")
    assert log.raw_answer == "Halo, ada yang bisa dibantu?"
    assert log.validator_ok in (True, False)
    assert log.validator_reason != "" or log.validator_ok is True
