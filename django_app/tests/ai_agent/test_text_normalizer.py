"""Test text normalizer (FIX #4) — pure, tanpa DB/LLM."""

from __future__ import annotations

from django.test import SimpleTestCase

from integrations.ai_agent.orchestrator import tool_selector
from integrations.ai_agent.orchestrator.text_normalizer import normalize


class TextNormalizerTests(SimpleTestCase):
    def test_barang_paling_larang(self):
        result = normalize("Barang paling larang?")

        self.assertEqual(result["normalized"], "produk paling mahal?")
        self.assertEqual(set(result["canonicals"]), {"produk", "mahal"})

    def test_pesan_kosong(self):
        self.assertEqual(
            normalize(""),
            {"raw": "", "normalized": "", "canonicals": [], "tokens": []},
        )
        self.assertEqual(normalize(None)["tokens"], [])

    def test_orderan_terbaru(self):
        result = normalize("Orderan terbaru")

        self.assertEqual(result["normalized"], "order terbaru")
        self.assertIn("order", result["canonicals"])
        self.assertIn("terbaru", result["canonicals"])

    def test_frasa_multi_kata(self):
        result = normalize("surat perintah kerja")

        self.assertEqual(result["normalized"], "work order")
        self.assertEqual(result["canonicals"], ["work_order"])

    def test_mesin_rewel(self):
        result = normalize("mesin rewel?")

        self.assertIn("work_center", result["canonicals"])
        self.assertIn("rewel", result["canonicals"])
        self.assertEqual(result["normalized"], "work center rewel?")

    def test_royal_dan_boros(self):
        royal = normalize("customer royal")
        boros = normalize("pemakaian boros")

        self.assertIn("customer", royal["canonicals"])
        self.assertIn("royal", royal["canonicals"])
        self.assertIn("boros", boros["canonicals"])

    def test_kata_di_dalam_kata_tidak_diganti(self):
        result = normalize("orderanku")

        self.assertEqual(result["canonicals"], [])
        self.assertEqual(result["tokens"], ["orderanku"])

    def test_punctuation_dibersihkan_di_tokens(self):
        result = normalize("  STATUS (PO), terakhir! ")

        self.assertEqual(result["tokens"][0], "status")
        self.assertIn("purchase_order", result["canonicals"])

    def test_kata_kanonik_tidak_duplikat(self):
        result = normalize("barang produk item")

        self.assertEqual(result["canonicals"], ["produk"])
        self.assertEqual(result["tokens"], ["produk", "produk", "produk"])


class ToolSelectorCanonicalTests(SimpleTestCase):
    def test_barang_memilih_postgres_dan_analytics(self):
        self.assertEqual(
            tool_selector.select_tools("ANALYTICS_QUERY", {}, "barang paling mahal?"),
            ["mcp-analytics", "mcp-postgres-query"],
        )

    def test_mesin_rewel_memilih_analytics(self):
        self.assertEqual(
            tool_selector.select_tools("DIAGNOSTIC", {}, "mesin rewel?"),
            ["mcp-analytics", "mcp-event-log"],
        )

    def test_orderan_memilih_postgres(self):
        self.assertEqual(
            tool_selector.select_tools("DATA_LOOKUP", {}, "orderan terbaru?"),
            ["mcp-postgres-query"],
        )

    def test_faktur_memilih_odoo(self):
        self.assertEqual(
            tool_selector.select_tools("DATA_LOOKUP", {}, "faktur terbaru?"),
            ["mcp-postgres-query", "mcp-odoo-rpc"],
        )
