"""Test F.4 — cost tracker, drift detector, task, budget chat."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from core.audit.models import AuditLog
from core.auth.models import Role, User
from integrations.ai_agent.models import AIDecisionLog
from integrations.ai_agent.observability import cost_tracker, drift_detector
from integrations.ai_agent.tasks import detect_ai_drift


def make_log(*, cost="0.25", intent="scrap.query", days_ago=0, user=None):
    row = AIDecisionLog.objects.create(
        user=user,
        query_text="q",
        decision_gate_result="LLM_NEEDED",
        intent=intent,
        total_cost_usd=Decimal(cost),
    )
    if days_ago:
        AIDecisionLog.objects.filter(pk=row.pk).update(
            timestamp=timezone.now() - timedelta(days=days_ago)
        )
    row.refresh_from_db()
    return row


class CostTrackerTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username="cost-user",
            password="x",
            role=Role.objects.get(code=Role.Code.SUPERVISOR),
        )

    def test_record_daily_total(self):
        cost_tracker.record_cost(make_log(cost="0.25", user=self.user))
        cost_tracker.record_cost(make_log(cost="0.75", user=self.user))

        self.assertEqual(
            cost_tracker.get_daily_cost(timezone.localdate()), Decimal("1")
        )

    def test_get_daily_cost(self):
        cost_tracker.record_cost(make_log(cost="0.5"))

        self.assertEqual(
            cost_tracker.get_daily_cost(timezone.localdate()), Decimal("0.5")
        )

    def test_get_monthly_cost(self):
        cost_tracker.record_cost(make_log(cost="1.5"))
        today = timezone.localdate()

        self.assertEqual(
            cost_tracker.get_monthly_cost(today.year, today.month), Decimal("1.5")
        )

    def test_get_user_cost(self):
        cost_tracker.record_cost(make_log(cost="2", user=self.user))
        today = timezone.localdate()

        self.assertEqual(
            cost_tracker.get_user_cost(self.user, today.month, today.year),
            Decimal("2"),
        )

    def test_budget_belum_lewat(self):
        cost_tracker.record_cost(make_log(cost="1", user=self.user))

        result = cost_tracker.check_budget(self.user)

        self.assertFalse(result["exceeded"])
        self.assertEqual(result["budget_usd"], Decimal("5.0"))

    def test_budget_lewat(self):
        cost_tracker.record_cost(make_log(cost="6", user=self.user))

        self.assertTrue(cost_tracker.check_budget(self.user)["exceeded"])


class DriftTests(TestCase):
    def test_nol_log_tidak_drift(self):
        self.assertFalse(drift_detector.detect_drift()["drifted"])

    def test_distribusi_sama_tidak_drift(self):
        for _ in range(5):
            make_log(intent="scrap.query", days_ago=20)
            make_log(intent="scrap.query", days_ago=1)

        result = drift_detector.detect_drift()

        self.assertFalse(result["drifted"])
        self.assertEqual(result["delta_pct"]["scrap.query"], 0.0)

    def test_distribusi_bergeser_drift(self):
        for _ in range(10):
            make_log(intent="scrap.query", days_ago=20)
            make_log(intent="stock.query", days_ago=1)

        result = drift_detector.detect_drift()

        self.assertTrue(result["drifted"])
        self.assertGreater(abs(result["delta_pct"]["stock.query"]), 20)

    def test_task_audit_saat_drift(self):
        with patch.object(
            drift_detector,
            "detect_drift",
            return_value={
                "drifted": True,
                "delta_pct": {"x": 50.0},
                "threshold_pct": 20.0,
            },
        ):
            result = detect_ai_drift()

        self.assertTrue(result["drifted"])
        self.assertTrue(AuditLog.objects.filter(action="ai.drift_detected").exists())


@override_settings(AI_AGENT_ENABLED=True)
class ChatBudgetTests(TestCase):
    def test_budget_lewat_429(self):
        user = User.objects.create_user(
            username="chat-budget",
            password="x",
            role=Role.objects.get(code=Role.Code.SUPERVISOR),
        )
        client = APIClient()
        client.force_authenticate(user)

        with patch(
            "integrations.ai_agent.api.views.cost_tracker.check_budget",
            return_value={"exceeded": True, "used_usd": Decimal("6"), "budget_usd": Decimal("5")},
        ):
            response = client.post("/api/v1/ai/chat", {"message": "halo"}, format="json")

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["error"], "budget_exceeded")
