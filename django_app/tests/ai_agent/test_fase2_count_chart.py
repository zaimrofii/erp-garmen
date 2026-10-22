"""Test Fase 2 — total count DB, chart relevan, ordering, dan cache key."""

from __future__ import annotations

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps_industry.garment.models import Order
from integrations.ai_agent.api.handlers.llm_pipeline import build_cache_scope
from integrations.ai_agent.data_access.orders import OrderRepository
from integrations.ai_agent.orchestrator.chart_builder import build_chart_data
from integrations.ai_agent.orchestrator.context_builder import build_context
from integrations.analytics.core import event_listener
from master.models import Partner


METRICS = [
    {
        "metric_id": "garment.scrap_rate",
        "dimension": "period",
        "unit": "%",
        "rows": [
            {"label": "2026-10-18", "value": 1.6},
            {"label": "2026-10-19", "value": 2.0},
            {"label": "2026-10-20", "value": 2.4},
        ],
    },
    {
        "metric_id": "garment.lead_time",
        "dimension": "period",
        "unit": "jam",
        "rows": [
            {"label": "2026-10-18", "value": 20.0},
            {"label": "2026-10-19", "value": 21.5},
            {"label": "2026-10-20", "value": 22.0},
        ],
    },
    {
        "metric_id": "garment.oee",
        "dimension": "period",
        "unit": "%",
        "rows": [
            {"label": "2026-10-18", "value": 70.0},
            {"label": "2026-10-19", "value": 72.0},
            {"label": "2026-10-20", "value": 71.0},
        ],
    },
    {
        "metric_id": "garment.bottleneck",
        "dimension": "period",
        "unit": "%",
        "rows": [
            {"label": "2026-10-18", "value": 10.0},
            {"label": "2026-10-19", "value": 12.0},
        ],
    },
]

class TotalCountTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_big_test", stdout=StringIO())
        # Seed dev punya 25 customer; test DB mulai dari master kosong.
        for index in range(15):
            Partner.objects.get_or_create(
                code=f"FASE2-CUST-{index:02d}",
                defaults={"name": f"Customer Fase 2 {index}", "is_customer": True},
            )
        # Pastikan semua order masuk periode bulan/hari yang diuji.
        Order.objects.update(created_at=timezone.now())

    def _context(self, message: str) -> dict:
        return build_context(
            "DATA_LOOKUP", ["mcp-postgres-query"], message, {}, user=None
        )

    def test_total_order_dari_count_bukan_20_baris(self):
        data = self._context("total order?")
        self.assertEqual(data["total_counts"]["total"], 50)
        self.assertNotIn("orders", data)

    def test_total_order_bulan_ini(self):
        data = self._context("total order bulan ini?")
        self.assertEqual(data["total_counts"]["total"], 50)
        self.assertEqual(data["total_counts"]["period"], "bulan_ini")

    def test_total_order_hari_ini(self):
        data = self._context("total order hari ini?")
        self.assertEqual(
            data["total_counts"]["total"],
            Order.objects.filter(created_at__date=timezone.localdate()).count(),
        )

    def test_total_bundle(self):
        self.assertEqual(self._context("total bundle?")["total_counts"]["total"], 200)

    def test_total_customer(self):
        data = self._context("total customer?")
        self.assertEqual(data["total_counts"]["total"], 25)

    def test_total_order_konsisten_tiga_kali(self):
        totals = [
            self._context("total order?")["total_counts"]["total"] for _ in range(3)
        ]
        self.assertEqual(totals, [50, 50, 50])

    def test_breakdown_state_order(self):
        data = self._context("total order?")
        self.assertEqual(data["total_counts"]["breakdown"]["DONE"], 30)



class ChartRelevanceTests(SimpleTestCase):
    def test_total_order_tanpa_chart(self):
        self.assertIsNone(
            build_chart_data({"metrics": METRICS}, "ANALYTICS_QUERY", "total order?")
        )

    def test_produk_termahal_tanpa_chart(self):
        self.assertIsNone(
            build_chart_data({"metrics": METRICS}, "ANALYTICS_QUERY", "produk termahal?")
        )

    def test_tren_scrap_chart_scrap(self):
        chart = build_chart_data(
            {"metrics": METRICS}, "ANALYTICS_QUERY", "tren scrap?"
        )
        self.assertIsNotNone(chart)
        self.assertEqual(chart["metric_id"], "garment.scrap_rate")
        self.assertEqual(chart["title"], "Tren Scrap")

    def test_tren_lead_time_chart_lead_time(self):
        chart = build_chart_data(
            {"metrics": METRICS}, "ANALYTICS_QUERY", "tren lead time?"
        )
        self.assertIsNotNone(chart)
        self.assertEqual(chart["metric_id"], "garment.lead_time")

    def test_oee_chart_oee(self):
        chart = build_chart_data(
            {"metrics": METRICS}, "ANALYTICS_QUERY", "OEE SEWING-2?"
        )
        self.assertIsNotNone(chart)
        self.assertEqual(chart["metric_id"], "garment.oee")

    def test_bottleneck_tanpa_chart(self):
        self.assertIsNone(
            build_chart_data({"metrics": METRICS}, "ANALYTICS_QUERY", "bottleneck?")
        )


class CacheAndOrderingTests(TestCase):
    def test_ordering_tiebreaker_id(self):
        now = timezone.now()
        first = Order.objects.create(code="FASE2-TIE-1")
        second = Order.objects.create(code="FASE2-TIE-2")
        Order.objects.filter(pk__in=[first.pk, second.pk]).update(created_at=now)

        rows = OrderRepository().get_list(limit=2)

        self.assertEqual([row["id"] for row in rows], [second.pk, first.pk])

    def test_cache_key_beda_filter_dan_context(self):
        with patch(
            "integrations.ai_agent.api.handlers.llm_pipeline._data_version",
            return_value="v1",
        ):
            base = build_cache_scope(
                "SUPERVISOR", "DESKTOP", "total order?", {"page_type": "list"}
            )
            same = build_cache_scope(
                "SUPERVISOR", "DESKTOP", "total order?", {"page_type": "list"}
            )
            other_context = build_cache_scope(
                "SUPERVISOR",
                "DESKTOP",
                "total order?",
                {"page_type": "detail", "resource_id": 7},
            )
            other_filter = build_cache_scope(
                "SUPERVISOR", "DESKTOP", "total order bulan ini?", {"page_type": "list"}
            )

        self.assertEqual(base, same)
        self.assertNotEqual(base, other_context)
        self.assertNotEqual(base, other_filter)

    def test_order_event_invalidasi_cache(self):
        with patch(
            "integrations.analytics.services.analytics_config_services.invalidate_cache"
        ), patch(
            "integrations.ai_agent.memory.semantic_cache.invalidate"
        ) as invalidate:
            event_listener.handle_order_state_changed(
                event_name="ORDER_STATE_CHANGED", payload={"order_id": 1}
            )

        invalidate.assert_called_once_with(trigger="order_state")

