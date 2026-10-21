"""Test decision gate (D.2) — 10 skenario."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from integrations.ai_agent.config import AI_CONFIG
from integrations.ai_agent.decision_gate import cost_estimator, rule_evaluator


def _user(role_code: str):
    return SimpleNamespace(role=SimpleNamespace(code=role_code))


class RuleEvaluatorTests(SimpleTestCase):
    def test_r1_analytics_off_rule_hit(self):
        with patch(
            "integrations.ai_agent.decision_gate.rule_evaluator."
            "analytics_config_services.analytics_enabled",
            return_value=False,
        ):
            result = rule_evaluator.evaluate("analitik belum aktif?", {}, _user("SUPERVISOR"))

        self.assertEqual(result["result"], "RULE_HIT")
        self.assertEqual(result["rule_id"], "R1")
        self.assertIn("Analitik belum aktif", result["answer"])
        self.assertEqual(result["tokens"], 0)

    def test_r1_analytics_on_llm_needed(self):
        with patch(
            "integrations.ai_agent.decision_gate.rule_evaluator."
            "analytics_config_services.analytics_enabled",
            return_value=True,
        ):
            result = rule_evaluator.evaluate("analitik belum aktif?", {}, _user("SUPERVISOR"))

        self.assertEqual(result["result"], "LLM_NEEDED")

    def test_r2_role_tidak_berhak_blocked(self):
        result = rule_evaluator.evaluate("berapa produk aktif?", {}, _user("OPERATOR"))

        self.assertEqual(result["result"], "BLOCKED")
        self.assertEqual(result["rule_id"], "R2")
        self.assertIn("tidak berhak", result["answer"])

    def test_r3_context_invalid_blocked(self):
        result = rule_evaluator.evaluate(
            "jelaskan",
            {"page_type": "detail", "resource_type": "product", "resource_id": None},
            _user("SUPERVISOR"),
        )

        self.assertEqual(result["result"], "BLOCKED")
        self.assertEqual(result["rule_id"], "R3")

    def test_default_llm_needed(self):
        result = rule_evaluator.evaluate("kenapa scrap naik?", {}, _user("SUPERVISOR"))

        self.assertEqual(result["result"], "LLM_NEEDED")
        self.assertEqual(result["tokens"], 0)

    def test_blocked_tokens_nol(self):
        result = rule_evaluator.evaluate("produk apa?", {}, _user("QC"))

        self.assertEqual(result["tokens"], 0)


class CostEstimatorTests(SimpleTestCase):
    def test_pesan_pendek_tidak_exceed(self):
        estimation = cost_estimator.estimate("halo", {})

        self.assertLess(estimation["total_cost_usd"], 0.05)
        self.assertFalse(estimation["exceeds_budget"])

    def test_pesan_panjang_exceed_budget_kecil(self):
        message = "kata " * 1200
        with patch.dict(
            AI_CONFIG,
            {"decision_gate": {"rule_hit_max_tokens": 0, "cost_budget_usd_per_query": 0.0001}},
        ):
            estimation = cost_estimator.estimate(message, {})

        self.assertTrue(estimation["exceeds_budget"])

    def test_context_besar_biaya_lebih_tinggi(self):
        small = cost_estimator.estimate("halo", {})
        large = cost_estimator.estimate(
            "halo", {"snapshot": "x" * 4000, "route": "/master/products/1"}
        )

        self.assertGreater(large["total_cost_usd"], small["total_cost_usd"])
        self.assertGreater(large["prompt_tokens"], small["prompt_tokens"])

    def test_completion_tokens_default_200(self):
        estimation = cost_estimator.estimate("halo", {})

        self.assertEqual(estimation["completion_tokens"], 200)
        self.assertGreater(estimation["total_cost_usd"], 0)
