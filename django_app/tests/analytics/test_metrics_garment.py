"""Test 3 metrik garment (B.6) — formula CONTRACT §8."""

from __future__ import annotations

import itertools
import uuid
from datetime import datetime, timedelta

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps_industry.garment.models import Bundle, BundleEvent, ScrapAccumulator
from apps_industry.garment.tests.factories import (
    make_bundle,
    make_line,
    make_order_line,
    make_scrap_accumulator,
    make_work_center,
    make_work_order,
)
from integrations.analytics.core import registry
from integrations.analytics.plugins.garment.metrics import (
    lead_time,
    rework_rate,
    scrap_rate,
)
from integrations.analytics.plugins.garment.plugin import METRICS
from master.models import Product

DAY = timezone.make_aware(datetime(2026, 10, 10, 12, 0))
_ODOO_SEQ = itertools.count(1)


class GarmentMetricsTestBase(TestCase):
    """Helper pembuat bundle + event dengan timestamp terkontrol."""

    def _bundle(self, *, qty=10, wo_qty=1000, wc=None, line=None):
        product = Product.objects.create(
            code=f"P-{uuid.uuid4().hex[:8]}", name="Produk", odoo_id=next(_ODOO_SEQ)
        )
        order_line = make_order_line(product=product)
        work_order = make_work_order(order_line=order_line, qty_planned=wo_qty)
        return make_bundle(
            work_order=work_order,
            qty=qty,
            current_work_center=wc,
            production_line=line,
        )

    def _event(self, bundle, event_type: str, ts=None, payload=None):
        event = BundleEvent.objects.create(
            bundle=bundle, event_type=event_type, payload=payload or {}
        )
        if ts is not None:
            BundleEvent.objects.filter(pk=event.pk).update(ts=ts)
        return event

    def _scrap(self, bundle, qty=1, *, wc=None, ts=DAY):
        accumulator = make_scrap_accumulator(
            bundle=bundle,
            work_center=wc or bundle.current_work_center or make_work_center(),
            qty=qty,
        )
        ScrapAccumulator.objects.filter(pk=accumulator.pk).update(created_at=ts)
        return accumulator


class RegistryAutodiscoverTests(GarmentMetricsTestBase):
    def test_autodiscover_menemukan_lima_metrik(self):
        self.addCleanup(registry.discover_metrics)
        registry._reset_for_tests()

        count = registry.discover_metrics()

        self.assertEqual(count, 5)
        self.assertEqual(
            {metric.metric_id for metric in registry.list_metrics("garment")},
            {
                "garment.scrap_rate",
                "garment.rework_rate",
                "garment.lead_time",
                "garment.line_balance",
                "garment.bottleneck",
            },
        )


class ScrapRateTests(GarmentMetricsTestBase):
    def test_denominator_bundle_qty_bukan_wo_qty_planned(self):
        bundle = self._bundle(qty=10, wo_qty=1000)
        self._event(bundle, "BUNDLE_FINISH", ts=DAY)
        self._scrap(bundle, 1)

        rows = scrap_rate._compute_scrap_rate(
            {"granularity": "day", "group_by": "period"}
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["denominator"], 10)  # Bundle.qty, bukan 1000
        self.assertEqual(rows[0]["value"], 10.0)

    def test_denominator_nol_value_none(self):
        bundle = self._bundle()
        self._scrap(bundle, 3)

        rows = scrap_rate._compute_scrap_rate(
            {"granularity": "day", "group_by": "period"}
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["denominator"], 0)
        self.assertIsNone(rows[0]["value"])

    def test_compute_set_based_maks_tiga_query(self):
        bundle = self._bundle()
        self._event(bundle, "BUNDLE_FINISH", ts=DAY)
        self._scrap(bundle, 1)

        with CaptureQueriesContext(connection) as queries:
            scrap_rate._compute_scrap_rate(
                {"granularity": "day", "group_by": "period"}
            )

        self.assertLessEqual(len(queries), 3)


class ReworkRateTests(GarmentMetricsTestBase):
    def test_numerator_payload_qty(self):
        bundle = self._bundle(qty=12)
        self._event(bundle, "BUNDLE_FINISH", ts=DAY)
        self._event(bundle, "REWORK", ts=DAY, payload={"qty": 3})

        rows = rework_rate._compute_rework_rate(
            {"granularity": "day", "group_by": "period"}
        )

        self.assertEqual(rows[0]["value"], 25.0)

    def test_numerator_fallback_satu_per_event(self):
        bundle = self._bundle(qty=10)
        self._event(bundle, "BUNDLE_FINISH", ts=DAY)
        self._event(bundle, "REWORK", ts=DAY, payload={})

        rows = rework_rate._compute_rework_rate(
            {"granularity": "day", "group_by": "period"}
        )

        self.assertEqual(rows[0]["value"], 10.0)

    def test_tidak_memakai_scrap_accumulator_rework_qty(self):
        bundle = self._bundle(qty=10)
        self._event(bundle, "BUNDLE_FINISH", ts=DAY)
        make_scrap_accumulator(bundle=bundle, rework_qty=5)

        rows = rework_rate._compute_rework_rate(
            {"granularity": "day", "group_by": "period"}
        )

        self.assertEqual(rows[0]["value"], 0.0)


