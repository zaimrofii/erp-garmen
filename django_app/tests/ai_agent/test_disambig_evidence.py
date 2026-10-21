"""Test Fix #14 — disambiguasi berbasis bukti (harga/kategori), bukan kode."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from core.auth.models import Role, User
from integrations.ai_agent.clarification import resolver, templates
from integrations.ai_agent.clarification.resolver import ResolutionType
from integrations.ai_agent.orchestrator import context_builder
from integrations.ai_agent.orchestrator.text_normalizer import normalize
from master.models import Product

USER = SimpleNamespace(role=SimpleNamespace(code="ADMIN"))


def _candidate(candidate_id=1, label="Kaos Polos", **attrs):
    return {"id": candidate_id, "label": label, "attrs": attrs, "score": 0.7}


class CandidateAttrsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        for index, price in enumerate((50000, 60000, 70000, 80000, 90000), 1):
            Product.objects.create(
                code=f"ODOO-{60 + index}",
                name="Kaos Polos",
                category="Kaos",
                sale_price=Decimal(str(price)),
            )

    def _candidates(self):
        rows = context_builder.get_repo("product").get_list(limit=20)
        return context_builder._collect_candidates(
            normalize("produk kaos polos"), {"product_list": rows}
        )

    def test_candidates_produk_punya_harga_dan_kategori(self):
        candidates, entity = self._candidates()

        self.assertEqual(entity, "product")
        self.assertEqual(len(candidates), 5)
        for candidate in candidates:
            self.assertIn("harga", candidate["attrs"])
            self.assertIn("kategori", candidate["attrs"])

    def test_candidates_produk_tanpa_kode(self):
        candidates, _entity = self._candidates()

        for candidate in candidates:
            attrs = candidate["attrs"]
            self.assertNotIn("kode", attrs)
            self.assertNotIn("code", attrs)
            self.assertNotIn("id", attrs)

    def test_harga_format_rupiah_titik(self):
        candidates, _entity = self._candidates()
        prices = {candidate["attrs"]["harga"] for candidate in candidates}

        self.assertIn("Rp50.000", prices)
        self.assertIn("Rp90.000", prices)
        self.assertNotIn("Rp50,000", prices)


class AmbiguousEvidenceTests(SimpleTestCase):
    def test_header_label_sama(self):
        candidates = [
            _candidate(1, harga="Rp50.000", kategori="Kaos"),
            _candidate(2, harga="Rp60.000", kategori="Kaos"),
            _candidate(3, harga="Rp70.000", kategori="Kaos"),
            _candidate(4, harga="Rp80.000", kategori="Kaos"),
            _candidate(5, harga="Rp90.000", kategori="Kaos"),
        ]

        text = templates.ambiguous_question(candidates)

        self.assertTrue(text.startswith("Ada 5 Kaos Polos:"))
        self.assertIn("(1) Rp50.000, kategori Kaos", text)

    def test_entri_label_berbeda_tampil_nama_dan_bukti(self):
        candidates = [
            _candidate(1, "Kaos Polos Cotton", harga="Rp50.000", kategori="Kaos"),
            _candidate(2, "Kaos Polos Premium", harga="Rp75.000", kategori="Kaos"),
        ]

        text = templates.ambiguous_question(candidates)

        self.assertIn(
            "(1) Kaos Polos Cotton — Rp50.000, kategori Kaos", text
        )
        self.assertTrue(text.startswith("Ada 2 yang cocok:"))

    def test_kode_tidak_muncul_di_output(self):
        candidates = [
            _candidate(1, kode="ODOO-66", harga="Rp50.000", kategori="Kaos"),
            _candidate(2, kode="ODOO-67", harga="Rp75.000", kategori="Kaos"),
        ]

        text = templates.ambiguous_question(candidates)

        self.assertNotIn("ODOO-66", text)
        self.assertNotIn("ODOO-67", text)
        self.assertIn("Rp50.000", text)

    def test_weak_question_tanpa_kode(self):
        candidate = _candidate(
            1, "Kaos Polos Premium", kode="ODOO-99", harga="Rp75.000", kategori="Kaos"
        )

        text = templates.weak_question(candidate)

        self.assertEqual(
            text,
            "Apakah maksud Anda: Kaos Polos Premium — Rp75.000, kategori Kaos? (ya/tidak)",
        )
        self.assertNotIn("ODOO-99", text)


class ResolverAttrsTests(SimpleTestCase):
    def test_fuzzy_bisa_match_ke_harga(self):
        candidates = [
            _candidate(1, "Kaos Polos", harga="Rp50.000", kategori="Kaos"),
            _candidate(2, "Kaos Polos", harga="Rp75.000", kategori="Kaos"),
        ]

        result = resolver.resolve("Rp75.000", candidates)

        self.assertEqual(result.type, ResolutionType.FUZZY)
        self.assertEqual(result.candidate["id"], 2)

URL = "/api/v1/ai/chat"
PROVIDER = "integrations.ai_agent.orchestrator.response_synthesizer.get_llm_provider"
INTENT = "integrations.ai_agent.api.views.intent_classifier.classify"
TOOLS = "integrations.ai_agent.api.views.tool_selector.select_tools"


@override_settings(AI_AGENT_ENABLED=True)
class ChatEvidenceE2ETests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.role = Role.objects.get(code=Role.Code.SUPERVISOR)
        for index, price in enumerate((50000, 60000, 70000, 80000, 90000), 1):
            Product.objects.create(
                code=f"ODOO-{60 + index}",
                name="Kaos Polos",
                category="Kaos",
                sale_price=Decimal(str(price)),
            )

    def setUp(self):
        super().setUp()
        cache.clear()
        self.user = User.objects.create_user(
            username="fix14-user", password="x", role=self.role
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

    def test_chat_harga_kaos_polos_tampilkan_bukti_bukan_kode(self):
        with patch(PROVIDER) as provider:
            response = self.api.post(
                URL, {"message": "berapa harga kaos polos?"}, format="json"
            )

        body = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertIn("Ada 5 Kaos Polos:", body["answer"])
        self.assertIn("Rp50.000, kategori Kaos", body["answer"])
        self.assertNotIn("ODOO-66", body["answer"])
        self.assertEqual(body["decision_gate_result"], "RULE_HIT")
        self.assertEqual(body["tokens"]["total_cost_usd"], 0)
        provider.assert_not_called()

