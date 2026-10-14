"""Test endpoint purchase vendors (F1 / B12) — `GET /api/v1/purchase/vendors/`.

Read-only dari `master.Partner` (cache). ``IsAuthenticated`` → 403.

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_purchase_vendors.py -q
"""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from core.auth.models import User
from master.models import Partner

VENDORS_URL = "/api/v1/purchase/vendors/"

TOP_KEYS = {"rows", "total_count", "has_more", "next_cursor"}
ROW_KEYS = {"id", "name", "odoo_id", "email", "phone", "city", "is_customer", "is_vendor"}


class PurchaseVendorsAuthTests(TestCase):
    def test_anonim_403(self):
        self.assertEqual(APIClient().get(VENDORS_URL).status_code, 403)


class PurchaseVendorsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="pur-vend", password="x")

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def test_shape_listpage_lengkap(self):
        Partner.objects.create(
            code="V-001",
            name="PT Supplier A",
            odoo_id=15,
            email="supplier@example.com",
            phone="+62 812",
            city="Solo",
            is_customer=False,
            is_vendor=True,
        )

        body = self.api.get(VENDORS_URL).json()

        self.assertEqual(set(body), TOP_KEYS)
        self.assertEqual(body["total_count"], 1)
        self.assertFalse(body["has_more"])
        self.assertIsNone(body["next_cursor"])
        row = body["rows"][0]
        self.assertEqual(set(row), ROW_KEYS)
        self.assertEqual(row["name"], "PT Supplier A")
        self.assertEqual(row["odoo_id"], 15)
        # H1.6: field itu KINI ada di model → nilai nyata (sebelumnya selalu null).
        self.assertEqual(row["email"], "supplier@example.com")
        self.assertEqual(row["phone"], "+62 812")
        self.assertEqual(row["city"], "Solo")
        self.assertIs(row["is_customer"], False)
        self.assertIs(row["is_vendor"], True)

    def test_field_kosong_dikembalikan_null(self):
        """Field teks yang belum diisi → ``null`` (bukan string kosong)."""
        Partner.objects.create(code="C-001", name="Toko Retail", is_customer=True)

        row = self.api.get(VENDORS_URL).json()["rows"][0]

        self.assertIsNone(row["email"])
        self.assertIsNone(row["phone"])
        self.assertIsNone(row["city"])

    def test_db_kosong(self):
        body = self.api.get(VENDORS_URL).json()

        self.assertEqual(body["rows"], [])
        self.assertEqual(body["total_count"], 0)

    def test_dua_partner_urut_nama(self):
        Partner.objects.create(code="P-002", name="Beta Corp", odoo_id=102)
        Partner.objects.create(code="P-001", name="Alpha Corp", odoo_id=101)

        body = self.api.get(VENDORS_URL).json()

        self.assertEqual(body["total_count"], 2)
        self.assertEqual([row["name"] for row in body["rows"]], ["Alpha Corp", "Beta Corp"])
        self.assertEqual(body["rows"][0]["odoo_id"], 101)

    def test_search_q_match_name(self):
        Partner.objects.create(code="V-001", name="PT Supplier A")
        Partner.objects.create(code="C-001", name="Toko Retail")

        body = self.api.get(VENDORS_URL, {"q": "supplier"}).json()

        self.assertEqual(body["total_count"], 1)
        self.assertEqual(body["rows"][0]["name"], "PT Supplier A")

    def test_limit_tidak_valid_400(self):
        self.assertEqual(self.api.get(VENDORS_URL, {"limit": 0}).status_code, 400)
