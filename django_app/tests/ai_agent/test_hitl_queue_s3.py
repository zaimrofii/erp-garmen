"""Test S.3 — endpoint antrean HITL: filter, pagination, approve/reject."""

from __future__ import annotations

from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from core.auth.models import Role, User
from integrations.ai_agent.hitl import hitl_services
from integrations.ai_agent.models import AIHitlQueue

QUEUE_URL = "/api/v1/ai/hitl/queue/"


def _make_row(
    *,
    risk: str = "MEDIUM",
    required: str = "SUPERVISOR",
    status: str = "PENDING",
    action: str = "rework BND-A-1",
) -> AIHitlQueue:
    log = hitl_services.make_decision_log(
        {
            "query_text": "apa yang harus saya lakukan?",
            "decision_gate_result": "LLM_NEEDED",
        }
    )
    log.intent = "SUGGEST_ACTION"
    log.confidence_score = 0.8
    log.hitl_required = True
    log.save(update_fields=["intent", "confidence_score", "hitl_required"])

    return AIHitlQueue.objects.create(
        decision_log=log,
        risk_level=risk,
        proposed_action={
            "type": "suggest_actions",
            "problem": "scrap tinggi",
            "actions": [
                {"action": action, "impact": risk, "confidence": 0.8, "reason": "x"}
            ],
            "count": 1,
        },
        required_approver_role=required,
        channel="DESKTOP",
        status=status,
        expires_at=timezone.now() + timedelta(hours=4),
    )


@override_settings(AI_AGENT_ENABLED=True)
class HitlQueueApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.supervisor_role = Role.objects.get(code=Role.Code.SUPERVISOR)
        cls.operator_role = Role.objects.get(code=Role.Code.OPERATOR)

    def setUp(self):
        super().setUp()
        cache.clear()
        self.supervisor = User.objects.create_user(
            username="hitl-sup", password="x", role=self.supervisor_role
        )
        self.operator = User.objects.create_user(
            username="hitl-op", password="x", role=self.operator_role
        )
        self.api = APIClient()
        self.api.force_authenticate(self.supervisor)

    def test_default_hanya_pending(self):
        _make_row(status="PENDING")
        _make_row(status="APPROVED")

        body = self.api.get(QUEUE_URL).json()

        self.assertEqual(body["total_count"], 1)
        self.assertEqual(body["rows"][0]["status"], "PENDING")

    def test_filter_status_approved(self):
        approved = _make_row(status="APPROVED")
        approved.decided_by = self.supervisor
        approved.decided_at = timezone.now()
        approved.save(update_fields=["decided_by", "decided_at"])

        body = self.api.get(f"{QUEUE_URL}?status=APPROVED").json()

        self.assertEqual(body["total_count"], 1)
        self.assertEqual(body["rows"][0]["id"], approved.pk)
        self.assertEqual(body["rows"][0]["decided_by"], "hitl-sup")

    def test_filter_risk_high(self):
        _make_row(risk="MEDIUM")
        high = _make_row(risk="HIGH")

        body = self.api.get(f"{QUEUE_URL}?risk=HIGH").json()

        self.assertEqual([row["id"] for row in body["rows"]], [high.pk])

    def test_pagination_offset(self):
        first = _make_row()
        second = _make_row()

        page1 = self.api.get(f"{QUEUE_URL}?limit=1&offset=0").json()
        page2 = self.api.get(f"{QUEUE_URL}?limit=1&offset=1").json()

        self.assertEqual(page1["total_count"], 2)
        self.assertTrue(page1["has_more"])
        self.assertEqual(page1["next_cursor"], 1)
        self.assertFalse(page2["has_more"])
        self.assertIsNone(page2["next_cursor"])
        self.assertEqual({page1["rows"][0]["id"], page2["rows"][0]["id"]}, {first.pk, second.pk})

    def test_status_tidak_dikenal_400(self):
        response = self.api.get(f"{QUEUE_URL}?status=HACKED")

        self.assertEqual(response.status_code, 400)

    def test_operator_403(self):
        self.api.force_authenticate(self.operator)

        response = self.api.get(QUEUE_URL)

        self.assertEqual(response.status_code, 403)

    def test_approve_lalu_muncul_di_filter_approved(self):
        row = _make_row()

        response = self.api.post(f"/api/v1/ai/hitl/{row.pk}/approve/", {"note": "ok"}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "APPROVED")

        body = self.api.get(f"{QUEUE_URL}?status=APPROVED").json()
        self.assertEqual(body["rows"][0]["id"], row.pk)
        self.assertEqual(body["rows"][0]["decided_by"], "hitl-sup")

    def test_reject_tanpa_alasan_400_lalu_sukses(self):
        row = _make_row()

        bad = self.api.post(f"/api/v1/ai/hitl/{row.pk}/reject/", {}, format="json")
        self.assertEqual(bad.status_code, 400)

        ok = self.api.post(
            f"/api/v1/ai/hitl/{row.pk}/reject/",
            {"reason": "data belum lengkap"},
            format="json",
        )
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["status"], "REJECTED")
        self.assertEqual(ok.json()["rejection_reason"], "data belum lengkap")
