"""Test MCP aggregator T2.2 — agregasi database."""

from __future__ import annotations

from types import SimpleNamespace

from django.test import TestCase

from apps_industry.garment.models import ScrapAccumulator
from apps_industry.garment.tests.factories import make_bundle, make_work_center
from integrations.ai_agent.mcp_servers import mcp_aggregator


def _user(role="SUPERVISOR"):
    return SimpleNamespace(role=SimpleNamespace(code=role))


def _bundles():
    for value in range(1, 6):
        make_bundle(code=f"AGG-{value}", qty_done=value, state="DONE")


class AggregatorTests(TestCase):
    def setUp(self):
        _bundles()

    def _aggregate(self, **params):
        payload = {"table": "garment_bundle", "column": "qty_done"}
        payload.update(params)
        return mcp_aggregator.handle("aggregate", payload, _user())

    def test_sum(self):
        result = self._aggregate(agg="sum")

        self.assertTrue(result["ok"])
        self.assertEqual(result["result"], 15.0)
        self.assertEqual(result["count"], 5)

    def test_avg(self):
        result = self._aggregate(agg="avg")

        self.assertAlmostEqual(result["result"], 3.0)
        self.assertEqual(result["count"], 5)

    def test_count(self):
        result = self._aggregate(agg="count")

        self.assertEqual(result["result"], 5.0)
        self.assertEqual(result["count"], 5)

    def test_min_max(self):
        self.assertEqual(self._aggregate(agg="min")["result"], 1.0)
        self.assertEqual(self._aggregate(agg="max")["result"], 5.0)

    def test_p50_p90(self):
        p50 = self._aggregate(agg="p50")
        p90 = self._aggregate(agg="p90")

        self.assertAlmostEqual(p50["result"], 3.0, places=6)
        self.assertAlmostEqual(p90["result"], 4.6, places=6)

    def test_filter_state(self):
        result = self._aggregate(agg="sum", filters={"state": "DONE"})

        self.assertEqual(result["result"], 15.0)

    def test_group_by(self):
        wc_a = make_work_center(code="AGG-WC-A")
        wc_b = make_work_center(code="AGG-WC-B")
        ScrapAccumulator.objects.create(
            work_center=wc_a, qty=2, notes="agg-test"
        )
        ScrapAccumulator.objects.create(
            work_center=wc_b, qty=3, notes="agg-test"
        )

        result = mcp_aggregator.handle(
            "aggregate",
            {
                "table": "garment_scrapaccumulator",
                "column": "qty",
                "agg": "sum",
                "group_by": "work_center_id",
            },
            _user(),
        )

        self.assertTrue(result["ok"])
        self.assertIn("groups", result)
        self.assertEqual(result["result"], 5.0)

    def test_table_tidak_allowlist(self):
        result = mcp_aggregator.handle(
            "aggregate",
            {"table": "core_auth_user", "column": "id", "agg": "count"},
            _user(),
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "table_not_allowed")

    def test_agg_tidak_dikenal(self):
        result = self._aggregate(agg="median")

        self.assertEqual(result["error"], "agg_not_allowed")

    def test_role_operator_forbidden(self):
        result = mcp_aggregator.handle(
            "aggregate",
            {"table": "garment_bundle", "column": "qty_done", "agg": "sum"},
            _user("OPERATOR"),
        )

        self.assertEqual(result["error"], "forbidden")
