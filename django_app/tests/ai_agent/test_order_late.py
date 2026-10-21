"""Test Order.completed_at / late metrics / backfill (FIX #12)."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps_industry.garment.models import BundleEvent, Order
from apps_industry.garment.tests.factories import (
    make_bundle,
    make_order,
    make_order_line,
    make_work_order,
)
from integrations.ai_agent.data_access.metrics import MetricsRepository
from integrations.ai_agent.orchestrator import context_builder


def _user():
    return SimpleNamespace(role=SimpleNamespace(code="ADMIN"))


class OrderLatePropertyTests(TestCase):
    def test_late_true(self):
        now = timezone.now()
        order = make_order(
            state="DONE",
            deadline=now - timedelta(days=1),
            completed_at=now,
        )

        self.assertTrue(order.is_late)

    def test_late_false_on_time(self):
        now = timezone.now()
        order = make_order(
            state="DONE",
            deadline=now + timedelta(days=1),
            completed_at=now,
        )

        self.assertFalse(order.is_late)

    def test_draft_tanpa_completed_at_false(self):
        order = make_order(state="DRAFT", deadline=timezone.now())

        self.assertFalse(order.is_late)

    def test_order_late_percentage(self):
        now = timezone.now()
        make_order(
            state="DONE",
            deadline=now - timedelta(days=1),
            completed_at=now,
        )
        make_order(
            state="DONE",
            deadline=now + timedelta(days=1),
            completed_at=now,
        )
        make_order(state="DRAFT")

        stats = MetricsRepository().order_late_percentage()

        self.assertEqual(stats["total_completed"], 2)
        self.assertEqual(stats["late_count"], 1)
        self.assertEqual(stats["on_time_count"], 1)
        self.assertEqual(stats["late_percentage"], 50.0)

    def test_context_order_telat(self):
        now = timezone.now()
        make_order(
            state="DONE",
            deadline=now - timedelta(days=1),
            completed_at=now,
        )

        data = context_builder.build_context(
            "ANALYTICS_QUERY", [], "berapa persen order telat?", {}, user=_user()
        )

        self.assertIn("order_late_stats", data)
        self.assertEqual(data["order_late_stats"]["late_count"], 1)


class OrderCompletedBackfillTests(TestCase):
    def _done_order_with_event(self):
        order = make_order(state="DONE", deadline=timezone.now())
        line = make_order_line(order=order)
        wo = make_work_order(order_line=line)
        bundle = make_bundle(work_order=wo)
        event = BundleEvent.objects.create(
            bundle=bundle, event_type="BUNDLE_FINISH", payload={}
        )
        finished = timezone.now() - timedelta(days=2)
        BundleEvent.objects.filter(pk=event.pk).update(ts=finished)
        return order, finished

    def test_backfill_dari_event(self):
        order, finished = self._done_order_with_event()

        call_command("backfill_order_completed_at")
        order.refresh_from_db()

        self.assertIsNotNone(order.completed_at)
        self.assertEqual(order.completed_at, finished)

    def test_backfill_idempoten(self):
        order, _ = self._done_order_with_event()
        call_command("backfill_order_completed_at")
        order.refresh_from_db()
        first = order.completed_at

        call_command("backfill_order_completed_at")
        order.refresh_from_db()

        self.assertEqual(order.completed_at, first)
