"""Test seed demo LLM (G.7) — idempoten + jumlah data demo."""

from __future__ import annotations

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps_industry.garment.models import (
    Bundle,
    BundleEvent,
    Order,
    ScrapAccumulator,
)
from integrations.ai_agent.management.commands.seed_demo_llm import LOG_PREFIX, MARK
from integrations.ai_agent.models import AIDecisionLog, AIHitlQueue


def _seed():
    call_command("seed_demo_llm", stdout=StringIO())


class DemoSeedTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _seed()

    def test_idempoten_dijalankan_dua_kali(self):
        before = (
            Bundle.objects.filter(code__startswith="DEMO-LLM-").count(),
            BundleEvent.objects.filter(payload__notes=MARK).count(),
            AIDecisionLog.objects.filter(query_text__startswith=LOG_PREFIX).count(),
            AIHitlQueue.objects.filter(
                decision_log__query_text__startswith=LOG_PREFIX
            ).count(),
        )

        _seed()

        after = (
            Bundle.objects.filter(code__startswith="DEMO-LLM-").count(),
            BundleEvent.objects.filter(payload__notes=MARK).count(),
            AIDecisionLog.objects.filter(query_text__startswith=LOG_PREFIX).count(),
            AIHitlQueue.objects.filter(
                decision_log__query_text__startswith=LOG_PREFIX
            ).count(),
        )
        self.assertEqual(before, after)

    def test_tiga_bundle_scrap_tinggi_di_sewing_2(self):
        bundles = Bundle.objects.filter(code__startswith="DEMO-LLM-SCRAP-")
        scraps = ScrapAccumulator.objects.filter(
            notes=MARK, work_center__code="SEWING-2"
        )

        self.assertEqual(bundles.count(), 3)
        self.assertEqual(scraps.count(), 3)
        self.assertGreaterEqual(sum(row.qty for row in scraps), 12)

    def test_dua_bundle_rework_di_qc_1(self):
        bundles = Bundle.objects.filter(code__startswith="DEMO-LLM-REWORK-")
        reworks = BundleEvent.objects.filter(
            event_type="REWORK", payload__notes=MARK, payload__work_center_code="QC-1"
        )

        self.assertEqual(bundles.count(), 2)
        self.assertEqual(reworks.count(), 2)

    def test_dua_puluh_bundle_event(self):
        self.assertEqual(BundleEvent.objects.filter(payload__notes=MARK).count(), 20)

    def test_lima_ai_decision_log(self):
        logs = AIDecisionLog.objects.filter(query_text__startswith=LOG_PREFIX)

        self.assertEqual(logs.count(), 5)
        self.assertEqual(logs.filter(decision_gate_result="RULE_HIT").count(), 1)
        self.assertEqual(logs.filter(intent="DIAGNOSTIC").count(), 1)
        self.assertEqual(logs.filter(intent="DATA_LOOKUP").count(), 2)

    def test_satu_hitl_pending(self):
        queue = AIHitlQueue.objects.filter(
            decision_log__query_text__startswith=LOG_PREFIX,
            status="PENDING",
        )

        self.assertEqual(queue.count(), 1)
        self.assertEqual(queue.get().required_approver_role, "SUPERVISOR")

    def test_tiga_order_dua_done(self):
        orders = Order.objects.filter(code__startswith="DEMO-LLM-SO-")

        self.assertEqual(orders.count(), 3)
        self.assertEqual(orders.filter(state="DONE").count(), 2)
        self.assertEqual(orders.filter(state="IN_PROGRESS").count(), 1)

    def test_bundle_late_lead_time_lima_hari(self):
        bundle = Bundle.objects.get(code="DEMO-LLM-LATE-01")
        start = bundle.events.get(event_type="BUNDLE_START").ts
        finish = bundle.events.get(event_type="BUNDLE_FINISH").ts

        self.assertEqual((finish - start).days, 5)
