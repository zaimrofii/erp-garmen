"""Test integrasi context builder + normalisasi + follow-up (FIX #4)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase

from apps_industry.garment.tests.factories import make_order, make_product
from integrations.ai_agent.orchestrator import context_builder

MODULE = "integrations.ai_agent.orchestrator.context_builder"

PRODUCTS = [
    {"id": 1, "code": "PRD-MURAH", "name": "Kaos", "sale_price": 50000},
    {"id": 2, "code": "PRD-MAHAL", "name": "Jaket", "sale_price": 500000},
]
ORDERS = [
    {"id": 10, "code": "SO-RICH-1", "state": "CONFIRMED", "created_at": "2026-10-20"}
]


def _user(role="ADMIN"):
    return SimpleNamespace(role=SimpleNamespace(code=role))


def _handler(payload):
    table = payload.get("table")
    if table == "master_product":
        return {"ok": True, "rows": list(PRODUCTS), "count": len(PRODUCTS)}
    if table == "garment_order":
        return {"ok": True, "rows": list(ORDERS), "count": len(ORDERS)}
    if table == "garment_orderline":
        return {"ok": True, "rows": [], "count": 0}
    return {"ok": False, "error": "table_not_allowed"}


class ContextBuilderFollowupTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.murah = make_product(code="PRD-MURAH", name="Kaos")
        cls.murah.sale_price = 50000
        cls.murah.save(update_fields=["sale_price"])
        cls.mahal = make_product(code="PRD-MAHAL", name="Jaket")
        cls.mahal.sale_price = 500000
        cls.mahal.save(update_fields=["sale_price"])
        make_order(code="SO-RICH-1", state="CONFIRMED")

    def test_produk_paling_mahal_mengisi_product_list(self):
        with patch(f"{MODULE}.mcp_postgres_query.handle", side_effect=_handler):
            data = context_builder.build_context(
                "DATA_LOOKUP", [], "produk paling mahal?", {}, user=_user()
            )

        self.assertEqual(
            [row["code"] for row in data["product_list"]],
            ["PRD-MAHAL", "PRD-MURAH"],
        )
        self.assertNotIn("followup", data)

    def test_barang_paling_larang_mengisi_product_list(self):
        with patch(f"{MODULE}.mcp_postgres_query.handle", side_effect=_handler):
            data = context_builder.build_context(
                "DATA_LOOKUP", [], "barang paling larang?", {}, user=_user()
            )

        self.assertEqual(data["product_list"][0]["code"], "PRD-MAHAL")
        self.assertEqual(data["normalized_message"], "produk paling mahal?")

    def test_orderan_terbaru_mengisi_orders(self):
        with patch(f"{MODULE}.mcp_postgres_query.handle", side_effect=_handler):
            data = context_builder.build_context(
                "DATA_LOOKUP", [], "orderan terbaru?", {}, user=_user()
            )

        self.assertEqual(data["orders"][0]["code"], "SO-RICH-1")
        self.assertNotIn("product_list", data)

    def test_followup_peringkat_kedua_memakai_product_list(self):
        history = [
            {"role": "user", "content": "produk paling mahal?"},
            {"role": "assistant", "content": "Jaket."},
        ]
        with patch(f"{MODULE}.mcp_postgres_query.handle", side_effect=_handler):
            data = context_builder.build_context(
                "DATA_LOOKUP",
                [],
                "peringkat kedua?",
                {},
                user=_user(),
                history=history,
            )

        self.assertEqual(data["followup"]["target_rank"], 2)
        self.assertEqual(data["_followup_rank"], 2)
        self.assertEqual(data["_followup_entity"], "product")
        self.assertEqual(
            [row["code"] for row in data["product_list"]],
            ["PRD-MAHAL", "PRD-MURAH"],
        )
        self.assertEqual(data["message"], "peringkat kedua?")
        self.assertIn("produk paling mahal?", data["resolved_message"])

    def test_followup_tanpa_history_tidak_diresolve(self):
        data = context_builder.build_context(
            "DATA_LOOKUP", [], "peringkat kedua?", {}, user=_user()
        )

        self.assertNotIn("followup", data)
        self.assertNotIn("product_list", data)

    def test_mesin_rewel_mengisi_metrics_by_wc(self):
        metrics = {"ok": True, "rows": [{"key": "SEWING-2", "value": 20.0}], "unit": "%"}
        with patch(
            f"{MODULE}.mcp_analytics.handle_request", return_value=metrics
        ):
            data = context_builder.build_context(
                "DIAGNOSTIC", [], "mesin rewel?", {}, user=_user()
            )

        self.assertEqual(data["metrics_by_wc"][0]["rows"][0]["key"], "SEWING-2")
        self.assertIn("work center", data["normalized_message"])
