"""Test conversation context (FIX #4) — resolve follow-up tanpa LLM."""

from __future__ import annotations

from types import SimpleNamespace

from django.test import SimpleTestCase

from integrations.ai_agent.orchestrator.conversation_context import (
    is_followup,
    resolve_followup,
)

HISTORY = [
    {"role": "user", "content": "produk paling mahal?"},
    {"role": "assistant", "content": "Jaket Premium adalah yang termahal."},
]


class FollowupDetectionTests(SimpleTestCase):
    def test_peringkat_kedua_adalah_followup(self):
        self.assertTrue(is_followup("peringkat kedua?"))

    def test_pertanyaan_biasa_bukan_followup(self):
        self.assertFalse(is_followup("produk apa saja?"))

    def test_order_terbaru_bukan_followup(self):
        self.assertFalse(is_followup("orderan terbaru?"))

    def test_kemarin_adalah_followup(self):
        self.assertTrue(is_followup("kalau yang kemarin?"))


class FollowupResolutionTests(SimpleTestCase):
    def test_resolve_peringkat_kedua(self):
        result = resolve_followup("peringkat kedua?", HISTORY)

        self.assertTrue(result["is_followup"])
        self.assertEqual(result["target_rank"], 2)
        self.assertEqual(result["previous_query"], "produk paling mahal?")
        self.assertEqual(result["previous_answer"], "Jaket Premium adalah yang termahal.")
        self.assertEqual(result["target_entity"], "product")
        self.assertEqual(result["topic"], "product_ranking")
        self.assertIn("produk paling mahal?", result["resolved_message"])
        self.assertIn("peringkat kedua?", result["resolved_message"])

    def test_tanpa_history_bukan_followup(self):
        result = resolve_followup("peringkat kedua?", [])

        self.assertFalse(result["is_followup"])
        self.assertIsNone(result["target_rank"])

    def test_peringkat_ketiga(self):
        result = resolve_followup("peringkat ketiga?", HISTORY)

        self.assertEqual(result["target_rank"], 3)

    def test_history_hanya_user(self):
        result = resolve_followup(
            "yang tadi?", [{"role": "user", "content": "order terbaru?"}]
        )

        self.assertTrue(result["is_followup"])
        self.assertEqual(result["previous_query"], "order terbaru?")
        self.assertEqual(result["target_entity"], "order")
        self.assertIsNone(result["previous_answer"])

    def test_history_objek_bukan_dict(self):
        history = [
            SimpleNamespace(role="user", content="bundle mana paling lambat?"),
            SimpleNamespace(role="assistant", content="BND-1."),
        ]
        result = resolve_followup("peringkat kedua?", history)

        self.assertTrue(result["is_followup"])
        self.assertEqual(result["target_entity"], "bundle")
        self.assertEqual(result["target_rank"], 2)

    def test_yg_kemarin_dengan_history_tren_scrap(self):
        history = [
            {"role": "user", "content": "tren scrap 30 hari?"},
            {"role": "assistant", "content": "Scrap menurun."},
        ]
        result = resolve_followup("yg kemarin?", history)

        self.assertTrue(result["is_followup"])
        self.assertEqual(result["previous_query"], "tren scrap 30 hari?")
        self.assertIn("follow-up", result["resolved_message"])

    def test_assistant_tanpa_user_tidak_dianggap_followup(self):
        result = resolve_followup(
            "peringkat kedua?", [{"role": "assistant", "content": "Halo."}]
        )

        self.assertFalse(result["is_followup"])
