"""Test Fix #13 — anti over-clarification (kode spesifik, agregat, harga)."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from core.auth.models import Role, User
from integrations.ai_agent.clarification import EpistemicStatus, classify
from integrations.ai_agent.orchestrator import context_builder
from master.models import Product

USER = SimpleNamespace(role=SimpleNamespace(code="ADMIN"))

CANDIDATES = [
    {"id": 1, "label": "Kaos A", "attrs": {}, "score": 0.7, "entity": "product"},
    {"id": 2, "label": "Kaos B", "attrs": {}, "score": 0.7, "entity": "product"},
    {"id": 3, "label": "Kaos C", "attrs": {}, "score": 0.7, "entity": "product"},
]


class SpecificCodeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Product.objects.create(
            code="KPP-DEWASA-V2", name="KPP Dewasa V2", sale_price=Decimal("75000")
        )
        Product.objects.create(
            code="FG-KAOS-001", name="Kaos Polos", sale_price=Decimal("50000")
        )

    def _build(self, message: str) -> dict:
        return context_builder.build_context("DATA_LOOKUP", [], message, {}, user=USER)

    def test_kode_spesifik_satu_hasil_exact(self):
        data = self._build("produk KPP-DEWASA-V2?")

        self.assertEqual(len(data["_candidates"]), 1)
        self.assertEqual(data["_candidates"][0]["score"], 0.95)
        self.assertEqual(data["_candidates"][0]["label"], "KPP Dewasa V2")
        self.assertEqual(
            classify(data["_candidates"], "produk KPP-DEWASA-V2?").status,
            EpistemicStatus.EXACT,
        )

    def test_kode_fg_kaos_diambil_dengan_detail(self):
        data = self._build("produk FG-KAOS-001?")

        self.assertEqual(len(data["_candidates"]), 1)
        self.assertEqual(data["product_list"][0]["code"], "FG-KAOS-001")
        self.assertEqual(data["_entity_label"], "produk")

    def test_kode_tidak_ada_tetap_empty(self):
        data = self._build("produk XYZ-999?")

        self.assertEqual(data["_candidates"], [])
        self.assertEqual(data["_entity_label"], "produk")
        self.assertEqual(
            classify(data["_candidates"], "produk XYZ-999?").status,
            EpistemicStatus.EMPTY,
        )


class AggregateTests(SimpleTestCase):
    def test_line_tidak_seimbang_agregat_exact(self):
        message = "line mana tidak seimbang?"

        self.assertTrue(context_builder.is_aggregate_query(message))
        self.assertEqual(
            classify(CANDIDATES, message, is_aggregate_query=True).status,
            EpistemicStatus.EXACT,
        )

    def test_bottleneck_agregat_exact(self):
        message = "bottleneck di mana?"

        self.assertTrue(context_builder.is_aggregate_query(message))
        self.assertEqual(
            classify(CANDIDATES, message, is_aggregate_query=True).status,
            EpistemicStatus.EXACT,
        )

    def test_top_customer_agregat_exact(self):
        message = "top 3 customer?"

        self.assertTrue(context_builder.is_aggregate_query(message))
        self.assertEqual(
            classify(CANDIDATES, message, is_aggregate_query=True).status,
            EpistemicStatus.EXACT,
        )

class PriceLookupTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Product.objects.create(
            code="FG-KAOS-001", name="Kaos Polos", sale_price=Decimal("50000")
        )
        Product.objects.create(
            code="FG-KEMEJA-001", name="Kemeja Formal", sale_price=Decimal("120000")
        )

    def _build(self, message: str) -> dict:
        return context_builder.build_context("DATA_LOOKUP", [], message, {}, user=USER)

    def test_berapa_harga_kaos_polos_ambil_produk(self):
        data = self._build("berapa harga kaos polos?")

        self.assertIn("product_list", data)
        self.assertEqual(data["product_list"][0]["name"], "Kaos Polos")
        self.assertEqual(len(data["_candidates"]), 1)
        self.assertEqual(data["_candidates"][0]["score"], 0.95)

    def test_harga_kemeja_formal_ambil_produk(self):
        data = self._build("harga kemeja formal?")

        self.assertIn("product_list", data)
        self.assertEqual(data["product_list"][0]["name"], "Kemeja Formal")

    def test_harga_produk_tidak_ada_empty(self):
        data = self._build("harga produk X?")

        self.assertEqual(data["_candidates"], [])
        self.assertEqual(
            classify(data["_candidates"], "harga produk X?").status,
            EpistemicStatus.EMPTY,
        )


URL = "/api/v1/ai/chat"
PROVIDER = "integrations.ai_agent.orchestrator.response_synthesizer.get_llm_provider"
INTENT = "integrations.ai_agent.api.views.intent_classifier.classify"
TOOLS = "integrations.ai_agent.api.views.tool_selector.select_tools"


@override_settings(AI_AGENT_ENABLED=True)
class ChatOverClarificationE2ETests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.role = Role.objects.get(code=Role.Code.SUPERVISOR)
        Product.objects.create(
            code="KPP-DEWASA-V2", name="KPP Dewasa V2", sale_price=Decimal("75000")
        )

    def setUp(self):
        super().setUp()
        cache.clear()
        self.user = User.objects.create_user(
            username="fix13-user", password="x", role=self.role
        )
        self.api = APIClient()
        self.api.force_authenticate(self.user)

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

    def _fake(self, text: str) -> SimpleNamespace:
        return SimpleNamespace(
            text=text,
            prompt_tokens=10,
            completion_tokens=5,
            total_cost_usd=0.001,
            model="deepseek-chat",
            latency_ms=12,
        )

    def test_chat_kode_spesifik_dijawab_bukan_empty(self):
        answer = "Produk KPP Dewasa V2 harga Rp75.000."

        with patch(PROVIDER) as provider:
            provider.return_value.complete.return_value = self._fake(answer)
            response = self.api.post(
                URL, {"message": "produk KPP-DEWASA-V2?"}, format="json"
            )

        body = response.json()

        self.assertEqual(body["answer"], answer)
        self.assertEqual(body["decision_gate_result"], "LLM_NEEDED")
        self.assertNotIn("Tidak ada produk", body["answer"])
        provider.return_value.complete.assert_called_once()

    def test_chat_line_tidak_seimbang_dijawab_bukan_tanya(self):
        answer = "Line B paling tidak seimbang (0.45)."

        with patch(PROVIDER) as provider:
            provider.return_value.complete.return_value = self._fake(answer)
            response = self.api.post(
                URL, {"message": "line mana tidak seimbang?"}, format="json"
            )

        body = response.json()

        self.assertEqual(body["answer"], answer)
        self.assertNotIn("Yang mana?", body["answer"])
        provider.return_value.complete.assert_called_once()

    def test_chat_bottleneck_dijawab_bukan_tanya(self):
        answer = "SEWING-2 bottleneck: buffer 25, avg wait 2.5 jam."

        with patch(PROVIDER) as provider:
            provider.return_value.complete.return_value = self._fake(answer)
            response = self.api.post(
                URL, {"message": "bottleneck di mana?"}, format="json"
            )

        body = response.json()

        self.assertEqual(body["answer"], answer)
        self.assertNotIn("Yang mana?", body["answer"])
        provider.return_value.complete.assert_called_once()

