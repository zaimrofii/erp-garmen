"""Acceptance Fase 4 — 12 pertanyaan negasi, agregat, dan edge case."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.models import (
    Bundle,
    BundleEvent,
    Order,
    OrderLine,
    WorkOrder,
)
from core.auth.models import Role, User
from integrations.analytics.services import analytics_config_services
from master.models import Partner, Product

URL = "/api/v1/ai/chat"


def _data(prompt: str) -> tuple[str, dict]:
    question = ""
    if "PERTANYAAN USER:" in prompt:
        after = prompt.split("PERTANYAAN USER:", 1)[1]
        question = after.split("KONTEKS HALAMAN:", 1)[0].strip()
    marker = "DATA DARI SISTEM:"
    if marker not in prompt:
        return question, {}
    text = prompt.split(marker, 1)[1].strip()
    try:
        value, _ = json.JSONDecoder().raw_decode(text)
    except (TypeError, ValueError):
        return question, {}
    return question, value if isinstance(value, dict) else {}


def _rupiah(value) -> str:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return str(value)
    return "Rp{:,.0f}".format(amount).replace(",", ".")


def _product_rows(data: dict, question: str) -> list[dict]:
    rows = list(data.get("product_list") or [])
    q = question.lower()
    if "harga 0" in q:
        return [row for row in rows if float(row.get("sale_price") or 0) == 0]
    if "tanpa kategori" in q:
        return [row for row in rows if not row.get("category")]
    if "di atas 100" in q:
        return [row for row in rows if float(row.get("sale_price") or 0) > 100000]
    if "di bawah 50" in q:
        return [row for row in rows if float(row.get("sale_price") or 0) < 50000]
    return rows


class FakeProvider:
    def complete(self, *, system_prompt=None, user_prompt=None, max_tokens=None):
        question, data = _data(user_prompt or "")
        q = question.lower()
        answer = "Data tidak cukup."

        if isinstance(data.get("product_list"), list):
            rows = _product_rows(data, question)
            values = [float(row.get("sale_price") or 0) for row in rows]
            if "rata-rata" in q and values:
                answer = f"Rata-rata harga produk {_rupiah(sum(values) / len(values))}."
            elif "tertinggi" in q and values:
                answer = f"Harga tertinggi produk {_rupiah(max(values))}."
            elif "terendah" in q and values:
                answer = f"Harga terendah produk {_rupiah(min(values))}."
            elif "total nilai" in q and values:
                answer = f"Total nilai semua produk {_rupiah(sum(values))}."
            elif rows:
                answer = "; ".join(
                    f"{row.get('name')} {_rupiah(row.get('sale_price'))}"
                    for row in rows
                )
            elif any(word in q for word in ("harga 0", "tanpa kategori", "di atas 100", "di bawah 50")):
                answer = "Tidak ada produk yang cocok."
        elif isinstance(data.get("orders"), list):
            rows = list(data["orders"])
            if "tanpa customer" in q:
                rows = [row for row in rows if not row.get("customer_id")]
            if "qty > 50" in q:
                rows = [
                    row
                    for row in rows
                    if any(float(line.get("qty") or 0) > 50 for line in row.get("lines") or [])
                ]
            answer = (
                "; ".join(str(row.get("code")) for row in rows)
                if rows
                else "Tidak ada order yang cocok."
            )
        elif isinstance(data.get("bundles"), list):
            rows = [row for row in data["bundles"] if float(row.get("qty") or 0) > 10]
            answer = (
                "; ".join(str(row.get("code")) for row in rows)
                if rows
                else "Tidak ada bundle yang cocok."
            )

        return SimpleNamespace(
            text=answer,
            prompt_tokens=1,
            completion_tokens=1,
            total_cost_usd=0,
            model="mock",
            latency_ms=1,
        )


class AcceptanceFase4Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.customer = Partner.objects.create(
            code="F4-CUST", name="Customer Fase 4", is_customer=True
        )
        cls.products = {}
        for code, name, price, category in (
            ("F4-ZERO", "Zero Product", 0, ""),
            ("F4-LOW", "Low Product", 25000, "Kaos"),
            ("F4-MID", "Mid Product", 50000, "Kaos"),
            ("F4-HIGH", "High Product", 100000, "Jaket"),
            ("F4-TOP", "Top Product", 250000, "Jaket"),
        ):
            cls.products[code] = Product.objects.create(
                code=code,
                name=name,
                sale_price=price,
                cost_price=price,
                category=category,
            )

        cls.order_nocust = Order.objects.create(code="F4-ORD-NOCUST")
        cls.order_cust = Order.objects.create(code="F4-ORD-CUST", customer=cls.customer)
        OrderLine.objects.create(
            order=cls.order_nocust,
            product=cls.products["F4-MID"],
            qty=60,
            price_unit=50000,
        )
        OrderLine.objects.create(
            order=cls.order_cust,
            product=cls.products["F4-MID"],
            qty=10,
            price_unit=50000,
        )
        cls.wo_nocust = WorkOrder.objects.create(
            code="F4-WO-NOCUST",
            order_line=cls.order_nocust.lines.first(),
            qty_planned=60,
        )
        cls.wo_cust = WorkOrder.objects.create(
            code="F4-WO-CUST",
            order_line=cls.order_cust.lines.first(),
            qty_planned=10,
        )
        cls.bundle_no_event = Bundle.objects.create(
            code="F4-BND-NOEVENT",
            work_order=cls.wo_nocust,
            qty=20,
            qty_done=20,
            state="DONE",
        )
        cls.bundle_event = Bundle.objects.create(
            code="F4-BND-EVENT",
            work_order=cls.wo_cust,
            qty=5,
            qty_done=5,
            state="DONE",
        )
        BundleEvent.objects.create(
            bundle=cls.bundle_event, event_type="BUNDLE_FINISH", text="finish"
        )
        cls.owner = User.objects.filter(role__code="OWNER").first() or User.objects.create_user(
            username="f4-owner",
            password="x",
            role=Role.objects.get(code=Role.Code.OWNER),
        )

    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        self.patches = [
            patch(
                "integrations.ai_agent.api.views.intent_classifier.classify",
                return_value={"intent": "DATA_LOOKUP", "confidence": 0.9, "cost_usd": 0},
            ),
            patch(
                "integrations.ai_agent.orchestrator.response_synthesizer.get_llm_provider",
                return_value=FakeProvider(),
            ),
            patch.object(
                analytics_config_services, "analytics_enabled", return_value=True
            ),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def chat(self, message: str) -> dict:
        response = self.api.post(URL, {"message": message}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()


    def test_01_produk_harga_0(self):
        body = self.chat("produk dengan harga 0?")
        self.assertIn("Zero Product", body["answer"])
        self.assertIn("Rp0", body["answer"])

    def test_02_order_tanpa_customer(self):
        body = self.chat("order tanpa customer?")
        self.assertIn("F4-ORD-NOCUST", body["answer"])
        self.assertNotIn("F4-ORD-CUST", body["answer"])

    def test_03_bundle_tanpa_event(self):
        body = self.chat("bundle tanpa event?")
        self.assertIn("F4-BND-NOEVENT", body["answer"])
        self.assertNotIn("F4-BND-EVENT", body["answer"])

    def test_04_produk_tanpa_kategori(self):
        body = self.chat("produk tanpa kategori?")
        self.assertIn("Zero Product", body["answer"])
        self.assertNotIn("Mid Product", body["answer"])

    def test_05_rata_rata_harga(self):
        body = self.chat("rata-rata harga produk?")
        self.assertIn("85.000", body["answer"])

    def test_06_harga_tertinggi(self):
        body = self.chat("harga tertinggi produk?")
        self.assertIn("250.000", body["answer"])

    def test_07_harga_terendah(self):
        body = self.chat("harga terendah produk?")
        self.assertIn("Rp0", body["answer"])

    def test_08_total_nilai_produk(self):
        body = self.chat("total nilai semua produk?")
        self.assertIn("425.000", body["answer"])

    def test_09_di_atas_100rb(self):
        body = self.chat("produk dengan harga di atas 100rb?")
        self.assertIn("Top Product", body["answer"])
        self.assertNotIn("High Product", body["answer"])

    def test_10_di_bawah_50rb(self):
        body = self.chat("produk dengan harga di bawah 50rb?")
        self.assertIn("Zero Product", body["answer"])
        self.assertIn("Low Product", body["answer"])
        self.assertNotIn("Mid Product", body["answer"])

    def test_11_order_qty_lebih_50(self):
        body = self.chat("order dengan qty > 50?")
        self.assertIn("F4-ORD-NOCUST", body["answer"])
        self.assertNotIn("F4-ORD-CUST", body["answer"])

    def test_12_bundle_qty_lebih_10(self):
        body = self.chat("bundle dengan qty > 10?")
        self.assertIn("F4-BND-NOEVENT", body["answer"])
        self.assertNotIn("F4-BND-EVENT", body["answer"])

