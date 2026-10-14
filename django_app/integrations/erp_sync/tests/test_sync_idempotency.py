"""Test SyncIdempotency (Fase 4.1): ledger sync per (resource, resource_id, stage)."""

from __future__ import annotations

from django.test import TestCase

from integrations.erp_sync.idempotency import (
    STAGE_FG,
    STAGE_MASTER_PULL,
    STAGE_MASTER_PUSH,
    STAGE_WIP,
    VALID_STAGES,
    SyncIdempotency,
)
from integrations.erp_sync.models import SyncRecord, SyncStatus

RESOURCE = "bundle"
RESOURCE_ID = "7"
PAYLOAD = {"ref": "BND-7", "qty": 10, "product_ref": "KAOS-PUTIH"}


class SyncIdempotencyTests(TestCase):
    """Satu baris per (resource, resource_id, stage); retry meng-update baris itu."""

    def setUp(self):
        self.sync = SyncIdempotency()

    def create(self, stage: str = STAGE_WIP, payload: dict | None = None, resource_id: str = RESOURCE_ID):
        return self.sync.get_or_create_sync_record(
            RESOURCE, resource_id, stage, payload if payload is not None else PAYLOAD
        )

    def test_stage_konstan_sesuai_kontrak(self):
        self.assertEqual(STAGE_WIP, "WIP")
        self.assertEqual(STAGE_FG, "FG")
        # H1.1 — stage master (MES → Odoo & Odoo → MES) ikut diakui idempotensi.
        self.assertEqual(STAGE_MASTER_PUSH, "MASTER_PUSH")
        self.assertEqual(STAGE_MASTER_PULL, "MASTER_PULL")
        self.assertEqual(
            VALID_STAGES,
            (
                "WIP",
                "FG",
                "SCRAP",
                "INVOICE",
                "MASTER_PUSH",
                "MASTER_PULL",
                # H2.1 — transaksi Sales Order MES → Odoo.
                "SALE_ORDER_PUSH",
                # H2.2 — transaksi Purchase Order MES → Odoo.
                "PURCHASE_ORDER_PUSH",
                # H2.3 — Work Order MES-only (ledger ditulis dengan status SKIPPED).
                "WORK_ORDER_PUSH",
                # H2.4 — Bundle MES-only (perubahan objek; pergerakan stok tetap WIP/FG).
                "BUNDLE_PUSH",
                # H2.5 — Inventory Adjustment MES → Odoo (transaksi nyata).
                "INVENTORY_ADJUST",
                # H2.6 — Stock Transfer MES → Odoo (internal transfer).
                "STOCK_TRANSFER",
                # H3.2 — Vendor Bill MES → Odoo (`account.move` in_invoice draft).
                "VENDOR_BILL",
                # H3.3 — Payment MES → Odoo (`account.payment` draft, dua arah).
                "PAYMENT",
                # H3.4 — Journal Entry manual MES → Odoo (`account.move` entry draft).
                "JOURNAL_ENTRY",
            ),
        )

    def test_get_or_create_membuat_record_baru(self):
        record = self.create()

        self.assertEqual(record.status, SyncStatus.PENDING)
        self.assertEqual(record.attempts, 0)
        self.assertEqual(record.payload, PAYLOAD)
        self.assertIsNone(record.sent_at)
        self.assertIsNone(record.erp_id)
        self.assertEqual(SyncRecord.objects.count(), 1)

    def test_get_or_create_mengembalikan_record_lama(self):
        first = self.create()
        second = self.create()

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(SyncRecord.objects.count(), 1)

    def test_get_or_create_tidak_menimpa_payload_lama(self):
        self.create(payload={"ref": "BND-7", "qty": 10})
        second = self.create(payload={"ref": "BND-7", "qty": 99})

        self.assertEqual(second.payload["qty"], 10)

    def test_stage_wip_dan_fg_punya_record_terpisah(self):
        wip = self.create(STAGE_WIP)
        fg = self.create(STAGE_FG)

        self.assertNotEqual(wip.pk, fg.pk)
        self.assertEqual(SyncRecord.objects.count(), 2)

    def test_resource_id_berbeda_punya_record_terpisah(self):
        self.create(resource_id="1")
        self.create(resource_id="2")

        self.assertEqual(SyncRecord.objects.count(), 2)

    def test_resource_berbeda_punya_record_terpisah(self):
        self.sync.get_or_create_sync_record("bundle", "1", STAGE_WIP, PAYLOAD)
        self.sync.get_or_create_sync_record("work_order", "1", STAGE_WIP, PAYLOAD)

        self.assertEqual(SyncRecord.objects.count(), 2)

    def test_stage_tidak_dikenal_raise_value_error(self):
        with self.assertRaisesMessage(ValueError, "Stage sync tidak dikenal"):
            self.create(stage="QC")

    def test_stage_tidak_dikenal_tidak_membuat_baris(self):
        with self.assertRaises(ValueError):
            self.create(stage="WIPX")

        self.assertEqual(SyncRecord.objects.count(), 0)

    def test_mark_sent(self):
        record = self.sync.mark_sent(self.create(), "9001")

        self.assertEqual(record.status, SyncStatus.SENT)
        self.assertEqual(record.erp_id, "9001")
        self.assertIsNotNone(record.sent_at)
        self.assertEqual(record.last_error, "")

    def test_mark_sent_tersimpan_di_db_dan_id_dijadikan_string(self):
        record = self.sync.mark_sent(self.create(), 9001)
        record.refresh_from_db()

        self.assertEqual(record.status, SyncStatus.SENT)
        self.assertEqual(record.erp_id, "9001")
        self.assertIsNotNone(record.sent_at)

    def test_mark_sent_menghapus_error_lama(self):
        record = self.sync.mark_failed(self.create(), "timeout")
        self.sync.mark_sent(record, "9002")
        record.refresh_from_db()

        self.assertEqual(record.last_error, "")

    def test_mark_failed_menaikkan_attempts(self):
        record = self.create()
        self.sync.mark_failed(record, "koneksi putus")
        self.sync.mark_failed(record, "koneksi putus lagi")
        record.refresh_from_db()

        self.assertEqual(record.status, SyncStatus.FAILED)
        self.assertEqual(record.attempts, 2)
        self.assertEqual(record.last_error, "koneksi putus lagi")

    def test_mark_failed_menyimpan_error_panjang_utuh(self):
        error = "x" * 1000
        record = self.sync.mark_failed(self.create(), error)
        record.refresh_from_db()

        self.assertEqual(record.last_error, error)

    def test_mark_duplicate(self):
        record = self.sync.mark_duplicate(self.create())
        record.refresh_from_db()

        self.assertEqual(record.status, SyncStatus.DUPLICATE)

    def test_is_already_sent(self):
        record = self.create()

        self.assertFalse(self.sync.is_already_sent(record))
        self.sync.mark_failed(record, "gagal")
        self.assertFalse(self.sync.is_already_sent(record))
        self.sync.mark_sent(record, "1")
        self.assertTrue(self.sync.is_already_sent(record))
        record.status = SyncStatus.DUPLICATE
        self.assertTrue(self.sync.is_already_sent(record))
        self.assertFalse(self.sync.is_already_sent(None))
