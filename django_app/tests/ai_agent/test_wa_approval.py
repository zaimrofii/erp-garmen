"""Test WA approval Sprint F.2 — format, notifikasi, router, webhook."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.auth.models import Role, User
from integrations.ai_agent.hitl import escalation_router, hitl_services
from integrations.ai_agent.models import AIHitlQueue
from integrations.wa_bot import hitl_messages

WEBHOOK = "/api/v1/wa/webhook/"

WA_SETTINGS = {
    "AI_HITL_WA_TO": "628999",
    "AI_HITL_WA_APPROVERS": {"628111": "wa-sup"},
}


def hitl_stub(**overrides):
    data = {
        "pk": 5,
        "risk_level": "MEDIUM",
        "proposed_action": {"action": "update", "resource": "bundle", "summary": "Pindahkan 5 bundle"},
        "status": "PENDING",
    }
    data.update(overrides)
    return SimpleNamespace(**data)


class FormatAndNotifyTests(TestCase):
    def test_format_pesan(self):
        body = hitl_messages.format_hitl_message(hitl_stub())

        self.assertIn("Persetujuan AI dibutuhkan", body)
        self.assertIn("Pindahkan 5 bundle", body)
        self.assertIn("Risiko: MEDIUM", body)
        self.assertIn("APPROVE 5", body)
        self.assertIn("REJECT 5", body)

    @override_settings(AI_HITL_WA_TO="628999")
    def test_send_memanggil_gateway(self):
        gateway = MagicMock()
        gateway.send_message.return_value = SimpleNamespace(
            ok=True, message_id="M1", error=None
        )

        with patch.object(hitl_messages, "get_wa_gateway", return_value=gateway):
            result = hitl_messages.send_hitl_notification(hitl_stub())

        self.assertTrue(result["ok"])
        self.assertEqual(result["message_id"], "M1")
        gateway.send_message.assert_called_once()

    def test_tanpa_nomor_dilewati(self):
        with override_settings(AI_HITL_WA_TO="", HITL_ALERT_WA_TO=""):
            result = hitl_messages.send_hitl_notification(hitl_stub())

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "no_recipient")


@override_settings(AI_AGENT_ENABLED=True)
class RouterWaTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="router-wa",
            password="x",
            role=Role.objects.get(code=Role.Code.SUPERVISOR),
        )

    def test_channel_wa_mengirim_notifikasi(self):
        with patch(
            "integrations.wa_bot.hitl_messages.send_hitl_notification",
            return_value={"ok": True, "message_id": "M2"},
        ) as send:
            result = escalation_router.route(
                {
                    "decision_gate_result": "LLM_NEEDED",
                    "query_text": "pindahkan bundle",
                    "proposed_action": {"action": "update", "resource": "bundle"},
                },
                self.user,
            )

        self.assertTrue(result["hitl_required"])
        self.assertEqual(result["channel"], "WA")
        send.assert_called_once()
        self.assertEqual(AIHitlQueue.objects.count(), 1)


@override_settings(**WA_SETTINGS)
class WebhookTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.approver = User.objects.create_user(
            username="wa-sup",
            password="x",
            role=Role.objects.get(code=Role.Code.SUPERVISOR),
        )

    def post(self, text, sender="628111"):
        return APIClient().post(WEBHOOK, {"from": sender, "text": text}, format="json")

    def test_approve_memanggil_service(self):
        with patch(
            "integrations.wa_bot.views.hitl_services.approve", return_value={}
        ) as approve:
            response = self.post("APPROVE 5")

        self.assertEqual(response.status_code, 200)
        approve.assert_called_once_with(5, self.approver, note="WA")

    def test_reject_memanggil_service(self):
        with patch(
            "integrations.wa_bot.views.hitl_services.reject", return_value={}
        ) as reject:
            response = self.post("REJECT 5 stok tidak cukup")

        self.assertEqual(response.status_code, 200)
        reject.assert_called_once_with(5, self.approver, reason="stok tidak cukup")

    def test_nomor_tidak_terdaftar_diabaikan(self):
        response = self.post("APPROVE 5", sender="620000")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ignored"])

    def test_format_tidak_dikenal_diabaikan(self):
        response = self.post("halo apa kabar")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ignored"])

    def test_id_tidak_ada_error(self):
        with patch(
            "integrations.wa_bot.views.hitl_services.approve",
            side_effect=hitl_services.HitlNotFound("x"),
        ):
            response = self.post("APPROVE 999")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"], "not_found")
