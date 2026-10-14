"""Test endpoint inventory products (F1 / B7) — `GET /api/v1/inventory/products/`.

Read-only dari `master.Product` + stok WIP/FG via `TwoStageAggregator`.
``IsAuthenticated`` → 403.

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_inventory_products.py -q
"""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.tests.factories import (
    make_bundle,
    make_order_line,
    make_product,
    make_work_center,
    make_work_order,
)
from core.auth.models import User
from master.models import Product

PRODUCTS_URL = "/api/v1/inventory/products/"

TOP_KEYS = {"rows", "total_count", "has_more", "next_cursor"}
ROW_KEYS = {"id", "code", "name", "odoo_id", "stock_qty"}


class InventoryProductsAuthTests(TestCase):
    def test_anonim_403(self):
        self.assertEqual(APIClient().get(PRODUCTS_URL).status_code, 403)


class InventoryProductsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="inv-prod", password="x")

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def test_shape_listpage_lengkap(self):
        make_product(code="TS-001", name="Kaos Polos")

        body = self.api.get(PRODUCTS_URL).json()

        self.assertEqual(set(body), TOP_KEYS)
        self.assertEqual(body["total_count"], 1)
        self.assertFalse(body["has_more"])
        self.assertIsNone(body["next_cursor"])
        row = body["rows"][0]
        self.assertEqual(set(row), ROW_KEYS)
        self.assertEqual(row["code"], "TS-001")
        self.assertEqual(row["name"], "Kaos Polos")
        self.assertEqual(row["stock_qty"], 0)  # tanpa bundle → 0

    def test_db_kosong(self):
        body = self.api.get(PRODUCTS_URL).json()

        self.assertEqual(body["rows"], [])
        self.assertEqual(body["total_count"], 0)

    def test_dua_produk_field_benar(self):
        Product.objects.create(code="P-001", name="Produk A", odoo_id=101)
        Product.objects.create(code="P-002", name="Produk B", odoo_id=102)

        body = self.api.get(PRODUCTS_URL).json()

        self.assertEqual(body["total_count"], 2)
        self.assertEqual([row["code"] for row in body["rows"]], ["P-001", "P-002"])
        self.assertEqual(body["rows"][0]["odoo_id"], 101)
        self.assertEqual(body["rows"][0]["name"], "Produk A")

    def test_search_q_match_name(self):
        make_product(code="TS-001", name="Kaos Polos")
        make_product(code="PO-001", name="Polo Shirt")

        body = self.api.get(PRODUCTS_URL, {"q": "kaos"}).json()

        self.assertEqual(body["total_count"], 1)
        self.assertEqual(body["rows"][0]["name"], "Kaos Polos")


class InventoryProductsStockTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="inv-stock", password="x")

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def test_stock_qty_wip_dari_bundle(self):
        product = make_product(code="TS-STOCK", name="Kaos Stok")
        work_center = make_work_center(code="SEW-ST")
        order_line = make_order_line(product=product, qty=20)
        work_order = make_work_order(order_line=order_line)
        make_bundle(
            work_order=work_order,
            code="B-ST1",
            qty=7,
            state="SEWING",
            current_work_center=work_center,
        )

        body = self.api.get(PRODUCTS_URL, {"q": "TS-STOCK"}).json()

        self.assertEqual(body["total_count"], 1)
        self.assertEqual(body["rows"][0]["stock_qty"], 7)

    def test_stock_qty_nol_untuk_produk_lain(self):
        product_aktif = make_product(code="TS-AKTIF", name="Aktif")
        make_product(code="TS-DIAM", name="Diam")
        work_center = make_work_center(code="SEW-ST2")
        order_line = make_order_line(product=product_aktif, qty=20)
        work_order = make_work_order(order_line=order_line)
        make_bundle(
            work_order=work_order,
            qty=5,
            state="SEWING",
            current_work_center=work_center,
        )

        body = self.api.get(PRODUCTS_URL).json()

        per_code = {row["code"]: row["stock_qty"] for row in body["rows"]}
        self.assertEqual(per_code["TS-AKTIF"], 5)
        self.assertEqual(per_code["TS-DIAM"], 0)
