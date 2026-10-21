"""Seed dataset garmen kaya (FIX #3) — marker `UAT DEMO 2026-10`."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps_industry.garment.models import (
    Bundle,
    BundleEvent,
    CustomerInvoice,
    JournalEntry,
    MaterialReadiness,
    Order,
    OrderLine,
    Payment,
    ProcessRouting,
    ProductionLine,
    PurchaseOrder,
    PurchaseOrderLine,
    ScrapAccumulator,
    VendorBill,
    VendorBillLine,
    WorkCenter,
    WorkOrder,
)
from core.auth.models import User
from integrations.ai_agent.demo_products import ensure_demo_polos_products
from integrations.ai_agent.models import AIDecisionLog, AIHitlQueue
from integrations.erp_sync.models import SyncRecord
from master.models import BOM, BOMLine, Account, Journal, Partner, Product, UoM

MARK = "UAT DEMO 2026-10"


class Command(BaseCommand):
    help = "Seed data garmen lengkap untuk demo AI (idempoten, marker UAT DEMO)."

    def handle(self, *args, **options):
        with transaction.atomic():
            self._master()
            self._orders()
            self._work_orders_and_bundles()
            self._finance()
            self._ai_seed()
            self._sync_records()
        self._aggregate()
        self.stdout.write(self.style.SUCCESS("Seed rich garment selesai (idempoten)."))

    def _uom(self, names, fallback):
        for name in names:
            found = UoM.objects.filter(name__iexact=name).first()
            if found:
                return found
        return UoM.objects.filter(name__iexact=fallback).first() or UoM.objects.first()

    def _master(self):
        unit = self._uom(["Units", "PCS", "Unit"], "Units")
        yarn = self._uom(["kg", "Roll"], "Units")
        fabric = self._uom(["m²", "Meter"], "Units")
        self.unit = unit

        wc_specs = [
            ("CUTTING", "Cutting", "cutting", 100),
            ("SEWING-1", "Sewing 1", "sewing", 50),
            ("SEWING-2", "Sewing 2", "sewing", 50),
            ("SEWING-3", "Sewing 3", "sewing", 50),
            ("QC-1", "QC 1", "qc", 100),
            ("QC-2", "QC 2", "qc", 100),
            ("FINISHING", "Finishing", "finishing", 80),
            ("PACKING", "Packing", "packing", 120),
        ]
        self.wcs = {}
        for code, name, wc_type, capacity in wc_specs:
            wc, _ = WorkCenter.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "wc_type": wc_type,
                    "capacity_per_hour": Decimal(capacity),
                    "description": MARK,
                    "is_active": True,
                },
            )
            self.wcs[code] = wc

        self.lines = {}
        for code in ("Line-A", "Line-B", "Line-C"):
            line, _ = ProductionLine.objects.get_or_create(
                code=code,
                defaults={"name": code, "description": MARK, "is_active": True},
            )
            line.work_centers.set(list(self.wcs.values()))
            self.lines[code] = line

        for code, name in (
            ("ROUT-STD-RICH", "Routing Standard Rich"),
            ("ROUT-REWORK-RICH", "Routing Rework Rich"),
        ):
            ProcessRouting.objects.get_or_create(
                code=code,
                defaults={"name": name, "description": MARK, "is_active": True},
            )

        self.products = {}
        product_specs = [
            ("FG-KAOS-RICH", "Kaos Polos Premium", "Kaos", unit, 75000, 50000),
            ("FG-KMJ-RICH", "Kemeja Formal", "Kemeja", unit, 150000, 100000),
            ("FG-DRS-RICH", "Dress Casual", "Dress", unit, 175000, 110000),
            ("FG-CHN-RICH", "Celana Chino", "Celana", unit, 160000, 105000),
            ("FG-JKT-RICH", "Jaket Bomber", "Jaket", unit, 250000, 175000),
            ("RM-KAIN-RICH", "Kain Cotton Combed", "Material", fabric, 45000, 30000),
            ("RM-BENANG-RICH", "Benang Jahit", "Material", yarn, 50000, 35000),
            ("RM-KANCING-RICH", "Kancing Baju", "Aksesoris", unit, 500, 300),
        ]
        for code, name, category, uom, sale, cost in product_specs:
            product, _ = Product.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "category": category,
                    "uom": uom,
                    "sale_price": Decimal(sale),
                    "cost_price": Decimal(cost),
                    "is_active": True,
                },
            )
            self.products[code] = product

        # Fix #15 — produk ODOO-65..69 (5 "Kaos Polos") wajib punya pembeda.
        ensure_demo_polos_products(uom=unit)

        for index in range(1, 5):
            fg_code = (
                "FG-KAOS-RICH",
                "FG-KMJ-RICH",
                "FG-DRS-RICH",
                "FG-CHN-RICH",
            )[index - 1]
            bom, _ = BOM.objects.get_or_create(
                code=f"RICH-BOM-{index:02d}",
                defaults={
                    "product": self.products[fg_code],
                    "name": f"BOM {self.products[fg_code].name}",
                    "output_qty": Decimal("1"),
                    "uom": unit,
                    "notes": MARK,
                    "is_active": True,
                },
            )
            for component in ("RM-KAIN-RICH", "RM-BENANG-RICH", "RM-KANCING-RICH"):
                BOMLine.objects.get_or_create(
                    bom=bom,
                    product=self.products[component],
                    defaults={
                        "product_qty": Decimal("1"),
                        "uom": self.products[component].uom,
                        "notes": MARK,
                    },
                )

        self.customers = []
        self.vendors = []
        customer_names = [
            "PT Retail Fashion Indonesia",
            "CV Butik Modern",
            "PT Demo Fashion Nusantara",
        ]
        vendor_names = ["PT Textile Supply", "UD Benang Jaya", "CV Kain Nusantara"]
        for index in range(1, 4):
            customer, _ = Partner.objects.get_or_create(
                code=f"RICH-CUST-{index:02d}",
                defaults={
                    "name": customer_names[index - 1],
                    "is_customer": True,
                    "is_vendor": False,
                    "is_company": True,
                    "city": "Jakarta",
                },
            )
            vendor, _ = Partner.objects.get_or_create(
                code=f"RICH-VEND-{index:02d}",
                defaults={
                    "name": vendor_names[index - 1],
                    "is_customer": False,
                    "is_vendor": True,
                    "is_company": True,
                    "city": "Bandung",
                },
            )
            self.customers.append(customer)
            self.vendors.append(vendor)

    def _orders(self):
        now = timezone.now()
        types = (
            ["EXPORT"] * 5 + ["CUSTOM"] * 3 + ["BRAND"] * 2
        )
        self.orders = []
        self.order_lines = []
        for index in range(1, 11):
            order, _ = Order.objects.get_or_create(
                code=f"RICH-SO-{index:02d}",
                defaults={
                    "client_order_ref": f"RICH-SO-{index:02d}",
                    "customer": self.customers[(index - 1) % 3],
                    "order_type": types[index - 1],
                    "state": "CONFIRMED",
                    "priority": 10 - index,
                    "deadline": now + timedelta(days=7 + (index % 24)),
                },
            )
            Order.objects.filter(pk=order.pk).update(
                created_at=now - timedelta(days=30 - index * 2)
            )
            product = self.products[
                (
                    "FG-KAOS-RICH",
                    "FG-KMJ-RICH",
                    "FG-DRS-RICH",
                    "FG-CHN-RICH",
                    "FG-JKT-RICH",
                )[(index - 1) % 5]
            ]
            line, _ = OrderLine.objects.get_or_create(
                order=order,
                product=product,
                defaults={
                    "tag": f"{types[index - 1]}-{index}",
                    "qty": 20 + index * 3,
                    "price_unit": product.sale_price,
                },
            )
            MaterialReadiness.objects.get_or_create(
                order_line=line,
                defaults={
                    "required_qty": line.qty,
                    "received_qty": line.qty,
                    "shortage_qty": 0,
                    "status": "READY",
                },
            )
            self.orders.append(order)
            self.order_lines.append(line)

    def _work_orders_and_bundles(self):
        now = timezone.now()
        wo_states = (
            ["DRAFT"] * 2
            + ["CUTTING"] * 3
            + ["SEWING"] * 4
            + ["QC"] * 3
            + ["FINISHING"] * 2
            + ["DONE"] * 6
        )
        work_orders = []
        for order_index in range(10):
            for pair in range(2):
                state = wo_states[order_index * 2 + pair]
                wo, _ = WorkOrder.objects.get_or_create(
                    code=f"RICH-WO-{order_index + 1:02d}-{pair + 1}",
                    defaults={
                        "order_line": self.order_lines[order_index],
                        "qty_planned": 30,
                        "qty_done": 30 if state == "DONE" else 10,
                        "state": state,
                    },
                )
                work_orders.append(wo)

        bundle_states = (
            ["DONE"] * 20
            + ["SEWING"] * 7
            + ["CUTTING"] * 4
            + ["QC"] * 4
            + ["REWORK"] * 10
            + ["SCRAP"] * 5
        )
        self.bundles = []
        seq = 0
        for wo_index, wo in enumerate(work_orders):
            count = 3 if wo_index < 10 else 2
            for part in range(count):
                state = bundle_states[seq]
                seq += 1
                if state == "DONE":
                    wc = self.wcs["SEWING-2"] if seq == 1 else self.wcs["PACKING"]
                elif state == "REWORK":
                    wc = self.wcs["QC-1"] if seq <= 39 else self.wcs["SEWING-2"]
                elif state == "SCRAP":
                    wc = self.wcs["SEWING-2"]
                elif state == "CUTTING":
                    wc = self.wcs["CUTTING"]
                elif state == "QC":
                    wc = self.wcs["QC-2"]
                else:
                    wc = self.wcs["SEWING-1"]
                bundle, _ = Bundle.objects.get_or_create(
                    code=f"RICH-BND-{seq:02d}",
                    defaults={
                        "work_order": wo,
                        "size": ("S", "M", "L", "XL")[seq % 4],
                        "sku_variant": self.order_lines[wo_index // 2].product.code,
                        "qty": 10,
                        "qty_done": 10 if state == "DONE" else (5 if state in {"SEWING", "CUTTING", "QC"} else 0),
                        "state": state,
                        "current_work_center": wc,
                        "production_line": self.lines[("Line-A", "Line-B", "Line-C")[seq % 3]],
                    },
                )
                self.bundles.append(bundle)

        self._events(now)
        self._scrap(now)

    def _event(self, bundle, event_type, when, kind, payload):
        event, _ = BundleEvent.objects.get_or_create(
            bundle=bundle,
            event_type=event_type,
            text=f"rich-{bundle.code}-{kind}",
            defaults={"payload": {**payload, "notes": MARK}},
        )
        BundleEvent.objects.filter(pk=event.pk).update(ts=when)

    def _events(self, now):
        for index, bundle in enumerate(self.bundles, start=1):
            start = now - timedelta(days=5, hours=index % 6)
            finish = now - timedelta(days=1, hours=index % 8)
            if bundle.state == "DONE":
                if index <= 2:
                    start = now - timedelta(days=8)
                    finish = now - timedelta(days=1)
                self._event(
                    bundle,
                    "BUNDLE_START",
                    start,
                    "start",
                    {"work_center_code": "CUTTING", "qty": bundle.qty},
                )
                self._event(
                    bundle,
                    "QC_PASS",
                    start + (finish - start) / 2,
                    "qc-pass",
                    {"work_center_code": "QC-1", "qty": bundle.qty},
                )
                self._event(
                    bundle,
                    "BUNDLE_FINISH",
                    finish,
                    "finish",
                    {"work_center_code": "PACKING", "qty": bundle.qty},
                )
            elif bundle.state == "REWORK":
                self._event(
                    bundle,
                    "BUNDLE_START",
                    now - timedelta(days=6, hours=index % 5),
                    "start",
                    {"work_center_code": "CUTTING", "qty": bundle.qty},
                )
                self._event(
                    bundle,
                    "QC_FAIL",
                    now - timedelta(days=4, hours=index % 4),
                    "qc-fail",
                    {"work_center_code": "QC-1", "qty": 2},
                )
                self._event(
                    bundle,
                    "REWORK",
                    now - timedelta(days=3, hours=index % 3),
                    "rework",
                    {"work_center_code": "QC-1", "qty": 2},
                )
            elif bundle.state == "SCRAP":
                self._event(
                    bundle,
                    "BUNDLE_START",
                    now - timedelta(days=5, hours=index % 5),
                    "start",
                    {"work_center_code": "CUTTING", "qty": bundle.qty},
                )
                self._event(
                    bundle,
                    "SCRAP",
                    now - timedelta(days=2, hours=index % 4),
                    "scrap",
                    {"work_center_code": "SEWING-2", "qty": 4},
                )
                self._event(
                    bundle,
                    "QC_FAIL",
                    now - timedelta(days=1, hours=index % 3),
                    "qc-fail",
                    {"work_center_code": "QC-1", "qty": 1},
                )
            else:
                self._event(
                    bundle,
                    "BUNDLE_START",
                    now - timedelta(days=3, hours=index % 4),
                    "start",
                    {"work_center_code": "CUTTING", "qty": bundle.qty},
                )
                self._event(
                    bundle,
                    "BUNDLE_STATE_CHANGED",
                    now - timedelta(days=2, hours=index % 3),
                    "progress",
                    {"work_center_code": "SEWING-1", "qty": bundle.qty},
                )
                self._event(
                    bundle,
                    "QC_PASS",
                    now - timedelta(days=1, hours=index % 2),
                    "qc-pass",
                    {"work_center_code": "QC-2", "qty": 2},
                )

    def _scrap(self, now):
        sewing = [b for b in self.bundles if b.current_work_center_id == self.wcs["SEWING-2"].pk]
        qc = [
            b
            for b in self.bundles
            if b.state == "REWORK" and b.current_work_center_id == self.wcs["QC-1"].pk
        ]
        selected = sewing[:6] + qc[:3]
        remaining = [bundle for bundle in self.bundles if bundle.pk not in {b.pk for b in selected}]
        extra_codes = ["CUTTING", "SEWING-1", "SEWING-3", "QC-2", "FINISHING"]
        specs = []
        for item in sewing[:6]:
            specs.append((self.wcs["SEWING-2"], item, 4, 0))
        for item in qc[:3]:
            specs.append((self.wcs["QC-1"], item, 2, 2))
        for index in range(11):
            if not remaining:
                break
            bundle = remaining[index % len(remaining)]
            specs.append((self.wcs[extra_codes[index % len(extra_codes)]], bundle, 1, 0))
        for index, (wc, bundle, qty, rework) in enumerate(specs[:20]):
            row, _ = ScrapAccumulator.objects.get_or_create(
                work_center=wc,
                bundle=bundle,
                defaults={
                    "qty": qty,
                    "rework_qty": rework,
                    "end_loss_qty": 1 if index % 3 == 0 else 0,
                    "reason": "UAT DEMO",
                    "notes": MARK,
                },
            )
            ScrapAccumulator.objects.filter(pk=row.pk).update(
                created_at=now - timedelta(days=index % 10)
            )

    def _finance(self):
        today = date.today()
        self.invoices = []
        invoice_states = ["DONE"] * 5 + ["CONFIRMED"] * 3 + ["DRAFT"] * 2
        for index in range(1, 11):
            order = self.orders[index - 1]
            invoice, _ = CustomerInvoice.objects.get_or_create(
                code=f"RICH-INV-{index:02d}",
                defaults={
                    "order": order,
                    "customer": order.customer,
                    "invoice_date": today - timedelta(days=index % 10),
                    "state": invoice_states[index - 1],
                    "amount_total": Decimal(5_000_000 + index * 4_500_000),
                    "notes": MARK,
                },
            )
            self.invoices.append(invoice)

        self.purchase_orders = []
        po_states = ["CONFIRMED"] * 3 + ["DRAFT"] * 2
        for index in range(1, 6):
            po, _ = PurchaseOrder.objects.get_or_create(
                code=f"RICH-PO-{index:02d}",
                defaults={
                    "vendor": self.vendors[(index - 1) % 3],
                    "state": po_states[index - 1],
                    "partner_ref": f"RICH-PO-{index:02d}",
                    "expected_date": today + timedelta(days=7 + index),
                    "notes": MARK,
                },
            )
            PurchaseOrderLine.objects.get_or_create(
                po=po,
                product=self.products["RM-KAIN-RICH"],
                defaults={
                    "qty": Decimal(10 + index),
                    "price_unit": self.products["RM-KAIN-RICH"].cost_price,
                    "date_planned": today + timedelta(days=7 + index),
                },
            )
            self.purchase_orders.append(po)

        self.vendor_bills = []
        for index in range(1, 6):
            bill, _ = VendorBill.objects.get_or_create(
                code=f"RICH-VB-{index:02d}",
                defaults={
                    "purchase_order": self.purchase_orders[index - 1],
                    "vendor": self.vendors[(index - 1) % 3],
                    "ref": f"VENDOR-INV-{index:03d}",
                    "invoice_date": today - timedelta(days=index),
                    "state": "CONFIRMED" if index <= 3 else "DRAFT",
                    "amount_total": Decimal(3_000_000 + index * 2_000_000),
                    "notes": MARK,
                },
            )
            VendorBillLine.objects.get_or_create(
                bill=bill,
                product=self.products["RM-KAIN-RICH"],
                defaults={
                    "qty": Decimal(5 + index),
                    "price_unit": self.products["RM-KAIN-RICH"].cost_price,
                },
            )
            self.vendor_bills.append(bill)

        self.payments = []
        for index in range(1, 9):
            if index <= 5:
                invoice = self.invoices[index - 1]
                payment, _ = Payment.objects.get_or_create(
                    code=f"RICH-PAY-{index:02d}-IN",
                    defaults={
                        "payment_type": Payment.PaymentType.INBOUND,
                        "partner": invoice.customer,
                        "customer_invoice": invoice,
                        "amount": invoice.amount_total / 2,
                        "payment_date": today - timedelta(days=index),
                        "state": "CONFIRMED",
                        "payment_method": Payment.Method.BANK,
                    },
                )
            else:
                bill = self.vendor_bills[index - 6]
                payment, _ = Payment.objects.get_or_create(
                    code=f"RICH-PAY-{index:02d}-OUT",
                    defaults={
                        "payment_type": Payment.PaymentType.OUTBOUND,
                        "partner": bill.vendor,
                        "vendor_bill": bill,
                        "amount": bill.amount_total / 2,
                        "payment_date": today - timedelta(days=index),
                        "state": "CONFIRMED",
                        "payment_method": Payment.Method.BANK,
                    },
                )
            self.payments.append(payment)

        journal, _ = Journal.objects.get_or_create(
            code="RICH-GEN",
            defaults={"name": "Rich General Journal", "journal_type": "general", "is_active": True},
        )
        account_debit, _ = Account.objects.get_or_create(
            code="RICH-ACC-01",
            defaults={"name": "Rich Cash", "account_type": "asset_cash"},
        )
        account_credit, _ = Account.objects.get_or_create(
            code="RICH-ACC-02",
            defaults={"name": "Rich Revenue", "account_type": "income"},
        )
        self.journal_entries = []
        for index in range(1, 4):
            entry, _ = JournalEntry.objects.get_or_create(
                code=f"RICH-JE-{index:02d}",
                defaults={
                    "journal": journal,
                    "entry_date": today - timedelta(days=index),
                    "ref": f"RICH-JE-{index:02d}",
                    "memo": MARK,
                    "total_debit": Decimal(1_000_000),
                    "total_credit": Decimal(1_000_000),
                    "state": "DRAFT",
                    "notes": MARK,
                },
            )
            self.journal_entries.append(entry)
        self.accounts = (account_debit, account_credit)

    def _ai_seed(self):
        admin = (
            User.objects.filter(is_active=True, role__code__in=["ADMIN", "OWNER"]).first()
            or User.objects.filter(is_active=True).first()
        )
        now = timezone.now()
        specs = [
            ("analitik belum aktif?", "RULE_HIT", "GENERAL_CHAT"),
            ("analytics off?", "RULE_HIT", "GENERAL_CHAT"),
            ("status AI?", "RULE_HIT", "GENERAL_CHAT"),
            ("kenapa scrap naik?", "LLM_NEEDED", "DIAGNOSTIC"),
            ("bundle mana paling lambat?", "LLM_NEEDED", "DATA_LOOKUP"),
            ("total produksi minggu ini?", "LLM_NEEDED", "ANALYTICS_QUERY"),
            ("tren rework 30 hari?", "LLM_NEEDED", "ANALYTICS_QUERY"),
            ("stok produk di Odoo?", "LLM_NEEDED", "DATA_LOOKUP"),
            ("order ini boleh lanjut?", "LLM_NEEDED", "DIAGNOSTIC"),
            ("bandingkan scrap minggu ini vs lalu", "LLM_NEEDED", "DIAGNOSTIC"),
            ("prediksi scrap besok?", "LLM_NEEDED", "ANALYTICS_QUERY"),
            ("kapan order RICH-SO-01 selesai?", "LLM_NEEDED", "ANALYTICS_QUERY"),
            ("produk bermasalah?", "LLM_NEEDED", "DIAGNOSTIC"),
            ("data invoice customer lain", "BLOCKED", "DATA_LOOKUP"),
            ("data produk terlarang", "BLOCKED", "DATA_LOOKUP"),
        ]
        logs = []
        for index, (query, gate, intent) in enumerate(specs):
            query_text = f"[UAT DEMO] {query}"
            log, _ = AIDecisionLog.objects.get_or_create(
                query_text=query_text,
                defaults={
                    "user": admin,
                    "channel": "DESKTOP" if index % 2 == 0 else "FLOATING",
                    "decision_gate_result": gate,
                    "intent": intent,
                    "confidence_score": 0.95 if gate == "RULE_HIT" else 0.82,
                    "impact_score": "LOW",
                    "prompt_tokens": 0 if gate == "RULE_HIT" else 500 + index * 10,
                    "completion_tokens": 0 if gate == "RULE_HIT" else 100 + index * 3,
                    "total_cost_usd": Decimal("0") if gate == "RULE_HIT" else Decimal("0.001"),
                    "cache_hit": index % 4 == 0,
                    "latency_ms": 120 + index * 20,
                    "response_text": MARK,
                },
            )
            AIDecisionLog.objects.filter(pk=log.pk).update(
                timestamp=now - timedelta(hours=index)
            )
            logs.append(log)

        for index, log in enumerate(logs[3:8]):
            AIHitlQueue.objects.get_or_create(
                decision_log=log,
                defaults={
                    "risk_level": "MEDIUM" if index < 3 else "LOW",
                    "proposed_action": {"action": "review_demo", "index": index},
                    "required_approver_role": "SUPERVISOR",
                    "channel": "WA",
                    "status": "PENDING" if index < 3 else "APPROVED",
                    "decided_by": admin if index >= 3 else None,
                    "decided_at": now - timedelta(hours=1) if index >= 3 else None,
                    "expires_at": now + timedelta(hours=24),
                },
            )

    def _sync(self, resource, resource_id, stage, erp_id):
        SyncRecord.objects.get_or_create(
            resource=resource,
            resource_id=str(resource_id),
            stage=stage,
            defaults={
                "status": "SENT",
                "erp_id": str(erp_id),
                "sent_at": timezone.now(),
                "payload": {"notes": MARK},
            },
        )

    def _sync_records(self):
        counter = 10_000
        for order in self.orders:
            self._sync("order", order.code, "SALE_ORDER_PUSH", counter)
            counter += 1
        for invoice in self.invoices:
            self._sync("customer_invoice", invoice.code, "INVOICE", counter)
            counter += 1
        for po in self.purchase_orders:
            self._sync("purchase_order", po.code, "PURCHASE_ORDER_PUSH", counter)
            counter += 1
        for bill in self.vendor_bills:
            self._sync("vendor_bill", bill.code, "VENDOR_BILL", counter)
            counter += 1
        for payment in self.payments:
            self._sync("payment", payment.code, "PAYMENT", counter)
            counter += 1
        for entry in self.journal_entries:
            self._sync("journal_entry", entry.code, "JOURNAL_ENTRY", counter)
            counter += 1
        for wo in WorkOrder.objects.filter(code__startswith="RICH-WO-"):
            self._sync("work_order", wo.code, "WORK_ORDER_PUSH", counter)
            counter += 1
        for bundle in self.bundles:
            self._sync("bundle", bundle.code, "BUNDLE_PUSH", counter)
            counter += 1

    def _aggregate(self):
        from integrations.analytics.plugins.garment.tasks import aggregate_daily

        try:
            result = aggregate_daily()
            self.stdout.write(f"Snapshot metrics: {result}")
        except Exception as exc:  # noqa: BLE001 - seed tetap sukses
            self.stdout.write(self.style.WARNING(f"Snapshot dilewati: {type(exc).__name__}"))







