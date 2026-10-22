"""Acceptance Fase 6 — HITL chat, FG filter, cache consistency, chart relevance."""

from __future__ import annotations

import json
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.models import Order
from core.auth.models import Role, User
from integrations.ai_agent.models import AIHitlQueue
from integrations.analytics.services import analytics_config_services
from master.models import Partner, Product

URL = "/api/v1/ai/chat"


def _data(prompt: str) -> dict:
    marker = "DATA DARI SISTEM:"
    if marker not in prompt:
        return {}
    text = prompt.split(marker, 1)[1].strip()
    try:
        value, _ = json.JSONDecoder().raw_decode(text)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


SUGGEST_JSON = json.dumps(
    {
        "problem": "scrap tinggi di SEWING-2",
        "proposed_actions": [
            {
                "action": "rework BND-F6-1",
                "impact": "MEDIUM",
                "confidence": 0.82,
                "reason": "scrap 8.4%",
            },
            {
                "action": "audit proses SEWING-2",
                "impact": "MEDIUM",
                "confidence": 0.74,
                "reason": "scrap berulang",
            },
        ],
    }
)


class FakeProvider:
    """Mock LLM: suggestion JSON atau jawaban ringkas dari context."""

    def complete(self, *, system_prompt=None, user_prompt=None, max_tokens=None):
        prompt = str(system_prompt or "")
        if "proposed_actions" in prompt or "HANYA JSON" in prompt:
            answer = SUGGEST_JSON
        else:
            data = _data(user_prompt or "")
            if isinstance(data.get("total_counts"), dict):
                total = data["total_counts"]
                answer = f"Total {total.get('label', 'data')} {total.get('total')}."
            elif isinstance(data.get("metrics"), list):
                answer = "Tren scrap tersedia."
            else:
                answer = "Data tidak cukup."

        return SimpleNamespace(
            text=answer,
            prompt_tokens=1,
            completion_tokens=1,
            total_cost_usd=0,
            model="mock",
            latency_ms=1,
        )


class AcceptanceFase6Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_big_test", stdout=StringIO())
        # Samakan dengan angka acceptance: 50 seed + 23 fixture = 73 order.
        for index in range(23):
            Order.objects.create(code=f"F6-ORDER-{index:03d}", state="DRAFT")
        for index in range(15):
            Partner.objects.get_or_create(
                code=f"F6-CUST-{index:02d}",
                defaults={
                    "name": f"Customer Fase 6 {index}",
                    "is_customer": True,
                },
            )
        Product.objects.create(
            code="RM-MAHAL-F6",
            name="Kain Sutra F6",
            sale_price=9000000,
            cost_price=9000000,
            category="Material",
            is_active=True,
        )
        Product.objects.create(
            code="FG-MAHAL-F6",
            name="Jaket Premium F6",
            sale_price=500000,
            cost_price=300000,
            category="Jaket",
            is_active=True,
        )
        Product.objects.create(
            code="RM-MURAH-F6",
            name="Kain Murah F6",
            sale_price=1,
            cost_price=1,
            category="Material",
            is_active=True,
        )
        Product.objects.create(
            code="FG-MURAH-F6",
            name="Kaos Murah F6",
            sale_price=10000,
            cost_price=7000,
            category="Kaos",
            is_active=True,
        )
        cls.owner = User.objects.create_user(
            username="f6-owner",
            password="x",
            role=Role.objects.get(code=Role.Code.OWNER),
        )

    def setUp(self):
        cache.clear()
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        self.history = []

        def classify(message):
            text = str(message or "").lower()
            if "setujui" in text:
                return {"intent": "DATA_LOOKUP", "confidence": 0.9, "cost_usd": 0}
            if "apa yang harus" in text:
                return {"intent": "SUGGEST_ACTION", "confidence": 0.9, "cost_usd": 0}
            if "tren" in text or "scrap" in text:
                return {"intent": "ANALYTICS_QUERY", "confidence": 0.9, "cost_usd": 0}
            return {"intent": "DATA_LOOKUP", "confidence": 0.9, "cost_usd": 0}

        self.patches = [
            patch(
                "integrations.ai_agent.api.views.intent_classifier.classify",
                side_effect=classify,
            ),
            patch(
                "integrations.ai_agent.orchestrator.response_synthesizer.get_llm_provider",
                return_value=FakeProvider(),
            ),
            patch.object(
                analytics_config_services,
                "analytics_enabled",
                return_value=True,
            ),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def chat(self, message: str) -> dict:
        response = self.api.post(
            URL,
            {"message": message, "history": self.history},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.history.extend(
            [
                {"role": "user", "content": message},
                {"role": "assistant", "content": body.get("answer", "")},
            ]
        )
        return body

    def test_01_suggest_action_creates_hitl(self):
        response = self.chat("apa yang harus saya lakukan untuk scrap tinggi?")

        self.assertTrue(response["hitl_required"])
        self.assertIsNotNone(response["hitl_request_id"])

    def test_02_approve_action_via_chat(self):
        self.chat("apa yang harus saya lakukan untuk scrap tinggi?")
        response = self.chat("setujui aksi itu")

        answer = response["answer"].lower()
        self.assertTrue("disetujui" in answer or "approved" in answer)
        hitl = AIHitlQueue.objects.latest("created_at")
        self.assertEqual(hitl.status, "APPROVED")

    def test_03_produk_termahal_hanya_fg(self):
        answer = self.chat("produk termahal?")["answer"]

        self.assertIn("Jaket Premium F6", answer)
        self.assertNotIn("Kain Sutra F6", answer)

    def test_04_produk_termurah_hanya_fg(self):
        answer = self.chat("produk termurah?")["answer"]

        self.assertIn("Kaos Murah F6", answer)
        self.assertNotIn("Kain Murah F6", answer)

    def test_05_total_order_tiga_kali_sama_73(self):
        answers = [self.chat("total order?")["answer"] for _ in range(3)]

        self.assertTrue(all("73" in answer for answer in answers), answers)
        self.assertEqual(len(set(answers)), 1)

    def test_06_total_order_setelah_cache_expired_sama_73(self):
        first = self.chat("total order?")["answer"]
        cache.clear()  # simulasi TTL 5 menit habis
        second = self.chat("total order?")["answer"]

        self.assertEqual(first, second)
        self.assertIn("73", second)

    def test_07_total_order_tanpa_chart(self):
        body = self.chat("total order?")

        self.assertIsNone(body.get("chart_data"))

    def test_08_tren_scrap_ada_chart(self):
        body = self.chat("tren scrap?")

        self.assertIsNotNone(body.get("chart_data"))
        self.assertEqual(body["chart_data"]["metric_id"], "garment.scrap_rate")
