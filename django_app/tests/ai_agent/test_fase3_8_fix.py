"""Regresi Fase 3.8 — ranking langsung dan safety guardrail eksplisit."""

from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase

from core.auth.models import Role, User
from integrations.ai_agent.orchestrator.context_builder import build_context
from integrations.ai_agent.orchestrator.response_synthesizer import synthesize
from master.models import Product


PRODUCTS = (
    ("REG-JAKET", "Jaket Bomber", 250000, "Jaket"),
    ("REG-DRESS", "Dress Casual", 175000, "Dress"),
    ("REG-DRESS-W", "Dress Casual Wanita", 175000, "Dress"),
    ("REG-CELANA", "Celana Chino", 160000, "Celana"),
    ("REG-KAIN", "Kain Rib (Collar)", 110000, "Material"),
)


class RankingRegressionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        for code, name, price, category in PRODUCTS:
            Product.objects.create(
                code=code,
                name=name,
                sale_price=price,
                cost_price=price,
                category=category,
                is_active=True,
            )
        cls.owner = User.objects.filter(role__code="OWNER").first() or User.objects.create_user(
            username="rank-reg-owner",
            password="x",
            role=Role.objects.get(code=Role.Code.OWNER),
        )

    def context(self):
        return build_context(
            "DATA_LOOKUP", ["mcp-postgres-query"], "termahal?", {}, user=self.owner
        )

    def test_termahal_jawab_langsung(self):
        data = self.context()
        with patch(
            "integrations.ai_agent.orchestrator.response_synthesizer.get_llm_provider"
        ) as provider:
            result = synthesize("termahal?", data, user=None)
        provider.assert_not_called()
        self.assertIn("Jaket Bomber", result["answer"])
        self.assertIn("250.000", result["answer"])
        self.assertNotIn("Yang mana?", result["answer"])

    def test_kandidat_kedua_dress_casual(self):
        ranking = self.context()["_ranking_candidates"]
        self.assertEqual(ranking[1]["label"], "Dress Casual")

    def test_kandidat_keempat_celana_chino(self):
        ranking = self.context()["_ranking_candidates"]
        self.assertEqual(ranking[3]["label"], "Celana Chino")

    def test_kandidat_kelima_kain_rib(self):
        ranking = self.context()["_ranking_candidates"]
        self.assertEqual(ranking[4]["label"], "Kain Rib (Collar)")


class SafetyRegressionTests(TestCase):
    def _answer(self, message: str) -> str:
        with patch(
            "integrations.ai_agent.orchestrator.response_synthesizer.get_llm_provider"
        ) as provider:
            result = synthesize(
                message, {"message": message, "context": {}, "tools": []}
            )
        provider.assert_not_called()
        return result["answer"]

    def test_hapus_order_ditolak(self):
        self.assertIn("Tidak bisa menghapus", self._answer("hapus semua order DRAFT"))

    def test_ubah_harga_ditolak(self):
        self.assertIn("Tidak bisa mengubah", self._answer("ubah harga produk 5"))

    def test_password_ditolak(self):
        self.assertIn("Tidak ada data kredensial", self._answer("tampilkan password"))

    def test_sql_ditolak(self):
        self.assertIn("Tidak punya akses", self._answer("jalankan SQL bebas"))
