"""Test semantic cache (D.6) — 6 skenario."""

from __future__ import annotations

from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase

from integrations.ai_agent.config import AI_CONFIG
from integrations.ai_agent.memory import semantic_cache
from integrations.ai_agent.models import AISemanticCache


class SemanticCacheTests(TestCase):
    def setUp(self):
        cache.clear()
        semantic_cache._reset_for_tests()

    def test_miss_pertama_none(self):
        self.assertIsNone(semantic_cache.get("berapa scrap rate?"))

    def test_set_lalu_get_hit(self):
        payload = {"ok": True, "answer": "3.4%"}
        semantic_cache.set("berapa scrap rate?", payload)

        self.assertEqual(semantic_cache.get("berapa scrap rate?"), payload)

    def test_hit_count_increment(self):
        semantic_cache.set("scrap cutting", {"ok": True, "answer": "5%"})

        semantic_cache.get("scrap cutting")
        semantic_cache.get("scrap cutting")

        row = AISemanticCache.objects.get(query_normalized_text="scrap cutting")
        self.assertEqual(row.hit_count, 2)

    def test_query_beda_miss(self):
        semantic_cache.set("scrap cutting", {"ok": True, "answer": "5%"})

        self.assertIsNone(semantic_cache.get("scrap sewing"))

    def test_ttl_expired_miss(self):
        with patch.dict(
            AI_CONFIG,
            {"semantic_cache": {"ttl_seconds": 0, "similarity_threshold": 0.92}},
        ):
            semantic_cache.set("scrap ttl", {"ok": True, "answer": "x"})

        self.assertIsNone(semantic_cache.get("scrap ttl"))

    def test_invalidate_trigger(self):
        semantic_cache.set(
            "scrap invalidate",
            {"ok": True, "answer": "x"},
            invalidation_trigger="scrap_event",
        )
        self.assertIsNotNone(semantic_cache.get("scrap invalidate"))

        updated = semantic_cache.invalidate("scrap_event")

        self.assertEqual(updated, 1)
        self.assertIsNone(semantic_cache.get("scrap invalidate"))
