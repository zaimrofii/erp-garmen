"""Test endpoint purchase reporting (F2 / B11) — `GET /api/v1/purchase/reporting/`.

Agregat PO (I3) + vendor bill (I6) lewat Odoo transport; **test memakai mock**
(tidak hit Odoo). Uji juga fail-safe ``ERP_ADAPTER=null`` (semua nol, bukan error).

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_purchase_reporting.py -q
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from core.auth.models import User
from master.models import Partner

REPORTING_URL = "/api/v1/purchase/reporting/"

TOP_KEYS = {"total_po", "total_amount", "by_state", "top_vendors", "vendor_bills"}

ORDERS = [
    {"id": 1, "name": "PO1", "partner_id": [15, "Vendor A"], "state": "purchase", "amount_total": 100.0},
    {"id": 2, "name": "PO2", "partner_id": [15, "Vendor A"], "state": "done", "amount_total": 50.0},
    {"id": 3, "name": "PO3", "partner_id": [16, "Vendor B"], "state": "draft", "amount_total": 10.0},
]

BILLS = [
    {"id": 1, "name": "BILL1", "partner_id": [15, "Vendor A"], "state": "posted", "amount_total": 20.0},
    {"id": 2, "name": "BILL2", "partner_id": [16, "Vendor B"], "state": "draft", "amount_total": 5.0},
]


def _mock_transport(orders=None, bills=None):
    transport = MagicMock()
    transport.fetch_purchase_orders.return_value = orders if orders is not None else []
    transport.fetch_vendor_bills.return_value = bills if bills is not None else []
    return transport


def _patch_transport(transport):
    return patch(
        "integrations.erp_sync.monitoring.get_transport", return_value=transport
    )


class PurchaseReportingAuthTests(TestCase):
    def test_anonim_403(self):
        self.assertEqual(APIClient().get(REPORTING_URL).status_code, 403)


class PurchaseReportingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="pur-report", password="x")

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def test_shape_lengkap(self):
        transport = _mock_transport(ORDERS, BILLS)

        with _patch_transport(transport):
            body = self.api.get(REPORTING_URL).json()

        self.assertTrue(TOP_KEYS.issubset(set(body)))
        self.assertEqual(set(body["by_state"]), {"draft", "purchase", "done"})
        self.assertIsInstance(body["top_vendors"], list)

    def test_agregat_po(self):
        transport = _mock_transport(ORDERS, BILLS)

        with _patch_transport(transport):
            body = self.api.get(REPORTING_URL).json()

        self.assertEqual(body["total_po"], 3)
        self.assertEqual(body["total_amount"], 160.0)  # 100 + 50 + 10
        self.assertEqual(body["by_state"], {"draft": 1, "purchase": 1, "done": 1})

    def test_top_vendors_urut_amount_desc(self):
        transport = _mock_transport(ORDERS, BILLS)

        with _patch_transport(transport):
            body = self.api.get(REPORTING_URL).json()

        top = body["top_vendors"]
        self.assertEqual(len(top), 2)
        self.assertEqual(top[0]["partner_name"], "Vendor A")
        self.assertEqual(top[0]["total_amount"], 150.0)  # 100 + 50
        self.assertEqual(top[0]["po_count"], 2)
        self.assertEqual(top[1]["partner_name"], "Vendor B")

    def test_vendor_bills_agregat(self):
        transport = _mock_transport(ORDERS, BILLS)

        with _patch_transport(transport):
            body = self.api.get(REPORTING_URL).json()

        self.assertEqual(body["vendor_bills"]["total"], 2)
        self.assertEqual(body["vendor_bills"]["total_amount"], 25.0)  # 20 + 5
        self.assertEqual(body["vendor_bills"]["by_state"], {"posted": 1, "draft": 1})

    @override_settings(ERP_ADAPTER="null")
    def test_erp_adapter_null_fail_safe(self):
        # Tanpa patch: transport null → orders/bills kosong, bukan error.
        response = self.api.get(REPORTING_URL)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total_po"], 0)
        self.assertEqual(body["total_amount"], 0.0)
        self.assertEqual(body["by_state"], {"draft": 0, "purchase": 0, "done": 0})
        self.assertEqual(body["top_vendors"], [])
        self.assertEqual(body["vendor_bills"]["total"], 0)


class PurchaseReportingGapTests(TestCase):
    """G5b (aditif) — monthly_series + top_vendors (vendor_name/vendor_code/amount_total)."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="pr-gap", password="x")

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def test_monthly_series_6_entry_ascending(self):
        transport = _mock_transport([], [])

        with _patch_transport(transport):
            body = self.api.get(REPORTING_URL).json()

        series = body["monthly_series"]
        self.assertEqual(len(series), 6)
        months = [entry["month"] for entry in series]
        self.assertEqual(months, sorted(months))
        for entry in series:
            self.assertEqual(
                set(entry),
                {"month", "po_count", "amount_total", "vendor_bill_count"},
            )

    def test_monthly_series_menghitung_po_dan_bill(self):
        now = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
        orders = [
            {
                "id": 1,
                "name": "PO1",
                "partner_id": [15, "Vendor A"],
                "state": "purchase",
                "amount_total": 100.0,
                "date_order": now,
            }
        ]
        bills = [
            {
                "id": 1,
                "name": "BILL1",
                "partner_id": [15, "Vendor A"],
                "state": "posted",
                "amount_total": 20.0,
                "invoice_date": now[:10],
            }
        ]
        transport = _mock_transport(orders, bills)

        with _patch_transport(transport):
            body = self.api.get(REPORTING_URL).json()

        current = now[:7]
        entry = next(e for e in body["monthly_series"] if e["month"] == current)
        self.assertEqual(entry["po_count"], 1)
        self.assertEqual(entry["amount_total"], 100.0)
        self.assertEqual(entry["vendor_bill_count"], 1)

    def test_top_vendors_max5_desc_dan_vendor_code(self):
        Partner.objects.create(code="SUP-A", name="Vendor A", odoo_id=15)
        orders = [
            {
                "id": index,
                "name": f"PO{index}",
                "partner_id": [15, "Vendor A"],
                "state": "purchase",
                "amount_total": float(index),
                "date_order": "2026-10-01 00:00:00",
            }
            for index in range(1, 8)
        ]
        transport = _mock_transport(orders, [])

        with _patch_transport(transport):
            body = self.api.get(REPORTING_URL).json()

        top = body["top_vendors"]
        self.assertLessEqual(len(top), 5)
        self.assertEqual(top[0]["vendor_name"], "Vendor A")
        self.assertEqual(top[0]["vendor_code"], "SUP-A")
        amounts = [vendor["amount_total"] for vendor in top]
        self.assertEqual(amounts, sorted(amounts, reverse=True))

    def test_kosong_monthly_series_dan_top_vendors(self):
        transport = _mock_transport([], [])

        with _patch_transport(transport):
            body = self.api.get(REPORTING_URL).json()

        self.assertEqual(len(body["monthly_series"]), 6)
        self.assertTrue(all(entry["po_count"] == 0 for entry in body["monthly_series"]))
        self.assertEqual(body["top_vendors"], [])

