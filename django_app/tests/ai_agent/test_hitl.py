"""Test HITL Sprint F.1 — scorer, policy, router, queue, endpoint, task."""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from core.audit.models import AuditLog
from core.auth.models import Role, User
from integrations.ai_agent.hitl import (
    active_learning,
    confidence_scorer,
    escalation_router,
    hitl_services,
    impact_scorer,
    policy_checker,
)
from integrations.ai_agent.models import AIDecisionLog, AIHitlQueue
from integrations.ai_agent.tasks import hitl_expire_pending

QUEUE_URL = "/api/v1/ai/hitl/queue/"


def make_log(**overrides) -> AIDecisionLog:
    data = {
        "query_text": "pindahkan 5 bundle",
        "decision_gate_result": "LLM_NEEDED",
        "intent": "bundle.move",
        "confidence_score": 0.8,
    }
    data.update(overrides)
    return AIDecisionLog.objects.create(**data)


def make_hitl(required_role="SUPERVISOR", status="PENDING", expired=False, **overrides):
    data = {
        "decision_log": make_log(),
        "risk_level": "MEDIUM",
        "proposed_action": {"action": "update", "resource": "bundle"},
        "required_approver_role": required_role,
        "channel": "WA",
        "status": status,
        "expires_at": timezone.now() + timedelta(hours=-2 if expired else 24),
    }
    data.update(overrides)
    return AIHitlQueue.objects.create(**data)


class ScorerTests(TestCase):
    def test_confidence_rule_hit(self):
        self.assertEqual(confidence_scorer.score({"decision_gate_result": "RULE_HIT"}), 0.95)

    def test_confidence_blocked(self):
        self.assertEqual(confidence_scorer.score({"decision_gate_result": "BLOCKED"}), 0.0)

    def test_confidence_llm_pakai_nilai_response(self):
        self.assertAlmostEqual(
            confidence_scorer.score(
                {"decision_gate_result": "LLM_NEEDED", "confidence_score": 0.42}
            ),
            0.42,
        )

    def test_impact_tanpa_aksi_low(self):
        self.assertEqual(impact_scorer.score("x", [], None), "LOW")

    def test_impact_create_medium(self):
        self.assertEqual(
            impact_scorer.score("x", [], {"action": "create", "resource": "bundle"}),
            "MEDIUM",
        )

    def test_impact_finance_high(self):
        self.assertEqual(
            impact_scorer.score("x", [], {"action": "create", "resource": "invoice"}),
            "HIGH",
        )

    def test_impact_batch_naik_level(self):
        action = {"action": "update", "resource": "bundle", "items": [1] * 11}
        self.assertEqual(impact_scorer.score("x", [], action), "HIGH")

    def test_policy_low_auto(self):
        self.assertEqual(
            policy_checker.check("LOW", "operator"),
            {"allowed": True, "required_role": None, "reason": None},
        )

    def test_policy_medium_supervisor(self):
        result = policy_checker.check("MEDIUM", "supervisor")
        self.assertTrue(result["allowed"])
        self.assertEqual(result["required_role"], "SUPERVISOR")

    def test_policy_high_owner(self):
        self.assertEqual(policy_checker.check("HIGH", "owner")["required_role"], "OWNER")

    def test_policy_operator_medium_ditolak(self):
        result = policy_checker.check("MEDIUM", "operator")
        self.assertFalse(result["allowed"])


@override_settings(AI_AGENT_ENABLED=True)
class EscalationRouterTests(TestCase):
    def setUp(self):
        self.supervisor = User.objects.create_user(
            username="r-sup", password="x", role=Role.objects.get(code=Role.Code.SUPERVISOR)
        )
        self.operator = User.objects.create_user(
            username="r-op", password="x", role=Role.objects.get(code=Role.Code.OPERATOR)
        )

    def test_low_tanpa_hitl(self):
        result = escalation_router.route(
            {"decision_gate_result": "RULE_HIT", "query_text": "halo"}, self.supervisor
        )

        self.assertFalse(result["hitl_required"])
        self.assertIsNone(result["hitl_request_id"])
        self.assertEqual(AIHitlQueue.objects.count(), 0)

    def test_medium_buat_queue_supervisor(self):
        result = escalation_router.route(
            {
                "decision_gate_result": "LLM_NEEDED",
                "query_text": "pindahkan bundle",
                "proposed_action": {"action": "update", "resource": "bundle", "summary": "Pindah"},
            },
            self.supervisor,
        )

        self.assertTrue(result["hitl_required"])
        self.assertEqual(result["required_approver_role"], "SUPERVISOR")
        self.assertEqual(result["channel"], "WA")
        row = AIHitlQueue.objects.get(pk=result["hitl_request_id"])
        self.assertEqual(row.status, "PENDING")
        self.assertEqual(row.risk_level, "MEDIUM")

    def test_high_owner(self):
        result = escalation_router.route(
            {
                "decision_gate_result": "LLM_NEEDED",
                "query_text": "buat invoice",
                "proposed_action": {"action": "create", "resource": "invoice"},
            },
            self.supervisor,
        )

        self.assertEqual(result["required_approver_role"], "OWNER")
        self.assertTrue(result["hitl_required"])

    def test_operator_medium_ditolak(self):
        result = escalation_router.route(
            {
                "decision_gate_result": "LLM_NEEDED",
                "query_text": "hapus bundle",
                "proposed_action": {"action": "delete", "resource": "bundle"},
            },
            self.operator,
        )

        self.assertFalse(result["allowed"])
        self.assertFalse(result["hitl_required"])
        self.assertEqual(AIHitlQueue.objects.count(), 0)

