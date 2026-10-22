"""Seed data demo LLM (G.7) — idempoten, marker `DEMO LLM 2026-10`."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps_industry.garment.models import (
    Bundle,
    BundleEvent,
    Order,
    OrderLine,
    ProductionLine,
    ScrapAccumulator,
    WorkCenter,
    WorkOrder,
)
from core.auth.models import User
from integrations.ai_agent.models import AIDecisionLog, AIHitlQueue
from master.models import Partner, Product

MARK = "DEMO LLM 2026-10"
LOG_PREFIX = "[DEMO LLM]"


class Command(BaseCommand):
    help = "Seed data demo LLM (PT. Demo Fashion, scrap/rework/late, AI logs, HITL)."

    def handle(self, *args, **options):
        with transaction.atomic():
            self._master()
            orders = self._orders()
            bundles = self._bundles(orders)
            self._events(bundles)
            self._ai_demo()
        from integrations.ai_agent.data_access import invariants

        invariants.assert_clean("seed_demo_llm")
        self.stdout.write(self.style.SUCCESS("Seed demo LLM selesai (idempoten)."))

    # ------------------------------------------------------------------ master
    def _master(self):
        self.customer, _ = Partner.objects.get_or_create(
            code="DEMO-LLM-CUST-01",
            defaults={
                "name": "PT. Demo Fashion",
                "is_customer": True,
                "is_vendor": False,
                "is_company": True,
                "city": "Bandung",
                "address": "Jl. Demo Industri No. 1",
            },
        )
        self.product, _ = Product.objects.get_or_create(
            code="DEMO-LLM-FG-01",
            defaults={
                "name": "Kaos Demo Fashion",
                "category": "Kaos",
                "sale_price": Decimal("75000"),
                "is_active": True,
            },
        )
        self.sewing, _ = WorkCenter.objects.get_or_create(
            code="SEWING-2",
            defaults={
                "name": "Sewing 2",
                "wc_type": "sewing",
                "capacity_per_hour": Decimal("50"),
                "description": MARK,
                "is_active": True,
            },
        )
        self.qc, _ = WorkCenter.objects.get_or_create(
            code="QC-1",
            defaults={
                "name": "QC 1",
                "wc_type": "qc",
                "capacity_per_hour": Decimal("100"),
                "description": MARK,
                "is_active": True,
            },
        )
        self.line, _ = ProductionLine.objects.get_or_create(
            code="DEMO-LLM-LINE",
            defaults={"name": "Line Demo", "description": MARK, "is_active": True},
        )
        self.line.work_centers.set([self.sewing, self.qc])

    # ------------------------------------------------------------------ orders
    def _orders(self):
        specs = [
            ("DEMO-LLM-SO-01", "DONE"),
            ("DEMO-LLM-SO-02", "DONE"),
            ("DEMO-LLM-SO-03", "IN_PROGRESS"),
        ]
        work_orders = []
        for index, (code, state) in enumerate(specs, start=1):
            order, _ = Order.objects.get_or_create(
                code=code,
                defaults={
                    "client_order_ref": code,
                    "customer": self.customer,
                    "order_type": Order.OrderType.BRAND,
                    "state": state,
                    "priority": 5 if state == "IN_PROGRESS" else 2,
                    "deadline": timezone.now() + timedelta(days=7 + index),
                },
            )
            line, _ = OrderLine.objects.get_or_create(
                order=order,
                product=self.product,
                tag=f"DEMO-{index}",
                defaults={"qty": 10, "price_unit": Decimal("75000")},
            )
            work_order, _ = WorkOrder.objects.get_or_create(
                code=f"DEMO-LLM-WO-{index:02d}",
                defaults={
                    "order_line": line,
                    "qty_planned": 10,
                    "qty_done": 10 if state == "DONE" else 4,
                    "state": state,
                },
            )
            work_orders.append(work_order)
        return work_orders

    def _bundles(self, work_orders):
        bundles = {"scrap": [], "rework": [], "late": None}

        for index in range(1, 4):
            bundle, _ = Bundle.objects.get_or_create(
                code=f"DEMO-LLM-SCRAP-{index:02d}",
                defaults={
                    "work_order": work_orders[(index - 1) % len(work_orders)],
                    "size": ("S", "M", "L")[index - 1],
                    "sku_variant": "DEMO-KAOS",
                    "qty": 10,
                    "qty_done": 10,
                    "state": "DONE",
                    "current_work_center": self.sewing,
                    "production_line": self.line,
                },
            )
            ScrapAccumulator.objects.get_or_create(
                work_center=self.sewing,
                bundle=bundle,
                defaults={
                    "qty": 4,
                    "rework_qty": 1,
                    "end_loss_qty": 2,
                    "reason": "demo scrap tinggi",
                    "notes": MARK,
                },
            )
            bundles["scrap"].append(bundle)

        for index in range(1, 3):
            bundle, _ = Bundle.objects.get_or_create(
                code=f"DEMO-LLM-REWORK-{index:02d}",
                defaults={
                    "work_order": work_orders[index % len(work_orders)],
                    "size": "M",
                    "sku_variant": "DEMO-KAOS",
                    "qty": 10,
                    "qty_done": 0,
                    "state": "REWORK",
                    "current_work_center": self.qc,
                    "production_line": self.line,
                },
            )
            bundles["rework"].append(bundle)

        bundles["late"], _ = Bundle.objects.get_or_create(
            code="DEMO-LLM-LATE-01",
            defaults={
                "work_order": work_orders[0],
                "size": "L",
                "sku_variant": "DEMO-KAOS",
                "qty": 15,
                "qty_done": 15,
                "state": "DONE",
                "current_work_center": self.sewing,
                "production_line": self.line,
            },
        )
        return bundles

    # ------------------------------------------------------------------ events
    def _event(self, bundle, event_type, when, text, payload):
        event, _ = BundleEvent.objects.get_or_create(
            bundle=bundle,
            event_type=event_type,
            text=text,
            defaults={"payload": {**payload, "notes": MARK}},
        )
        BundleEvent.objects.filter(pk=event.pk).update(ts=when)

    def _events(self, bundles):
        now = timezone.now()

        for index, bundle in enumerate(bundles["scrap"], start=1):
            self._event(
                bundle,
                "BUNDLE_START",
                now - timedelta(days=3, hours=index),
                f"demo-scrap-start-{index}",
                {"work_center_code": "CUTTING", "qty": 10},
            )
            self._event(
                bundle,
                "SCRAP",
                now - timedelta(days=1, hours=index),
                f"demo-scrap-event-{index}",
                {"work_center_code": "SEWING-2", "qty": 4},
            )
            self._event(
                bundle,
                "BUNDLE_FINISH",
                now - timedelta(hours=6 + index),
                f"demo-scrap-finish-{index}",
                {"work_center_code": "PACKING", "qty": 10},
            )

        for index, bundle in enumerate(bundles["rework"], start=1):
            self._event(
                bundle,
                "BUNDLE_START",
                now - timedelta(days=2, hours=index),
                f"demo-rework-start-{index}",
                {"work_center_code": "CUTTING", "qty": 10},
            )
            self._event(
                bundle,
                "REWORK",
                now - timedelta(days=1, hours=index),
                f"demo-rework-event-{index}",
                {
                    "work_center_id": self.qc.pk,
                    "work_center_code": "QC-1",
                    "qty": 3,
                },
            )
            self._event(
                bundle,
                "BUNDLE_FINISH",
                now - timedelta(hours=4 + index),
                f"demo-rework-finish-{index}",
                {"work_center_code": "PACKING", "qty": 10},
            )
            self._event(
                bundle,
                "QC_PASS",
                now - timedelta(hours=2 + index),
                f"demo-rework-pass-{index}",
                {"work_center_code": "QC-1", "qty": 7},
            )

        self._event(
            bundles["late"],
            "BUNDLE_START",
            now - timedelta(days=6),
            "demo-late-start",
            {"work_center_code": "CUTTING", "qty": 15},
        )
        self._event(
            bundles["late"],
            "BUNDLE_STATE_CHANGED",
            now - timedelta(days=3),
            "demo-late-progress",
            {"work_center_code": "SEWING-2", "qty": 15},
        )
        self._event(
            bundles["late"],
            "BUNDLE_FINISH",
            now - timedelta(days=1),
            "demo-late-finish",
            {"work_center_code": "PACKING", "qty": 15},
        )

    # ------------------------------------------------------------------ AI demo
    def _ai_demo(self):
        admin = (
            User.objects.filter(is_active=True, role__code__in=["ADMIN", "OWNER"]).first()
            or User.objects.filter(is_active=True).first()
        )
        now = timezone.now()
        specs = [
            (
                f"{LOG_PREFIX} analitik belum aktif?",
                "RULE_HIT",
                "GENERAL_CHAT",
                0,
                0,
                Decimal("0"),
            ),
            (
                f"{LOG_PREFIX} kenapa scrap naik minggu ini?",
                "LLM_NEEDED",
                "DIAGNOSTIC",
                820,
                210,
                Decimal("0.002"),
            ),
            (
                f"{LOG_PREFIX} bundle mana paling lambat?",
                "LLM_NEEDED",
                "DATA_LOOKUP",
                640,
                180,
                Decimal("0.002"),
            ),
            (
                f"{LOG_PREFIX} berapa scrap rate SEWING-2?",
                "LLM_NEEDED",
                "ANALYTICS_QUERY",
                500,
                150,
                Decimal("0.0015"),
            ),
            (
                f"{LOG_PREFIX} produk ini kategorinya apa?",
                "LLM_NEEDED",
                "DATA_LOOKUP",
                450,
                120,
                Decimal("0.001"),
            ),
        ]
        logs = []
        for index, (query, gate, intent, prompt, completion, cost) in enumerate(specs):
            log, _ = AIDecisionLog.objects.get_or_create(
                query_text=query,
                defaults={
                    "user": admin,
                    "channel": "DESKTOP" if index % 2 == 0 else "FLOATING",
                    "decision_gate_result": gate,
                    "intent": intent,
                    "confidence_score": 0.95 if gate == "RULE_HIT" else 0.82,
                    "impact_score": "LOW",
                    "prompt_tokens": prompt,
                    "completion_tokens": completion,
                    "total_cost_usd": cost,
                    "cache_hit": False,
                    "latency_ms": 180 + index * 60,
                    "response_text": f"{LOG_PREFIX} simulasi jawaban demo",
                },
            )
            AIDecisionLog.objects.filter(pk=log.pk).update(
                timestamp=now - timedelta(hours=index)
            )
            logs.append(log)

        AIHitlQueue.objects.get_or_create(
            decision_log=logs[1],
            defaults={
                "risk_level": "MEDIUM",
                "proposed_action": {
                    "action": "update_bundle_qty",
                    "bundle_code": "DEMO-LLM-SCRAP-01",
                },
                "required_approver_role": "SUPERVISOR",
                "channel": "WA",
                "status": "PENDING",
                "expires_at": now + timedelta(hours=24),
            },
        )



