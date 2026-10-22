"""Regresi Fase 6.1 — HITL chat approve + filter FG ranking produk."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.auth.models import Role, User
from integrations.ai_agent.models import AIDecisionLog, AIHitlQueue
from integrations.ai_agent.orchestrator.context_builder import build_context
from master.models import Product

URL = "/api/v1/ai/chat"


class Fase61FixTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(
            username="f61-owner",
            password="x",
            role=Role.objects.get(code=Role.Code.OWNER),
        )
        Product.objects.create(
            code="RM-F61-MAHAL",
            name="Kain Sutra F61",
            category="Material",
            sale_price=9000000,
            cost_price=9000000,
        )
        Product.objects.create(
            code="FG-F61-MAHAL",
            name="Jaket Premium F61",
            category="Jaket",
            sale_price=500000,
            cost_price=300000,
        )
        Product.objects.create(
            code="RM-F61-MURAH",
            name="Kain Murah F61",
            category="Material",
            sale_price=1,
            cost_price=1,
        )
        Product.objects.create(
            code="FG-F61-MURAH",
            name="Kaos Murah F61",
            category="Kaos",
            sale_price=10000,
            cost_price=7000,
        )

    def _pending_hitl(self) -> AIHitlQueue:
        log = AIDecisionLog.objects.create(
            user=self.owner,
            query_text="scrap tinggi",
            decision_gate_result="LLM_NEEDED",
            intent="SUGGEST_ACTION",
        )
        return AIHitlQueue.objects.create(
            decision_log=log,
            risk_level="MEDIUM",
            proposed_action={"type": "suggest_actions", "actions": []},
            required_approver_role="SUPERVISOR",
            channel="DESKTOP",
            status="PENDING",
            expires_at=timezone.now() + timedelta(hours=1),
        )

    def test_approve_via_chat_updates_pending_and_zero_token(self):
        hitl = self._pending_hitl()
        api = APIClient()
        api.force_authenticate(self.owner)

        with patch(
            "integrations.ai_agent.orchestrator.response_synthesizer.get_llm_provider"
        ) as provider:
            response = api.post(URL, {"message": "setujui aksi itu"}, format="json")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("disetujui", body["answer"].lower())
        self.assertTrue(body["hitl_approved"])
        self.assertEqual(body["tokens"]["total_cost_usd"], 0)
        provider.assert_not_called()
        hitl.refresh_from_db()
        self.assertEqual(hitl.status, "APPROVED")

    def test_produk_termahal_hanya_fg(self):
        data = build_context(
            "DATA_LOOKUP", [], "produk termahal?", {}, user=self.owner
        )

        rows = data["product_list"]
        self.assertEqual(rows[0]["name"], "Jaket Premium F61")
        self.assertTrue(all(row["category"] != "Material" for row in rows))
        self.assertNotIn("Kain Sutra F61", [row["name"] for row in rows])

    def test_produk_termurah_hanya_fg(self):
        data = build_context(
            "DATA_LOOKUP", [], "produk termurah?", {}, user=self.owner
        )

        rows = data["product_list"]
        self.assertEqual(rows[0]["name"], "Kaos Murah F61")
        self.assertTrue(all(row["category"] != "Material" for row in rows))
        self.assertNotIn("Kain Murah F61", [row["name"] for row in rows])
