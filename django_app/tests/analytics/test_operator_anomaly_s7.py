"""Test S.7 — operator anomaly (phantom, cycle, scrap, reliability, context)."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps_industry.garment.models import BundleEvent
from apps_industry.garment.tests.factories import (
    make_bundle,
    make_scrap_accumulator,
    make_work_center,
)
from core.auth.models import Role, User
from integrations.ai_agent.orchestrator import context_builder, tool_selector
from integrations.analytics.plugins.garment.anomaly import operator_anomaly

DAY = timezone.make_aware(datetime(2026, 10, 10, 9, 0))


class AnomalyTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        role = Role.objects.get(code=Role.Code.OPERATOR)
        cls.operator = User.objects.create_user(
            username="op-anomaly", password="x", role=role
        )
        cls.other = User.objects.create_user(
            username="op-clean", password="x", role=role
        )

    def _event(self, bundle, event_type, ts, actor=None):
        event = BundleEvent.objects.create(
            bundle=bundle,
            event_type=event_type,
            actor=actor or self.operator,
        )
        BundleEvent.objects.filter(pk=event.pk).update(ts=ts)
        return event

    def _bundle(self, qty=100):
        return make_bundle(qty=qty)


class PhantomTests(AnomalyTestBase):
    def test_35_event_dalam_20_menit_suspicious(self):
        bundle = self._bundle()
        for index in range(35):
            self._event(bundle, "BUNDLE_START", DAY + timedelta(seconds=index * 30))

        result = operator_anomaly.detect_phantom_productivity(
            self.operator.pk, DAY.date()
        )

        self.assertTrue(result["suspicious"])
        self.assertEqual(result["max_events_in_window"], 35)
        self.assertIn("ditumpuk", result["message"])

    def test_event_tersebar_tidak_suspicious(self):
        bundle = self._bundle()
        for index in range(10):
            self._event(bundle, "BUNDLE_START", DAY + timedelta(minutes=index * 10))

        result = operator_anomaly.detect_phantom_productivity(
            self.operator.pk, DAY.date()
        )

        self.assertFalse(result["suspicious"])

    def test_operator_lain_tidak_dihitung(self):
        bundle = self._bundle()
        for index in range(35):
            self._event(
                bundle,
                "BUNDLE_START",
                DAY + timedelta(seconds=index * 10),
                actor=self.other,
            )

        result = operator_anomaly.detect_phantom_productivity(
            self.operator.pk, DAY.date()
        )

        self.assertEqual(result["events"], 0)
        self.assertFalse(result["suspicious"])

    def test_tanpa_event_aman(self):
        result = operator_anomaly.detect_phantom_productivity(
            self.operator.pk, DAY.date()
        )

        self.assertFalse(result["suspicious"])
        self.assertEqual(result["max_events_in_window"], 0)


class ImpossibleCycleTests(AnomalyTestBase):
    def test_siklus_30_detik_suspicious(self):
        bundle = self._bundle()
        self._event(bundle, "BUNDLE_START", DAY)
        self._event(bundle, "BUNDLE_FINISH", DAY + timedelta(seconds=30))

        result = operator_anomaly.detect_impossible_cycle_time(bundle.pk)

        self.assertTrue(result["suspicious"])
        self.assertEqual(result["min_cycle_seconds"], 30.0)

    def test_siklus_90_detik_aman(self):
        bundle = self._bundle()
        self._event(bundle, "BUNDLE_START", DAY)
        self._event(bundle, "BUNDLE_FINISH", DAY + timedelta(seconds=90))

        result = operator_anomaly.detect_impossible_cycle_time(bundle.pk)

        self.assertFalse(result["suspicious"])
        self.assertEqual(result["min_cycle_seconds"], 90.0)

    def test_tanpa_finish_tidak_ada_siklus(self):
        bundle = self._bundle()
        self._event(bundle, "BUNDLE_START", DAY)

        result = operator_anomaly.detect_impossible_cycle_time(bundle.pk)

        self.assertFalse(result["suspicious"])
        self.assertIsNone(result["min_cycle_seconds"])

    def test_multi_siklus_menghitung_yang_mustahil(self):
        bundle = self._bundle()
        self._event(bundle, "BUNDLE_START", DAY)
        self._event(bundle, "BUNDLE_FINISH", DAY + timedelta(seconds=20))
        self._event(bundle, "BUNDLE_START", DAY + timedelta(minutes=10))
        self._event(bundle, "BUNDLE_FINISH", DAY + timedelta(minutes=11))

        result = operator_anomaly.detect_impossible_cycle_time(bundle.pk)

        self.assertEqual(result["occurrences"], 2)
        self.assertEqual(result["impossible_count"], 1)

class ScrapDiscrepancyTests(AnomalyTestBase):
    def test_scrap_15_persen_suspicious(self):
        bundle = self._bundle(qty=100)
        wc = make_work_center("SEWING-1")
        make_scrap_accumulator(bundle=bundle, work_center=wc, qty=15)

        result = operator_anomaly.detect_scrap_discrepancy(
            bundle.work_order.order_line.order_id
        )

        self.assertTrue(result["suspicious"])
        self.assertEqual(result["scrap_ratio"], 0.15)

    def test_scrap_5_persen_aman(self):
        bundle = self._bundle(qty=100)
        wc = make_work_center("SEWING-2")
        make_scrap_accumulator(bundle=bundle, work_center=wc, qty=5)

        result = operator_anomaly.detect_scrap_discrepancy(
            bundle.work_order.order_line.order_id
        )

        self.assertFalse(result["suspicious"])

    def test_input_nol_tidak_suspicious(self):
        bundle = self._bundle(qty=0)
        wc = make_work_center("SEWING-3")
        make_scrap_accumulator(bundle=bundle, work_center=wc, qty=10)

        result = operator_anomaly.detect_scrap_discrepancy(
            bundle.work_order.order_line.order_id
        )

        self.assertFalse(result["suspicious"])
        self.assertEqual(result["scrap_ratio"], 0.0)

    def test_tanpa_scrap_aman(self):
        bundle = self._bundle(qty=50)

        result = operator_anomaly.detect_scrap_discrepancy(
            bundle.work_order.order_line.order_id
        )

        self.assertFalse(result["suspicious"])


class ReliabilityTests(AnomalyTestBase):
    def _now(self, seconds_ago: int):
        return timezone.now() - timedelta(seconds=seconds_ago)

    def _make_bad_operator(self):
        bundle = self._bundle(qty=100)
        for index in range(35):
            self._event(
                bundle, "BUNDLE_START", self._now(1200 - index * 20)
            )

        cycle_bundle = self._bundle(qty=10)
        self._event(cycle_bundle, "BUNDLE_START", self._now(600))
        self._event(cycle_bundle, "BUNDLE_FINISH", self._now(580))

        wc = make_work_center("SEWING-1")
        make_scrap_accumulator(bundle=bundle, work_center=wc, qty=15)
        return bundle

    def test_operator_bermasalah_skor_rendah(self):
        self._make_bad_operator()

        result = operator_anomaly.compute_reliability_index(self.operator.pk)

        self.assertEqual(result["score"], 55)
        self.assertEqual(result["level"], "RENDAH")
        self.assertTrue(result["suspicious"])
        self.assertEqual(result["breakdown"]["phantom_days"], 1)
        self.assertEqual(result["breakdown"]["impossible_cycles"], 1)
        self.assertEqual(result["breakdown"]["scrap_discrepancies"], 1)

    def test_operator_bersih_skor_100(self):
        bundle = self._bundle()
        for index in range(3):
            self._event(
                bundle,
                "BUNDLE_START",
                self._now(7200 - index * 1800),
                actor=self.other,
            )

        result = operator_anomaly.compute_reliability_index(self.other.pk)

        self.assertEqual(result["score"], 100)
        self.assertEqual(result["level"], "BAIK")
        self.assertFalse(result["suspicious"])

    def test_penalti_dibatasi(self):
        bundle = self._bundle()
        for index in range(35):
            self._event(bundle, "BUNDLE_START", self._now(1800 - index * 10))
        for index in range(5):
            cycle = self._bundle(qty=1)
            self._event(cycle, "BUNDLE_START", self._now(3000 + index * 100))
            self._event(cycle, "BUNDLE_FINISH", self._now(2995 + index * 100))

        result = operator_anomaly.compute_reliability_index(self.operator.pk)

        self.assertLessEqual(result["breakdown"]["penalty_cycle"], 30)
        self.assertGreaterEqual(result["score"], 0)

    def test_scan_dan_collect(self):
        self._make_bad_operator()
        clean_bundle = self._bundle()
        self._event(clean_bundle, "BUNDLE_START", self._now(60), actor=self.other)

        scanned = operator_anomaly.scan_suspicious_operators()
        summary = operator_anomaly.collect_operator_anomalies()

        self.assertEqual(scanned[0]["operator_id"], self.operator.pk)
        self.assertGreaterEqual(summary["suspicious_count"], 1)
        self.assertTrue(summary["summary"])

    def test_keyword_selector_mcp_analytics(self):
        for message in (
            "OEE SEWING-2?",
            "WIP per jam?",
            "WC idle?",
            "operator mana yang inputnya tidak wajar?",
        ):
            with self.subTest(message=message):
                self.assertIn(
                    "mcp-analytics",
                    tool_selector.select_tools("ANALYTICS_QUERY", {}, message),
                )

    def test_context_builder_menambah_operator_anomalies(self):
        self._make_bad_operator()
        path = "integrations.ai_agent.orchestrator.context_builder.builder.mcp_analytics.handle_request"
        with patch(path, return_value={"ok": False, "error": "analytics_disabled"}):
            data = context_builder.build_context(
                "ANALYTICS_QUERY",
                ["mcp-analytics"],
                "operator mana yang inputnya tidak wajar?",
                {},
                user=self.operator,
            )

        self.assertIn("operator_anomalies", data)
        self.assertIn("operators", data["operator_anomalies"])

