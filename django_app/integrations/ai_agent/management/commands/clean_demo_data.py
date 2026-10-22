"""Hapus data transaksi/demo, pertahankan master & konfigurasi.

Command ini **tidak** drop database. Semua penghapusan dibungkus satu
``transaction.atomic()`` dan hanya berjalan dengan ``--confirm``.

Urutan hapus mengikuti dependency FK (PROTECT):
Payment → Invoice/Bill → PO → Journal → produksi → AI → sync → analytics.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps_industry.garment.models import (
    Bundle,
    BundleEvent,
    CustomerInvoice,
    CustomerInvoiceLine,
    HITLRequest,
    InventoryAdjustment,
    JournalEntry,
    JournalEntryLine,
    MaterialReadiness,
    Order,
    OrderLine,
    Payment,
    PurchaseOrder,
    PurchaseOrderLine,
    ScrapAccumulator,
    StockReconciliation,
    StockTransfer,
    VendorBill,
    VendorBillLine,
    WorkOrder,
)
from integrations.ai_agent.models import AIDecisionLog, AIHitlQueue, AISemanticCache
from integrations.ai_agent.memory import semantic_cache
from integrations.analytics.models import DailySummary, Document, MetricSnapshot
from integrations.erp_sync.models import SyncRecord

#: Model transaksi yang dihapus. Urutan HARUS aman terhadap FK PROTECT.
TRANSACTION_MODELS = (
    ("Payment", Payment),
    ("CustomerInvoiceLine", CustomerInvoiceLine),
    ("CustomerInvoice", CustomerInvoice),
    ("VendorBillLine", VendorBillLine),
    ("VendorBill", VendorBill),
    ("PurchaseOrderLine", PurchaseOrderLine),
    ("PurchaseOrder", PurchaseOrder),
    ("JournalEntryLine", JournalEntryLine),
    ("JournalEntry", JournalEntry),
    ("InventoryAdjustment", InventoryAdjustment),
    ("StockTransfer", StockTransfer),
    ("StockReconciliation", StockReconciliation),
    ("BundleEvent", BundleEvent),
    ("ScrapAccumulator", ScrapAccumulator),
    ("Bundle", Bundle),
    ("WorkOrder", WorkOrder),
    ("MaterialReadiness", MaterialReadiness),
    ("OrderLine", OrderLine),
    ("Order", Order),
    ("HITLRequest", HITLRequest),
    ("AIHitlQueue", AIHitlQueue),
    ("AIDecisionLog", AIDecisionLog),
    ("AISemanticCache", AISemanticCache),
    ("SyncRecord", SyncRecord),
    ("DailySummary", DailySummary),
    ("Document", Document),
    ("MetricSnapshot", MetricSnapshot),
)

#: Model yang dipertahankan (dipakai untuk laporan before/after).
MASTER_MODELS = ("Product", "Partner", "WorkCenter", "ProductionLine", "User")


class Command(BaseCommand):
    help = "Hapus data transaksi/demo (butuh --confirm); master tetap."

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Wajib: konfirmasi bahwa data transaksi akan dihapus.",
        )

    def handle(self, *args, **options):
        if not options["confirm"]:
            raise CommandError(
                "clean_demo_data menolak berjalan tanpa --confirm. "
                "Gunakan: python manage.py clean_demo_data --confirm"
            )

        from apps_industry.garment.models import ProductionLine, WorkCenter
        from core.auth.models import User
        from master.models import Partner, Product

        before_master = {
            "Product": Product.objects.count(),
            "Partner": Partner.objects.count(),
            "WorkCenter": WorkCenter.objects.count(),
            "ProductionLine": ProductionLine.objects.count(),
            "User": User.objects.count(),
        }

        deleted: list[tuple[str, int]] = []
        with transaction.atomic():
            for label, model in TRANSACTION_MODELS:
                count, _detail = model.objects.all().delete()
                deleted.append((label, count))

        # Mirror ORM sudah kosong; bump versi cache agar jawaban lama di Redis
        # tidak dipakai lagi setelah reset.
        semantic_cache.invalidate("clean_demo_data")

        self.stdout.write(self.style.SUCCESS("clean_demo_data selesai."))
        self.stdout.write("Dihapus:")
        total = 0
        for label, count in deleted:
            total += count
            self.stdout.write(f"  {label:<22} {count:>7}")
        self.stdout.write(f"  {'TOTAL':<22} {total:>7}")

        self.stdout.write("Master dipertahankan:")
        for label in MASTER_MODELS:
            after = {
                "Product": Product.objects.count(),
                "Partner": Partner.objects.count(),
                "WorkCenter": WorkCenter.objects.count(),
                "ProductionLine": ProductionLine.objects.count(),
                "User": User.objects.count(),
            }[label]
            self.stdout.write(f"  {label:<22} {before_master[label]:>7} -> {after:>7}")
            if after != before_master[label]:
                raise CommandError(
                    f"Master {label} berubah ({before_master[label]} -> {after})!"
                )
