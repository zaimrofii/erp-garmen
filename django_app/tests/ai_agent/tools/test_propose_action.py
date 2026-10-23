"""Test propose_action → AIHitlQueue (tidak mengeksekusi apa pun)."""

from __future__ import annotations

import pytest

from apps_industry.garment.models import Order
from core.auth.models import Role, User
from integrations.ai_agent.models import AIHitlQueue
from integrations.ai_agent.tools import TOOLS, execute_tool
from integrations.ai_agent.tools import propose_action as tool


@pytest.mark.django_db
def test_propose_action_menulis_ke_hitl_tanpa_mengubah_data():
    before = Order.objects.count()
    result = tool.run("rework", "bundle", "BDL-001", reason="scrap tinggi", confidence=0.8)
    assert result.ok
    assert result.data["status"] == "PENDING"
    queue = AIHitlQueue.objects.get(pk=result.data["hitl_id"])
    assert queue.status == "PENDING"
    assert queue.proposed_action["action_type"] == "rework"
    assert queue.required_approver_role == "SUPERVISOR"
    assert Order.objects.count() == before


@pytest.mark.django_db
def test_propose_action_action_type_tidak_dikenal():
    with pytest.raises(ValueError):
        tool.run("hapus_semua", "order", "SO-1")


@pytest.mark.django_db
def test_propose_action_hanya_supervisor_plus():
    roles = TOOLS["propose_action"].roles
    assert roles == {"SUPERVISOR", "ADMIN", "OWNER"}
    result = execute_tool("propose_action", {"action_type": "audit", "entity_type": "order", "entity_id": "SO-1"}, "OPERATOR")
    assert result.error == "forbidden"


@pytest.mark.django_db
def test_execute_tool_propose_action_menyimpan_user():
    supervisor = User.objects.create_user(
        username="sup-propose", password="x", role=Role.objects.get(code=Role.Code.SUPERVISOR)
    )
    result = execute_tool(
        "propose_action",
        {"action_type": "stop", "entity_type": "work_center", "entity_id": "SEWING-2"},
        "SUPERVISOR",
        supervisor,
    )
    assert result.ok
    queue = AIHitlQueue.objects.get(pk=result.data["hitl_id"])
    assert queue.decision_log.user_id == supervisor.pk
