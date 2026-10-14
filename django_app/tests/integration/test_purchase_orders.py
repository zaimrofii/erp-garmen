"""Test endpoint purchase orders (F2 / B10) — `GET /api/v1/purchase/orders/`.

Read-only lewat Odoo transport; **test memakai mock** (tidak hit Odoo). Uji juga
fail-safe ``ERP_ADAPTER=null`` → 200 ``rows=[]``.

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_purchase_orders.py -q
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.auth.models import User
from master.models import Partner

ORDERS_URL = "/api/v1/purchase/orders/"

TOP_KEYS = {"rows", "total_count", "has_more", "next_cursor"}
ROW_KEYS = {"id", "name", "partner_name", "state", "date_order", "date_planned", "amount_total", "vendor_code", "lines"}

ORDERS = [
    {
        "id": 1,
        "name": "PO0001",
        "partner_id": [15, "PT Supplier A"],
        "state": "purchase",
        "date_order": "2026-10-06 10:00:00",
        "date_planned": "2026-10-10 10:00:00",
        "amount_total": 1500000.0,
    },
    {
        "id": 2,
        "name": "PO0002",
        "partner_id": [16, "CV Supplier B"],
        "state": "done",
        "date_order": "2026-10-07 09:00:00",
        "date_planned": "2026-10-12 09:00:00",
        "amount_total": 250000.0,
    },
]


def _mock_transport(orders=None):
    transport = MagicMock()
    transport.fetch_purchase_orders.return_value = orders if orders is not None else []
    return transport


def _patch_transport(transport):
    return patch(
        "integrations.erp_sync.monitoring.get_transport", return_value=transport
    )


class PurchaseOrdersAuthTests(TestCase):
    def test_anonim_403(self):
        self.assertEqual(APIClient().get(ORDERS_URL).status_code, 403)


class PurchaseOrdersTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="pur-orders", password="x")

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def test_shape_listpage_lengkap(self):
        transport = _mock_transport(ORDERS)

        with _patch_transport(transport):
            body = self.api.get(ORDERS_URL).json()

        self.assertEqual(set(body), TOP_KEYS)
        self.assertEqual(body["total_count"], 2)
        self.assertFalse(body["has_more"])
        self.assertIsNone(body["next_cursor"])
        row = body["rows"][0]
        self.assertEqual(set(row), ROW_KEYS)
        self.assertEqual(row["name"], "PO0001")
        self.assertEqual(row["partner_name"], "PT Supplier A")
        self.assertEqual(row["state"], "purchase")
        self.assertEqual(row["amount_total"], 1500000.0)
        # Tanpa param state → ketiga state diminta.
        transport.fetch_purchase_orders.assert_called_once_with(
            states=("draft", "purchase", "done")
        )

    def test_filter_state(self):
        transport = _mock_transport([ORDERS[0]])

        with _patch_transport(transport):
            self.api.get(ORDERS_URL, {"state": "draft"})

        transport.fetch_purchase_orders.assert_called_once_with(states=("draft",))

    def test_state_invalid_400(self):
        transport = _mock_transport([])

        with _patch_transport(transport):
            response = self.api.get(ORDERS_URL, {"state": "cancel"})

        self.assertEqual(response.status_code, 400)
        transport.fetch_purchase_orders.assert_not_called()

    @override_settings(ERP_ADAPTER="null")
    def test_erp_adapter_null_fail_safe(self):
        # Tanpa patch: transport null (client None) → fetch_* return [] (bukan error).
        response = self.api.get(ORDERS_URL)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["rows"], [])
        self.assertEqual(body["total_count"], 0)
        self.assertFalse(body["has_more"])


class PurchaseOrdersGapTests(TestCase):
    """G5 (aditif) — vendor_code + lines."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="po-gap", password="x")

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def test_vendor_code_dari_partner_master(self):
        Partner.objects.create(code="SUP-A", name="PT Supplier A", odoo_id=15)
        transport = _mock_transport([ORDERS[0]])
        transport.fetch_purchase_order_lines.return_value = []

        with _patch_transport(transport):
            body = self.api.get(ORDERS_URL).json()

        self.assertEqual(body["rows"][0]["vendor_code"], "SUP-A")

    def test_lines_kosong_kalau_po_tanpa_line(self):
        transport = _mock_transport([ORDERS[0]])
        transport.fetch_purchase_order_lines.return_value = []

        with _patch_transport(transport):
            body = self.api.get(ORDERS_URL).json()

        self.assertEqual(body["rows"][0]["lines"], [])

    def test_lines_terisi_dengan_subtotal(self):
        transport = _mock_transport([ORDERS[0]])
        transport.fetch_purchase_order_lines.return_value = [
            {
                "id": 1,
                "order_id": [1, "PO0001"],
                "product_id": [101, "Kaos Polos"],
                "product_qty": 100,
                "price_unit": 25000.0,
            }
        ]

        with _patch_transport(transport):
            body = self.api.get(ORDERS_URL).json()

        line = body["rows"][0]["lines"][0]
        self.assertEqual(line["description"], "Kaos Polos")
        self.assertEqual(line["qty"], 100)
        self.assertEqual(line["price_unit"], 25000.0)
        self.assertEqual(line["subtotal"], 2500000.0)

