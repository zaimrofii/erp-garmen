"""Test seed rich garment (FIX #3) — idempoten + target counts."""

from __future__ import annotations

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps_industry.garment.models import (
    Bundle,
    BundleEvent,
    CustomerInvoice,
    Order,
    PurchaseOrder,
    ScrapAccumulator,
    WorkOrder,
)
from integrations.ai_agent.management.commands.seed_rich_garment import MARK
from integrations.ai_agent.models import AIDecisionLog, AIHitlQueue
from integrations.erp_sync.models import SyncRecord


def _seed():
    call_command("seed_rich_garment", stdout=StringIO())


class RichSeedTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _seed()

    def test_idempoten(self):
        before = (
            Order.objects.filter(code__startswith="RICH-SO-").count(),
            WorkOrder.objects.filter(code__startswith="RICH-WO-").count(),
            Bundle.objects.filter(code__startswith="RICH-BND-").count(),
            BundleEvent.objects.filter(payload__notes=MARK).count(),
            ScrapAccumulator.objects.filter(notes=MARK).count(),
        )

        _seed()

        after = (
            Order.objects.filter(code__startswith="RICH-SO-").count(),
            WorkOrder.objects.filter(code__startswith="RICH-WO-").count(),
            Bundle.objects.filter(code__startswith="RICH-BND-").count(),
            BundleEvent.objects.filter(payload__notes=MARK).count(),
            ScrapAccumulator.objects.filter(notes=MARK).count(),
        )
        self.assertEqual(before, after)

    def test_10_order_20_wo_50_bundle(self):
        self.assertEqual(Order.objects.filter(code__startswith="RICH-SO-").count(), 10)
        self.assertEqual(WorkOrder.objects.filter(code__startswith="RICH-WO-").count(), 20)
        self.assertEqual(Bundle.objects.filter(code__startswith="RICH-BND-").count(), 50)

    def test_6_scrap_sewing_2(self):
        rows = ScrapAccumulator.objects.filter(
            notes=MARK, work_center__code="SEWING-2"
        )
        self.assertEqual(rows.count(), 6)

    def test_4_bundle_rework_qc_1(self):
        rows = Bundle.objects.filter(
            code__startswith="RICH-BND-",
            state="REWORK",
            current_work_center__code="QC-1",
        )
        self.assertEqual(rows.count(), 4)

    def test_20_scrap_accumulator(self):
        self.assertEqual(ScrapAccumulator.objects.filter(notes=MARK).count(), 20)

    def test_150_bundle_event(self):
        self.assertEqual(BundleEvent.objects.filter(payload__notes=MARK).count(), 150)

    def test_10_invoice_5_po(self):
        self.assertEqual(
            CustomerInvoice.objects.filter(code__startswith="RICH-INV-").count(), 10
        )
        self.assertEqual(
            PurchaseOrder.objects.filter(code__startswith="RICH-PO-").count(), 5
        )

    def test_15_ai_log_5_hitl(self):
        self.assertEqual(
            AIDecisionLog.objects.filter(query_text__startswith="[UAT DEMO]").count(),
            15,
        )
        self.assertEqual(
            AIHitlQueue.objects.filter(
                decision_log__query_text__startswith="[UAT DEMO]"
            ).count(),
            5,
        )
        self.assertEqual(
            AIHitlQueue.objects.filter(
                decision_log__query_text__startswith="[UAT DEMO]",
                status="PENDING",
            ).count(),
            3,
        )

    def test_sync_sent_with_erp_id(self):
        rows = SyncRecord.objects.filter(payload__notes=MARK)
        self.assertGreaterEqual(rows.count(), 50)
        self.assertFalse(rows.exclude(status="SENT").exists())
        self.assertFalse(rows.filter(erp_id__isnull=True).exists())
        self.assertFalse(rows.filter(erp_id="").exists())
