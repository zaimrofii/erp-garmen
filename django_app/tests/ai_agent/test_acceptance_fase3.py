"""Acceptance Fase 3 — 20 pertanyaan kritis, mock LLM (biaya $0)."""

from __future__ import annotations

import json
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps_industry.garment.models import Order
from core.auth.models import Role, User
from integrations.ai_agent.clarification import pending_state
from integrations.analytics.services import analytics_config_services
from master.models import Partner, Product

URL = "/api/v1/ai/chat"


def _json_block(prompt: str) -> dict:
    marker = "DATA DARI SISTEM:"
    if marker not in prompt:
        return {}
    text = prompt.split(marker, 1)[1].strip()
    try:
        value, _ = json.JSONDecoder().raw_decode(text)
    except (ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _rupiah(value) -> str:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return str(value)
    if amount <= 0:
        return "Rp0"
    return "Rp{:,.0f}".format(amount).replace(",", ".")


class FakeProvider:
    """Mock LLM yang membaca context_data dan menghasilkan jawaban akhir."""

    def complete(self, *, system_prompt=None, user_prompt=None, max_tokens=None):
        data = _json_block(user_prompt or "")
        answer = "Data tidak cukup."

        candidate = data.get("_resolved_candidate")
        if isinstance(candidate, dict) and candidate.get("label"):
            attrs = candidate.get("attrs") or {}
            harga = attrs.get("harga")
            answer = str(candidate["label"])
            if harga:
                answer = f"{answer}, {harga}"
        elif isinstance(data.get("total_counts"), dict):
            total = data["total_counts"]
            answer = f"Total {total.get('label', 'data')} {total.get('total')}."
        elif isinstance(data.get("bundle_specific"), list) and data["bundle_specific"]:
            row = data["bundle_specific"][0]
            answer = (
                f"Bundle {row.get('code')} terkait order {row.get('order_code')}."
            )
        elif isinstance(data.get("product_list"), list) and data["product_list"]:
            row = max(
                data["product_list"],
                key=lambda item: float(item.get("sale_price") or 0),
            )
            answer = f"{row.get('name')}, {_rupiah(row.get('sale_price'))}"

        return SimpleNamespace(
            text=answer,
            prompt_tokens=1,
            completion_tokens=1,
            total_cost_usd=0,
            model="mock",
            latency_ms=1,
        )


class AcceptanceFase3Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_big_test", stdout=StringIO())
        # Data acceptance: 73 order, 200 bundle, 25 customer, semua order Oktober.
        for index in range(23):
            Order.objects.create(code=f"ACC-ORDER-{index:03d}", state="DRAFT")
        for index in range(15):
            Partner.objects.get_or_create(
                code=f"ACC-CUST-{index:02d}",
                defaults={"name": f"Customer Acceptance {index}", "is_customer": True},
            )
        for code, name, price, category in (
            ("ACC-FG-DRESS-WANITA", "Dress Casual Wanita", 175000, "Dress"),
            ("ACC-FG-KAIN-RIB", "Kain Rib (Collar)", 110000, "Material"),
        ):
            Product.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "sale_price": price,
                    "cost_price": price,
                    "category": category,
                    "is_active": True,
                },
            )
        cls.owner = User.objects.filter(role__code="OWNER").first() or User.objects.create_user(
            username="acceptance-owner",
            password="x",
            role=Role.objects.get(code=Role.Code.OWNER),
        )

    def setUp(self):
        cache.clear()
        self.session = f"user-{self.owner.pk}"
        pending_state.clear(self.owner.pk, self.session)
        self.history = []
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

        def classify(message):
            text = str(message or "").lower()
            intent = "ANALYTICS_QUERY" if any(
                word in text for word in ("tren", "scrap", "grafik", "chart")
            ) else "DATA_LOOKUP"
            return {"intent": intent, "confidence": 0.9, "cost_usd": 0}

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

    def test_01_total_order_73(self):
        body = self.chat("total order?")
        self.assertIn("73", body["answer"])
        self.assertIsNone(body.get("chart_data"))

    def test_02_total_bundle_200(self):
        body = self.chat("total bundle?")
        self.assertIn("200", body["answer"])

    def test_03_total_customer_25(self):
        body = self.chat("total customer?")
        self.assertIn("25", body["answer"])

    def test_04_total_order_done_30_konsisten_tiga_kali(self):
        answers = [self.chat("berapa order DONE?")["answer"] for _ in range(3)]
        self.assertTrue(all("30" in answer for answer in answers), answers)
        self.assertEqual(len(set(answers)), 1)

    def test_05_total_order_bulan_ini_73(self):
        body = self.chat("total order bulan ini?")
        self.assertIn("73", body["answer"])



    def test_06_produk_termahal_langsung(self):
        body = self.chat("produk termahal?")
        self.assertIn("Jaket Bomber", body["answer"])
        self.assertIn("250.000", body["answer"])
        self.assertNotIn("Yang mana?", body["answer"])

    def test_07_yang_kedua_dress_casual(self):
        self.chat("produk termahal?")
        body = self.chat("yang kedua?")
        self.assertIn("Dress Casual", body["answer"])
        self.assertIn("175.000", body["answer"])
        self.assertNotIn("Yang mana?", body["answer"])

    def test_08_yang_keempat_celana_chino(self):
        self.chat("produk termahal?")
        self.chat("yang kedua?")
        body = self.chat("yang keempat?")
        self.assertIn("Celana Chino", body["answer"])
        self.assertIn("160.000", body["answer"])
        self.assertNotIn("Yang mana?", body["answer"])

    def test_09_harga_kaos_polos_klarifikasi(self):
        body = self.chat("berapa harga kaos polos?")
        self.assertIn("Ada ", body["answer"])
        self.assertIn("Yang mana?", body["answer"])

    def test_10_yang_kedua_setelah_klarifikasi(self):
        self.chat("berapa harga kaos polos?")
        body = self.chat("yang kedua?")
        self.assertNotIn("Yang mana?", body["answer"])
        self.assertTrue(body["answer"].strip())

    def test_11_lupakan_total_order_73(self):
        body = self.chat("lupakan, total order?")
        self.assertIn("73", body["answer"])
        self.assertNotIn("20 order", body["answer"])

    def test_12_batal_tren_scrap_chart(self):
        body = self.chat("batal, tren scrap?")
        self.assertIsNotNone(body.get("chart_data"))
        self.assertEqual(body["chart_data"]["metric_id"], "garment.scrap_rate")


    def test_13_total_order_tanpa_chart(self):
        body = self.chat("total order?")
        self.assertIsNone(body.get("chart_data"))

    def test_14_tren_scrap_ada_chart(self):
        body = self.chat("tren scrap?")
        self.assertIsNotNone(body.get("chart_data"))
        self.assertEqual(body["chart_data"]["metric_id"], "garment.scrap_rate")

    def test_15_bundle_big_detail_order(self):
        body = self.chat("bundle BND-BIG-0001?")
        self.assertIn("SO-BIG-0001", body["answer"])

    def test_16_order_apa_setelah_bundle(self):
        self.chat("bundle BND-BIG-0001?")
        body = self.chat("order apa?")
        self.assertIn("SO-BIG-0001", body["answer"])


    def test_17_produk_tidak_ada(self):
        body = self.chat("produk XYZ-999?")
        self.assertIn("Tidak ada produk", body["answer"])

    def test_18_order_tidak_ada(self):
        body = self.chat("order SO-9999?")
        self.assertIn("Tidak ada order", body["answer"])

    def test_19_hapus_order_draft_ditolak(self):
        body = self.chat("hapus semua order DRAFT")
        self.assertIn("Tidak bisa menghapus", body["answer"])

    def test_20_password_tidak_ada(self):
        body = self.chat("tampilkan password")
        self.assertIn("Tidak ada data kredensial", body["answer"])

