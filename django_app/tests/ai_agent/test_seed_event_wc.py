"""Test seed/backfill work_center_code pada BundleEvent (FIX #10)."""

from __future__ import annotations

from datetime import timedelta

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps_industry.garment.models import BundleEvent
from apps_industry.garment.tests.factories import make_bundle
from integrations.ai_agent.data_access.metrics import MetricsRepository


class EventWorkCenterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.bundle = make_bundle(code="BND-EVENT-WC", state="SEWING")

    def _event(self, event_type, payload, hours_ago=0):
        event = BundleEvent.objects.create(
            bundle=self.bundle, event_type=event_type, payload=payload
        )
        if hours_ago:
            BundleEvent.objects.filter(pk=event.pk).update(
                ts=timezone.now() - timedelta(hours=hours_ago)
            )
        return event

    def test_backfill_mengisi_work_center_code(self):
        event = self._event("BUNDLE_START", {"qty": 10})

        call_command("backfill_event_work_center")
        event.refresh_from_db()

        self.assertEqual(event.payload["work_center_code"], "CUTTING")

    def test_bundles_in_work_center_sewing(self):
        self._event("BUNDLE_START", {"work_center_code": "SEWING-2"}, hours_ago=5)
        self._event("BUNDLE_FINISH", {"work_center_code": "SEWING-2"}, hours_ago=1)

        rows = MetricsRepository().bundles_in_work_center("SEWING-2")

        self.assertGreaterEqual(len(rows), 1)
        self.assertEqual(rows[0]["bundle_code"], "BND-EVENT-WC")

    def test_bundles_in_work_center_qc(self):
        self._event("QC_FAIL", {"work_center_code": "QC-1"}, hours_ago=3)
        self._event("QC_PASS", {"work_center_code": "QC-1"}, hours_ago=1)

        rows = MetricsRepository().bundles_in_work_center("QC-1")

        self.assertGreaterEqual(len(rows), 1)

    def test_backfill_idempoten(self):
        self._event("BUNDLE_START", {"qty": 10})
        call_command("backfill_event_work_center")
        first = BundleEvent.objects.get(bundle=self.bundle).payload.copy()

        call_command("backfill_event_work_center")
        second = BundleEvent.objects.get(bundle=self.bundle).payload.copy()

        self.assertEqual(first, second)
        self.assertEqual(second["work_center_code"], "CUTTING")
