"""Seed data MASIF untuk test besar (marker `BIG TEST 2026-10`).

Memanggil seed master yang sudah ada (seed_rich_garment + seed_documents),
lalu menambah transaksi 30 hari, finance, inventory, AI, summary, sync.
Idempoten: semua record dicari lewat `code`.
"""

from __future__ import annotations

import io
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps_industry.garment.models import (
    Bundle,
    BundleEvent,
    CustomerInvoice,
    InventoryAdjustment,
    JournalEntry,
    Order,
    OrderLine,
    Payment,
    PurchaseOrder,
    PurchaseOrderLine,
    ScrapAccumulator,
    StockTransfer,
    VendorBill,
    VendorBillLine,
    WorkCenter,
    WorkOrder,
)
from core.auth.models import User
from integrations.ai_agent.models import AIDecisionLog, AIHitlQueue, AISemanticCache
from integrations.analytics.models import DailySummary
from integrations.erp_sync.models import SyncRecord
from master.models import Account, BOM, Journal, Location, Partner, Product, UoM

MARK = "BIG TEST 2026-10"
_DONE = "DONE"
_SHIFT_CODES = ("SHIFT_1", "SHIFT_2", "SHIFT_3")
_SHIFT_BY_PATTERN = (
    "SHIFT_1",
    "SHIFT_1",
    "SHIFT_1",
    "SHIFT_1",
    "SHIFT_1",
    "SHIFT_2",
    "SHIFT_2",
    "SHIFT_2",
    "SHIFT_3",
    "SHIFT_3",
)


