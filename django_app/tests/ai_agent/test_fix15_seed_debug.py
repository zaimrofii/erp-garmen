"""Test Fix #15 — seed produk realistis, over-execute, fallback attrs kosong."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from core.auth.models import Role, User
from integrations.ai_agent.clarification import pending_state, templates
from integrations.ai_agent.demo_products import DEMO_POLOS_PRODUCTS, ensure_demo_polos_products
from master.models import Product

URL = "/api/v1/ai/chat"
PROVIDER = "integrations.ai_agent.orchestrator.response_synthesizer.get_llm_provider"
INTENT = "integrations.ai_agent.api.views.intent_classifier.classify"
TOOLS = "integrations.ai_agent.api.views.tool_selector.select_tools"

CODES = [spec[0] for spec in DEMO_POLOS_PRODUCTS]
PENDING_CANDIDATES = [
    {
        "id": index,
        "label": "Kaos Polos",
        "attrs": {"harga": "Rp50.000", "kategori": "Kaos"},
        "score": 0.7,
        "entity": "product",
    }
    for index in range(1, 6)
]


class SeedDemoProductsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_demo_polos_products()

    def test_semua_harga_di_atas_nol(self):
        rows = Product.objects.filter(code__in=CODES)

        self.assertEqual(rows.count(), len(DEMO_POLOS_PRODUCTS))
        for row in rows:
            self.assertGreater(row.sale_price, Decimal("0"))

    def test_semua_kategori_kaos(self):
        rows = Product.objects.filter(code__in=CODES)

        self.assertEqual({row.category for row in rows}, {"Kaos"})

    def test_nama_produk_berbeda(self):
        names = list(
            Product.objects.filter(code__in=CODES).values_list("name", flat=True)
        )
        expected = len(DEMO_POLOS_PRODUCTS)

        self.assertEqual(len(names), expected)
        self.assertEqual(len(set(names)), expected)


@override_settings(AI_AGENT_ENABLED=True)
class OverExecuteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.role = Role.objects.get(code=Role.Code.SUPERVISOR)
        ensure_demo_polos_products()

    def setUp(self):
        super().setUp()
        cache.clear()
        self.user = User.objects.create_user(
            username="fix15-user", password="x", role=self.role
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

    def _fake(self, text: str) -> SimpleNamespace:
        return SimpleNamespace(
            text=text,
            prompt_tokens=10,
            completion_tokens=5,
            total_cost_usd=0.001,
            model="deepseek-chat",
            latency_ms=12,
        )

    def test_harga_kaos_polos_ambiguous(self):
        with patch(PROVIDER) as provider:
            response = self.api.post(
                URL, {"message": "berapa harga kaos polos?"}, format="json"
            )

        body = response.json()

        self.assertIn("Ada 5 yang cocok:", body["answer"])
        self.assertIn("Rp50.000, kategori Kaos", body["answer"])
        self.assertEqual(body["decision_gate_result"], "RULE_HIT")
        provider.assert_not_called()

    def test_harga_kaos_polos_dengan_spasi_tetap_ambiguous(self):
        with patch(PROVIDER) as provider:
            response = self.api.post(
                URL, {"message": "berapa harga kaos polos ?"}, format="json"
            )

        body = response.json()

        self.assertIn("Ada 5 yang cocok:", body["answer"])
        self.assertNotIn("ODOO-66", body["answer"])
        provider.assert_not_called()

    def test_harga_nama_spesifik_exact(self):
        answer = "Kaos Polos Cotton Combed 30s harganya Rp50.000."

        with patch(PROVIDER) as provider:
            provider.return_value.complete.return_value = self._fake(answer)
            response = self.api.post(
                URL,
                {"message": "harga kaos polos cotton combed 30s?"},
                format="json",
            )

        body = response.json()

        self.assertEqual(body["answer"], answer)
        self.assertEqual(body["decision_gate_result"], "LLM_NEEDED")
        provider.return_value.complete.assert_called_once()

    def test_pertanyaan_berulang_saat_state_aktif_tidak_over_execute(self):
        pending_state.save(
            self.user.pk,
            self.session_id,
            {
                "candidates": PENDING_CANDIDATES,
                "original_query": "berapa harga kaos polos?",
                "question": "Yang mana?",
                "turn_count": 0,
                "entity": "product",
            },
        )

        with patch(PROVIDER) as provider:
            response = self.api.post(
                URL, {"message": "berapa harga kaos polos ?"}, format="json"
            )

        body = response.json()

        self.assertIn("Ada 5 yang cocok:", body["answer"])
        provider.assert_not_called()
        state = pending_state.load(self.user.pk, self.session_id)
        self.assertEqual(len(state["candidates"]), 5)

class AttrFallbackTests(SimpleTestCase):
    def _candidate(self, index: int, **attrs):
        return {"id": index, "label": "Kaos Polos", "attrs": attrs, "score": 0.7}

    def test_attrs_placeholder_fallback_dan_catatan(self):
        candidates = [
            self._candidate(
                index,
                kode=f"ODOO-{64 + index}",
                harga="harga belum diisi",
                kategori="tanpa kategori",
            )
            for index in range(1, 6)
        ]

        text = templates.ambiguous_question(candidates)

        self.assertIn("Ada 5 yang cocok:", text)
        self.assertIn("(1) Kaos Polos", text)
        self.assertIn("data pembeda (harga, kategori) belum lengkap", text)
        self.assertIn("Yang mana?", text)
        self.assertNotIn("ODOO-65", text)

    def test_attrs_lengkap_format_bukti(self):
        prices = ["Rp50.000", "Rp75.000", "Rp45.000", "Rp60.000", "Rp35.000"]
        candidates = [
            self._candidate(index, harga=price, kategori="Kaos")
            for index, price in enumerate(prices, start=1)
        ]

        text = templates.ambiguous_question(candidates)

        self.assertTrue(text.startswith("Ada 5 Kaos Polos:"))
        self.assertIn("(1) Rp50.000, kategori Kaos", text)
        self.assertIn("(2) Rp75.000, kategori Kaos", text)

    def test_harga_nol_jadi_placeholder(self):
        from integrations.ai_agent.orchestrator import context_builder

        self.assertEqual(context_builder._format_rupiah(0), "harga belum diisi")
        self.assertEqual(context_builder._format_rupiah(None), "harga belum diisi")
        self.assertEqual(
            context_builder._format_rupiah(Decimal("50000")), "Rp50.000"
        )

