"""Test task Celery two-stage sync (Fase 4.2) — adapter selalu di-mock.

Tidak ada panggilan Odoo nyata: ``integrations.erp_sync.tasks.get_adapter``
di-patch, jadi test hanya memeriksa kontrak task + perubahan ``SyncRecord``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.test import TestCase

from integrations.erp_sync.adapters.base import ERPResponse
from integrations.erp_sync.idempotency import STAGE_FG, STAGE_WIP, SyncIdempotency
from integrations.erp_sync.models import SyncRecord, SyncStatus
from integrations.erp_sync.tasks import push_fg_receipt, push_wip_issue

PAYLOAD = {"product_ref": "PROD-1", "qty": 10, "ref": "WO-DEMO-1"}
GET_ADAPTER = "integrations.erp_sync.tasks.get_adapter"


def make_record(
    stage: str = STAGE_WIP,
    resource_id: str = "WO-DEMO-1",
    **overrides,
) -> SyncRecord:
    """Buat SyncRecord PENDING (opsional: override status/erp_id untuk uji duplikat)."""
    record = SyncIdempotency().get_or_create_sync_record(
        "work_order", resource_id, stage, PAYLOAD
    )
    if overrides:
        for field, value in overrides.items():
            setattr(record, field, value)
        record.save()
    return record


class PushStageTaskTests(TestCase):
    """Perilaku kedua task sync: sent / duplicate-ignored / failed + retry."""

    def make_adapter(self, response: ERPResponse) -> MagicMock:
        adapter = MagicMock()
        adapter.push_wip_issue.return_value = response
        adapter.push_fg_receipt.return_value = response
        return adapter

    def test_push_wip_issue_sukses_menandai_sent(self):
        record = make_record()
        adapter = self.make_adapter(
            ERPResponse(ok=True, erp_id="MOVE-1", stage=STAGE_WIP, ref=PAYLOAD["ref"])
        )

        with patch(GET_ADAPTER, return_value=adapter):
            result = push_wip_issue.apply(
                args=["work_order", "WO-DEMO-1", PAYLOAD, record.pk]
            ).get()

        record.refresh_from_db()
        self.assertEqual(result["status"], "sent")
        self.assertEqual(result["erp_id"], "MOVE-1")
        self.assertEqual(result["sync_record_id"], record.pk)
        self.assertEqual(record.status, SyncStatus.SENT)
        self.assertEqual(record.erp_id, "MOVE-1")
        self.assertIsNotNone(record.sent_at)
        adapter.push_wip_issue.assert_called_once_with(PAYLOAD)
        adapter.close.assert_called_once_with()

    def test_push_fg_receipt_sukses_menandai_sent(self):
        record = make_record(stage=STAGE_FG)
        adapter = self.make_adapter(
            ERPResponse(ok=True, erp_id="MOVE-2", stage=STAGE_FG, ref=PAYLOAD["ref"])
        )

        with patch(GET_ADAPTER, return_value=adapter):
            result = push_fg_receipt.apply(
                args=["work_order", "WO-DEMO-1", PAYLOAD, record.pk]
            ).get()

        record.refresh_from_db()
        self.assertEqual(result["status"], "sent")
        self.assertEqual(result["stage"], STAGE_FG)
        self.assertEqual(record.status, SyncStatus.SENT)
        adapter.push_fg_receipt.assert_called_once_with(PAYLOAD)
        adapter.push_wip_issue.assert_not_called()

    def test_push_duplicate_dilewati_tanpa_memanggil_adapter(self):
        record = make_record(status=SyncStatus.SENT, erp_id="MOVE-LAMA")
        adapter = self.make_adapter(ERPResponse(ok=True, erp_id="MOVE-BARU"))

        with patch(GET_ADAPTER, return_value=adapter) as fake:
            result = push_wip_issue.apply(
                args=["work_order", "WO-DEMO-1", PAYLOAD, record.pk]
            ).get()

        record.refresh_from_db()
        self.assertEqual(result["status"], "duplicate-ignored")
        self.assertEqual(result["erp_id"], "MOVE-LAMA")
        self.assertEqual(record.erp_id, "MOVE-LAMA")
        self.assertEqual(record.attempts, 0)
        fake.assert_not_called()
        adapter.push_wip_issue.assert_not_called()

    def test_push_gagal_menandai_failed_dan_meminta_retry(self):
        record = make_record()
        adapter = self.make_adapter(
            ERPResponse(ok=False, error="Odoo menolak", stage=STAGE_WIP, ref=PAYLOAD["ref"])
        )

        with patch(GET_ADAPTER, return_value=adapter):
            result = push_wip_issue.apply(args=["work_order", "WO-DEMO-1", PAYLOAD, record.pk])

        record.refresh_from_db()
        self.assertEqual(record.status, SyncStatus.FAILED)
        # Mode eager: Celery langsung menjalankan retry (max_retries=3), jadi
        # `attempts` bertambah beberapa kali -> yang diuji "bertambah", bukan angka pasti.
        self.assertGreaterEqual(record.attempts, 1)
        self.assertEqual(record.last_error, "Odoo menolak")
        self.assertIsNone(record.sent_at)
        self.assertIn(result.state, ("FAILURE", "RETRY"))
        self.assertIsInstance(result.result, Exception)
        self.assertIn("Odoo menolak", str(result.result))

    def test_push_gagal_dua_kali_attempts_menumpuk(self):
        record = make_record()
        adapter = self.make_adapter(ERPResponse(ok=False, error="timeout"))

        with patch(GET_ADAPTER, return_value=adapter):
            first = push_wip_issue.apply(args=["work_order", "WO-DEMO-1", PAYLOAD, record.pk])
            second = push_wip_issue.apply(args=["work_order", "WO-DEMO-1", PAYLOAD, record.pk])

        record.refresh_from_db()
        self.assertEqual(record.status, SyncStatus.FAILED)
        self.assertGreater(record.attempts, 1)
        self.assertIn(first.state, ("FAILURE", "RETRY"))
        self.assertIn(second.state, ("FAILURE", "RETRY"))

    def test_push_record_tidak_ada_gagal_dengan_pesan_jelas(self):
        with patch(GET_ADAPTER) as fake:
            result = push_wip_issue.apply(args=["work_order", "WO-X", PAYLOAD, 99999])

        self.assertIn(result.state, ("FAILURE", "RETRY"))
        self.assertIn("SyncRecord 99999 tidak ditemukan", str(result.result))
        fake.assert_not_called()

    def test_konfigurasi_retry_kedua_task(self):
        self.assertEqual(push_wip_issue.name, "erp_sync.push_wip_issue")
        self.assertEqual(push_fg_receipt.name, "erp_sync.push_fg_receipt")
        for task in (push_wip_issue, push_fg_receipt):
            self.assertEqual(task.max_retries, 3)
            self.assertTrue(task.retry_backoff)
            self.assertEqual(task.retry_backoff_max, 600)
            self.assertTrue(task.retry_jitter)

    def test_routing_ke_queue_erp_sync(self):
        import fnmatch

        from django.conf import settings

        routes = settings.CELERY_TASK_ROUTES
        for task_name in ("erp_sync.ping", "erp_sync.push_wip_issue", "erp_sync.push_fg_receipt"):
            matched = [pattern for pattern in routes if fnmatch.fnmatch(task_name, pattern)]
            self.assertTrue(matched, task_name)
            self.assertEqual(routes[matched[0]]["queue"], "erp_sync")