class Command(BaseCommand):
    help = (
        "Seed 40 order + 80 WO + 150 bundle + 600 event BIG TEST "
        "(idempoten; total dengan seed_rich = 50/100/200/833)."
    )

    def handle(self, *args, **options):
        call_command("seed_rich_garment", stdout=io.StringIO())
        call_command("seed_documents", stdout=io.StringIO())

        with transaction.atomic():
            self._master_extra()
            self._orders()

        with transaction.atomic():
            self._work_orders()
            self._bundles()
            self._events()
            self._normalize_event_metadata()

        with transaction.atomic():
            self._scrap()
            self._finance()

        with transaction.atomic():
            self._inventory()
            self._ai()
            self._summaries()
            self._sync()

        self._analytics()
        self.stdout.write(self.style.SUCCESS("Seed BIG TEST selesai (idempoten)."))

    # ------------------------------------------------------------------ master
    def _master_extra(self):
        unit = UoM.objects.filter(name__iexact="Units").first() or UoM.objects.first()
        self.unit = unit

        self.customers = list(
            Partner.objects.filter(code__startswith="RICH-CUST").order_by("code")
        )
        for index in range(4, 11):
            customer, _ = Partner.objects.get_or_create(
                code=f"BIG-CUST-{index:02d}",
                defaults={
                    "name": f"PT BIG Customer {index}",
                    "is_customer": True,
                    "is_vendor": False,
                    "is_company": True,
                    "city": "Jakarta",
                },
            )
            self.customers.append(customer)
        self.vendors = list(
            Partner.objects.filter(code__startswith="RICH-VEND").order_by("code")
        )
        for index in range(1, 3):
            vendor, _ = Partner.objects.get_or_create(
                code=f"BIG-VEND-{index:02d}",
                defaults={
                    "name": f"CV BIG Vendor {index}",
                    "is_customer": False,
                    "is_vendor": True,
                    "is_company": True,
                    "city": "Bandung",
                },
            )
            self.vendors.append(vendor)

        for code, name, category, price in (
            ("FG-KAOS-BIG-1", "Kaos Polos Varian 1", "Kaos", 70000),
            ("FG-KAOS-BIG-2", "Kaos Polos Varian 2", "Kaos", 72000),
            ("FG-KAOS-BIG-3", "Kaos Polos Varian 3", "Kaos", 74000),
            ("FG-KAOS-BIG-4", "Kaos Polos Varian 4", "Kaos", 76000),
            ("FG-KMJ-BIG-2", "Kemeja Lengan Panjang", "Kemeja", 165000),
        ):
            Product.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "category": category,
                    "uom": unit,
                    "sale_price": Decimal(price),
                    "cost_price": Decimal(price * 2 // 3),
                    "is_active": True,
                },
            )
        for code, name, price in (
            ("RM-KAIN-BIG-1", "Kain Drill", 48000),
            ("RM-KAIN-BIG-2", "Kain Rayon", 52000),
            ("RM-LABEL-BIG", "Label Woven", 800),
        ):
            Product.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "category": "Material",
                    "uom": unit,
                    "sale_price": Decimal(price),
                    "cost_price": Decimal(price),
                    "is_active": True,
                },
            )

        self.fg_products = list(Product.objects.filter(code__startswith="FG-"))
        self.material = Product.objects.filter(code__startswith="RM-").first()
        self.bom = BOM.objects.filter(code__startswith="RICH-BOM").first()
        self.operators = list(
            User.objects.filter(username__startswith="op-").order_by("username")
        )
        if not self.operators:
            fallback = User.objects.order_by("id").first()
            self.operators = [fallback] if fallback is not None else []

    # ------------------------------------------------------------------ orders
    def _orders(self):
        now = timezone.now()
        today = timezone.localdate()
        month_days = max(1, today.day)
        types = ["EXPORT"] * 15 + ["CUSTOM"] * 17 + ["BRAND"] * 8
        states = [_DONE] * 30 + ["IN_PROGRESS"] * 5 + ["DRAFT"] * 5
        self.new_orders: list[Order] = []

        for index in range(1, 41):
            state = states[index - 1]
            code = f"SO-BIG-{index:04d}"
            order, _ = Order.objects.get_or_create(
                code=code,
                defaults={
                    "client_order_ref": code,
                    "customer": self.customers[(index - 1) % len(self.customers)],
                    "order_type": types[index - 1],
                    "state": state,
                    "priority": 20 - (index % 10),
                    "deadline": now + timedelta(days=7 + index % 24),
                    "completed_at": now - timedelta(days=index % 12)
                    if state == _DONE
                    else None,
                    "notes": MARK,
                },
            )
            Order.objects.filter(pk=order.pk).update(
                created_at=now - timedelta(days=index % month_days),
                notes=MARK,
            )
            product = self.fg_products[(index - 1) % len(self.fg_products)]
            OrderLine.objects.get_or_create(
                order=order,
                product=product,
                defaults={
                    "tag": f"BIG-{types[index - 1]}-{index}",
                    "qty": 60 + (index % 5) * 10,
                    "price_unit": product.sale_price,
                },
            )
            self.new_orders.append(order)

    # ------------------------------------------------------- work orders/bundles
    def _work_orders(self):
        states = (
            [_DONE] * 54
            + ["SEWING"] * 16
            + ["CUTTING"] * 7
            + ["QC"] * 2
            + ["DRAFT"] * 1
        )
        self.new_wos: list[WorkOrder] = []
        seq = 0
        for order in self.new_orders:
            line = order.lines.first()
            for pair in range(2):
                state = states[seq]
                seq += 1
                wo, _ = WorkOrder.objects.get_or_create(
                    code=f"WO-BIG-{order.code[-4:]}-{pair + 1}",
                    defaults={
                        "order_line": line,
                        "qty_planned": 60,
                        "qty_done": 60 if state == _DONE else 20,
                        "state": state,
                    },
                )
                self.new_wos.append(wo)

    def _bundles(self):
        states = (
            [_DONE] * 80
            + ["SEWING"] * 33
            + ["QC"] * 14
            + ["REWORK"] * 11
            + ["SCRAP"] * 10
            + ["DRAFT"] * 2
        )
        wc = {item.code: item for item in WorkCenter.objects.all()}
        line_codes = ["Line-A", "Line-B", "Line-C"]
        self.new_bundles: list[Bundle] = []

        for index in range(1, 151):
            wo = self.new_wos[(index - 1) % 75]
            state = states[index - 1]
            if state == "SEWING":
                code = "SEWING-2" if index <= 20 else ("SEWING-1" if index % 2 else "SEWING-3")
            elif state == "QC":
                code = "QC-2"
            elif state == "REWORK":
                code = "QC-1"
            elif state == "SCRAP":
                code = "SEWING-2"
            elif state == "DRAFT":
                code = "CUTTING"
            else:
                code = "PACKING"

            bundle, _ = Bundle.objects.get_or_create(
                code=f"BND-BIG-{index:04d}",
                defaults={
                    "work_order": wo,
                    "size": ("S", "M", "L", "XL")[index % 4],
                    "sku_variant": wo.order_line.product.code,
                    "qty": 10,
                    "qty_done": 10 if state == _DONE else (5 if state in {"SEWING", "QC"} else 0),
                    "state": state,
                    "current_work_center": wc.get(code),
                    "notes": MARK,
                },
            )
            Bundle.objects.filter(pk=bundle.pk).update(notes=MARK)
            self.new_bundles.append(bundle)

    # ------------------------------------------------------------------ events
    def _events(self):
        today = timezone.localdate()
        self.event_count = 0

        for index, bundle in enumerate(self.new_bundles, start=1):
            state = bundle.state
            if state == "REWORK":
                types = ["BUNDLE_START", "QC_FAIL", "REWORK", "BUNDLE_FINISH"]
            elif state == "SCRAP":
                types = ["BUNDLE_START", "QC_FAIL", "SCRAP", "BUNDLE_FINISH"]
            elif state == _DONE:
                types = ["BUNDLE_START", "QC_PASS", "BUNDLE_FINISH", "BUNDLE_SEND"]
            else:
                types = ["BUNDLE_START", "QC_PASS", "BUNDLE_MOVE_OUT", "BUNDLE_MOVE_IN"]

            pattern = index % 10
            shift_code = _SHIFT_BY_PATTERN[pattern]
            shift_no = int(shift_code[-1])
            hour = 8 + (index % 5) if shift_no == 1 else (
                14 + index % 7 if shift_no == 2 else 22 + index % 3
            )
            if hour >= 24:
                hour -= 24
            day = today - timedelta(days=(index % 28) + 1)
            operator = self.operators[(index - 1) % len(self.operators)] if self.operators else None
            payload = {
                "notes": MARK,
                "shift": shift_no,  # kompatibilitas test lama; sumber utama = field shift
                "operator_id": operator.pk if operator is not None else None,
            }

            for pos, event_type in enumerate(types):
                ts = timezone.make_aware(
                    datetime.combine(day, time(hour, min(50, 5 + pos * 10)))
                )
                event, _ = BundleEvent.objects.get_or_create(
                    bundle=bundle,
                    event_type=event_type,
                    text=f"{MARK} {bundle.code} {pos}",
                    defaults={
                        "actor": operator,
                        "shift": shift_code,
                        "payload": payload,
                    },
                )
                BundleEvent.objects.filter(pk=event.pk).update(
                    ts=ts,
                    actor=operator,
                    shift=shift_code,
                    payload=payload,
                )
                self.event_count += 1

    def _normalize_event_metadata(self):
        """Isi operator + shift untuk event lama (terutama seed rich).

        Big seed sudah mengisi keduanya; pass ini memastikan kontrak global:
        semua event punya ``payload.operator_id`` dan ``shift`` terstruktur.
        """
        if not self.operators:
            return
        for index, event in enumerate(BundleEvent.objects.order_by("ts", "pk")):
            operator = self.operators[index % len(self.operators)]
            shift_code = _SHIFT_BY_PATTERN[index % 10]
            payload = dict(event.payload or {})
            updates = {}
            if not payload.get("operator_id"):
                payload["operator_id"] = operator.pk
                updates["payload"] = payload
            if not event.shift:
                updates["shift"] = shift_code
            if event.actor_id is None:
                updates["actor"] = operator
            if updates:
                BundleEvent.objects.filter(pk=event.pk).update(**updates)

    # ------------------------------------------------------------------ scrap
    def _scrap(self):
        """Buat ~50 scrap valid; hanya bundle DONE dan qty <= qty_done."""
        today = timezone.localdate()
        wc = {item.code: item for item in WorkCenter.objects.all()}
        done_bundles = [
            bundle
            for bundle in self.new_bundles
            if bundle.state == _DONE and bundle.qty_done > 0
        ]
        if not done_bundles or not wc:
            return

        for index, bundle in enumerate(done_bundles[:50]):
            day_index = index % 14
            created = timezone.make_aware(
                datetime.combine(
                    today - timedelta(days=day_index),
                    time(10 + (day_index % 8), 0),
                )
            )
            if index < 30:
                work_center = wc["SEWING-2"]
                qty = min(9 - (day_index % 7), bundle.qty_done)
                rework = 1
            else:
                work_center = wc["QC-1"]
                qty = min(1 + (index % 2), bundle.qty_done)
                rework = 4 if day_index < 7 else 2

            row = ScrapAccumulator.objects.update_or_create(
                work_center=work_center,
                bundle=bundle,
                defaults={
                    "qty": qty,
                    "rework_qty": rework,
                    "notes": MARK,
                },
            )[0]
            ScrapAccumulator.objects.filter(pk=row.pk).update(created_at=created)

    # ------------------------------------------------------------------ finance
    def _finance(self):
        today = timezone.localdate()
        invoice_states = [_DONE] * 25 + ["CONFIRMED"] * 7 + ["DRAFT"] * 8
        self.new_invoices: list[CustomerInvoice] = []
        for index, order in enumerate(self.new_orders, start=1):
            invoice, _ = CustomerInvoice.objects.get_or_create(
                code=f"INV-DEMO-{index:04d}",
                defaults={
                    "order": order,
                    "customer": order.customer,
                    "invoice_date": today - timedelta(days=index % 30),
                    "due_date": today + timedelta(days=14 + index % 10),
                    "state": invoice_states[index - 1],
                    "amount_total": Decimal(5_000_000 + index * 1_100_000),
                    "notes": MARK,
                },
            )
            self.new_invoices.append(invoice)

        po_states = ["CONFIRMED"] * 7 + ["DRAFT"] * 8
        self.new_pos: list[PurchaseOrder] = []
        for index in range(1, 16):
            po, _ = PurchaseOrder.objects.get_or_create(
                code=f"PO-DEMO-{index:04d}",
                defaults={
                    "vendor": self.vendors[(index - 1) % len(self.vendors)],
                    "state": po_states[index - 1],
                    "partner_ref": f"PO-DEMO-{index:04d}",
                    "expected_date": today + timedelta(days=7 + index),
                    "notes": MARK,
                },
            )
            PurchaseOrderLine.objects.get_or_create(
                po=po,
                product=self.material,
                defaults={
                    "qty": Decimal(20 + index),
                    "price_unit": self.material.cost_price,
                    "date_planned": today + timedelta(days=7 + index),
                },
            )
            self.new_pos.append(po)

        confirmed = [po for po in self.new_pos if po.state == "CONFIRMED"]
        self.new_bills: list[VendorBill] = []
        for index in range(1, 16):
            po = confirmed[(index - 1) % len(confirmed)] if confirmed else self.new_pos[0]
            bill, _ = VendorBill.objects.get_or_create(
                code=f"VB-DEMO-{index:04d}",
                defaults={
                    "purchase_order": po,
                    "vendor": po.vendor,
                    "ref": f"VENDOR-BIG-{index:03d}",
                    "invoice_date": today - timedelta(days=index % 20),
                    "due_date": today + timedelta(days=10),
                    "state": "CONFIRMED" if index <= 10 else "DRAFT",
                    "amount_total": Decimal(3_000_000 + index * 900_000),
                    "notes": MARK,
                },
            )
            VendorBillLine.objects.get_or_create(
                bill=bill,
                product=self.material,
                defaults={
                    "qty": Decimal(10 + index),
                    "price_unit": self.material.cost_price,
                },
            )
            self.new_bills.append(bill)

        payable_invoices = [inv for inv in self.new_invoices if inv.state != "DRAFT"]
        for index in range(1, 23):
            if index <= 15:
                invoice = payable_invoices[(index - 1) % len(payable_invoices)]
                Payment.objects.get_or_create(
                    code=f"PAY-DEMO-{index:04d}-IN",
                    defaults={
                        "payment_type": Payment.PaymentType.INBOUND,
                        "partner": invoice.customer,
                        "customer_invoice": invoice,
                        "amount": invoice.amount_total / 2,
                        "payment_date": today - timedelta(days=index % 25),
                        "state": "CONFIRMED",
                        "payment_method": Payment.Method.BANK,
                        "notes": MARK,
                    },
                )
            else:
                bill = self.new_bills[(index - 16) % len(self.new_bills)]
                Payment.objects.get_or_create(
                    code=f"PAY-DEMO-{index:04d}-OUT",
                    defaults={
                        "payment_type": Payment.PaymentType.OUTBOUND,
                        "partner": bill.vendor,
                        "vendor_bill": bill,
                        "amount": bill.amount_total / 2,
                        "payment_date": today - timedelta(days=index % 25),
                        "state": "CONFIRMED",
                        "payment_method": Payment.Method.BANK,
                        "notes": MARK,
                    },
                )

        journal, _ = Journal.objects.get_or_create(
            code="DEMO-GEN",
            defaults={
                "name": "BIG General Journal",
                "journal_type": "general",
                "is_active": True,
            },
        )
        Account.objects.get_or_create(
            code="DEMO-ACC-01",
            defaults={"name": "BIG Operational", "account_type": "expense"},
        )
        Account.objects.get_or_create(
            code="DEMO-ACC-02",
            defaults={"name": "BIG Cash", "account_type": "asset_cash"},
        )
        for index in range(1, 8):
            JournalEntry.objects.get_or_create(
                code=f"JE-DEMO-{index:04d}",
                defaults={
                    "journal": journal,
                    "entry_date": today - timedelta(days=index * 3),
                    "ref": f"OPEX-{index}",
                    "memo": f"{MARK} opex {index}",
                    "total_debit": Decimal(2_000_000 + index * 500_000),
                    "total_credit": Decimal(2_000_000 + index * 500_000),
                    "state": "DRAFT",
                    "notes": MARK,
                },
            )

    # ---------------------------------------------------------------- inventory
    def _inventory(self):
        stock, _ = Location.objects.get_or_create(
            code="WH/Stok",
            defaults={"name": "WH Stok", "usage": "internal", "is_active": True},
        )
        fg, _ = Location.objects.get_or_create(
            code="WH/FG",
            defaults={"name": "WH Finish Good", "usage": "internal", "is_active": True},
        )
        today = timezone.localdate()

        for index in range(1, 11):
            delta = Decimal(50) if index % 2 else Decimal(-10)
            before = Decimal(100 + index * 3)
            InventoryAdjustment.objects.get_or_create(
                code=f"ADJ-DEMO-{index:04d}",
                defaults={
                    "product": self.fg_products[index % len(self.fg_products)],
                    "location": stock,
                    "qty_delta": delta,
                    "qty_before": before,
                    "qty_after": before + delta,
                    "reason": f"{MARK} koreksi stok {index}",
                    "state": "SYNCED",
                },
            )

        for index in range(1, 11):
            StockTransfer.objects.get_or_create(
                code=f"TRF-DEMO-{index:04d}",
                defaults={
                    "product": self.fg_products[index % len(self.fg_products)],
                    "from_location": stock,
                    "to_location": fg,
                    "qty": Decimal(20),
                    "qty_before": Decimal(100),
                    "reason": f"{MARK} transfer FG {index}",
                    "state": "SYNCED",
                },
            )

    # ----------------------------------------------------------------------- AI
    def _ai(self):
        now = timezone.now()
        operator = User.objects.filter(username="op-andi").first() or User.objects.first()
        supervisor = (
            User.objects.filter(role__code="SUPERVISOR").order_by("id").first() or operator
        )
        gates = ["RULE_HIT", "LLM_NEEDED", "LLM_NEEDED", "BLOCKED"]
        intents = ["ANALYTICS_QUERY", "DIAGNOSTIC", "SUGGEST_ACTION", "DATA_LOOKUP"]
        questions = [
            "kenapa scrap naik?",
            "bottleneck di mana?",
            "rework di mana?",
            "kenapa lead time naik?",
            "operator tidak wajar?",
            "cacat shift 2?",
            "ringkasan hari ini",
            "SOP rework apa?",
        ]

        self.ai_logs: list[AIDecisionLog] = []
        for index in range(1, 36):
            ai_log, _ = AIDecisionLog.objects.get_or_create(
                query_text=f"{MARK} {questions[index % len(questions)]} #{index:02d}",
                defaults={
                    "user": operator,
                    "channel": "DESKTOP" if index % 2 else "FLOATING",
                    "decision_gate_result": gates[index % len(gates)],
                    "intent": intents[index % len(intents)],
                    "confidence_score": 0.7 if index % 3 else 0.9,
                    "impact_score": "MEDIUM" if index % 5 == 0 else "LOW",
                    "prompt_tokens": 100 + index,
                    "completion_tokens": 40 + index,
                    "total_cost_usd": Decimal("0.0002"),
                    "response_text": "Jawaban demo BIG TEST.",
                    "latency_ms": 120 + index,
                },
            )
            AIDecisionLog.objects.filter(pk=ai_log.pk).update(
                timestamp=now - timedelta(hours=index)
            )
            self.ai_logs.append(ai_log)

        statuses = ["PENDING", "PENDING", "APPROVED", "REJECTED", "REJECTED"]
        for index, status in enumerate(statuses):
            log = self.ai_logs[index]
            AIHitlQueue.objects.get_or_create(
                decision_log=log,
                defaults={
                    "risk_level": "HIGH" if index == 0 else "MEDIUM",
                    "proposed_action": {
                        "type": "suggest_actions",
                        "actions": [{"action": f"rework BND-BIG-{index + 1:04d}"}],
                        "problem": "scrap tinggi",
                    },
                    "required_approver_role": "SUPERVISOR",
                    "channel": "WA" if index % 2 else "DESKTOP",
                    "status": status,
                    "decided_by": supervisor if status != "PENDING" else None,
                    "decided_at": now - timedelta(hours=2) if status != "PENDING" else None,
                    "rejection_reason": "data belum lengkap" if status == "REJECTED" else "",
                    "expires_at": now + timedelta(hours=24),
                },
            )

        for index in range(1, 21):
            AISemanticCache.objects.get_or_create(
                query_normalized_text=f"{MARK} cache query {index}",
                defaults={
                    "query_embedding_id": f"big-{index:03d}",
                    "response_text": f"cached response {index}",
                    "tool_calls_signature": "mcp-analytics",
                    "hit_count": index,
                    "expires_at": now + timedelta(days=7),
                },
            )

    # ---------------------------------------------------------------- summaries
    def _summaries(self):
        today = timezone.localdate()
        for index in range(30):
            DailySummary.objects.update_or_create(
                date=today - timedelta(days=index),
                defaults={
                    "total_output": float(500 + index * 25),
                    "total_scrap": float(15 + (index % 7) * 3),
                    "total_rework": float(8 + index % 5),
                    "avg_lead_time": float(20 + (29 - index) * 2),
                    "oee": float(72 - (index % 9)),
                    "top_wc": "SEWING-2",
                    "top_operator": "op-andi" if index % 2 else "op-budi",
                },
            )

    # --------------------------------------------------------------------- sync
    def _sync(self):
        today = timezone.localdate()
        for index, order in enumerate(Order.objects.order_by("id"), start=1):
            SyncRecord.objects.update_or_create(
                resource="order",
                resource_id=str(order.pk),
                stage="SALE_ORDER_PUSH",
                defaults={
                    "status": "SENT",
                    "erp_id": f"ERP-SO-{index:04d}",
                    "payload": {"code": order.code, "notes": MARK},
                    "sent_at": timezone.now(),
                },
            )
        for index, invoice in enumerate(CustomerInvoice.objects.order_by("id"), start=1):
            SyncRecord.objects.update_or_create(
                resource="order",
                resource_id=str(invoice.pk),
                stage="INVOICE",
                defaults={
                    "status": "SENT",
                    "erp_id": f"ERP-INV-{index:04d}",
                    "payload": {"code": invoice.code, "notes": MARK},
                    "sent_at": timezone.now(),
                },
            )

    # ----------------------------------------------------------------- analytics
    def _analytics(self):
        from integrations.analytics.models import AnalyticsConfig

        AnalyticsConfig.objects.update_or_create(
            pk=1,
            defaults={
                "enabled": True,
                "enabled_domains": ["garment"],
                "enabled_metrics": [],
                "disabled_reason": "",
            },
        )

        try:
            from integrations.analytics.plugins.garment.tasks import (
                aggregate_daily,
                aggregate_hourly,
            )

            aggregate_daily()
            aggregate_hourly()
        except Exception:  # noqa: BLE001 - snapshot opsional untuk demo
            pass