class LeadTimeTests(GarmentMetricsTestBase):
    def test_lead_time_jam_benar(self):
        bundle = self._bundle()
        self._event(bundle, "BUNDLE_START", ts=DAY - timedelta(hours=2))
        self._event(bundle, "BUNDLE_FINISH", ts=DAY)

        rows = lead_time._compute_lead_time(
            {"granularity": "day", "group_by": "period"}
        )

        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["value"], 2.0, places=6)

    def test_bundle_tanpa_finish_incomplete_pairs(self):
        bundle = self._bundle()
        self._event(bundle, "BUNDLE_START", ts=DAY - timedelta(hours=1))

        self.assertGreaterEqual(lead_time.count_incomplete_pairs({}), 1)

    def test_p50_p90_manual(self):
        for hours in (1, 2, 10):
            bundle = self._bundle()
            self._event(bundle, "BUNDLE_START", ts=DAY - timedelta(hours=hours))
            self._event(bundle, "BUNDLE_FINISH", ts=DAY)

        rows = lead_time._compute_lead_time(
            {"granularity": "day", "group_by": "period"}
        )

        self.assertEqual(rows[0]["p50"], 2.0)
        self.assertEqual(rows[0]["p90"], 10.0)
        self.assertEqual(rows[0]["n_bundles"], 3)


class GroupingFilterTests(GarmentMetricsTestBase):
    def test_group_by_work_center(self):
        wc1 = make_work_center()
        wc2 = make_work_center()
        for wc, qty in ((wc1, 1), (wc2, 2)):
            bundle = self._bundle(wc=wc)
            self._event(bundle, "BUNDLE_FINISH", ts=DAY)
            self._scrap(bundle, qty, wc=wc)

        rows = scrap_rate._compute_scrap_rate(
            {"granularity": "day", "group_by": "work_center"}
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual({row["key"] for row in rows}, {str(wc1.pk), str(wc2.pk)})

    def test_group_by_line(self):
        line1 = make_line()
        line2 = make_line()
        for production_line in (line1, line2):
            bundle = self._bundle(line=production_line)
            self._event(bundle, "BUNDLE_FINISH", ts=DAY)
            self._scrap(bundle, 1)

        rows = scrap_rate._compute_scrap_rate(
            {"granularity": "day", "group_by": "line"}
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(
            {row["key"] for row in rows}, {str(line1.pk), str(line2.pk)}
        )

    def test_filter_work_center_id(self):
        wc1 = make_work_center()
        wc2 = make_work_center()
        for wc in (wc1, wc2):
            bundle = self._bundle(wc=wc)
            self._event(bundle, "BUNDLE_FINISH", ts=DAY)
            self._scrap(bundle, 1)

        rows = scrap_rate._compute_scrap_rate(
            {"granularity": "day", "group_by": "work_center", "work_center_id": wc1.pk}
        )

        self.assertEqual([row["key"] for row in rows], [str(wc1.pk)])

    def test_filter_line_id(self):
        line1 = make_line()
        line2 = make_line()
        for production_line in (line1, line2):
            bundle = self._bundle(line=production_line)
            self._event(bundle, "BUNDLE_FINISH", ts=DAY)
            self._scrap(bundle, 1)

        rows = scrap_rate._compute_scrap_rate(
            {"granularity": "day", "group_by": "line", "line_id": line2.pk}
        )

        self.assertEqual([row["key"] for row in rows], [str(line2.pk)])


class MetricMetadataTests(TestCase):
    def test_formula_version_satu(self):
        self.assertTrue(all(metric.formula_version == "1.0" for metric in METRICS))

    def test_source_models_sesuai_kontrak(self):
        by_id = {metric.metric_id: metric for metric in METRICS}

        self.assertEqual(
            by_id["garment.scrap_rate"].source_models,
            ["garment.ScrapAccumulator", "garment.BundleEvent"],
        )
        self.assertEqual(
            by_id["garment.rework_rate"].source_models,
            ["garment.BundleEvent", "garment.Bundle"],
        )
        self.assertEqual(
            by_id["garment.lead_time"].source_models,
            ["garment.BundleEvent", "garment.Bundle"],
        )

    def test_null_policy_denominator_zero(self):
        by_id = {metric.metric_id: metric for metric in METRICS}

        for metric_id in (
            "garment.scrap_rate",
            "garment.rework_rate",
            "garment.lead_time",
        ):
            self.assertEqual(
                by_id[metric_id].null_policy, "denominator_zero_returns_null"
            )

        # R.4 — metrik snapshot memakai null policy sendiri.
        self.assertEqual(
            by_id["garment.line_balance"].null_policy, "no_line_returns_empty"
        )
        self.assertEqual(
            by_id["garment.bottleneck"].null_policy, "no_active_returns_empty"
        )

    def test_granularities(self):
        by_id = {metric.metric_id: metric for metric in METRICS}

        self.assertEqual(by_id["garment.scrap_rate"].granularities, ["hour", "day"])
        self.assertEqual(by_id["garment.rework_rate"].granularities, ["hour", "day"])
        self.assertEqual(by_id["garment.lead_time"].granularities, ["day"])

