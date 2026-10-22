"""Test seed BIG TEST — count, relasi, pola, idempoten."""

from __future__ import annotations

from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps_industry.garment.models import (
    Bundle,
    BundleEvent,
    CustomerInvoice,
    InventoryAdjustment,
    JournalEntry,
    Order,
    Payment,
    PurchaseOrder,
    ScrapAccumulator,
    StockTransfer,
    VendorBill,
    WorkOrder,
)
from integrations.ai_agent.models import AIDecisionLog, AIHitlQueue, AISemanticCache
from integrations.analytics.models import DailySummary, Document, MetricSnapshot
from integrations.erp_sync.models import SyncRecord
from core.auth.models import User
from integrations.ai_agent.orchestrator import context_builder
from integrations.analytics.plugins.garment.anomaly import operator_anomaly

MARK = "BIG TEST 2026-10"


class BigSeedTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_big_test", stdout=StringIO())


class CountTests(BigSeedTestBase):
    def test_count_order_wo_bundle(self):
        self.assertEqual(Order.objects.count(), 50)
        self.assertEqual(WorkOrder.objects.count(), 100)
        self.assertEqual(Bundle.objects.count(), 200)

    def test_count_event_minimal_500(self):
        self.assertGreaterEqual(BundleEvent.objects.count(), 500)

    def test_count_finance(self):
        self.assertEqual(CustomerInvoice.objects.count(), 50)
        self.assertEqual(PurchaseOrder.objects.count(), 20)
        self.assertEqual(Payment.objects.count(), 30)
        self.assertEqual(VendorBill.objects.count(), 20)
        self.assertEqual(JournalEntry.objects.count(), 10)

    def test_count_inventory(self):
        self.assertEqual(InventoryAdjustment.objects.count(), 10)
        self.assertEqual(StockTransfer.objects.count(), 10)

    def test_count_ai_dan_summary(self):
        self.assertEqual(AIDecisionLog.objects.count(), 50)
        self.assertEqual(AIHitlQueue.objects.count(), 10)
        self.assertEqual(AISemanticCache.objects.count(), 20)
        self.assertEqual(DailySummary.objects.count(), 30)
        self.assertEqual(Document.objects.count(), 8)
        self.assertEqual(User.objects.filter(username__startswith="op-").count(), 6)

    def test_distribusi_order_type_dan_state(self):
        self.assertEqual(Order.objects.filter(order_type="EXPORT").count(), 20)
        self.assertEqual(Order.objects.filter(order_type="CUSTOM").count(), 20)
        self.assertEqual(Order.objects.filter(order_type="BRAND").count(), 10)
        self.assertEqual(Order.objects.filter(state="DONE").count(), 30)
        self.assertEqual(Order.objects.filter(state="CONFIRMED").count(), 10)
        self.assertEqual(Order.objects.filter(state="IN_PROGRESS").count(), 5)
        self.assertEqual(Order.objects.filter(state="DRAFT").count(), 5)


class RelationTests(BigSeedTestBase):
    def test_bundle_wo_order_customer_valid(self):
        for bundle in Bundle.objects.select_related(
            "work_order__order_line__order__customer"
        )[:200]:
            self.assertIsNotNone(bundle.work_order)
            self.assertIsNotNone(bundle.work_order.order_line.order)
            self.assertIsNotNone(bundle.work_order.order_line.order.customer)

    def test_event_scrap_bundle_valid(self):
        scrap = ScrapAccumulator.objects.filter(notes=MARK).select_related("bundle")
        self.assertTrue(scrap.exists())
        for row in scrap:
            self.assertIsNotNone(row.bundle)
            self.assertIsNotNone(row.work_center)

    def test_rework_qc1_dan_scrap_sewing2(self):
        self.assertGreaterEqual(
            Bundle.objects.filter(state="REWORK", current_work_center__code="QC-1").count(),
            15,
        )
        self.assertGreaterEqual(
            Bundle.objects.filter(state="SCRAP", current_work_center__code="SEWING-2").count(),
            15,
        )


