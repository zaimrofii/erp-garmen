"""Test `ScrapSyncService` (TX-SCRAP) — adapter di-mock, tanpa Odoo.

Cakupan: `sync_one` sukses/gagal/tanpa `odoo_id`/tanpa `ODOO_UOM_ID`,
`collect_pending` melewati yang sudah SENT (idempotensi), `sync_batch` counter
`{sent, failed, skipped}`, `qty == 0` tidak pernah dikirim, dan wiring
`get_adapter()` default (dipanggil + ditutup).

Idempotensi = `SyncRecord(resource="scrap_accumulator", stage="SCRAP")`.
"""

from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from apps_industry.garment.models import (
    Bundle,
    Order,
    OrderLine,
    ScrapAccumulator,
    WorkCenter,
    WorkOrder,
)
from integrations.erp_sync.adapters.base import ERPResponse
from integrations.erp_sync.adapters.odoo import STAGE_SCRAP
from integrations.erp_sync.models import (
    SyncRecord,
    SyncResource,
    SyncStage,
    SyncStatus,
)
from integrations.erp_sync.services.scrap_sync import RESOURCE, STAGE, ScrapSyncService
from master.models import Product

GET_ADAPTER = "integrations.erp_sync.services.scrap_sync.get_adapter"
UOM_ID = 33


class FakeAdapter:
    """Adapter palsu: hasil ``push_scrap_wo`` ditentukan test."""

    def __init__(self, ok=True, erp_id="555", error=None, results=None):
        self.ok = ok
        self.erp_id = erp_id
        self.error = error
        self.results = list(results or [])
        self.calls = []
        self.closed = False

    def push_scrap_wo(self, wo):
        self.calls.append(wo)
        if self.results:
            return self.results.pop(0)
        return ERPResponse(
            ok=self.ok,
            erp_id=self.erp_id,
            error=self.error,
            stage=STAGE_SCRAP,
            ref=wo.get("ref", ""),
        )

    def close(self):
        self.closed = True


