"""Test Fase 1 — model baru, seed BIG TEST bersih, marker, dan clean command."""

from __future__ import annotations

from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models import F
from django.test import TestCase

from apps_industry.garment.models import (
    Bundle,
    BundleEvent,
    Order,
    ScrapAccumulator,
)
from core.auth.models import User
from integrations.ai_agent.models import AIDecisionLog, AIHitlQueue
from integrations.analytics.models import Document, MetricSnapshot
from master.models import Partner, Product

MARK = "BIG TEST 2026-10"


class ModelFieldTests(TestCase):
    def test_order_punya_notes(self):
        field = Order._meta.get_field("notes")
        self.assertEqual(field.get_internal_type(), "TextField")

    def test_bundle_punya_notes(self):
        field = Bundle._meta.get_field("notes")
        self.assertEqual(field.get_internal_type(), "TextField")

    def test_bundle_event_shift_choices(self):
        field = BundleEvent._meta.get_field("shift")
        self.assertEqual(field.max_length, 8)
        self.assertTrue(field.db_index)
        self.assertEqual(
            {choice[0] for choice in field.choices},
            {"SHIFT_1", "SHIFT_2", "SHIFT_3"},
        )


class CleanSeedTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_big_test", stdout=StringIO())

    def test_count_order(self):
        self.assertEqual(Order.objects.count(), 50)

    def test_count_bundle(self):
        self.assertEqual(Bundle.objects.count(), 200)

    def test_count_event_minimal_833(self):
        self.assertGreaterEqual(BundleEvent.objects.count(), 833)

    def test_scrap_tidak_melebihi_output(self):
        invalid = ScrapAccumulator.objects.filter(qty__gt=F("bundle__qty_done"))
        self.assertEqual(invalid.count(), 0)

    def test_operator_id_selalu_ada(self):
        self.assertEqual(
            BundleEvent.objects.filter(payload__operator_id__isnull=True).count(),
            0,
        )

    def test_shift_selalu_terisi(self):
        self.assertEqual(BundleEvent.objects.filter(shift="").count(), 0)

    def test_seed_idempoten(self):
        before = (
            Order.objects.count(),
            Bundle.objects.count(),
            BundleEvent.objects.count(),
            ScrapAccumulator.objects.count(),
            AIDecisionLog.objects.count(),
            AIHitlQueue.objects.count(),
        )

        call_command("seed_big_test", stdout=StringIO())

        after = (
            Order.objects.count(),
            Bundle.objects.count(),
            BundleEvent.objects.count(),
            ScrapAccumulator.objects.count(),
            AIDecisionLog.objects.count(),
            AIHitlQueue.objects.count(),
        )
        self.assertEqual(before, after)

    def test_order_marker_queryable(self):
        self.assertEqual(Order.objects.filter(notes__icontains="BIG TEST").count(), 40)

    def test_bundle_marker_queryable(self):
        self.assertEqual(
            Bundle.objects.filter(notes__icontains="BIG TEST").count(), 150
        )

    def test_clean_command_menghapus_transaksi(self):
        call_command("clean_demo_data", "--confirm", stdout=StringIO())

        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(Bundle.objects.count(), 0)
        self.assertEqual(BundleEvent.objects.count(), 0)
        self.assertEqual(ScrapAccumulator.objects.count(), 0)
        self.assertEqual(AIDecisionLog.objects.count(), 0)
        self.assertEqual(AIHitlQueue.objects.count(), 0)
        self.assertEqual(Document.objects.count(), 0)
        self.assertEqual(MetricSnapshot.objects.count(), 0)

    def test_clean_command_mempertahankan_master(self):
        before = (Product.objects.count(), Partner.objects.count(), User.objects.count())

        call_command("clean_demo_data", "--confirm", stdout=StringIO())

        after = (Product.objects.count(), Partner.objects.count(), User.objects.count())
        self.assertEqual(before, after)

    def test_clean_command_tanpa_confirm_ditolak(self):
        with self.assertRaises(CommandError):
            call_command("clean_demo_data", stdout=StringIO())
