"""Test model SyncRecord: unique constraint, default, payload JSON, choices."""

from __future__ import annotations

from django.db import IntegrityError, transaction
from django.test import TestCase

from integrations.erp_sync.models import SyncRecord, SyncResource, SyncStage, SyncStatus

PAYLOAD = {
    "ref": "BND-1",
    "qty": 10,
    "metadata": {"wc": "SEWING-1", "tags": ["EXPORT", "FAST_TRACK"]},
}


class SyncRecordModelTests(TestCase):
    """Skema tabel ledger sync (Fase 4.1)."""

    def make(self, **kwargs) -> SyncRecord:
        defaults = {
            "resource": SyncResource.BUNDLE,
            "resource_id": "1",
            "stage": SyncStage.WIP,
            "payload": PAYLOAD,
        }
        defaults.update(kwargs)
        return SyncRecord.objects.create(**defaults)

    def test_default_kolom(self):
        record = self.make()

        self.assertEqual(record.status, SyncStatus.PENDING)
        self.assertEqual(record.attempts, 0)
        self.assertIsNone(record.erp_id)
        self.assertEqual(record.last_error, "")
        self.assertIsNone(record.sent_at)
        self.assertIsNotNone(record.created_at)
        self.assertIsNotNone(record.updated_at)
        self.assertEqual(record.payload, PAYLOAD)

    def test_unique_resource_id_stage(self):
        self.make()

        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make()

    def test_stage_beda_boleh_dua_baris(self):
        self.make(stage=SyncStage.WIP)
        self.make(stage=SyncStage.FG)

        self.assertEqual(SyncRecord.objects.count(), 2)

    def test_resource_id_beda_boleh_dua_baris(self):
        self.make(resource_id="1")
        self.make(resource_id="2")

        self.assertEqual(SyncRecord.objects.count(), 2)

    def test_payload_json_roundtrip(self):
        record = self.make()
        record.refresh_from_db()

        self.assertEqual(record.payload, PAYLOAD)
        self.assertEqual(record.payload["metadata"]["tags"], ["EXPORT", "FAST_TRACK"])

    def test_erp_id_boleh_null(self):
        self.assertIsNone(self.make().erp_id)

    def test_nama_constraint(self):
        names = [constraint.name for constraint in SyncRecord._meta.constraints]

        self.assertIn("uniq_sync_record_resource_stage", names)

    def test_ordering_by_id(self):
        first = self.make()
        second = self.make(resource_id="2")

        self.assertEqual(
            list(SyncRecord.objects.values_list("id", flat=True)), [first.pk, second.pk]
        )

    def test_str_menampilkan_resource_stage_status(self):
        record = self.make()

        self.assertEqual(str(record), "bundle#1:WIP [PENDING]")

    def test_choices_values(self):
        self.assertEqual(
            list(SyncResource.values),
            [
                "bundle",
                "work_order",
                "scrap_accumulator",
                "order",
                "inventory_adjustment",
                # H2.6 — Stock Transfer (log transfer antar lokasi internal).
                "stock_transfer",
                "master.product",
                "master.uom",
                "master.warehouse",
                "master.location",
                "master.bom",
                "master.partner",
                "master.work_center",
                "master.production_line",
                "master.process_routing",
                # H3.6 — master Tax (`account.tax`): CRUD tarif/jenis + pajak default MES.
                "master.tax",
                # H3.1 — Customer Invoice MES (`account.move` out_invoice, jalur manual).
                "customer_invoice",
                "master.number_sequence",
                # H2.2 — transaksi Purchase Order MES → Odoo (resource aditif).
                "purchase_order",
                # H3.2 — Vendor Bill MES (`account.move` in_invoice; jalur manual —
                # I6 tetap tarik `fetch_vendor_bills` & TIDAK memakai resource ini).
                "vendor_bill",
                # H3.3 — Payment MES (`account.payment`, dua arah lewat `payment_type`).
                "payment",
                # H3.4 — Journal Entry manual MES (`account.move` move_type='entry').
                "journal_entry",
                # H3.4 — master Account / chart of accounts (`account.account`, pull-only).
                "master.account",
                # H5.2 — master Currency (`res.currency`; mirror I1) — MES-only: tidak ada
                # konsumen MES yang mengirim mata uang ke Odoo (`Payment.currency` = teks
                # bebas; invoice/journal TIDAK mengirim `currency_id`) ⇒ ledger SKIPPED.
                "master.currency",
                # H5.1 — Company Profile MES (greenfield, **singleton**) — MES-only: tidak
                # ada konsumen MES yang memakai `res.company` & tidak ada transport company
                # ⇒ ledger SKIPPED (pola H5.2/Sprint C).
                "master.company",
                # H5.6 — profil config integrasi MES ↔ Odoo (greenfield, **singleton**,
                # Opsi B: konsumen tetap membaca `.env`) ⇒ ledger SKIPPED.
                "master.integration_config",
                # H5.8 — profil gateway WhatsApp (greenfield, **singleton**; konsumen
                # `get_wa_gateway` tetap membaca `.env`) ⇒ ledger SKIPPED.
                "master.wa_config",
                # H5.7 — profil printer thermal ESC/POS (greenfield, **singleton**;
                # konsumen `get_backend` tetap membaca `.env`) ⇒ ledger SKIPPED.
                "master.printer_config",
                # H5.4 — profil izin role × resource × action (greenfield, multi-row
                # **overlay**; enforcement tetap hardcoded di kode) ⇒ ledger SKIPPED.
                "core_auth.role_permission",
            ],
        )
        self.assertEqual(
            list(SyncStage.values),
            [
                "WIP",
                "FG",
                "SCRAP",
                "INVOICE",
                "MASTER_PUSH",
                "MASTER_PULL",
                # H2.1 — transaksi Sales Order MES → Odoo (stage aditif).
                "SALE_ORDER_PUSH",
                # H2.2 — transaksi Purchase Order MES → Odoo (stage aditif; 19 char,
                # kolom `stage` diperlebar 16 → 24 di migration erp_sync.0015).
                "PURCHASE_ORDER_PUSH",
                # H2.3 — Work Order MES-only: ledger tetap ditulis, status SKIPPED
                # (Odoo `mrp.workorder` = operasi per `mrp.production`, bukan WO per
                # OrderLine). Stage DIPISAH dari WIP/FG yang memakai resource sama.
                "WORK_ORDER_PUSH",
                # H2.4 — Bundle MES-only: perubahan OBJEK bundle (create/update/delete/
                # split/merge) ⇒ SKIPPED; pergerakan stok tetap WIP/FG.
                "BUNDLE_PUSH",
                # H2.5 — Inventory Adjustment MES → Odoo (transaksi nyata: quant + apply).
                "INVENTORY_ADJUST",
                # H2.6 — Stock Transfer MES → Odoo (internal transfer via stock.picking).
                "STOCK_TRANSFER",
                # H3.2 — Vendor Bill MES → Odoo (`account.move` in_invoice draft;
                # stage BARU, terpisah dari INVOICE milik customer invoice).
                "VENDOR_BILL",
                # H3.3 — Payment MES → Odoo (`account.payment` draft; satu stage untuk
                # dua arah, arahnya di field `payment_type`).
                "PAYMENT",
                # H3.4 — Journal Entry manual MES → Odoo (`account.move` move_type='entry'
                # draft; stage BARU, terpisah dari INVOICE/VENDOR_BILL dokumen dagang).
                "JOURNAL_ENTRY",
            ],
        )
        self.assertEqual(
            list(SyncStatus.values),
            ["PENDING", "SENT", "FAILED", "DUPLICATE", "SKIPPED"],
        )