@override_settings(ODOO_UOM_ID=UOM_ID)
class ScrapSyncServiceTestCase(TestCase):
    """Data: Product(odoo_id) → order → line → WO → bundle → ScrapAccumulator."""

    @classmethod
    def setUpTestData(cls):
        cls.product = Product.objects.create(
            code="KTS-TXSCRAP", name="Kaos Scrap", odoo_id=100
        )
        cls.bundle = cls.make_bundle_for(cls.product, "A")
        cls.work_center = WorkCenter.objects.create(code="WC-TXSCRAP-1", name="Sewing")
        cls.acc = ScrapAccumulator.objects.create(
            work_center=cls.work_center, bundle=cls.bundle, qty=3
        )

    # ------------------------------------------------------------------ helper
    @classmethod
    def make_bundle_for(cls, product, code):
        """Rantai minimal order → line → WO → bundle untuk produk tertentu."""
        order = Order.objects.create(code=f"ORD-TXSCRAP-{code}")
        line = OrderLine.objects.create(order=order, product=product, qty=10)
        work_order = WorkOrder.objects.create(
            code=f"WO-TXSCRAP-{code}", order_line=line, qty_planned=10
        )
        return Bundle.objects.create(
            code=f"BND-TXSCRAP-{code}", work_order=work_order, size="L", qty=5
        )

    def make_acc(self, code, qty, product=None):
        """ScrapAccumulator baru pada bundle baru (hindari unique (wc, bundle))."""
        bundle = self.make_bundle_for(product or self.product, code)
        return ScrapAccumulator.objects.create(
            work_center=self.work_center, bundle=bundle, qty=qty
        )

    def mark_sent(self, accumulator):
        """SyncRecord SENT (seolah sudah pernah terkirim ke Odoo)."""
        return SyncRecord.objects.create(
            resource=SyncResource.SCRAP_ACCUMULATOR,
            resource_id=str(accumulator.pk),
            stage=SyncStage.SCRAP,
            status=SyncStatus.SENT,
            erp_id="1",
        )

    # --------------------------------------------------------------- sync_one
    def test_sync_one_happy_path_sent(self):
        adapter = FakeAdapter(ok=True, erp_id="555")

        record = ScrapSyncService(adapter=adapter).sync_one(self.acc)

        self.assertEqual(record.status, SyncStatus.SENT)
        self.assertEqual(record.erp_id, "555")
        self.assertIsNotNone(record.sent_at)
        self.assertEqual(record.resource, RESOURCE)
        self.assertEqual(record.stage, STAGE)
        self.assertEqual(record.resource_id, str(self.acc.pk))
        self.assertEqual(SyncRecord.objects.count(), 1)

        # Payload yang dikirim ke adapter (mapping Product.odoo_id + ref + uom).
        self.assertEqual(len(adapter.calls), 1)
        wo = adapter.calls[0]
        self.assertEqual(wo["product_id"], self.product.pk)
        self.assertEqual(wo["qty"], 3)
        self.assertEqual(wo["uom_id"], UOM_ID)
        self.assertEqual(wo["ref"], f"SCRAP-{self.acc.pk}-{timezone.localdate()}")
        # Adapter di-inject → service TIDAK menutupnya.
        self.assertFalse(adapter.closed)

    def test_sync_one_adapter_gagal_failed_tidak_raise(self):
        adapter = FakeAdapter(ok=False, erp_id=None, error="Odoo menolak: stok kurang")

        record = ScrapSyncService(adapter=adapter).sync_one(self.acc)

        self.assertEqual(record.status, SyncStatus.FAILED)
        self.assertIn("stok kurang", record.last_error)
        self.assertEqual(record.attempts, 1)
        self.assertIsNone(record.erp_id)
        self.assertEqual(len(adapter.calls), 1)  # tetap dipanggil sekali

    def test_sync_one_tanpa_odoo_id_failed_tanpa_panggil_adapter(self):
        product = Product.objects.create(code="TANPA-ODOO", name="Belum Sync")
        accumulator = self.make_acc("B", qty=2, product=product)
        adapter = FakeAdapter()

        record = ScrapSyncService(adapter=adapter).sync_one(accumulator)

        self.assertEqual(record.status, SyncStatus.FAILED)
        self.assertIn("belum punya odoo_id", record.last_error)
        self.assertEqual(adapter.calls, [])

    def test_sync_one_uom_belum_dikonfigurasi_failed(self):
        adapter = FakeAdapter()

        with override_settings(ODOO_UOM_ID=None):
            record = ScrapSyncService(adapter=adapter).sync_one(self.acc)

        self.assertEqual(record.status, SyncStatus.FAILED)
        self.assertIn("ODOO_UOM_ID", record.last_error)
        self.assertEqual(adapter.calls, [])

    # ----------------------------------------------------------- collect/batch
    def test_collect_pending_melewati_yang_sudah_sent(self):
        self.mark_sent(self.acc)
        acc_baru = self.make_acc("C", qty=2)

        pending = list(ScrapSyncService().collect_pending())

        self.assertEqual([acc.pk for acc in pending], [acc_baru.pk])

    def test_sync_batch_counter_sent_failed_skipped(self):
        self.mark_sent(self.acc)   # sudah SENT → skipped
        self.make_acc("D", qty=1)  # pending → sent
        self.make_acc("E", qty=2)  # pending → sent
        adapter = FakeAdapter(ok=True)

        result = ScrapSyncService(adapter=adapter).sync_batch()

        self.assertEqual(result, {"sent": 2, "failed": 0, "skipped": 1})
        self.assertEqual(len(adapter.calls), 2)
        self.assertEqual(SyncRecord.objects.count(), 3)  # 1 lama + 2 baru

    def test_sync_batch_satu_gagal_tidak_hentikan_batch(self):
        self.mark_sent(self.acc)  # sisakan 2 accumulator pending
        self.make_acc("F", qty=1)
        self.make_acc("G", qty=1)
        adapter = FakeAdapter(
            results=[
                ERPResponse(ok=False, error="Odoo mati"),
                ERPResponse(ok=True, erp_id="777"),
            ]
        )

        result = ScrapSyncService(adapter=adapter).sync_batch()

        self.assertEqual(result, {"sent": 1, "failed": 1, "skipped": 1})
        self.assertEqual(len(adapter.calls), 2)  # item kedua tetap diproses

    def test_scrap_qty_nol_tidak_dikirim(self):
        self.mark_sent(self.acc)  # sisakan hanya accumulator qty=0
        acc_nol = self.make_acc("H", qty=0)
        adapter = FakeAdapter()

        result = ScrapSyncService(adapter=adapter).sync_batch()

        self.assertFalse(
            ScrapSyncService().collect_pending().filter(pk=acc_nol.pk).exists()
        )
        self.assertEqual(adapter.calls, [])
        self.assertEqual(result, {"sent": 0, "failed": 0, "skipped": 2})

    def test_get_adapter_default_dipanggil_dan_ditutup(self):
        adapter = FakeAdapter()

        with patch(GET_ADAPTER, return_value=adapter) as get_adapter_mock:
            ScrapSyncService().sync_one(self.acc)

        get_adapter_mock.assert_called_once_with()
        self.assertTrue(adapter.closed)
