"""Test audit **push ERP** (I8.11) — 1 test per stage + jalur gagal.

Sebelum I8.11 hanya **endpoint** sync (``api.py``, action ``SYNC_WIP``/``SYNC_FG``)
yang menulis ``AuditLog``; task/service yang benar-benar mengirim stok tidak.
Test ini mengunci perbaikan itu lewat format yang sama untuk semua stage:

    action      ``erp_sync.push_wip`` | ``push_fg`` | ``push_scrap`` | ``push_invoice``
    resource    resource MES ("work_order" / "scrap_accumulator" / "order")
    resource_id id resource MES
    result      ``AuditLog.Result.OK`` (sent) | ``FAILED``
    metadata    {"status", "erp_id", "error", "task_id"}

Adapter disetel ``null`` (``ERP_ADAPTER``) → tanpa Odoo, ``erp_id`` = ``NULL-<uuid>``.
Percobaan yang **dilewati** karena record sudah ``SENT`` sengaja tidak diaudit
(lihat docstring ``integrations/erp_sync/audit.py``).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from apps_industry.garment.tests.factories import (
    make_bundle,
    make_order,
    make_order_line,
    make_scrap_accumulator,
    make_work_order,
)
from core.audit.models import AuditLog
from integrations.erp_sync.adapters.base import ERPAdapterError, ERPResponse
from integrations.erp_sync.audit import (
    ACTION_FG,
    ACTION_INVOICE,
    ACTION_SCRAP,
    ACTION_WIP,
)
from integrations.erp_sync.idempotency import SyncIdempotency
from integrations.erp_sync.models import SyncRecord, SyncStage, SyncStatus
from integrations.erp_sync.services.invoice_sync import InvoiceSyncService
from integrations.erp_sync.tasks import push_fg_receipt, push_wip_issue
from integrations.erp_sync.tasks_invoice import sync_invoice
from integrations.erp_sync.tasks_scrap import sync_scrap_accumulator
from master.models import Product

ADAPTER_TASKS = "integrations.erp_sync.tasks.get_adapter"
PAYLOAD = {"ref": "WO-AUD-1", "qty": 3}


@override_settings(ERP_ADAPTER="null", ODOO_UOM_ID=33)
class AuditPushTasksTests(TestCase):
    """Tiap stage menulis 1 baris AuditLog dengan format seragam (I8.11)."""

    @staticmethod
    def make_record(stage, resource="work_order", resource_id="WO-AUD-1", payload=None):
        """SyncRecord lewat jalur idempotensi (sama seperti endpoint/task)."""
        return SyncIdempotency().get_or_create_sync_record(
            resource, resource_id, stage, payload or PAYLOAD
        )

    def assert_audit(self, log, *, action, resource, resource_id, status):
        """Assert satu baris audit sesuai format I8.11."""
        self.assertEqual(log.action, action)
        self.assertEqual(log.resource, resource)
        self.assertEqual(log.resource_id, str(resource_id))
        self.assertEqual(log.metadata["status"], status)
        self.assertIsNone(log.user)  # dipicu task/sistem, bukan user request
        self.assertEqual(
            log.result,
            AuditLog.Result.OK if status == "sent" else AuditLog.Result.FAILED,
        )
        return log

    # ------------------------------------------------------------------- WIP
    def test_task_wip_menulis_audit_sent(self):
        record = self.make_record(SyncStage.WIP)

        result = push_wip_issue.apply(
            args=("work_order", "WO-AUD-1", PAYLOAD, record.pk)
        ).get()

        self.assertEqual(result["status"], "sent")
        self.assertTrue(result["erp_id"].startswith("NULL-"))
        record.refresh_from_db()
        self.assertEqual(record.status, SyncStatus.SENT)

        log = self.assert_audit(
            AuditLog.objects.get(action=ACTION_WIP),
            action=ACTION_WIP,
            resource="work_order",
            resource_id="WO-AUD-1",
            status="sent",
        )
        self.assertEqual(log.payload, PAYLOAD)
        self.assertEqual(log.metadata["erp_id"], record.erp_id)
        self.assertIsNotNone(log.metadata["task_id"])  # terisi dari Celery request

    def test_task_wip_gagal_menulis_audit_failed(self):
        record = self.make_record(SyncStage.WIP, resource_id="WO-AUD-FAIL")
        adapter = MagicMock()
        adapter.push_wip_issue.return_value = ERPResponse(
            ok=False, error="odoo menolak", stage=SyncStage.WIP
        )

        with patch(ADAPTER_TASKS, return_value=adapter):
            with self.assertRaises(ERPAdapterError):
                push_wip_issue.apply(
                    args=("work_order", "WO-AUD-FAIL", PAYLOAD, record.pk)
                ).get()

        # Task di-retry (autoretry_for + max_retries=3) → ada beberapa baris
        # audit FAILED, semuanya dengan error yang sama.
        logs = AuditLog.objects.filter(action=ACTION_WIP)
        self.assertGreaterEqual(logs.count(), 1)
        for log in logs:
            self.assert_audit(
                log,
                action=ACTION_WIP,
                resource="work_order",
                resource_id="WO-AUD-FAIL",
                status="failed",
            )
            self.assertEqual(log.metadata["error"], "odoo menolak")
        self.assertEqual(
            SyncRecord.objects.get(pk=record.pk).status, SyncStatus.FAILED
        )

    # -------------------------------------------------------------------- FG
    def test_task_fg_menulis_audit_sent(self):
        record = self.make_record(SyncStage.FG, resource_id="WO-AUD-FG")

        result = push_fg_receipt.apply(
            args=("work_order", "WO-AUD-FG", PAYLOAD, record.pk)
        ).get()

        self.assertEqual(result["status"], "sent")
        self.assert_audit(
            AuditLog.objects.get(action=ACTION_FG),
            action=ACTION_FG,
            resource="work_order",
            resource_id="WO-AUD-FG",
            status="sent",
        )

    # ----------------------------------------------------------------- SCRAP
    def test_task_scrap_menulis_audit_sent(self):
        product = Product.objects.create(
            code="TS-AUD-SCRAP", name="Kaos Scrap", odoo_id=901
        )
        bundle = make_bundle(
            work_order=make_work_order(order_line=make_order_line(product=product))
        )
        accumulator = make_scrap_accumulator(bundle=bundle, qty=2)

        result = sync_scrap_accumulator.apply().get()

        self.assertEqual(result["sent"], 1)
        log = self.assert_audit(
            AuditLog.objects.get(action=ACTION_SCRAP),
            action=ACTION_SCRAP,
            resource="scrap_accumulator",
            resource_id=accumulator.pk,
            status="sent",
        )
        self.assertEqual(log.payload["qty"], 2)
        self.assertTrue(log.metadata["erp_id"].startswith("NULL-"))

    def test_scrap_payload_tidak_lengkap_menulis_audit_failed(self):
        # Bundle tanpa product.odoo_id → payload tidak bisa dibangun → FAILED.
        product = Product.objects.create(code="TS-AUD-NOID", name="Kaos Tanpa Id")
        bundle = make_bundle(
            work_order=make_work_order(order_line=make_order_line(product=product))
        )
        accumulator = make_scrap_accumulator(bundle=bundle, qty=1)

        result = sync_scrap_accumulator.apply().get()

        self.assertEqual(result["failed"], 1)
        log = self.assert_audit(
            AuditLog.objects.get(action=ACTION_SCRAP),
            action=ACTION_SCRAP,
            resource="scrap_accumulator",
            resource_id=accumulator.pk,
            status="failed",
        )
        self.assertIn("odoo_id", log.metadata["error"])

    # --------------------------------------------------------------- INVOICE
    def test_task_invoice_menulis_audit_sent(self):
        order = make_order(code="ORD-AUD-1")
        InvoiceSyncService().enqueue(order)

        result = sync_invoice.apply().get()

        self.assertEqual(result["sent"], 1)
        log = self.assert_audit(
            AuditLog.objects.get(action=ACTION_INVOICE),
            action=ACTION_INVOICE,
            resource="order",
            resource_id=order.pk,
            status="sent",
        )
        self.assertTrue(log.metadata["erp_id"].startswith("NULL-"))
        self.assertEqual(
            SyncRecord.objects.get(
                resource="order", resource_id=str(order.pk), stage=SyncStage.INVOICE
            ).status,
            SyncStatus.SENT,
        )
