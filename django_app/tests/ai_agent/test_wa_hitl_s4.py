"""Test S.4 — WA approval HITL: notifikasi, gateway mock/fonnte, webhook."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from core.auth.models import Role, User
from integrations.ai_agent.hitl import hitl_services
from integrations.ai_agent.models import AIHitlQueue
from integrations.wa_bot import hitl_messages
from integrations.wa_bot.services import (
    FonnteGateway,
    MockWAGateway,
    get_wa_gateway,
    send_hitl_notification,
)

WEBHOOK = "/api/v1/wa/webhook/"


def _make_hitl(status: str = "PENDING") -> AIHitlQueue:
    log = hitl_services.make_decision_log(
        {
            "query_text": "apa yang harus saya lakukan?",
            "decision_gate_result": "LLM_NEEDED",
        }
    )
    log.intent = "SUGGEST_ACTION"
    log.save(update_fields=["intent"])
    return AIHitlQueue.objects.create(
        decision_log=log,
        risk_level="MEDIUM",
        proposed_action={
            "type": "suggest_actions",
            "problem": "scrap SEWING-2",
            "actions": [
                {
                    "action": "rework BND-A-12",
                    "impact": "MEDIUM",
                    "confidence": 0.8,
                },
                {
                    "action": "pindah BND-A-14 ke SEWING-1",
                    "impact": "LOW",
                    "confidence": 0.6,
                },
            ],
            "count": 2,
        },
        required_approver_role="SUPERVISOR",
        channel="WA",
        status=status,
        expires_at=timezone.now() + timedelta(hours=4),
    )


class NotificationTests(TestCase):
    def test_format_nested_actions(self):
        body = hitl_messages.format_hitl_message(_make_hitl())

        self.assertIn("rework BND-A-12", body)
        self.assertIn("+1 aksi lain", body)
        self.assertIn("Risiko: MEDIUM", body)
        self.assertIn("APPROVE", body)
        self.assertIn("REJECT", body)

    @override_settings(AI_HITL_WA_TO="628999")
    def test_send_by_id_ke_nomor_approver(self):
        hitl = _make_hitl()
        gateway = MagicMock()
        gateway.send_message.return_value = SimpleNamespace(
            ok=True, message_id="M1", error=None
        )

        with patch.object(hitl_messages, "get_wa_gateway", return_value=gateway):
            result = send_hitl_notification(hitl.pk, "628111")

        self.assertTrue(result["ok"])
        gateway.send_message.assert_called_once()
        to, body = gateway.send_message.call_args.args
        self.assertEqual(to, "628111")
        self.assertIn("rework BND-A-12", body)

    def test_send_id_tidak_ada(self):
        result = send_hitl_notification(999999, "628111")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "not_found")

    def test_tanpa_nomor_dan_approver_dilewati(self):
        with override_settings(
            AI_HITL_WA_TO="", HITL_ALERT_WA_TO="", AI_HITL_WA_APPROVERS=[]
        ):
            result = hitl_messages.send_hitl_notification(_make_hitl())

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "no_recipient")

    def test_recipient_fallback_ke_approver(self):
        with override_settings(AI_HITL_WA_TO="", AI_HITL_WA_APPROVERS=["628777"]):
            self.assertEqual(hitl_messages._recipient(), "628777")

class GatewayTests(TestCase):
    def test_default_mock(self):
        with override_settings(WA_BACKEND="mock"):
            self.assertIsInstance(get_wa_gateway(), MockWAGateway)

    def test_fonnte_dengan_key(self):
        with override_settings(WA_BACKEND="fonnte", WA_API_KEY="kunci"):
            self.assertIsInstance(get_wa_gateway(), FonnteGateway)

    def test_fonnte_tanpa_key_fallback_mock(self):
        with override_settings(WA_BACKEND="fonnte", WA_API_KEY=""):
            self.assertIsInstance(get_wa_gateway(), MockWAGateway)

    def test_fonnte_send_request_benar(self):
        gateway = FonnteGateway("kunci", "https://api.fonnte.test/send")
        response = SimpleNamespace(
            content=b"{}", json=lambda: {"status": True, "id": ["F1"]}
        )

        with patch("httpx.post", return_value=response) as post:
            result = gateway.send_message("628111", "halo")

        self.assertTrue(result.ok)
        self.assertEqual(result.message_id, "F1")
        post.assert_called_once()
        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs["headers"]["Authorization"], "kunci")
        self.assertEqual(kwargs["data"], {"target": "628111", "message": "halo"})

    def test_fonnte_parse_incoming(self):
        gateway = FonnteGateway("kunci")
        message = gateway.parse_incoming({"sender": "628111", "message": "APPROVE 5"})

        self.assertEqual(message.sender, "628111")
        self.assertEqual(message.body, "APPROVE 5")

    def test_mock_parse_field_message(self):
        message = MockWAGateway().parse_incoming(
            {"from": "6281", "message": "REJECT 2 x"}
        )

        self.assertEqual((message.sender, message.body), ("6281", "REJECT 2 x"))

WA_SETTINGS = {
    "AI_HITL_WA_TO": "628999",
    "AI_HITL_WA_APPROVERS": {"628222": "wa-sup-s4"},
}


@override_settings(**WA_SETTINGS)
class WebhookTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.approver = User.objects.create_user(
            username="wa-sup-s4",
            password="x",
            role=Role.objects.get(code=Role.Code.SUPERVISOR),
        )

    def post(self, text, sender="628222", key="text"):
        return APIClient().post(WEBHOOK, {"from": sender, key: text}, format="json")

    def test_approve_memanggil_service(self):
        with patch(
            "integrations.wa_bot.views.hitl_services.approve",
            return_value={
                "status": "APPROVED",
                "execution": {"ok": True, "executed": True},
            },
        ) as approve:
            response = self.post("APPROVE 5")

        self.assertEqual(response.status_code, 200)
        approve.assert_called_once_with(5, self.approver, note="WA")
        self.assertTrue(response.json()["execution"]["executed"])

    def test_reject_memanggil_service(self):
        with patch(
            "integrations.wa_bot.views.hitl_services.reject", return_value={}
        ) as reject:
            response = self.post("REJECT 5 stok tidak cukup")

        self.assertEqual(response.status_code, 200)
        reject.assert_called_once_with(5, self.approver, reason="stok tidak cukup")

    def test_nomor_tidak_terdaftar_403(self):
        response = self.post("APPROVE 5", sender="620000")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], "forbidden")

    def test_format_invalid_400(self):
        response = self.post("halo apa kabar")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "invalid_format")

    def test_hitl_tidak_ada_404(self):
        with patch(
            "integrations.wa_bot.views.hitl_services.approve",
            side_effect=hitl_services.HitlNotFound("x"),
        ):
            response = self.post("APPROVE 999")

        self.assertEqual(response.status_code, 404)

    def test_field_message_diterima(self):
        with patch(
            "integrations.wa_bot.views.hitl_services.approve", return_value={}
        ) as approve:
            response = self.post("APPROVE 7", key="message")

        self.assertEqual(response.status_code, 200)
        approve.assert_called_once()


