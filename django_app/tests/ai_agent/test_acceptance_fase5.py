"""Acceptance Fase 5 — relasi bundle/order, operator, pronoun, customer."""

from __future__ import annotations

import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
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


class FakeProvider:
    def complete(self, *, system_prompt=None, user_prompt=None, max_tokens=None):
        question, data = _data(user_prompt or "")
        q = question.lower()
        answer = "Data tidak cukup."

        if (
            isinstance(data.get("bundle_operators"), list)
            and data["bundle_operators"]
            and "operator" in q
        ):
            answer = "; ".join(
                str(item.get("actor__username") or item.get("actor_name") or "")
                for item in data["bundle_operators"]
            )
        elif (
            isinstance(data.get("order_bundles"), list)
            and data["order_bundles"]
            and "total belanja" not in q
        ):
            answer = "Order SO-BIG-0001 bundles: " + "; ".join(
                str(item.get("code")) for item in data["order_bundles"]
            )
        elif isinstance(data.get("operator_anomalies"), dict):
            operators = data["operator_anomalies"].get("operators") or []
            if "kenapa" in q or "mencurigakan" in q:
                answer = "; ".join(
                    f"{item.get('username')} score {item.get('score')} "
                    f"phantom_days {item.get('breakdown', {}).get('phantom_days')} "
                    f"scrap_discrepancies {item.get('breakdown', {}).get('scrap_discrepancies')}"
                    for item in operators[:2]
                )
            else:
                answer = "; ".join(
                    f"{item.get('username')} score {item.get('score')}"
                    for item in operators[:4]
                )
        elif (
            isinstance(data.get("bundle_specific"), list)
            and data["bundle_specific"]
            and "customer" not in q
            and "total belanja" not in q
        ):
            row = data["bundle_specific"][0]
            answer = (
                f"Bundle {row.get('code')} order {row.get('order_code')} "
                f"customer {row.get('customer_name')} produk {row.get('product_name')}."
            )
        elif (
            isinstance(data.get("order_specific"), list)
            and data["order_specific"]
            and "total belanja" not in q
        ):
            row = data["order_specific"][0]
            answer = f"Order {row.get('code')} customer {row.get('customer_name')}."
        elif isinstance(data.get("customer_detail"), dict):
            detail = data["customer_detail"]
            answer = (
                f"Customer {detail.get('name')} total belanja "
                f"Rp{detail.get('total_spend', 0):,.0f}."
            )
        elif isinstance(data.get("bundles"), list):
            answer = "; ".join(str(row.get("code")) for row in data["bundles"])
        elif isinstance(data.get("customer_total_spend"), list):
            answer = "; ".join(
                f"{row.get('customer_name')} Rp{row.get('amount')}"
                for row in data["customer_total_spend"]
            )

        return SimpleNamespace(
            text=answer,
            prompt_tokens=1,
            completion_tokens=1,
            total_cost_usd=0,
            model="mock",
            latency_ms=1,
        )