class PatternTests(BigSeedTestBase):
    def test_scrap_sewing2_naik_7_hari(self):
        from datetime import timedelta

        today = timezone.localdate()
        recent = ScrapAccumulator.objects.filter(
            work_center__code="SEWING-2",
            created_at__date__gte=today - timedelta(days=6),
        )
        prior = ScrapAccumulator.objects.filter(
            work_center__code="SEWING-2",
            created_at__date__gte=today - timedelta(days=13),
            created_at__date__lt=today - timedelta(days=6),
        )
        recent_total = sum(row.qty for row in recent)
        prior_total = sum(row.qty for row in prior)

        self.assertGreater(recent_total, 0)
        self.assertGreater(recent_total, prior_total)

    def test_rework_qc1_dominan(self):
        from datetime import timedelta

        today = timezone.localdate()
        rows = ScrapAccumulator.objects.filter(
            work_center__code="QC-1",
            created_at__date__gte=today - timedelta(days=6),
        )
        rework = sum(row.rework_qty for row in rows)
        scrap = sum(row.qty for row in rows)

        self.assertGreater(rework, 0)
        self.assertGreater(rework / max(1, rework + scrap), 0.2)

    def test_shift_2_sekitar_30_persen(self):
        events = BundleEvent.objects.filter(payload__notes=MARK)
        total = events.count()
        shift_two = events.filter(payload__shift=2).count()

        self.assertGreater(total, 0)
        self.assertGreaterEqual(shift_two / total, 0.25)
        self.assertLessEqual(shift_two / total, 0.35)

    def test_dua_operator_mencurigakan(self):
        summary = operator_anomaly.collect_operator_anomalies()

        self.assertGreaterEqual(summary["suspicious_count"], 2)
        self.assertLess(min(item["score"] for item in summary["operators"]), 60)


class SyncAndAnalyticsTests(BigSeedTestBase):
    def test_sync_order_dan_invoice_sent(self):
        self.assertEqual(
            SyncRecord.objects.filter(
                stage="SALE_ORDER_PUSH", status="SENT", payload__notes=MARK
            ).count(),
            50,
        )
        self.assertEqual(
            SyncRecord.objects.filter(
                stage="INVOICE", status="SENT", payload__notes=MARK
            ).count(),
            50,
        )

    def test_metric_snapshot_terisi(self):
        self.assertGreater(MetricSnapshot.objects.count(), 0)

    def test_daily_summary_30_hari_berurutan(self):
        from datetime import timedelta

        dates = list(
            DailySummary.objects.order_by("-date").values_list("date", flat=True)
        )
        self.assertEqual(len(dates), 30)
        self.assertEqual(dates[0] - dates[-1], timedelta(days=29))


class ContextDataTests(BigSeedTestBase):
    def test_kenapa_scrap_naik_data_cukup(self):
        from core.auth.models import Role, User

        user = User.objects.create_user(
            username="big-context-sup",
            password="x",
            role=Role.objects.get(code=Role.Code.SUPERVISOR),
        )
        data = context_builder.build_context(
            "DIAGNOSTIC", ["mcp-analytics"], "kenapa scrap naik?", {}, user=user
        )

        self.assertIn("explanation", data)
        self.assertTrue(data["explanation"]["found"])
        self.assertTrue(data.get("metrics"))
        self.assertNotIn("belum lengkap", data["explanation"]["narrative"])


class IdempotencyTests(BigSeedTestBase):
    def _counts(self):
        return (
            Order.objects.count(),
            WorkOrder.objects.count(),
            Bundle.objects.count(),
            BundleEvent.objects.count(),
            ScrapAccumulator.objects.count(),
            CustomerInvoice.objects.count(),
            AIDecisionLog.objects.count(),
            AIHitlQueue.objects.count(),
            DailySummary.objects.count(),
        )

    def test_seed_idempoten(self):
        before = self._counts()

        call_command("seed_big_test", stdout=StringIO())

        self.assertEqual(before, self._counts())
