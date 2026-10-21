"""Test toggle analytics (B.2): model singleton, service, endpoint, readiness."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps_industry.garment.models import Bundle, BundleEvent
from apps_industry.garment.tests.factories import (
    make_bundle,
    make_order_line,
    make_product,
    make_work_order,
)
from core.audit.models import AuditLog
from core.auth.models import Role, User
from integrations.analytics.models import AnalyticsConfig
from integrations.analytics.services import analytics_config_services as svc
from integrations.erp_sync.idempotency import STAGE_WIP
from integrations.erp_sync.models import SyncRecord, SyncStatus

SETTINGS_URL = "/api/v1/settings/analytics/"
ENABLE_URL = "/api/v1/settings/analytics/enable/"
DISABLE_URL = "/api/v1/settings/analytics/disable/"
READINESS_URL = "/api/v1/analytics/readiness/"

READY_REPORT = {
    "ready": True,
    "blockers": [],
    "soft_blockers": [],
    "checked_at": "2026-10-18T05:10:00+07:00",
    "thresholds": {
        "products_without_odoo_id_in_active_bundles": 0,
        "bundles_without_events_older_than_24h": 0,
        "scrap_without_accumulator_older_than_24h": 0,
        "sync_records_failed_recent_7d": 0,
    },
    "counts": {"active_bundles": 1},
}

BLOCKED_REPORT = {
    **READY_REPORT,
    "ready": False,
    "blockers": ["sync_records_failed_recent_7d:2"],
}

SOFT_REPORT = {**READY_REPORT, "soft_blockers": ["no_active_bundles"]}


def make_user(username: str, role_code: str) -> User:
    """User dengan role tertentu (role di-seed migrasi core_auth)."""
    user = User.objects.create_user(username=username, password="rahasia")  # noqa: S106
    user.role = Role.objects.get(code=role_code)
    user.save(update_fields=["role"])
    return user


class AnalyticsSettingsApiTests(TestCase):
    """GET/PUT /api/v1/settings/analytics/."""

    def setUp(self):
        self.admin = make_user("admin-analytics", Role.Code.ADMIN)
        self.operator = make_user("op-analytics", Role.Code.OPERATOR)
        self.api = APIClient()
        self.api.force_authenticate(self.admin)

    def test_get_default_config_off(self):
        response = self.api.get(SETTINGS_URL)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["enabled"])
        self.assertEqual(body["disabled_reason"], "not_yet_enabled")
        self.assertEqual(body["enabled_domains"], [])

    def test_get_anon_forbidden(self):
        self.assertEqual(APIClient().get(SETTINGS_URL).status_code, 403)

    def test_get_operator_forbidden(self):
        api = APIClient()
        api.force_authenticate(self.operator)

        self.assertEqual(api.get(SETTINGS_URL).status_code, 403)

    def test_put_cannot_change_enabled(self):
        response = self.api.put(
            SETTINGS_URL, {"enabled": True, "enabled_domains": []}, format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("enable/disable", response.json()["detail"])

    def test_put_updates_filters_and_audits(self):
        response = self.api.put(
            SETTINGS_URL,
            {"enabled_domains": ["garment"], "enabled_metrics": ["garment.scrap_rate"]},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        config = AnalyticsConfig.objects.get(pk=1)
        self.assertEqual(config.enabled_domains, ["garment"])
        self.assertEqual(config.enabled_metrics, ["garment.scrap_rate"])
        self.assertTrue(
            AuditLog.objects.filter(action="analytics.config_update").exists()
        )

    def test_put_invalid_domains_400(self):
        response = self.api.put(
            SETTINGS_URL, {"enabled_domains": "garment"}, format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("list string", response.json()["detail"])


class AnalyticsEnableApiTests(TestCase):
    """POST enable: readiness pass setiap kali (bukan izin permanen)."""

    def setUp(self):
        self.admin = make_user("admin-enable", Role.Code.ADMIN)
        self.api = APIClient()
        self.api.force_authenticate(self.admin)

    def test_enable_blocked_by_readiness_400(self):
        with patch.object(svc, "readiness_report", return_value=BLOCKED_REPORT):
            response = self.api.post(ENABLE_URL, {}, format="json")

        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body["blockers"], BLOCKED_REPORT["blockers"])
        self.assertIn("checked_at", body)
        self.assertFalse(AnalyticsConfig.objects.get(pk=1).enabled)
        self.assertTrue(
            AuditLog.objects.filter(
                action="analytics.enable_blocked", result=AuditLog.Result.DENIED
            ).exists()
        )

    def test_enable_success_and_audit(self):
        with patch.object(svc, "readiness_report", return_value=READY_REPORT):
            response = self.api.post(ENABLE_URL, {}, format="json")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["enabled"])
        self.assertEqual(body["disabled_reason"], "")
        self.assertEqual(body["warnings"], [])
        self.assertTrue(
            AuditLog.objects.filter(action="analytics.enable_success").exists()
        )

    def test_enable_returns_soft_blocker_warning(self):
        with patch.object(svc, "readiness_report", return_value=SOFT_REPORT):
            response = self.api.post(ENABLE_URL, {}, format="json")

        self.assertEqual(response.status_code, 200)
        warnings = response.json()["warnings"]
        self.assertEqual([item["code"] for item in warnings], ["no_active_bundles"])

    def test_enable_rechecks_readiness_every_time(self):
        with patch.object(
            svc, "readiness_report", side_effect=[READY_REPORT, BLOCKED_REPORT]
        ):
            first = self.api.post(ENABLE_URL, {}, format="json")
            second = self.api.post(ENABLE_URL, {}, format="json")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 400)  # bukan izin permanen

    def test_enable_sets_acknowledged_and_user(self):
        with patch.object(svc, "readiness_report", return_value=READY_REPORT):
            self.api.post(ENABLE_URL, {"enabled_domains": ["garment"]}, format="json")

        config = AnalyticsConfig.objects.get(pk=1)
        self.assertIsNotNone(config.data_readiness_acknowledged_at)
        self.assertEqual(config.enabled_by_id, self.admin.pk)
        self.assertEqual(config.enabled_domains, ["garment"])

    def test_enable_singleton_only_one_row(self):
        with patch.object(svc, "readiness_report", return_value=READY_REPORT):
            self.api.post(ENABLE_URL, {}, format="json")
            self.api.post(ENABLE_URL, {}, format="json")

        self.assertEqual(AnalyticsConfig.objects.count(), 1)


class AnalyticsDisableApiTests(TestCase):
    """POST disable: alasan wajib, snapshot tidak dihapus."""

    def setUp(self):
        self.admin = make_user("admin-disable", Role.Code.ADMIN)
        self.api = APIClient()
        self.api.force_authenticate(self.admin)
        self.config = svc.get_config()
        self.config.enabled = True
        self.config.disabled_reason = ""
        self.config.save()

    def test_disable_requires_reason(self):
        response = self.api.post(DISABLE_URL, {"reason": "   "}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("Alasan disable wajib", response.json()["detail"])

    def test_disable_success_and_audit(self):
        response = self.api.post(
            DISABLE_URL, {"reason": "data master belum lengkap"}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["enabled"])
        self.assertEqual(body["disabled_reason"], "analytics_disabled")
        self.assertTrue(AuditLog.objects.filter(action="analytics.disable").exists())

    def test_disable_keeps_metric_snapshots(self):
        from django.utils import timezone

        from integrations.analytics.plugins.garment.models import MetricSnapshot

        now = timezone.now()
        MetricSnapshot.objects.create(
            metric_id="garment.scrap_rate",
            granularity="day",
            dimension_key="",
            period_start=now,
            period_end=now,
            value=1,
        )

        self.api.post(DISABLE_URL, {"reason": "uji snapshot"}, format="json")

        self.assertTrue(MetricSnapshot.objects.exists())

    def test_disable_idempotent(self):
        first = self.api.post(DISABLE_URL, {"reason": "alasan 1"}, format="json")
        second = self.api.post(DISABLE_URL, {"reason": "alasan 2"}, format="json")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(AnalyticsConfig.objects.count(), 1)


class IsMetricEnabledTests(TestCase):
    """Evaluasi 5 baris tabel TOGGLE-CONTRACT §5."""

    def setUp(self):
        self.config = svc.get_config()

    def _save(self, **fields):
        for key, value in fields.items():
            setattr(self.config, key, value)
        self.config.save()

    def test_disabled_returns_false(self):
        self.assertFalse(svc.is_metric_enabled("garment.scrap_rate"))

    def test_permissive_default_true(self):
        self._save(enabled=True, enabled_domains=[], enabled_metrics=[])

        self.assertTrue(svc.is_metric_enabled("garment.scrap_rate"))

    def test_domain_filter(self):
        self._save(enabled=True, enabled_domains=["garment"], enabled_metrics=[])

        self.assertTrue(svc.is_metric_enabled("garment.scrap_rate"))
        self.assertFalse(svc.is_metric_enabled("finance.margin"))

    def test_metric_filter(self):
        self._save(
            enabled=True,
            enabled_domains=[],
            enabled_metrics=["garment.rework_rate"],
        )

        self.assertTrue(svc.is_metric_enabled("garment.rework_rate"))
        self.assertFalse(svc.is_metric_enabled("garment.scrap_rate"))

    def test_metric_wins_over_domain(self):
        self._save(
            enabled=True,
            enabled_domains=["finance"],
            enabled_metrics=["garment.scrap_rate"],
        )

        self.assertTrue(svc.is_metric_enabled("garment.scrap_rate"))


class ReadinessReportTests(TestCase):
    """4 hard blocker + 1 soft; ready ⇔ blockers == []."""

    def test_products_without_odoo_id_in_active_bundles_blocks(self):
        product = make_product()  # odoo_id None
        work_order = make_work_order(order_line=make_order_line(product=product))
        make_bundle(work_order=work_order)

        report = svc.readiness_report()

        self.assertFalse(report["ready"])
        self.assertIn(
            "products_without_odoo_id_in_active_bundles:1", report["blockers"]
        )

    def test_historical_product_without_odoo_id_only_in_counts(self):
        make_product()  # tidak dipakai bundle aktif

        report = svc.readiness_report()

        self.assertEqual(
            report["counts"]["products_without_odoo_id_in_active_bundles"], 0
        )
        self.assertGreaterEqual(report["counts"]["products_without_odoo_id_total"], 1)
        self.assertTrue(report["ready"])  # hanya soft blocker
        self.assertEqual(report["soft_blockers"], ["no_active_bundles"])

    def test_bundles_without_events_older_than_24h_blocks(self):
        bundle = make_bundle()
        Bundle.objects.filter(pk=bundle.pk).update(
            created_at=timezone.now() - timedelta(hours=48)
        )

        report = svc.readiness_report()

        self.assertFalse(report["ready"])
        self.assertIn("bundles_without_events_older_than_24h:1", report["blockers"])

    def test_scrap_without_accumulator_blocks(self):
        bundle = make_bundle()
        event = BundleEvent.objects.create(bundle=bundle, event_type="SCRAP")
        BundleEvent.objects.filter(pk=event.pk).update(
            ts=timezone.now() - timedelta(hours=48)
        )

        report = svc.readiness_report()

        self.assertFalse(report["ready"])
        self.assertIn(
            "scrap_without_accumulator_older_than_24h:1", report["blockers"]
        )

    def test_sync_failed_recent_7d_blocks(self):
        SyncRecord.objects.create(
            resource="bundle",
            resource_id="BND-1",
            stage=STAGE_WIP,
            status=SyncStatus.FAILED,
            payload={},
        )

        report = svc.readiness_report()

        self.assertFalse(report["ready"])
        self.assertIn("sync_records_failed_recent_7d:1", report["blockers"])

    def test_no_active_bundles_is_soft_only(self):
        report = svc.readiness_report()

        self.assertTrue(report["ready"])
        self.assertEqual(report["blockers"], [])
        self.assertEqual(report["soft_blockers"], ["no_active_bundles"])

    def test_ready_when_no_blockers(self):
        from master.models import Product

        product = Product.objects.create(code="OK-1", name="Produk OK", odoo_id=10)
        work_order = make_work_order(order_line=make_order_line(product=product))
        make_bundle(work_order=work_order)

        report = svc.readiness_report()

        self.assertTrue(report["ready"])
        self.assertEqual(report["blockers"], [])
        self.assertEqual(report["soft_blockers"], [])


