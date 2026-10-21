"""Test integrasi floating chat (FIX #5) — page context + keyword data."""

from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.auth.models import Role, User
from apps_industry.garment.tests.factories import make_bundle
from master.models import Partner

URL = "/api/v1/ai/chat"
MODULE = "integrations.ai_agent.orchestrator.context_builder"
PRODUCT_PAGE = {"page_type": "list", "resource_type": "product"}

PRODUCTS = [
    {"id": 1, "code": "PRD-1", "name": "Kaos", "sale_price": 50000},
    {"id": 2, "code": "PRD-2", "name": "Jaket", "sale_price": 500000},
]
BUNDLES = [{"id": 30, "code": "BND-1", "state": "SEWING"}]
PARTNERS = [{"id": 10, "code": "CUST-1", "name": "PT Pelanggan"}]


def _handler(payload):
    table = payload.get("table")
    rows = {
        "master_product": PRODUCTS,
        "garment_bundle": BUNDLES,
        "master_partner": PARTNERS,
    }.get(table)
    if rows is None:
        return {"ok": False, "error": "table_not_allowed"}
    return {"ok": True, "rows": list(rows), "count": len(rows)}


def _fake_synthesize(message, context_data, **_kwargs):
    """Simulasi synthesizer: jawab dari data yang benar-benar diterima."""
    if context_data.get("bundles"):
        answer = f"Daftar bundle: {context_data['bundles'][0]['code']}."
    elif context_data.get("partners"):
        answer = f"Daftar customer: {context_data['partners'][0]['code']}."
    else:
        answer = "Data tidak cukup untuk menjawab."
    return {
        "ok": True,
        "answer": answer,
        "tokens": {"prompt": 1, "completion": 1, "total_cost_usd": 0},
        "model": "mock",
        "latency_ms": 1,
    }


class FloatingChatIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="floating-fix5",
            password="x",
            role=Role.objects.get(code=Role.Code.SUPERVISOR),
        )
        make_bundle(code="BND-1", state="SEWING")
        Partner.objects.create(code="CUST-1", name="PT Pelanggan")

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.intent = patch(
            "integrations.ai_agent.api.views.intent_classifier.classify",
            return_value={
                "intent": "DATA_LOOKUP",
                "confidence": 0.8,
                "tokens": 1,
            },
        )
        self.synth = patch(
            "integrations.ai_agent.api.views.response_synthesizer.synthesize",
            side_effect=_fake_synthesize,
        )
        self.rule = patch(
            "integrations.ai_agent.api.views.rule_evaluator.evaluate",
            return_value={"result": "LLM_NEEDED", "answer": ""},
        )
        self.cache_get = patch(
            "integrations.ai_agent.api.views.semantic_cache.get",
            return_value=None,
        )
        self.cache_set = patch(
            "integrations.ai_agent.api.views.semantic_cache.set",
        )
        self.mock_intent = self.intent.start()
        self.mock_synth = self.synth.start()
        self.rule.start()
        self.cache_get.start()
        self.cache_set.start()
        for patcher in (
            self.intent,
            self.synth,
            self.rule,
            self.cache_get,
            self.cache_set,
        ):
            self.addCleanup(patcher.stop)

    def _post(self, message):
        with override_settings(AI_AGENT_ENABLED=True), patch(
            f"{MODULE}.mcp_postgres_query.handle", side_effect=_handler
        ):
            return self.client.post(
                URL,
                {"message": message, "context": PRODUCT_PAGE},
                format="json",
            )

    def test_bundle_dari_halaman_product(self):
        response = self._post("bundle apa saja?")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        context = self.mock_synth.call_args.args[1]
        self.assertEqual(context["bundles"][0]["code"], "BND-1")
        self.assertEqual(context["resource_list_count"], 2)
        self.assertEqual(
            {row["code"] for row in context["resource_list"]},
            {"PRD-1", "PRD-2"},
        )
        self.assertIn("BND-1", response.json()["answer"])
        self.assertNotIn("Data tidak cukup", response.json()["answer"])

    def test_customer_dari_halaman_product(self):
        response = self._post("customer siapa saja?")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        context = self.mock_synth.call_args.args[1]
        self.assertEqual(context["partners"][0]["code"], "CUST-1")
        self.assertEqual(context["resource_list_count"], 2)
        self.assertIn("CUST-1", response.json()["answer"])
        self.assertNotIn("Data tidak cukup", response.json()["answer"])
