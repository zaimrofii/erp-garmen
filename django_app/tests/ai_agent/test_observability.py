"""Test observability Sprint F.3 — agregasi + endpoint + cache."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.auth.models import Role, User
from integrations.ai_agent.models import AIDecisionLog
from integrations.ai_agent.observability import decision_logger

URL = "/api/v1/ai/observability/"


def make_log(*, days_ago=0, cost="0.001", cache=False, hitl=None, tools=None):
    row = AIDecisionLog.objects.create(
        query_text="kenapa scrap naik?",
        decision_gate_result="LLM_NEEDED",
        prompt_tokens=10,
        completion_tokens=20,
        total_cost_usd=Decimal(cost),
        cache_hit=cache,
        hitl_required=hitl is not None,
        hitl_decision=hitl or "",
        tools_called=tools or [],
        latency_ms=100,
    )
    if days_ago:
        AIDecisionLog.objects.filter(pk=row.pk).update(
            timestamp=timezone.now() - timedelta(days=days_ago)
        )
    return row


class AggregateTests(TestCase):
    def window(self):
        now = timezone.now()
        return now - timedelta(days=30), now

    def test_nol_log(self):
        stats = decision_logger.aggregate_stats(*self.window())

        self.assertEqual(stats["totals"]["requests"], 0)
        self.assertEqual(stats["cache_hit_ratio"], 0)
        self.assertEqual(stats["by_day"], [])

    def test_lima_log_totals(self):
        for _ in range(5):
            make_log()

        stats = decision_logger.aggregate_stats(*self.window())

        self.assertEqual(stats["totals"]["requests"], 5)
        self.assertEqual(stats["totals"]["tokens_prompt"], 50)
        self.assertEqual(stats["totals"]["tokens_completion"], 100)
        self.assertAlmostEqual(stats["totals"]["cost_usd"], 0.005)

    def test_by_day(self):
        make_log(days_ago=1)
        make_log(days_ago=1)
        make_log()

        stats = decision_logger.aggregate_stats(*self.window())

        self.assertEqual(len(stats["by_day"]), 2)
        self.assertEqual(stats["by_day"][0]["requests"], 2)

    def test_by_tool(self):
        make_log(tools=[{"tool": "mcp-analytics", "duration_ms": 10}])
        make_log(tools=[{"tool": "mcp-analytics", "duration_ms": 30}])

        stats = decision_logger.aggregate_stats(*self.window())

        self.assertEqual(stats["by_tool"][0]["tool"], "mcp-analytics")
        self.assertEqual(stats["by_tool"][0]["calls"], 2)
        self.assertEqual(stats["by_tool"][0]["avg_duration_ms"], 20)

    def test_cache_ratio(self):
        make_log(cache=True)
        make_log(cache=True)
        make_log()
        make_log()
        make_log()

        stats = decision_logger.aggregate_stats(*self.window())

        self.assertEqual(stats["cache_hit_ratio"], 0.4)

    def test_hitl_approval_rate(self):
        for _ in range(3):
            make_log(hitl="APPROVED")
        make_log(hitl="REJECTED")

        stats = decision_logger.aggregate_stats(*self.window())

        self.assertEqual(stats["hitl_approval_rate"], 0.75)


class ObservabilityEndpointTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="obs-admin", password="x", role=Role.objects.get(code=Role.Code.ADMIN)
        )
        cls.supervisor = User.objects.create_user(
            username="obs-sup", password="x", role=Role.objects.get(code=Role.Code.SUPERVISOR)
        )

    def get(self, user, query=""):
        client = APIClient()
        if user is not None:
            client.force_authenticate(user)
        return client.get(f"{URL}{query}")

    def test_anonim_403(self):
        self.assertEqual(self.get(None).status_code, 403)

    def test_admin_200(self):
        make_log()

        response = self.get(self.admin)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["totals"]["requests"], 1)

    def test_supervisor_403(self):
        self.assertEqual(self.get(self.supervisor).status_code, 403)

    def test_cache_dan_nocache(self):
        make_log()

        with patch.object(
            decision_logger, "aggregate_stats", wraps=decision_logger.aggregate_stats
        ) as aggregate:
            first = self.get(self.admin, "?date_from=2026-01-01")
            second = self.get(self.admin, "?date_from=2026-01-01")
            third = self.get(self.admin, "?date_from=2026-01-01&_nocache=1")

        self.assertFalse(first.json()["cached"])
        self.assertTrue(second.json()["cached"])
        self.assertFalse(third.json()["cached"])
        self.assertEqual(aggregate.call_count, 2)