class AcceptanceFase5Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.customer = Partner.objects.create(
            code="F5-CUST",
            name="PT Retail Fashion Indonesia",
            is_customer=True,
        )
        cls.product = Product.objects.create(
            code="F5-CHN",
            name="Celana Chino",
            sale_price=160000,
            cost_price=100000,
            category="Celana",
        )
        cls.order = Order.objects.create(
            code="SO-BIG-0001", customer=cls.customer, state="DONE"
        )
        cls.line = OrderLine.objects.create(
            order=cls.order,
            product=cls.product,
            qty=10,
            price_unit=160000,
        )
        cls.wo = WorkOrder.objects.create(
            code="F5-WO-1", order_line=cls.line, qty_planned=10
        )
        cls.bundle = Bundle.objects.create(
            code="BND-BIG-0001",
            work_order=cls.wo,
            qty=10,
            qty_done=10,
            state="DONE",
        )
        cls.bundle2 = Bundle.objects.create(
            code="BND-BIG-0002",
            work_order=cls.wo,
            qty=10,
            qty_done=10,
            state="DONE",
        )
        cls.operator_role = Role.objects.get(code=Role.Code.OPERATOR)
        cls.op_andi = User.objects.create_user(
            username="op-andi", password="x", role=cls.operator_role
        )
        cls.op_budi = User.objects.create_user(
            username="op-budi", password="x", role=cls.operator_role
        )
        now = timezone.now()
        for operator, bundle, count in (
            (cls.op_andi, cls.bundle, 35),
            (cls.op_budi, cls.bundle2, 32),
        ):
            for index in range(count):
                event = BundleEvent.objects.create(
                    bundle=bundle,
                    event_type="BUNDLE_START",
                    text=f"F5 {operator.username} {index}",
                    actor=operator,
                )
                BundleEvent.objects.filter(pk=event.pk).update(
                    ts=now - timedelta(minutes=30) + timedelta(seconds=index * 20)
                )
            for offset in range(2):
                start = BundleEvent.objects.create(
                    bundle=bundle,
                    event_type="BUNDLE_START",
                    text=f"F5 cycle {operator.username} {offset} start",
                    actor=operator,
                )
                finish = BundleEvent.objects.create(
                    bundle=bundle,
                    event_type="BUNDLE_FINISH",
                    text=f"F5 cycle {operator.username} {offset} finish",
                    actor=operator,
                )
                base = now - timedelta(minutes=5, seconds=offset * 30)
                BundleEvent.objects.filter(pk=start.pk).update(ts=base)
                BundleEvent.objects.filter(pk=finish.pk).update(
                    ts=base + timedelta(seconds=10)
                )
        cls.owner = User.objects.filter(role__code="OWNER").first() or User.objects.create_user(
            username="f5-owner",
            password="x",
            role=Role.objects.get(code=Role.Code.OWNER),
        )

    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        self.history = []
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
        response = self.api.post(
            URL, {"message": message, "history": self.history}, format="json"
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


    def test_01_bundle_detail_order(self):
        body = self.chat("bundle BND-BIG-0001?")
        self.assertIn("SO-BIG-0001", body["answer"])
        self.assertIn("Celana Chino", body["answer"])

    def test_02_order_apa_followup(self):
        self.chat("bundle BND-BIG-0001?")
        body = self.chat("order apa?")
        self.assertIn("SO-BIG-0001", body["answer"])

    def test_03_customer_siapa_followup(self):
        self.chat("bundle BND-BIG-0001?")
        self.chat("order apa?")
        body = self.chat("customer siapa?")
        self.assertIn("PT Retail Fashion Indonesia", body["answer"])

    def test_04_order_detail_bundle(self):
        body = self.chat("order SO-BIG-0001?")
        self.assertIn("BND-BIG-0001", body["answer"])

    def test_05_bundle_apa_saja_followup(self):
        self.chat("order SO-BIG-0001?")
        body = self.chat("bundle apa saja?")
        self.assertIn("BND-BIG-0001", body["answer"])

    def test_06_operator_bundle(self):
        body = self.chat("operator yang mengerjakan bundle BND-BIG-0001?")
        self.assertIn("op-andi", body["answer"])

    def test_07_operator_tidak_wajar(self):
        body = self.chat("operator mana yang inputnya tidak wajar?")
        self.assertIn("op-andi", body["answer"])
        self.assertIn("op-budi", body["answer"])

    def test_08_kenapa_operator_mencurigakan(self):
        self.chat("operator mana yang inputnya tidak wajar?")
        body = self.chat("kenapa operator itu mencurigakan?")
        self.assertTrue(
            any(word in body["answer"].lower() for word in ("phantom", "siklus", "scrap")),
            body["answer"],
        )

    def test_09_bundle_produk_followup(self):
        self.chat("bundle BND-BIG-0001?")
        body = self.chat("produknya apa?")
        self.assertIn("Celana Chino", body["answer"])

    def test_10_order_total_belanja(self):
        self.chat("order SO-BIG-0001?")
        body = self.chat("total belanjanya?")
        self.assertIn("Rp", body["answer"])

    def test_11_customer_detail(self):
        body = self.chat("customer PT Retail Fashion Indonesia?")
        self.assertIn("PT Retail Fashion Indonesia", body["answer"])

    def test_12_customer_total_belanja(self):
        self.chat("customer PT Retail Fashion Indonesia?")
        body = self.chat("total belanjanya?")
        self.assertIn("Rp", body["answer"])

