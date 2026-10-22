"""Test Fix #20 — data gap WC idle, buffer, dan seed operator."""

from __future__ import annotations

from datetime import datetime, timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps_industry.garment.models import BundleEvent
from apps_industry.garment.tests.factories import make_bundle, make_work_center
from core.auth.models import User
from integrations.ai_agent.orchestrator import context_builder, tool_selector
from integrations.analytics.plugins.garment.anomaly import operator_anomaly
from integrations.analytics.plugins.garment.metrics import (
    buffer_status,
    wc_idle_status,
)

NOW = timezone.make_aware(datetime(2026, 10, 14, 14, 0))


def _event(wc, ts):
    bundle = make_bundle(current_work_center=wc)
    event = BundleEvent.objects.create(bundle=bundle, event_type="BUNDLE_START")
    BundleEvent.objects.filter(pk=event.pk).update(ts=ts)


class WcIdleStatusMetricTests(TestCase):
    def test_wc_idle_3_jam_status_idle(self):
        wc = make_work_center("SEWING-2")
        _event(wc, NOW - timedelta(hours=3))

        rows = wc_idle_status._compute_wc_idle_status({"now": NOW.isoformat()})
        row = next(item for item in rows if item["label"] == "SEWING-2")

        self.assertEqual(row["status"], "IDLE")
        self.assertAlmostEqual(row["idle_hours"], 3.0, places=1)
        self.assertEqual(row["last_event_at"][:10], NOW.date().isoformat())

    def test_wc_aktif_status_active(self):
        wc = make_work_center("QC-1")
        _event(wc, NOW - timedelta(minutes=30))

        rows = wc_idle_status._compute_wc_idle_status({"now": NOW.isoformat()})
        row = next(item for item in rows if item["label"] == "QC-1")

        self.assertEqual(row["status"], "ACTIVE")

    def test_wc_tanpa_event_no_event(self):
        make_work_center("CUTTING-1")

        rows = wc_idle_status._compute_wc_idle_status({"now": NOW.isoformat()})
        row = next(item for item in rows if item["label"] == "CUTTING-1")

        self.assertEqual(row["status"], "NO_EVENT")
        self.assertIsNone(row["idle_hours"])


class BufferStatusMetricTests(TestCase):
    def test_buffer_21_overflow(self):
        wc = make_work_center("SEWING-2")
        for _index in range(21):
            make_bundle(current_work_center=wc)

        rows = buffer_status._compute_buffer_status({})
        row = next(item for item in rows if item["label"] == "SEWING-2")

        self.assertEqual(row["buffer_length"], 21)
        self.assertTrue(row["overflow"])
        self.assertEqual(row["status"], "OVERFLOW")

    def test_buffer_20_ok(self):
        wc = make_work_center("SEWING-3")
        for _index in range(20):
            make_bundle(current_work_center=wc)

        rows = buffer_status._compute_buffer_status({})
        row = next(item for item in rows if item["label"] == "SEWING-3")

        self.assertFalse(row["overflow"])
        self.assertEqual(row["status"], "OK")

    def test_threshold_custom(self):
        wc = make_work_center("SEWING-4")
        for _index in range(6):
            make_bundle(current_work_center=wc)

        rows = buffer_status._compute_buffer_status({"threshold": 5})
        row = next(item for item in rows if item["label"] == "SEWING-4")

        self.assertTrue(row["overflow"])

class ContextStatusTests(TestCase):
    def _context(self, message):
        def handler(method, params, user=None):
            metric_id = (params or {}).get("metric_id")
            if metric_id == "garment.wc_idle_status":
                return {
                    "ok": True,
                    "rows": [
                        {
                            "label": "SEWING-2",
                            "status": "IDLE",
                            "idle_hours": 3.0,
                        }
                    ],
                }
            if metric_id == "garment.buffer_status":
                return {
                    "ok": True,
                    "rows": [
                        {
                            "label": "SEWING-2",
                            "buffer_length": 21,
                            "overflow": True,
                        }
                    ],
                }
            return {"ok": False, "error": "analytics_disabled"}

        path = "integrations.ai_agent.orchestrator.context_builder.builder.mcp_analytics.handle_request"
        with patch(path, side_effect=handler):
            return context_builder.build_context(
                "ANALYTICS_QUERY",
                ["mcp-analytics"],
                message,
                {},
                user=None,
            )

    def test_pertanyaan_idle_menambah_wc_status(self):
        data = self._context("WC mana yang idle?")

        self.assertEqual(data["wc_status"][0]["status"], "IDLE")
        self.assertEqual(data["wc_status"][0]["idle_hours"], 3.0)

    def test_pertanyaan_buffer_menambah_buffer_status(self):
        data = self._context("Buffer mana yang overflow?")

        self.assertTrue(data["buffer_status"][0]["overflow"])
        self.assertEqual(data["buffer_status"][0]["buffer_length"], 21)

    def test_tanpa_keyword_tidak_query_status(self):
        data = self._context("berapa scrap hari ini?")

        self.assertNotIn("wc_status", data)
        self.assertNotIn("buffer_status", data)

    def test_selector_buffer_memaksa_analytics(self):
        self.assertIn(
            "mcp-analytics",
            tool_selector.select_tools(
                "ANALYTICS_QUERY", {}, "Buffer mana overflow?"
            ),
        )


class SeedOperatorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_rich_garment", stdout=StringIO())

    def test_seed_membuat_enam_operator(self):
        self.assertEqual(User.objects.filter(username__startswith="op-").count(), 6)

    def test_minimal_dua_operator_mencurigakan(self):
        summary = operator_anomaly.collect_operator_anomalies()

        self.assertGreaterEqual(summary["suspicious_count"], 2)
        scores = [item["score"] for item in summary["operators"]]
        self.assertLess(min(scores), 60)

    def test_seed_operator_idempoten(self):
        before = (
            User.objects.filter(username__startswith="op-").count(),
            BundleEvent.objects.filter(text__startswith="UAT ANOMALY").count(),
        )

        call_command("seed_rich_garment", stdout=StringIO())

        after = (
            User.objects.filter(username__startswith="op-").count(),
            BundleEvent.objects.filter(text__startswith="UAT ANOMALY").count(),
        )
        self.assertEqual(before, after)