@override_settings(AI_AGENT_ENABLED=True)
class HitlEndpointTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.supervisor = User.objects.create_user(
            username="e-sup", password="x", role=Role.objects.get(code=Role.Code.SUPERVISOR)
        )
        cls.owner = User.objects.create_user(
            username="e-owner", password="x", role=Role.objects.get(code=Role.Code.OWNER)
        )
        cls.operator = User.objects.create_user(
            username="e-op", password="x", role=Role.objects.get(code=Role.Code.OPERATOR)
        )

    def post(self, path, payload, user):
        client = APIClient()
        client.force_authenticate(user)
        return client.post(path, payload, format="json")

    def get(self, path, user):
        client = APIClient()
        client.force_authenticate(user)
        return client.get(path)

    def test_queue_supervisor_200(self):
        make_hitl()

        response = self.get(QUEUE_URL, self.supervisor)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total_count"], 1)

    def test_queue_operator_403(self):
        response = self.get(QUEUE_URL, self.operator)

        self.assertEqual(response.status_code, 403)

    def test_approve_supervisor_sesuai_role(self):
        hitl = make_hitl()

        response = self.post(f"/api/v1/ai/hitl/{hitl.pk}/approve/", {}, self.supervisor)

        self.assertEqual(response.status_code, 200)
        hitl.refresh_from_db()
        self.assertEqual(hitl.status, "APPROVED")
        self.assertTrue(
            AuditLog.objects.filter(action="ai.hitl_approve").exists()
        )

    def test_approve_supervisor_owner_required_403(self):
        hitl = make_hitl(required_role="OWNER", risk_level="HIGH")

        response = self.post(f"/api/v1/ai/hitl/{hitl.pk}/approve/", {}, self.supervisor)

        self.assertEqual(response.status_code, 403)

    def test_owner_bisa_approve_semua(self):
        hitl = make_hitl(required_role="OWNER", risk_level="HIGH")

        response = self.post(f"/api/v1/ai/hitl/{hitl.pk}/approve/", {}, self.owner)

        self.assertEqual(response.status_code, 200)

    def test_reject_reason_kosong_400(self):
        hitl = make_hitl()

        response = self.post(
            f"/api/v1/ai/hitl/{hitl.pk}/reject/", {"reason": "  "}, self.supervisor
        )

        self.assertEqual(response.status_code, 400)

    def test_reject_valid_200(self):
        hitl = make_hitl()

        response = self.post(
            f"/api/v1/ai/hitl/{hitl.pk}/reject/",
            {"reason": "tidak sesuai SOP"},
            self.supervisor,
        )

        self.assertEqual(response.status_code, 200)
        hitl.refresh_from_db()
        self.assertEqual(hitl.status, "REJECTED")
        self.assertEqual(hitl.rejection_reason, "tidak sesuai SOP")

    def test_hitl_tidak_ditemukan_404(self):
        response = self.post("/api/v1/ai/hitl/999999/approve/", {}, self.supervisor)

        self.assertEqual(response.status_code, 404)


class HitlExpireTests(TestCase):
    def test_tiga_pending_kedaluwarsa(self):
        for _ in range(3):
            make_hitl(expired=True)

        count = hitl_expire_pending()

        self.assertEqual(count, 3)
        self.assertEqual(AIHitlQueue.objects.filter(status="EXPIRED").count(), 3)

    def test_tidak_sentuh_approved_rejected(self):
        make_hitl(status="APPROVED", expired=True)
        make_hitl(status="REJECTED", expired=True)
        pending = make_hitl(expired=True)

        count = hitl_expire_pending()

        self.assertEqual(count, 1)
        self.assertEqual(AIHitlQueue.objects.get(pk=pending.pk).status, "EXPIRED")
        self.assertEqual(AIHitlQueue.objects.filter(status="APPROVED").count(), 1)
        self.assertEqual(AIHitlQueue.objects.filter(status="REJECTED").count(), 1)

    def test_beat_schedule_19_entry(self):
        self.assertEqual(len(settings.CELERY_BEAT_SCHEDULE), 20)
        self.assertEqual(
            settings.CELERY_BEAT_SCHEDULE["ai-hitl-expire"]["task"],
            "ai_agent.hitl_expire_pending",
        )
        self.assertEqual(
            settings.CELERY_BEAT_SCHEDULE["ai-detect-drift"]["task"],
            "ai_agent.detect_drift",
        )

    def test_active_learning_audit(self):
        hitl = make_hitl()

        active_learning.record_feedback(hitl.pk, "approved", "ok")

        self.assertTrue(AuditLog.objects.filter(action="ai.hitl_feedback").exists())


@override_settings(AI_AGENT_ENABLED=False)
class StubCompatibilityTests(TestCase):
    def test_stub_lama_tetap_dipakai(self):
        """Flag false → endpoint memakai HITLRequest (bukan AIHitlQueue)."""
        from apps_industry.garment.models import HITLRequest

        user = User.objects.create_user(
            username="stub-sup", password="x", role=Role.objects.get(code=Role.Code.SUPERVISOR)
        )
        HITLRequest.objects.create(
            request_type="BUNDLE_MOVE",
            resource_type="bundle",
            resource_id="1",
            payload={},
            reason="uji",
            priority="NORMAL",
            state="PENDING",
        )

        client = APIClient()
        client.force_authenticate(user)
        response = client.get(QUEUE_URL)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total_count"], 1)

