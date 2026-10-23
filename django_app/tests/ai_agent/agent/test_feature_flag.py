"""Test feature flag agent tools di endpoint /ai/chat (Fase 1)."""

from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.response import Response
from rest_framework.test import APIClient

from core.auth.models import Role, User

URL = "/api/v1/ai/chat"


class AgentFlagTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.supervisor = User.objects.create_user(
            username="sup-flag",
            password="rahasia123",
            role=Role.objects.get(code=Role.Code.SUPERVISOR),
        )

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.supervisor)
        self.patches = [
            patch("integrations.ai_agent.api.views._is_rate_limited", return_value=False),
            patch(
                "integrations.ai_agent.api.views.handle_pending_clarification",
                return_value=None,
            ),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in self.patches:
            item.stop()

    @override_settings(AI_AGENT_TOOLS_ENABLED=False)
    def test_flag_false_pakai_jalur_lama(self):
        with patch(
            "integrations.ai_agent.api.views.run_pipeline",
            return_value={"result": {"ok": True, "answer": "lama"}},
        ) as legacy:
            response = self.api.post(URL, {"message": "berapa order?"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["answer"], "lama")
        self.assertTrue(legacy.called)

    @override_settings(AI_AGENT_TOOLS_ENABLED=True)
    def test_flag_true_pakai_agent_loop(self):
        with patch(
            "integrations.ai_agent.api.views._agent_response",
            return_value=Response({"ok": True, "answer": "tools", "agent_mode": "tools"}),
        ) as agent, patch(
            "integrations.ai_agent.api.views.run_pipeline"
        ) as legacy:
            response = self.api.post(URL, {"message": "berapa order?"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["agent_mode"], "tools")
        self.assertTrue(agent.called)
        self.assertFalse(legacy.called)
