"""Test model AI Agent (D.1) — 10 skenario."""

from __future__ import annotations

import importlib.util
from datetime import timedelta
from pathlib import Path

from django.apps import apps as django_apps
from django.core.exceptions import ValidationError
from django.conf import settings
from django.test import TestCase
from django.utils import timezone

from integrations.ai_agent.config import AI_CONFIG
from integrations.ai_agent.mcp_servers import registry as mcp_registry
from integrations.ai_agent.models import (
    AIDecisionLog,
    AIHitlQueue,
    AISemanticCache,
    AIToolRegistry,
)


class ToolRegistryTests(TestCase):
    def test_seed_12_tools(self):
        self.assertEqual(AIToolRegistry.objects.count(), 12)
        self.assertTrue(AIToolRegistry.objects.filter(name="mcp-analytics").exists())
        self.assertTrue(AIToolRegistry.objects.filter(name="mcp-aggregator").exists())
        self.assertTrue(AIToolRegistry.objects.filter(name="mcp-comparator").exists())

    def test_read_only_false_ditolak(self):
        tool = AIToolRegistry(
            name="mcp-write-test",
            mcp_endpoint_url="internal://x",
            read_only=False,
        )

        with self.assertRaises(ValidationError):
            tool.save()

    def test_name_immutable(self):
        tool = AIToolRegistry.objects.get(name="mcp-calculator")
        tool.name = "mcp-calculator-baru"

        with self.assertRaises(ValidationError):
            tool.save()

    def test_seed_idempoten(self):
        path = (
            Path(__file__).resolve().parents[2]
            / "integrations/ai_agent/migrations/0002_seed_tools.py"
        )
        spec = importlib.util.spec_from_file_location("seed_tools", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        module.seed_tools(django_apps, None)

        self.assertEqual(AIToolRegistry.objects.count(), 12)


class DecisionLogTests(TestCase):
    def test_create_read_ordering(self):
        first = AIDecisionLog.objects.create(
            query_text="pertama", decision_gate_result="RULE_HIT"
        )
        second = AIDecisionLog.objects.create(
            query_text="kedua", decision_gate_result="LLM_NEEDED"
        )

        logs = list(AIDecisionLog.objects.all())

        self.assertEqual(logs[0].pk, second.pk)
        self.assertEqual(logs[1].pk, first.pk)


class HitlQueueTests(TestCase):
    def setUp(self):
        self.log = AIDecisionLog.objects.create(
            query_text="ubah stok", decision_gate_result="LLM_NEEDED"
        )

    def test_status_default_pending(self):
        queue = AIHitlQueue.objects.create(
            decision_log=self.log,
            risk_level="HIGH",
            required_approver_role="SUPERVISOR",
            channel="WA",
            expires_at=timezone.now() + timedelta(hours=24),
        )

        self.assertEqual(queue.status, "PENDING")

    def test_cascade_delete(self):
        AIHitlQueue.objects.create(
            decision_log=self.log,
            risk_level="HIGH",
            required_approver_role="SUPERVISOR",
            channel="WA",
            expires_at=timezone.now() + timedelta(hours=1),
        )

        self.log.delete()

        self.assertEqual(AIHitlQueue.objects.count(), 0)


class SemanticCacheModelTests(TestCase):
    def test_create_read(self):
        row = AISemanticCache.objects.create(
            query_normalized_text="berapa scrap rate",
            response_text="3.4%",
            expires_at=timezone.now() + timedelta(minutes=5),
        )

        self.assertEqual(AISemanticCache.objects.get(pk=row.pk).hit_count, 0)


class ConfigAndAppTests(TestCase):
    def test_config_mengikuti_env(self):
        # Fase 5: AI_AGENT_ENABLED=true di .env; config harus konsisten.
        self.assertEqual(AI_CONFIG["enabled"], bool(settings.AI_AGENT_ENABLED))

    def test_app_ready_tanpa_error(self):
        config = django_apps.get_app_config("ai_agent")

        config.ready()

        # Sprint D: 4 MCP terdaftar (naik ke 8 setelah Sprint G).
        self.assertEqual(mcp_registry.discover_mcp_servers(), 10)
        self.assertIn("mcp-analytics", mcp_registry.list_mcp())
