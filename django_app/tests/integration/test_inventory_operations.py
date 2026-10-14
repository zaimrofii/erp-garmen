"""Test endpoint inventory operations (F1 / B8) — `GET /api/v1/inventory/operations/`.

Read-only dari `SyncRecord` (monitor; bukan trigger sync). ``IsAuthenticated`` → 403.

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_inventory_operations.py -q
"""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.tests.factories import (
    make_bundle,
    make_order_line,
    make_product,
    make_work_order,
)
from core.auth.models import User
from integrations.erp_sync.models import SyncRecord

OPERATIONS_URL = "/api/v1/inventory/operations/"

TOP_KEYS = {"rows", "total_count", "has_more", "next_cursor"}
ROW_KEYS = {"type", "ref", "product_code", "qty", "status", "at"}

TYPE_BY_STAGE = {
    "WIP": "WIP_ISSUE",
    "FG": "FG_RECEIPT",
    "SCRAP": "SCRAP",
    "INVOICE": "INVOICE",
}


class InventoryOperationsAuthTests(TestCase):
    def test_anonim_403(self):
        self.assertEqual(APIClient().get(OPERATIONS_URL).status_code, 403)


class InventoryOperationsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="inv-ops", password="x")

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def test_shape_listpage_lengkap(self):
        SyncRecord.objects.create(
            resource="bundle",
            resource_id="1",
            stage="WIP",
            status="SENT",
            payload={"product_ref": "TS-001", "qty": 10},
        )

        body = self.api.get(OPERATIONS_URL).json()

        self.assertEqual(set(body), TOP_KEYS)
        self.assertEqual(body["total_count"], 1)
        self.assertFalse(body["has_more"])
        self.assertIsNone(body["next_cursor"])
        row = body["rows"][0]
        self.assertEqual(set(row), ROW_KEYS)
        self.assertEqual(row["type"], "WIP_ISSUE")
        self.assertEqual(row["ref"], "1")
        self.assertEqual(row["product_code"], "TS-001")
        self.assertEqual(row["qty"], 10)
        self.assertEqual(row["status"], "SENT")
        self.assertIn("T", row["at"])

    def test_db_kosong(self):
        body = self.api.get(OPERATIONS_URL).json()

        self.assertEqual(body["rows"], [])
        self.assertEqual(body["total_count"], 0)

    def test_stage_mapping(self):
        SyncRecord.objects.create(
            resource="bundle", resource_id="10", stage="WIP", status="SENT"
        )
        SyncRecord.objects.create(
            resource="scrap_accumulator", resource_id="20", stage="SCRAP", status="FAILED"
        )

        body = self.api.get(OPERATIONS_URL).json()

        self.assertEqual(body["total_count"], 2)
        types = {row["type"] for row in body["rows"]}
        self.assertEqual(types, {"WIP_ISSUE", "SCRAP"})

    def test_filter_stage(self):
        SyncRecord.objects.create(
            resource="bundle", resource_id="1", stage="WIP", status="SENT"
        )
        SyncRecord.objects.create(
            resource="scrap_accumulator", resource_id="2", stage="SCRAP", status="SENT"
        )
        SyncRecord.objects.create(
            resource="bundle", resource_id="3", stage="FG", status="SENT"
        )

        body = self.api.get(OPERATIONS_URL, {"stage": "SCRAP"}).json()

        self.assertEqual(body["total_count"], 1)
        self.assertEqual(body["rows"][0]["type"], "SCRAP")
        self.assertEqual(body["rows"][0]["ref"], "2")

    def test_qty_dan_product_code_null_kalau_payload_kosong(self):
        SyncRecord.objects.create(
            resource="order", resource_id="7", stage="INVOICE", status="PENDING"
        )

        row = self.api.get(OPERATIONS_URL).json()["rows"][0]

        self.assertEqual(row["type"], "INVOICE")
        self.assertIsNone(row["qty"])
        self.assertIsNone(row["product_code"])

    def test_product_code_resolve_dari_bundle(self):
        product = make_product(code="TS-RESOLVE", name="Kaos Resolve")
        order_line = make_order_line(product=product, qty=10)
        work_order = make_work_order(order_line=order_line)
        bundle = make_bundle(work_order=work_order, code="B-RES")
        # Tanpa payload.product_ref -> harus di-resolve dari bundle.
        SyncRecord.objects.create(
            resource="bundle", resource_id=str(bundle.pk), stage="WIP", status="SENT"
        )

        row = self.api.get(OPERATIONS_URL).json()["rows"][0]

        self.assertEqual(row["product_code"], "TS-RESOLVE")
