"""Test prompt tegas + bundle-per-WC via BundleEvent (FIX #9)."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps_industry.garment.models import BundleEvent
from apps_industry.garment.tests.factories import (
    make_bundle,
    make_order,
    make_order_line,
    make_product,
    make_work_order,
)
from integrations.ai_agent.data_access.metrics import MetricsRepository
from integrations.ai_agent.orchestrator import context_builder
from integrations.ai_agent.orchestrator.response_synthesizer import SYSTEM_PROMPT
from master.models import Partner

MODULE = "integrations.ai_agent.orchestrator.context_builder"


def _user():
    return SimpleNamespace(role=SimpleNamespace(code="ADMIN"))


class BundleWorkCenterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.customer = Partner.objects.create(
            code="CUST-WC", name="Gemini Furniture"
        )
        cls.product = make_product(code="PRD-WC", name="Jaket WC")
        cls.order = make_order(code="ORD-WC", customer=cls.customer)
        line = make_order_line(order=cls.order, product=cls.product)
        wo = make_work_order(order_line=line, code="WO-WC")
        cls.bundle = make_bundle(
            work_order=wo, code="BND-WC", state="SEWING"
        )
        now = timezone.now()
        first = BundleEvent.objects.create(
            bundle=cls.bundle,
            event_type="BUNDLE_START",
            payload={"work_center_code": "SEWING-2"},
        )
        second = BundleEvent.objects.create(
            bundle=cls.bundle,
            event_type="BUNDLE_FINISH",
            payload={"work_center_code": "SEWING-2"},
        )
        BundleEvent.objects.filter(pk=first.pk).update(ts=now - timedelta(hours=5))
        BundleEvent.objects.filter(pk=second.pk).update(ts=now)

    def test_bundles_in_work_center_duration(self):
        rows = MetricsRepository().bundles_in_work_center("SEWING-2")

        self.assertEqual(rows[0]["bundle_code"], "BND-WC")
        self.assertEqual(rows[0]["duration_hours"], 5.0)
        self.assertEqual(rows[0]["events_count"], 2)
        self.assertEqual(rows[0]["customer_name"], "Gemini Furniture")

    def test_context_bundle_paling_lama_di_wc(self):
        data = context_builder.build_context(
            "DATA_LOOKUP", [], "bundle paling lama di SEWING-2?", {}, user=_user()
        )

        self.assertEqual(data["bundles_in_wc"][0]["bundle_code"], "BND-WC")


class OrphanProductPromptTests(TestCase):
    def test_prompt_produk_yatim_tegas(self):
        self.assertIn("belum pernah", SYSTEM_PROMPT)
        self.assertIn("(0 order, 0 bundle, 0 produksi)", SYSTEM_PROMPT)
        self.assertIn("JANGAN jawab", SYSTEM_PROMPT)

    def test_prompt_empty_list_bukan_data_tidak_cukup(self):
        self.assertIn("Tidak ada X", SYSTEM_PROMPT)
        self.assertIn("Belum ada order terkait", SYSTEM_PROMPT)

    def test_context_produk_yatim_nol_dan_list_kosong(self):
        product = make_product(code="KPP-DEWASA-V2", name="KPP Dewasa V2")
        handler = lambda payload: {
            "ok": True,
            "rows": [{"id": product.pk, "code": product.code, "name": product.name}],
        }
        with patch(f"{MODULE}.mcp_postgres_query.handle", side_effect=handler):
            data = context_builder.build_context(
                "DATA_LOOKUP",
                [],
                "produksi berapa kali?",
                {
                    "page_type": "detail",
                    "resource_type": "product",
                    "resource_id": product.pk,
                },
                user=_user(),
            )

        self.assertEqual(data["product_production_count"], 0)
        self.assertEqual(data["related_orders"], [])
        self.assertEqual(data["related_bundles"], [])

    def test_context_order_terkait_kosong(self):
        product = make_product(code="KPP-ORPHAN", name="KPP Orphan")
        handler = lambda payload: {
            "ok": True,
            "rows": [{"id": product.pk, "code": product.code}],
        }
        with patch(f"{MODULE}.mcp_postgres_query.handle", side_effect=handler):
            data = context_builder.build_context(
                "DATA_LOOKUP",
                [],
                "order terkait?",
                {
                    "page_type": "detail",
                    "resource_type": "product",
                    "resource_id": product.pk,
                },
                user=_user(),
            )

        self.assertEqual(data["related_orders"], [])
