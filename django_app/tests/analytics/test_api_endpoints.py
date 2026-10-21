"""Test endpoint analytics API (B.7) — auth, toggle OFF/ON, cache, filter."""

from __future__ import annotations

import itertools
import uuid

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps_industry.garment.models import BundleEvent
from apps_industry.garment.tests.factories import (
    make_bundle,
    make_order_line,
    make_scrap_accumulator,
    make_work_center,
    make_work_order,
)
from core.auth.models import Role, User
from integrations.analytics.core import registry
from integrations.analytics.plugins.garment.models import MetricSnapshot
from integrations.analytics.services import analytics_config_services as svc
from master.models import Product

METRICS_URL = "/api/v1/analytics/metrics/garment/"
METRIC_URL = "/api/v1/analytics/metric/garment.scrap_rate/"
HEALTH_URL = "/api/v1/analytics/health/"

_ODOO = itertools.count(1)


def make_user(username: str, role_code: str) -> User:
    user = User.objects.create_user(username=username, password="rahasia")  # noqa: S106
    user.role = Role.objects.get(code=role_code)
    user.save(update_fields=["role"])
    return user


class AnalyticsApiBase(TestCase):
    def setUp(self):
        cache.clear()
        registry.discover_metrics()

    def _seed_metric_data(self, wc=None):
        product = Product.objects.create(
            code=f"P-{uuid.uuid4().hex[:8]}", name="Produk", odoo_id=next(_ODOO)
        )
        work_order = make_work_order(
            order_line=make_order_line(product=product), qty_planned=1000
        )
        bundle = make_bundle(work_order=work_order, qty=10, current_work_center=wc)
        BundleEvent.objects.create(bundle=bundle, event_type="BUNDLE_FINISH")
        make_scrap_accumulator(
            bundle=bundle, work_center=wc or make_work_center(), qty=1
        )

    def _client(self, role_code: str) -> APIClient:
        api = APIClient()
        api.force_authenticate(make_user(f"u-{uuid.uuid4().hex[:6]}", role_code))
        return api


class AnalyticsAuthTests(AnalyticsApiBase):
    def test_anon_metrics_403(self):
        self.assertEqual(APIClient().get(METRICS_URL).status_code, 403)

    def test_anon_health_403(self):
        self.assertEqual(APIClient().get(HEALTH_URL).status_code, 403)

    def test_operator_403(self):
        api = self._client(Role.Code.OPERATOR)

        self.assertEqual(api.get(METRICS_URL).status_code, 403)

    def test_supervisor_200(self):
        api = self._client(Role.Code.SUPERVISOR)

        self.assertEqual(api.get(METRICS_URL).status_code, 200)

    def test_admin_200(self):
        api = self._client(Role.Code.ADMIN)

        self.assertEqual(api.get(METRICS_URL).status_code, 200)


class AnalyticsToggleOffTests(AnalyticsApiBase):
    def setUp(self):
        super().setUp()
        self.api = self._client(Role.Code.SUPERVISOR)

    def test_off_200_rows_kosong(self):
        response = self.api.get(METRICS_URL)

        self.assertEqual(response.status_code, 200)  # BUKAN 503
        body = response.json()
        self.assertFalse(body["enabled"])
        self.assertEqual(body["rows"], [])
        self.assertEqual(body["disabled_reason"], "analytics_disabled")

    def test_off_historical_false_tanpa_snapshot(self):
        self.assertFalse(self.api.get(METRICS_URL).json()["historical_data_available"])

    def test_off_historical_true_dengan_snapshot(self):
        now = timezone.now()
        MetricSnapshot.objects.create(
            metric_id="garment.scrap_rate",
            granularity="day",
            dimension_key="",
            period_start=now,
            period_end=now,
            value=1,
        )

        self.assertTrue(self.api.get(METRICS_URL).json()["historical_data_available"])


class AnalyticsToggleOnTests(AnalyticsApiBase):
    def setUp(self):
        super().setUp()
        self._seed_metric_data()
        config = svc.get_config()
        config.enabled = True
        config.disabled_reason = ""
        config.save()
        self.api = self._client(Role.Code.SUPERVISOR)

    def test_metrics_rows_terisi(self):
        body = self.api.get(METRICS_URL).json()

        self.assertTrue(body["enabled"])
        self.assertGreaterEqual(len(body["rows"]), 1)
        by_key = {row["key"]: row for row in body["rows"]}
        self.assertIn("garment.scrap_rate", by_key)

    def test_metric_tidak_ada_404(self):
        response = self.api.get("/api/v1/analytics/metric/garment.nope/")

        self.assertEqual(response.status_code, 404)

    def test_domain_tidak_ada_404(self):
        response = self.api.get("/api/v1/analytics/metrics/finance/")

        self.assertEqual(response.status_code, 404)

    def test_metric_metadata(self):
        body = self.api.get(METRIC_URL).json()

        metadata = body["summary"]["metadata"]
        self.assertEqual(metadata["metric_id"], "garment.scrap_rate")
        self.assertEqual(metadata["formula_version"], "1.0")
        self.assertEqual(
            metadata["source_models"],
            ["garment.ScrapAccumulator", "garment.BundleEvent"],
        )

    def test_health_200_dan_registry(self):
        body = self.api.get(HEALTH_URL).json()

        self.assertTrue(body["ok"])
        self.assertEqual(body["registry"]["metrics_registered"], 5)

    def test_health_historical(self):
        now = timezone.now()
        MetricSnapshot.objects.create(
            metric_id="garment.scrap_rate",
            granularity="day",
            dimension_key="",
            period_start=now,
            period_end=now,
            value=2,
        )

        body = self.api.get(HEALTH_URL).json()

        self.assertTrue(body["storage"]["historical_data_available"])
        self.assertEqual(body["storage"]["snapshots_total"], 1)

    def test_from_lebih_besar_dari_to_400(self):
        response = self.api.get(
            METRIC_URL,
            {
                "date_from": "2026-10-18T00:00:00+07:00",
                "date_to": "2026-10-10T00:00:00+07:00",
            },
        )

        self.assertEqual(response.status_code, 400)

    def test_group_by_tidak_dikenal_400(self):
        response = self.api.get(METRICS_URL, {"group_by": "bulan"})

        self.assertEqual(response.status_code, 400)

    def test_filter_work_center_id(self):
        wc = make_work_center()
        self._seed_metric_data(wc=wc)

        body = self.api.get(
            METRIC_URL, {"group_by": "work_center", "work_center_id": wc.pk}
        ).json()

        self.assertTrue(all(row["key"] == str(wc.pk) for row in body["rows"]))

    def test_cache_hit_lalu_cached_true(self):
        first = self.api.get(METRICS_URL).json()
        second = self.api.get(METRICS_URL).json()

        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])

    def test_nocache_tidak_menulis_cache(self):
        self.api.get(METRICS_URL, {"_nocache": "1"})

        self.assertFalse(self.api.get(METRICS_URL).json()["cached"])

    def test_nocache_cached_false(self):
        self.api.get(METRICS_URL)  # isi cache
        body = self.api.get(METRICS_URL, {"_nocache": "1"}).json()

        self.assertFalse(body["cached"])

