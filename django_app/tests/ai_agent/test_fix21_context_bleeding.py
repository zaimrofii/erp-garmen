"""Regresi FIX #21 — cegah context bleeding dari history."""

from __future__ import annotations

from django.test import SimpleTestCase

from integrations.ai_agent.orchestrator.conversation_context import resolve_followup


class ContextBleedingFixTests(SimpleTestCase):
    def test_topic_baru_tanpa_marker_tidak_prepend(self):
        history = [
            {"role": "user", "content": "produk scrap?"},
            {"role": "assistant", "content": "Scrap 8%."},
        ]

        result = resolve_followup("rata-rata harga?", history)

        self.assertFalse(result["is_followup"])
        self.assertEqual(result["resolved_message"], "rata-rata harga?")
        self.assertIsNone(result["previous_query"])

    def test_intent_analytics_baru_tidak_prepend_data_lookup(self):
        history = [
            {"role": "user", "content": "produk termahal?"},
            {"role": "assistant", "content": "Jaket Premium."},
        ]

        result = resolve_followup(
            "tren scrap?", history, intent="ANALYTICS_QUERY"
        )

        self.assertFalse(result["is_followup"])
        self.assertEqual(result["resolved_message"], "tren scrap?")
        self.assertIsNone(result["target_entity"])

    def test_kode_order_berbeda_tidak_prepend(self):
        history = [
            {"role": "user", "content": "SO-DEMO-0001?"},
            {"role": "assistant", "content": "Order SO-DEMO-0001."},
        ]

        result = resolve_followup("SO-BIG-0008?", history)

        self.assertFalse(result["is_followup"])
        self.assertEqual(result["resolved_message"], "SO-BIG-0008?")
        self.assertIsNone(result["entity_code"])
