"""Test `InvoiceSyncService` (TX-INVOICE, I5) — adapter di-mock, tanpa Odoo.

Cakupan: `enqueue` (idempoten lewat ``SyncRecord``), `sync_one`
(SENT / FAILED / skip kalau sudah SENT / order hilang / adapter melempar),
`sync_pending` (collect ``PENDING`` + ``FAILED`` ``attempts < MAX_ATTEMPTS``)
→ counter ``{sent, failed, skipped}``, dan wiring ``get_adapter()`` default.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.test import TestCase

from apps_industry.garment.models import Order, OrderLine
from integrations.erp_sync.adapters.base import ERPResponse
from integrations.erp_sync.adapters.odoo import STAGE_INVOICE
from integrations.erp_sync.models import (
    SyncRecord,
    SyncResource,
    SyncStage,
    SyncStatus,
)
from integrations.erp_sync.services.invoice_sync import (
    MAX_ATTEMPTS,
    RESOURCE,
    STAGE,
    InvoiceSyncService,
)
from master.models import Partner, Product

GET_ADAPTER = "integrations.erp_sync.services.invoice_sync.get_adapter"


class FakeAdapter:
    """Adapter palsu: hasil ``push_customer_invoice_wo`` ditentukan test."""

    def __init__(self, ok=True, erp_id="777", error=None):
        self.ok = ok
        self.erp_id = erp_id
        self.error = error
        self.calls = []
        self.closed = False

    def push_customer_invoice_wo(self, wo):
        self.calls.append(wo)
        return ERPResponse(
            ok=self.ok,
            erp_id=self.erp_id,
            error=self.error,
            stage=STAGE_INVOICE,
            ref=wo.get("ref", ""),
        )

    def close(self):
        self.closed = True


class InvoiceSyncServiceTestCase(TestCase):
    """Data: Partner(odoo_id) → Order → OrderLine."""

    @classmethod
    def setUpTestData(cls):
        cls.customer = Partner.objects.create(
            code="PT-INV-1", name="PT Invoice", odoo_id=51
        )
        cls.product = Product.objects.create(
            code="KTS-INV-1", name="Kaos Invoice", odoo_id=100
        )
        cls.order = Order.objects.create(code="ORD-INV-1000", customer=cls.customer)
        OrderLine.objects.create(order=cls.order, product=cls.product, qty=4)

    # ------------------------------------------------------------------ helper
    def make_order(self, code):
        order = Order.objects.create(code=code, customer=self.customer)
        OrderLine.objects.create(order=order, product=self.product, qty=1)
        return order

    @staticmethod
    def make_record(order, status=SyncStatus.PENDING, attempts=0):
        return SyncRecord.objects.create(
            resource=SyncResource.ORDER,
            resource_id=str(order.pk),
            stage=SyncStage.INVOICE,
            status=status,
            attempts=attempts,
        )

    # ----------------------------------------------------------------- enqueue
    def test_enqueue_membuat_sync_record_pending(self):
        record = InvoiceSyncService().enqueue(self.order)

        self.assertEqual(record.status, SyncStatus.PENDING)
        self.assertEqual(record.resource, "order")
        self.assertEqual(record.stage, "INVOICE")
        self.assertEqual(record.resource_id, str(self.order.pk))
        self.assertEqual(record.payload["ref"], f"INV-{self.order.code}")
        self.assertEqual(SyncRecord.objects.count(), 1)
        # Konstanta service menunjuk enum yang sudah dikunci di I5.1.
        self.assertEqual(RESOURCE, SyncResource.ORDER)
        self.assertEqual(STAGE, SyncStage.INVOICE)

    def test_enqueue_idempoten_dua_kali_tetap_satu_record(self):
        service = InvoiceSyncService()

        pertama = service.enqueue(self.order)
        kedua = service.enqueue(self.order)

        self.assertEqual(pertama.pk, kedua.pk)
        self.assertEqual(SyncRecord.objects.count(), 1)

    # ---------------------------------------------------------------- sync_one
    def test_sync_one_happy_path_sent(self):
        record = self.make_record(self.order)
        adapter = FakeAdapter(ok=True, erp_id="777")

        hasil = InvoiceSyncService(adapter=adapter).sync_one(record)

        self.assertEqual(hasil.status, SyncStatus.SENT)
        self.assertEqual(hasil.erp_id, "777")
        self.assertIsNotNone(hasil.sent_at)
        self.assertEqual(
            adapter.calls,
            [{"order_id": self.order.pk, "ref": f"INV-{self.order.code}"}],
        )
        # Adapter di-inject → service TIDAK menutupnya.
        self.assertFalse(adapter.closed)

    def test_sync_one_adapter_gagal_failed_tidak_raise(self):
        record = self.make_record(self.order)
        adapter = FakeAdapter(
            ok=False, erp_id=None, error="Odoo menolak: partner kosong"
        )

        hasil = InvoiceSyncService(adapter=adapter).sync_one(record)

        self.assertEqual(hasil.status, SyncStatus.FAILED)
        self.assertIn("Odoo menolak", hasil.last_error)
        self.assertEqual(hasil.attempts, 1)
        self.assertEqual(len(adapter.calls), 1)

    def test_sync_one_sudah_sent_dilewati(self):
        record = self.make_record(self.order, status=SyncStatus.SENT)
        adapter = FakeAdapter()

        hasil = InvoiceSyncService(adapter=adapter).sync_one(record)

        self.assertEqual(hasil.pk, record.pk)
        self.assertEqual(hasil.status, SyncStatus.SENT)
        self.assertEqual(adapter.calls, [])  # adapter TIDAK dipanggil

    # ------------------------------------------------------------- sync_pending
    def test_sync_pending_counter_sent_failed_skipped(self):
        order_pending = self.make_order("ORD-INV-2001")
        order_failed = self.make_order("ORD-INV-2002")
        order_sent = self.make_order("ORD-INV-2003")
        self.make_record(order_pending)
        self.make_record(order_failed, status=SyncStatus.FAILED, attempts=1)
        self.make_record(order_sent, status=SyncStatus.SENT)
        adapter = FakeAdapter(ok=True)

        result = InvoiceSyncService(adapter=adapter).sync_pending()

        self.assertEqual(result, {"sent": 2, "failed": 0, "skipped": 1})
        self.assertEqual(len(adapter.calls), 2)  # PENDING + FAILED dikirim ulang

    def test_sync_pending_melewati_failed_mentok(self):
        order = self.make_order("ORD-INV-3001")
        self.make_record(order, status=SyncStatus.FAILED, attempts=MAX_ATTEMPTS)
        adapter = FakeAdapter()

        result = InvoiceSyncService(adapter=adapter).sync_pending()

        self.assertEqual(result, {"sent": 0, "failed": 0, "skipped": 1})
        self.assertEqual(adapter.calls, [])

    # ------------------------------------------------------------------- bonus
    def test_sync_one_order_hilang_mark_failed(self):
        record = SyncRecord.objects.create(
            resource=SyncResource.ORDER,
            resource_id="999999",
            stage=SyncStage.INVOICE,
            status=SyncStatus.PENDING,
        )
        adapter = FakeAdapter()

        hasil = InvoiceSyncService(adapter=adapter).sync_one(record)

        self.assertEqual(hasil.status, SyncStatus.FAILED)
        self.assertIn("tidak ditemukan", hasil.last_error)
        self.assertEqual(adapter.calls, [])

    def test_sync_one_adapter_melempar_tidak_raise(self):
        record = self.make_record(self.order)
        adapter = FakeAdapter()
        adapter.push_customer_invoice_wo = MagicMock(
            side_effect=RuntimeError("odoo mati")
        )

        with self.assertLogs(
            "integrations.erp_sync.services.invoice_sync", level="ERROR"
        ):
            hasil = InvoiceSyncService(adapter=adapter).sync_one(record)

        self.assertEqual(hasil.status, SyncStatus.FAILED)
        self.assertIn("Adapter error", hasil.last_error)

    def test_get_adapter_default_dipanggil_dan_ditutup(self):
        record = self.make_record(self.order)
        adapter = FakeAdapter()

        with patch(GET_ADAPTER, return_value=adapter) as get_adapter_mock:
            InvoiceSyncService().sync_one(record)

        get_adapter_mock.assert_called_once_with()
        self.assertTrue(adapter.closed)
