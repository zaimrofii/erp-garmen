"""Test Fase 3.6 — kandidat ranking produk, raw total query, cache clear."""

from __future__ import annotations

import time
from io import StringIO
from types import SimpleNamespace

from django.core.management import call_command
from django.test import TestCase

from apps_industry.garment.models import Order
from core.auth.models import Role, User
from integrations.ai_agent.api.handlers.clarification import handle_pending_clarification
from integrations.ai_agent.clarification import pending_state
from integrations.ai_agent.memory import semantic_cache
from integrations.ai_agent.orchestrator.chart_builder import build_chart_data
from integrations.ai_agent.orchestrator.context_builder import build_context
from master.models import Partner

METRICS = [
    {
        "metric_id": "garment.scrap_rate",
        "dimension": "period",
        "unit": "%",
        "rows": [
            {"label": "2026-10-18", "value": 1.6},
            {"label": "2026-10-19", "value": 2.0},
            {"label": "2026-10-20", "value": 2.4},
        ],
    }
]


class Fase36Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_big_test", stdout=StringIO())
        # Seed test DB = 50 order / 10 customer; samakan dengan DB recon.
        for index in range(23):
            Order.objects.create(
                code=f"FASE36-ORDER-{index:03d}",
                state="DRAFT",
            )
        for index in range(15):
            Partner.objects.get_or_create(
                code=f"FASE36-CUST-{index:02d}",
                defaults={"name": f"Customer Fase 36 {index}", "is_customer": True},
            )
        cls.owner = User.objects.filter(role__code="OWNER").first()
        if cls.owner is None:
            cls.owner = User.objects.create_user(
                username="fase36-owner",
                password="x",
                role=Role.objects.get(code=Role.Code.OWNER),
            )

    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        pending_state.clear(self.owner.pk, "fase36")

    def context(self, message: str, history=None):
        return build_context(
            "DATA_LOOKUP",
            ["mcp-postgres-query"],
            message,
            {},
            user=self.owner,
            history=history or [],
        )

    def test_termahal_candidates_20(self):
        data = self.context("termahal?")
        self.assertEqual(len(data.get("_ranking_candidates") or []), 20)
        self.assertNotIn("_candidates", data)

    def test_kedua_rank_2(self):
        candidates = self.context("termahal?")["_ranking_candidates"]
        state = pending_state.load(self.owner.pk, "fase36")
        if state is None:
            pending_state.save(
                self.owner.pk,
                "fase36",
                {"candidates": candidates, "original_query": "termahal?", "turn_count": 0},
            )
        request = SimpleNamespace(user=self.owner)
        self.assertIsNone(
            handle_pending_clarification(
                request, "kedua?", session_id="fase36", started=time.monotonic()
            )
        )
        state = pending_state.load(self.owner.pk, "fase36")
        self.assertEqual(state["selected_id"], candidates[1]["id"])

    def test_keempat_rank_4_setelah_kedua(self):
        candidates = self.context("termahal?")["_ranking_candidates"]
        pending_state.save(
            self.owner.pk,
            "fase36",
            {"candidates": candidates, "original_query": "termahal?", "turn_count": 0},
        )
        request = SimpleNamespace(user=self.owner)
        for message in ("kedua?", "keempat?"):
            self.assertIsNone(
                handle_pending_clarification(
                    request, message, session_id="fase36", started=time.monotonic()
                )
            )
        state = pending_state.load(self.owner.pk, "fase36")
        self.assertEqual(state["successful_rank_count"], 2)
        self.assertEqual(state["selected_id"], candidates[3]["id"])

    def test_kelima_rank_5(self):
        candidates = self.context("termahal?")["_ranking_candidates"]
        pending_state.save(
            self.owner.pk,
            "fase36",
            {"candidates": candidates, "original_query": "termahal?", "turn_count": 0},
        )
        request = SimpleNamespace(user=self.owner)
        for message in ("kedua?", "keempat?", "kelima?"):
            self.assertIsNone(
                handle_pending_clarification(
                    request, message, session_id="fase36", started=time.monotonic()
                )
            )
        state = pending_state.load(self.owner.pk, "fase36")
        self.assertEqual(state["successful_rank_count"], 3)
        self.assertEqual(state["selected_id"], candidates[4]["id"])

    def test_lupakan_total_order_73_bukan_20(self):
        history = [
            {"role": "user", "content": "produk termahal?"},
            {"role": "assistant", "content": "20 order DRAFT"},
        ]
        data = self.context("lupakan, berapa total order?", history=history)
        self.assertEqual(data["total_counts"]["total"], 73)
        self.assertNotIn("orders", data)

    def test_lupakan_total_bundle_200(self):
        data = self.context("lupakan, berapa bundle?")
        self.assertEqual(data["total_counts"]["total"], 200)

    def test_batal_total_customer_25(self):
        data = self.context("batal, total customer?")
        self.assertEqual(data["total_counts"]["total"], 25)

    def test_batal_tren_scrap_chart(self):
        chart = build_chart_data(
            {"metrics": METRICS}, "ANALYTICS_QUERY", "batal, tren scrap?"
        )
        self.assertIsNotNone(chart)
        self.assertEqual(chart["metric_id"], "garment.scrap_rate")

    def test_clear_semantic_cache_command(self):
        semantic_cache.set("fase36-cache", {"ok": True, "answer": "lama"})
        call_command("clear_semantic_cache", stdout=StringIO())
        self.assertIsNone(semantic_cache.get("fase36-cache"))

