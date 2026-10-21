"""Seed dataset UAT garmen (Fase 2b.3) — idempoten, atomic, marker `UAT seed 2026-10`."""

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
    CustomerInvoiceLine,
    InventoryAdjustment,
    MaterialReadiness,
    Order,
    OrderLine,
    Payment,
    ProcessRouting,
    ProductionLine,
    PurchaseOrder,
    PurchaseOrderLine,
    RoutingStep,
    ScrapAccumulator,
    StockTransfer,
    VendorBill,
    VendorBillLine,
    WorkCenter,
    WorkOrder,
)
from core.auth.models import User
from integrations.ai_agent.models import AIDecisionLog, AIHitlQueue
from integrations.analytics.models import AnalyticsConfig
from integrations.erp_sync.models import SyncRecord
from master.models import BOM, BOMLine, Location, Partner, Product, UoM

MARK = "UAT seed 2026-10"


class Command(BaseCommand):
    help = "Seed dataset UAT garmen (2 klien, siklus penuh, HITL, observability)."

    def handle(self, *args, **options):
        with transaction.atomic():
            self._master()
            order_a = self._client_a()
            order_b = self._client_b()
            self._finance_inventory(order_a, order_b)
            self._ai_seed()
            self._analytics()
        self.stdout.write(self.style.SUCCESS("Seed UAT selesai (idempoten)."))

    # ------------------------------------------------------------------ helpers
    def _uom(self, names, fallback):
        for name in names:
            uom = UoM.objects.filter(name__iexact=name).first()
            if uom is not None:
                return uom
        return UoM.objects.filter(name__iexact=fallback).first() or UoM.objects.first()

    def _master(self):
        unit = self._uom(["Units", "PCS", "Unit"], "Units")
        yarn = self._uom(["kg", "Roll"], "Units")
        fabric = self._uom(["m²", "Meter"], "Units")

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
        wcs = {}
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
            wcs[code] = wc

        lines = {}
        for code in ("Line-A", "Line-B", "Line-C"):
            line, _ = ProductionLine.objects.get_or_create(
                code=code,
                defaults={"name": code, "description": MARK, "is_active": True},
            )
            line.work_centers.set(
                [
                    wcs["CUTTING"],
                    wcs["SEWING-1"],
                    wcs["SEWING-2"],
                    wcs["QC-1"],
                    wcs["FINISHING"],
                    wcs["PACKING"],
                ]
            )
            lines[code] = line

        self.unit = unit
        self.yarn = yarn
        self.fabric = fabric
        self.wcs = wcs
        self.lines = lines

        std, _ = ProcessRouting.objects.get_or_create(
            code="ROUT-STD",
            defaults={"name": "Routing Standard", "description": MARK, "is_active": True},
        )
        rework, _ = ProcessRouting.objects.get_or_create(
            code="ROUT-REWORK",
            defaults={"name": "Routing Rework", "description": MARK, "is_active": True},
        )
        std_specs = [
            ("CUTTING", "Cutting", wcs["CUTTING"]),
            ("SEWING-1", "Sewing 1", wcs["SEWING-1"]),
            ("SEWING-2", "Sewing 2", wcs["SEWING-2"]),
            ("QC-1", "QC 1", wcs["QC-1"]),
            ("FINISHING", "Finishing", wcs["FINISHING"]),
            ("PACKING", "Packing", wcs["PACKING"]),
        ]
        std_steps = []
        for order, (code, label, wc) in enumerate(std_specs, start=1):
            step, _ = RoutingStep.objects.get_or_create(
                routing=std,
                code=code,
                defaults={
                    "label": label,
                    "order": order,
                    "work_center": wc,
                    "is_initial": order == 1,
                    "is_terminal": order == len(std_specs),
                },
            )
            std_steps.append(step)
        for current, nxt in zip(std_steps, std_steps[1:]):
            current.allowed_next_steps.add(nxt)

        rework_steps = []
        for order, (code, label, wc) in enumerate(
            [("QC-1", "QC 1", wcs["QC-1"]), ("SEWING-2", "Sewing 2", wcs["SEWING-2"])],
            start=1,
        ):
            step, _ = RoutingStep.objects.get_or_create(
                routing=rework,
                code=code,
                defaults={"label": label, "order": order, "work_center": wc},
            )
            rework_steps.append(step)
        rework_steps[0].allowed_next_steps.add(rework_steps[1])
        rework_steps[1].allowed_next_steps.add(rework_steps[0])

        products = {}
        product_specs = [
            ("FG-KAOS-001", "Kaos Polos Cotton Combed 30s", "Kaos", unit, 50000),
            ("FG-KMJ-001", "Kemeja Formal Lengan Panjang", "Kemeja", unit, 150000),
            ("FG-DRS-001", "Dress Casual Wanita", "Dress", unit, 175000),
            ("RM-BENANG-001", "Benang Jahit Polyester", "Material", yarn, 50000),
            ("RM-KAIN-001", "Kain Cotton Combed 30s", "Material", fabric, 45000),
            ("RM-KANCING-001", "Kancing Baju 18L", "Aksesoris", unit, 500),
        ]
        for code, name, category, uom, price in product_specs:
            product, _ = Product.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "category": category,
                    "uom": uom,
                    "sale_price": Decimal(price),
                    "is_active": True,
                },
            )
            products[code] = product

        for code, fg_code, components in [
            (
                "BOM-KAOS-001",
                "FG-KAOS-001",
                [("RM-BENANG-001", 1), ("RM-KAIN-001", 2)],
            ),
            (
                "BOM-KMJ-001",
                "FG-KMJ-001",
                [("RM-BENANG-001", 1), ("RM-KAIN-001", 2.5), ("RM-KANCING-001", 6)],
            ),
        ]:
            bom, _ = BOM.objects.get_or_create(
                code=code,
                defaults={
                    "product": products[fg_code],
                    "name": f"BOM {products[fg_code].name}",
                    "output_qty": Decimal("1"),
                    "uom": unit,
                    "notes": MARK,
                    "is_active": True,
                },
            )
            for component_code, qty in components:
                BOMLine.objects.get_or_create(
                    bom=bom,
                    product=products[component_code],
                    defaults={"product_qty": qty, "uom": products[component_code].uom},
                )

        partner_specs = [
            ("CUST-001", "PT. Retail Fashion Indonesia", True, False, "Jakarta"),
            ("CUST-002", "CV. Butik Modern Surabaya", True, False, "Surabaya"),
            ("VEND-001", "PT. Textile Supply Nusantara", False, True, "Bandung"),
            ("VEND-002", "UD. Benang Jaya", False, True, "Solo"),
        ]
        for code, name, is_customer, is_vendor, city in partner_specs:
            Partner.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "is_customer": is_customer,
                    "is_vendor": is_vendor,
                    "is_company": True,
                    "city": city,
                },
            )

        self.products = products
        self.partners = {
            partner.code: partner
            for partner in Partner.objects.filter(code__in=[spec[0] for spec in partner_specs])
        }

    def _event(self, bundle, event_type, when, payload, text=""):
        if bundle.events.filter(event_type=event_type, text=text).exists():
            return
        event = BundleEvent.objects.create(
            bundle=bundle, event_type=event_type, text=text, payload=payload
        )
        BundleEvent.objects.filter(pk=event.pk).update(ts=when)

    def _client_a(self):
        customer = self.partners["CUST-001"]
        order, _ = Order.objects.get_or_create(
            code="SO-2026-0001",
            defaults={
                "client_order_ref": "SO-2026-0001",
                "customer": customer,
                "order_type": Order.OrderType.EXPORT,
                "state": "CONFIRMED",
                "priority": 5,
                "deadline": timezone.now() + timedelta(days=14),
            },
        )

        lines = []
        for size, qty in (("S", 30), ("M", 40), ("L", 30)):
            line, _ = OrderLine.objects.get_or_create(
                order=order,
                product=self.products["FG-KAOS-001"],
                tag=f"EXPORT-{size}",
                defaults={"qty": qty, "price_unit": Decimal("50000")},
            )
            lines.append(line)

        wo_specs = [
            ("WO-A-01", 0, 30, "DONE", 30),
            ("WO-A-02", 1, 40, "DONE", 40),
            ("WO-A-03", 2, 30, "DONE", 30),
            ("WO-A-04", 1, 20, "IN_PROGRESS", 0),
            ("WO-A-05", 1, 20, "IN_PROGRESS", 0),
        ]
        work_orders = []
        for code, line_index, qty, state, done in wo_specs:
            wo, _ = WorkOrder.objects.get_or_create(
                code=code,
                defaults={
                    "order_line": lines[line_index],
                    "qty_planned": qty,
                    "qty_done": done,
                    "state": state,
                },
            )
            work_orders.append(wo)

        states = (
            ["DONE"] * 10 + ["SEWING"] * 3 + ["REWORK"] + ["SCRAP"]
        )
        line_cycle = [self.lines["Line-A"], self.lines["Line-B"], self.lines["Line-C"]]
        now = timezone.now()

        for index, state in enumerate(states, start=1):
            bundle, _ = Bundle.objects.get_or_create(
                code=f"BND-A-{index:02d}",
                defaults={
                    "work_order": work_orders[(index - 1) % len(work_orders)],
                    "size": ("S", "M", "L")[(index - 1) % 3],
                    "sku_variant": "KAOS-30S",
                    "qty": 10,
                    "qty_done": 10 if state == "DONE" else (4 if state == "SEWING" else 0),
                    "state": state,
                    "current_work_center": (
                        self.wcs["PACKING"]
                        if state == "DONE"
                        else self.wcs["SEWING-2"]
                        if state in ("SEWING", "REWORK")
                        else self.wcs["QC-1"]
                    ),
                    "production_line": line_cycle[(index - 1) % 3],
                },
            )
            self._event(
                bundle,
                "BUNDLE_START",
                now - timedelta(days=3),
                {"work_center_code": "CUTTING", "state_from": "DRAFT", "state_to": "CUTTING", "qty": 10},
            )
            self._event(
                bundle,
                "BUNDLE_STATE_CHANGED",
                now - timedelta(days=3, hours=-6),
                {"work_center_code": "SEWING-1", "state_from": "CUTTING", "state_to": "SEWING", "qty": 10},
            )
            if state == "DONE":
                self._event(
                    bundle,
                    "BUNDLE_STATE_CHANGED",
                    now - timedelta(days=2),
                    {"work_center_code": "QC-1", "state_from": "SEWING", "state_to": "QC", "qty": 10},
                )
                self._event(
                    bundle,
                    "QC_PASS",
                    now - timedelta(days=2, hours=-4),
                    {"work_center_code": "QC-1", "qty": 10},
                )
                self._event(
                    bundle,
                    "BUNDLE_FINISH",
                    now - timedelta(days=1),
                    {"work_center_code": "PACKING", "state_from": "QC", "state_to": "DONE", "qty": 10},
                )
            elif state == "REWORK":
                self._event(
                    bundle,
                    "QC_FAIL",
                    now - timedelta(days=2),
                    {"work_center_code": "QC-1", "qty": 1, "defect": "jahitan lepas"},
                )
                self._event(
                    bundle,
                    "REWORK",
                    now - timedelta(days=2, hours=-1),
                    {"work_center_code": "SEWING-2", "qty": 1},
                )
                self._event(
                    bundle,
                    "QC_PASS",
                    now - timedelta(days=2, hours=-3),
                    {"work_center_code": "QC-1", "qty": 1},
                    text="rework-pass",
                )
            elif state == "SCRAP":
                self._event(
                    bundle,
                    "SCRAP_RECORDED",
                    now - timedelta(days=2, hours=-2),
                    {"work_center_code": "QC-1", "qty": 2, "reason": "end-loss"},
                )
            if state == "SEWING":
                self._event(
                    bundle,
                    "BUNDLE_STATE_CHANGED",
                    now - timedelta(hours=2),
                    {
                        "work_center_code": "SEWING-2",
                        "state_from": "SEWING",
                        "state_to": "SEWING",
                        "qty": 10,
                    },
                    text="recent-progress",
                )

        for index, line in enumerate(lines):
            required = line.qty
            ready = index < 2
            MaterialReadiness.objects.get_or_create(
                order_line=line,
                defaults={
                    "required_qty": required,
                    "received_qty": required if ready else 0,
                    "shortage_qty": 0 if ready else required,
                    "status": "READY" if ready else "WAITING",
                },
            )

        return order

    def _client_b(self):
        customer = self.partners["CUST-002"]
        order, _ = Order.objects.get_or_create(
            code="SO-2026-0002",
            defaults={
                "client_order_ref": "SO-2026-0002",
                "customer": customer,
                "order_type": Order.OrderType.CUSTOM,
                "state": "CONFIRMED",
                "priority": 10,
                "deadline": timezone.now() + timedelta(days=7),
            },
        )

        lines = []
        for size, qty in (("M", 25), ("L", 25)):
            line, _ = OrderLine.objects.get_or_create(
                order=order,
                product=self.products["FG-KMJ-001"],
                tag=f"FAST_TRACK-{size}",
                defaults={"qty": qty, "price_unit": Decimal("150000")},
            )
            lines.append(line)

        wo_specs = [
            ("WO-B-01", 0, 25, "DONE", 25),
            ("WO-B-02", 1, 25, "IN_PROGRESS", 0),
            ("WO-B-03", 1, 10, "IN_PROGRESS", 0),
        ]
        work_orders = []
        for code, line_index, qty, state, done in wo_specs:
            wo, _ = WorkOrder.objects.get_or_create(
                code=code,
                defaults={
                    "order_line": lines[line_index],
                    "qty_planned": qty,
                    "qty_done": done,
                    "state": state,
                },
            )
            work_orders.append(wo)

        states = ["DONE"] * 5 + ["REWORK", "REWORK", "SEWING"]
        now = timezone.now()
        line_cycle = [self.lines["Line-A"], self.lines["Line-B"], self.lines["Line-C"]]

        for index, state in enumerate(states, start=1):
            bundle, _ = Bundle.objects.get_or_create(
                code=f"BND-B-{index:02d}",
                defaults={
                    "work_order": work_orders[(index - 1) % len(work_orders)],
                    "size": ("M", "L")[(index - 1) % 2],
                    "sku_variant": "KMJ-FORMAL",
                    "qty": 10,
                    "qty_done": 10 if state == "DONE" else (3 if state == "SEWING" else 0),
                    "state": state,
                    "current_work_center": (
                        self.wcs["PACKING"]
                        if state == "DONE"
                        else self.wcs["SEWING-1"]
                    ),
                    "production_line": line_cycle[(index - 1) % 3],
                },
            )
            self._event(
                bundle,
                "BUNDLE_START",
                now - timedelta(days=2),
                {"work_center_code": "CUTTING", "state_from": "DRAFT", "state_to": "CUTTING", "qty": 10},
            )
            self._event(
                bundle,
                "BUNDLE_STATE_CHANGED",
                now - timedelta(days=2, hours=-4),
                {"work_center_code": "SEWING-1", "state_from": "CUTTING", "state_to": "SEWING", "qty": 10},
            )
            if state == "DONE":
                self._event(
                    bundle,
                    "BUNDLE_STATE_CHANGED",
                    now - timedelta(days=1),
                    {"work_center_code": "QC-1", "state_from": "SEWING", "state_to": "QC", "qty": 10},
                )
                self._event(
                    bundle,
                    "QC_PASS",
                    now - timedelta(days=1, hours=-3),
                    {"work_center_code": "QC-1", "qty": 10},
                )
                self._event(
                    bundle,
                    "BUNDLE_FINISH",
                    now - timedelta(hours=6),
                    {"work_center_code": "PACKING", "state_from": "QC", "state_to": "DONE", "qty": 10},
                )
            elif state == "REWORK":
                self._event(
                    bundle,
                    "QC_FAIL",
                    now - timedelta(days=1),
                    {"work_center_code": "QC-2", "qty": 1},
                )
                self._event(
                    bundle,
                    "REWORK",
                    now - timedelta(days=1, hours=-1),
                    {"work_center_code": "SEWING-2", "qty": 1},
                )
                self._event(
                    bundle,
                    "QC_PASS",
                    now - timedelta(days=1, hours=-2),
                    {"work_center_code": "QC-2", "qty": 1},
                    text="rework-pass",
                )

        for index, line in enumerate(lines):
            required = line.qty
            MaterialReadiness.objects.get_or_create(
                order_line=line,
                defaults={
                    "required_qty": required,
                    "received_qty": required,
                    "shortage_qty": 0,
                    "status": "READY",
                },
            )

        return order

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

    def _finance_inventory(self, order_a, order_b):
        customer = self.partners["CUST-001"]
        vendor = self.partners["VEND-001"]
        today = date.today()

        invoice, _ = CustomerInvoice.objects.get_or_create(
            code="INV-2026-0001",
            defaults={
                "order": order_a,
                "customer": customer,
                "invoice_date": today,
                "state": "CONFIRMED",
                "amount_total": Decimal("1500000"),
            },
        )
        CustomerInvoiceLine.objects.get_or_create(
            invoice=invoice,
            product=self.products["FG-KAOS-001"],
            defaults={"qty": 30, "price_unit": Decimal("50000")},
        )

        Payment.objects.get_or_create(
            code="PAY-2026-0002",
            defaults={
                "payment_type": Payment.PaymentType.INBOUND,
                "partner": customer,
                "customer_invoice": invoice,
                "amount": Decimal("750000"),
                "payment_date": today,
                "state": "CONFIRMED",
                "payment_method": Payment.Method.BANK,
            },
        )

        po, _ = PurchaseOrder.objects.get_or_create(
            code="PO-2026-0001",
            defaults={
                "vendor": vendor,
                "state": "CONFIRMED",
                "partner_ref": "PO-2026-0001",
            },
        )
        PurchaseOrderLine.objects.get_or_create(
            po=po,
            product=self.products["RM-BENANG-001"],
            defaults={"qty": Decimal("10"), "price_unit": Decimal("50000")},
        )
        PurchaseOrderLine.objects.get_or_create(
            po=po,
            product=self.products["RM-KAIN-001"],
            defaults={"qty": Decimal("100"), "price_unit": Decimal("45000")},
        )

        bill, _ = VendorBill.objects.get_or_create(
            code="VB-2026-0001",
            defaults={
                "purchase_order": po,
                "vendor": vendor,
                "ref": "INV-VENDOR-001",
                "invoice_date": today,
                "state": "CONFIRMED",
                "amount_total": Decimal("5000000"),
            },
        )
        VendorBillLine.objects.get_or_create(
            bill=bill,
            product=self.products["RM-BENANG-001"],
            defaults={"qty": Decimal("10"), "price_unit": Decimal("50000")},
        )
        VendorBillLine.objects.get_or_create(
            bill=bill,
            product=self.products["RM-KAIN-001"],
            defaults={"qty": Decimal("100"), "price_unit": Decimal("45000")},
        )

        Payment.objects.get_or_create(
            code="PAY-2026-0001",
            defaults={
                "payment_type": Payment.PaymentType.OUTBOUND,
                "partner": vendor,
                "vendor_bill": bill,
                "amount": Decimal("2500000"),
                "payment_date": today,
                "state": "CONFIRMED",
                "payment_method": Payment.Method.BANK,
            },
        )

        stock = Location.objects.filter(code="WH/Stok").first()
        finished = Location.objects.filter(code="WH/Finished Goods").first()

        InventoryAdjustment.objects.get_or_create(
            code="ADJ-2026-0001",
            defaults={
                "product": self.products["RM-KAIN-001"],
                "location": stock,
                "qty_delta": Decimal("50"),
                "qty_before": Decimal("0"),
                "qty_after": Decimal("50"),
                "reason": "UAT seed stok awal kain",
                "state": "SYNCED",
            },
        )
        StockTransfer.objects.get_or_create(
            code="TRF-2026-0001",
            defaults={
                "product": self.products["FG-KAOS-001"],
                "from_location": stock,
                "to_location": finished,
                "qty": Decimal("10"),
                "qty_before": Decimal("50"),
                "reason": "UAT seed transfer FG",
                "state": "SYNCED",
            },
        )

        scrap_a = Bundle.objects.filter(code="BND-A-15").first()
        rework_a = Bundle.objects.filter(code="BND-A-14").first()
        scrap_b1 = Bundle.objects.filter(code="BND-B-06").first()
        scrap_b2 = Bundle.objects.filter(code="BND-B-07").first()
        for wc_code, bundle, qty, rework, end_loss in [
            ("CUTTING", scrap_a, 1, 0, 1),
            ("SEWING-2", rework_a, 1, 1, 0),
            ("SEWING-1", scrap_b1, 1, 1, 0),
            ("QC-1", scrap_b2, 1, 1, 0),
        ]:
            if bundle is None:
                continue
            ScrapAccumulator.objects.get_or_create(
                work_center=self.wcs[wc_code],
                bundle=bundle,
                defaults={
                    "qty": qty,
                    "rework_qty": rework,
                    "end_loss_qty": end_loss,
                    "reason": "UAT seed",
                    "notes": MARK,
                },
            )

        for resource, resource_id, stage, erp_id in [
            ("order", "SO-2026-0001", "SALE_ORDER_PUSH", 1001),
            ("customer_invoice", "INV-2026-0001", "INVOICE", 1002),
            ("purchase_order", "PO-2026-0001", "PURCHASE_ORDER_PUSH", 2001),
            ("vendor_bill", "VB-2026-0001", "VENDOR_BILL", 2002),
            ("payment", "PAY-2026-0001", "PAYMENT", 2003),
            ("payment", "PAY-2026-0002", "PAYMENT", 2004),
            ("inventory_adjustment", "ADJ-2026-0001", "INVENTORY_ADJUST", 3001),
            ("stock_transfer", "TRF-2026-0001", "STOCK_TRANSFER", 3002),
        ]:
            self._sync(resource, resource_id, stage, erp_id)

    def _ai_seed(self):
        admin = (
            User.objects.filter(is_active=True, role__code__in=["ADMIN", "OWNER"]).first()
            or User.objects.filter(is_active=True).first()
        )
        now = timezone.now()

        specs = [
            ("UAT: analitik belum aktif?", "RULE_HIT", "DESKTOP", 0, 0, 0.001),
            ("UAT: analytics off ya?", "RULE_HIT", "FLOATING", 0, 0, 0.001),
            ("UAT: analitik belum aktif di sistem", "RULE_HIT", "DESKTOP", 0, 0, 0.001),
            ("UAT: kenapa scrap cutting naik?", "LLM_NEEDED", "DESKTOP", 820, 210, 0.002),
            ("UAT: bundle ini sudah sampai mana?", "LLM_NEEDED", "FLOATING", 640, 180, 0.002),
            ("UAT: berapa lead time kaos minggu ini?", "LLM_NEEDED", "DESKTOP", 1200, 260, 0.003),
            ("UAT: rework di sewing-2 berapa?", "LLM_NEEDED", "FLOATING", 500, 150, 0.002),
            ("UAT: order mana yang paling Prioritas?", "LLM_NEEDED", "DESKTOP", 1500, 300, 0.003),
            ("UAT: tampilkan data produk ini", "BLOCKED", "DESKTOP", 0, 0, 0.001),
            ("UAT: buka detail invoice customer lain", "BLOCKED", "FLOATING", 0, 0, 0.001),
        ]
        logs = []
        for index, (query, gate, channel, prompt, completion, cost) in enumerate(specs):
            log, _ = AIDecisionLog.objects.get_or_create(
                query_text=query,
                defaults={
                    "user": admin,
                    "channel": channel,
                    "decision_gate_result": gate,
                    "intent": "uat.seed",
                    "confidence_score": 0.95 if gate == "RULE_HIT" else 0.7,
                    "impact_score": "LOW",
                    "prompt_tokens": prompt,
                    "completion_tokens": completion,
                    "total_cost_usd": Decimal(str(cost)),
                    "cache_hit": index % 3 == 0,
                    "latency_ms": 120 + index * 90,
                    "response_text": "UAT seed response",
                },
            )
            AIDecisionLog.objects.filter(pk=log.pk).update(
                timestamp=now - timedelta(days=index % 4, hours=index)
            )
            logs.append(log)

        llm_logs = [log for log in logs if log.decision_gate_result == "LLM_NEEDED"]
        if llm_logs and not AIHitlQueue.objects.filter(decision_log=llm_logs[0]).exists():
            AIHitlQueue.objects.create(
                decision_log=llm_logs[0],
                risk_level="MEDIUM",
                proposed_action={"action": "update_bundle_qty", "bundle_id": 1},
                required_approver_role="SUPERVISOR",
                channel="WA",
                status="PENDING",
                expires_at=now + timedelta(hours=24),
            )
        if len(llm_logs) > 1 and not AIHitlQueue.objects.filter(decision_log=llm_logs[1]).exists():
            AIHitlQueue.objects.create(
                decision_log=llm_logs[1],
                risk_level="MEDIUM",
                proposed_action={"action": "move_bundle", "bundle_id": 2},
                required_approver_role="SUPERVISOR",
                channel="WA",
                status="APPROVED",
                decided_by=admin,
                decided_at=now - timedelta(hours=2),
                expires_at=now + timedelta(hours=24),
            )

    def _analytics(self):
        AnalyticsConfig.objects.get_or_create(
            pk=1,
            defaults={"enabled": False, "disabled_reason": "not_yet_enabled"},
        )






