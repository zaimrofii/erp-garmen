"""Test Fix #17 — state lifecycle, top N customer, dan count query."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps_industry.garment.tests.factories import make_order, make_order_line
from core.auth.models import Role, User
from integrations.ai_agent.clarification import pending_state
from integrations.ai_agent.demo_products import ensure_demo_polos_products
from integrations.ai_agent.orchestrator import context_builder
from master.models import Partner, Product

URL = "/api/v1/ai/chat"
BUILD = "integrations.ai_agent.api.views.context_builder.build_context"
PROVIDER = "integrations.ai_agent.orchestrator.response_synthesizer.get_llm_provider"
INTENT = "integrations.ai_agent.api.views.intent_classifier.classify"
TOOLS = "integrations.ai_agent.api.views.tool_selector.select_tools"

USER = SimpleNamespace(role=SimpleNamespace(code="ADMIN"))


def _context() -> dict:
    return {"intent": "DATA_LOOKUP", "message": "uji", "context": {}, "tools": []}


@override_settings(AI_AGENT_ENABLED=True)
class StateLifecycleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.role = Role.objects.get(code=Role.Code.SUPERVISOR)
        cls.products = [
            Product.objects.create(
                code=f"ODOO-{70 + index}",
                name=f"Kaos Uji {index}",
                category="Kaos",
                sale_price=Decimal("50000"),
            )
            for index in range(5)
        ]

    def setUp(self):
        super().setUp()
        cache.clear()
        self.user = User.objects.create_user(
            username="fix17-user", password="x", role=self.role
        )
        self.api = APIClient()
        self.api.force_authenticate(self.user)
        self.session_id = f"user-{self.user.pk}"

        self.intent_patch = patch(
            INTENT,
            return_value={"intent": "DATA_LOOKUP", "confidence": 0.9, "cost_usd": 0},
        )
        self.tools_patch = patch(TOOLS, return_value=[])
        self.intent_patch.start()
        self.tools_patch.start()

    def tearDown(self):
        self.intent_patch.stop()
        self.tools_patch.stop()
        super().tearDown()

    def _save_pending(self, turn_count: int = 0) -> None:
        pending_state.save(
            self.user.pk,
            self.session_id,
            {
                "candidates": [
                    {
                        "id": product.pk,
                        "label": product.name,
                        "attrs": {"harga": "Rp50.000", "kategori": "Kaos"},
                        "score": 0.7,
                        "entity": "product",
                    }
                    for product in self.products
                ],
                "original_query": "kaos mana?",
                "question": "Yang mana?",
                "turn_count": turn_count,
                "entity": "product",
            },
        )

    def _fake(self, text: str) -> SimpleNamespace:
        return SimpleNamespace(
            text=text,
            prompt_tokens=10,
            completion_tokens=5,
            total_cost_usd=0.001,
            model="deepseek-chat",
            latency_ms=12,
        )

    def test_state_tetap_hidup_setelah_rank(self):
        self._save_pending()

        with patch(BUILD, return_value=_context()), patch(PROVIDER) as provider:
            provider.return_value.complete.return_value = self._fake("Jawaban.")
            response = self.api.post(URL, {"message": "yg kedua"}, format="json")

        self.assertEqual(response.status_code, 200)
        state = pending_state.load(self.user.pk, self.session_id)
        self.assertIsNotNone(state)
        self.assertEqual(state["turn_count"], 1)
        self.assertEqual(len(state["candidates"]), 5)

    def test_yg_ke_3_setelah_rank(self):
        self._save_pending()
        captured: dict = {}

        def builder(_intent, _tools, _message, context=None, **_kwargs):
            captured.update(context or {})
            return _context()

        with patch(BUILD, side_effect=builder), patch(PROVIDER) as provider:
            provider.return_value.complete.return_value = self._fake("Jawaban.")
            self.api.post(URL, {"message": "yg kedua"}, format="json")
            response = self.api.post(URL, {"message": "yg ke 3 ?"}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured["_resolved_candidate"]["id"], self.products[2].pk)
        self.assertEqual(
            pending_state.load(self.user.pk, self.session_id)["turn_count"], 2
        )

    def test_yg_keempat_setelah_rank(self):
        self._save_pending()
        captured: dict = {}

        def builder(_intent, _tools, _message, context=None, **_kwargs):
            captured.update(context or {})
            return _context()

        with patch(BUILD, side_effect=builder), patch(PROVIDER) as provider:
            provider.return_value.complete.return_value = self._fake("Jawaban.")
            self.api.post(URL, {"message": "yg kedua"}, format="json")
            response = self.api.post(URL, {"message": "yg keempat"}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured["_resolved_candidate"]["id"], self.products[3].pk)

    def test_cancel_setelah_rank_membersihkan_state(self):
        self._save_pending()

        with patch(BUILD, return_value=_context()), patch(PROVIDER) as provider:
            provider.return_value.complete.return_value = self._fake("Jawaban.")
            self.api.post(URL, {"message": "yg kedua"}, format="json")
            response = self.api.post(URL, {"message": "bukan itu"}, format="json")

        self.assertIn("lupakan", response.json()["answer"])
        self.assertIsNone(pending_state.load(self.user.pk, self.session_id))

class TopCustomerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        for index in range(1, 5):
            customer = Partner.objects.create(
                code=f"CUST-T{index}",
                name=f"PT Pelanggan {index}",
                city="Jakarta",
            )
            order = make_order(code=f"SO-TOP-{index}", customer=customer)
            make_order_line(order=order, qty=10, price_unit=Decimal("100000"))

    def _build(self, message: str) -> dict:
        return context_builder.build_context(
            "ANALYTICS_QUERY", [], message, {}, user=USER
        )

    def test_top_3_customer(self):
        data = self._build("top 3 customer?")

        self.assertTrue(data["_aggregate_query"])
        self.assertIn("customer_total_spend", data)
        self.assertLessEqual(len(data["customer_total_spend"]), 3)

    def test_customer_terbaik(self):
        data = self._build("customer terbaik?")

        self.assertIn("customer_total_spend", data)
        self.assertTrue(data["_aggregate_query"])

    def test_top_customer(self):
        data = self._build("top customer")

        self.assertIn("customer_total_spend", data)
        self.assertEqual(data["_top_query"], {"entity": "customer", "limit": 10})


class CountQueryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_demo_polos_products()
        for index in range(1, 5):
            make_order(code=f"RICH-ORDER-{index}")
        for index in range(1, 4):
            Partner.objects.create(
                code=f"CUST-JKT-{index}",
                name=f"PT JKT {index}",
                city="Jakarta",
            )

    def _build(self, message: str) -> dict:
        return context_builder.build_context(
            "DATA_LOOKUP", [], message, {}, user=USER
        )

    def test_lima_produk_kaos_polos(self):
        data = self._build("5 produk kaos polos")

        self.assertTrue(data["_aggregate_query"])
        self.assertEqual(len(data["product_list"]), 5)
        self.assertNotIn("_candidates", data)
        self.assertEqual(data["requested_count"], 5)

    def test_tiga_order_rich(self):
        data = self._build("3 order RICH")

        self.assertEqual(len(data["orders"]), 3)
        self.assertTrue(data["_aggregate_query"])

    def test_dua_customer_jakarta(self):
        data = self._build("2 customer jakarta")

        self.assertEqual(len(data["partners"]), 2)
        self.assertTrue(data["_aggregate_query"])


