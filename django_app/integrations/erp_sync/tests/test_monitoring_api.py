"""Test endpoint monitoring read-only (FASE 4.4).

* ``GET /api/v1/finance/invoices/`` — antrean invoice (SyncRecord INVOICE + Order).
* ``GET /api/v1/sync/records/``     — daftar SyncRecord (filter stage/status).

Keduanya ``IsAuthenticated`` (anonim → 403), read-only (tidak ada mutasi).
"""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.models import Order
from core.auth.models import User
from integrations.erp_sync.models import SyncRecord

RECORDS_URL = "/api/v1/sync/records/"
INVOICE_URL = "/api/v1/finance/invoices/"

ROW_KEYS_RECORD = {
    "id",
    "resource",
    "resource_id",
    "stage",
    "status",
    "attempts",
    "last_error",
    "erp_id",
    "sent_at",
    "created_at",
}
ROW_KEYS_INVOICE = {
    "order_id",
    "order_no",
    "invoice_status",
    "erp_id",
    "attempts",
    "last_error",
    "sent_at",
    "created_at",
}


class MonitoringAuthTests(TestCase):
    """Kedua endpoint butuh login (konsisten endpoint sync lain, FASE 4.1)."""

    def setUp(self):
        self.api = APIClient()

    def test_sync_records_anonim_403(self):
        self.assertEqual(self.api.get(RECORDS_URL).status_code, 403)

    def test_invoices_anonim_403(self):
        self.assertEqual(self.api.get(INVOICE_URL).status_code, 403)


class SyncRecordListTests(TestCase):
    """`GET /api/v1/sync/records/` — daftar + filter + paging."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="mon-sync", password="x")
        cls.wip = SyncRecord.objects.create(
            resource="bundle", resource_id="1", stage="WIP", status="SENT", attempts=1
        )
        cls.scrap = SyncRecord.objects.create(
            resource="scrap_accumulator",
            resource_id="1",
            stage="SCRAP",
            status="FAILED",
            attempts=3,
            last_error="boom",
        )
        cls.invoice = SyncRecord.objects.create(
            resource="order", resource_id="1", stage="INVOICE", status="PENDING"
        )

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def test_daftar_semua_dengan_bentuk_kontrak(self):
        response = self.api.get(RECORDS_URL)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total_count"], 3)
        self.assertEqual(len(body["rows"]), 3)
        self.assertFalse(body["has_next"])
        self.assertIsNone(body["next_cursor"])
        self.assertEqual(set(body["rows"][0]), ROW_KEYS_RECORD)

    def test_filter_stage_wip(self):
        rows = self.api.get(RECORDS_URL, {"stage": "WIP"}).json()["rows"]

        self.assertEqual([row["stage"] for row in rows], ["WIP"])
        self.assertEqual(rows[0]["resource"], "bundle")

    def test_filter_status_failed(self):
        rows = self.api.get(RECORDS_URL, {"status": "FAILED"}).json()["rows"]

        self.assertEqual([row["status"] for row in rows], ["FAILED"])
        self.assertEqual(rows[0]["attempts"], 3)
        self.assertEqual(rows[0]["last_error"], "boom")

    def test_urut_terbaru_dulu(self):
        rows = self.api.get(RECORDS_URL).json()["rows"]

        created = [row["created_at"] for row in rows]
        self.assertEqual(created, sorted(created, reverse=True))

    def test_paging_limit_dan_cursor(self):
        pertama = self.api.get(RECORDS_URL, {"limit": 2}).json()

        self.assertEqual(len(pertama["rows"]), 2)
        self.assertTrue(pertama["has_next"])
        self.assertEqual(pertama["next_cursor"], 2)

        kedua = self.api.get(
            RECORDS_URL, {"limit": 2, "cursor": pertama["next_cursor"]}
        ).json()
        self.assertEqual(len(kedua["rows"]), 1)
        self.assertFalse(kedua["has_next"])

    def test_param_tidak_valid_400(self):
        self.assertEqual(self.api.get(RECORDS_URL, {"limit": 0}).status_code, 400)
        self.assertEqual(self.api.get(RECORDS_URL, {"limit": "abc"}).status_code, 400)
        self.assertEqual(self.api.get(RECORDS_URL, {"cursor": -1}).status_code, 400)

    def test_endpoint_read_only_tidak_menulis(self):
        sebelum = SyncRecord.objects.count()

        self.api.get(RECORDS_URL)
        self.api.get(RECORDS_URL, {"stage": "WIP"})

        self.assertEqual(SyncRecord.objects.count(), sebelum)


class InvoiceListTests(TestCase):
    """`GET /api/v1/finance/invoices/` — join SyncRecord(INVOICE) ↔ Order."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="mon-inv", password="x")
        cls.order = Order.objects.create(code="SO-MON-1")
        cls.invoice = SyncRecord.objects.create(
            resource="order",
            resource_id=str(cls.order.pk),
            stage="INVOICE",
            status="SENT",
            erp_id="77",
            attempts=1,
        )
        cls.orphan = SyncRecord.objects.create(
            resource="order",
            resource_id="999999",
            stage="INVOICE",
            status="FAILED",
            attempts=2,
            last_error="Order 999999 tidak ditemukan.",
        )
        # Bukan INVOICE → tidak boleh muncul di daftar invoice.
        SyncRecord.objects.create(
            resource="bundle", resource_id="5", stage="WIP", status="SENT"
        )

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def test_daftar_invoice_dengan_bentuk_kontrak(self):
        response = self.api.get(INVOICE_URL)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total_count"], 2)  # hanya stage INVOICE
        self.assertEqual(len(body["rows"]), 2)

        row = next(r for r in body["rows"] if r["order_id"] == self.order.pk)
        self.assertEqual(set(row), ROW_KEYS_INVOICE)
        self.assertEqual(row["order_no"], "SO-MON-1")
        self.assertEqual(row["invoice_status"], "SENT")
        self.assertEqual(row["erp_id"], "77")
        self.assertEqual(row["attempts"], 1)

    def test_orphan_order_no_none(self):
        rows = self.api.get(INVOICE_URL).json()["rows"]

        orphan = next(r for r in rows if r["order_id"] == 999999)
        self.assertIsNone(orphan["order_no"])
        self.assertEqual(orphan["invoice_status"], "FAILED")

    def test_filter_state_memakai_status_sync(self):
        rows = self.api.get(INVOICE_URL, {"state": "failed"}).json()["rows"]

        self.assertEqual([row["invoice_status"] for row in rows], ["FAILED"])

    def test_resource_id_bukan_angka_dianggap_orphan(self):
        SyncRecord.objects.create(
            resource="order", resource_id="bukan-angka", stage="INVOICE", status="FAILED"
        )

        rows = self.api.get(INVOICE_URL).json()["rows"]

        # `resource_id` non-numerik → `order_id=None` (satu-satunya baris seperti itu).
        aneh = next(r for r in rows if r["order_id"] is None)
        self.assertIsNone(aneh["order_no"])
        self.assertEqual(aneh["invoice_status"], "FAILED")
