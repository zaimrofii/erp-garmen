"""Test audit produk tanpa ``odoo_id`` (fase I8.8) — service + endpoint DRF.

Cakupan:

* service ``missing_odoo_id`` — hitung produk tanpa ``odoo_id`` (produk yang
  sudah punya ``odoo_id`` tidak ikut) dan daftarnya dipotong di ``PRODUCT_LIMIT``
  (``count`` tetap jumlah sesungguhnya);
* service ``used_in_open_bundles`` — hanya produk yang dipakai bundle
  **terbuka** (state bukan ``DONE``/``DRAFT``): produk tanpa bundle, hanya bundle
  ``DONE``, atau hanya bundle ``DRAFT`` tidak ikut;
* endpoint ``GET /api/v1/audit/products-missing-odoo-id/`` → 200 + struktur
  ``{count, products, used_in_open_bundles}``; anonim → **403**; ``POST`` → **405**.

Read-only: tidak ada transport/Odoo di jalur ini (service hanya query MES).
"""

from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.tests.factories import (
    make_bundle,
    make_order_line,
    make_work_order,
)
from core.auth.models import User
from integrations.erp_sync.services.product_audit import ProductAuditService
from master.models import Product

LIMIT_TARGET = "integrations.erp_sync.services.product_audit.PRODUCT_LIMIT"
URL = "/api/v1/audit/products-missing-odoo-id/"


def bundle_for(product, state):
    """Bundle untuk ``product`` dengan ``state`` tertentu (WO/Line otomatis)."""
    return make_bundle(
        work_order=make_work_order(order_line=make_order_line(product=product)),
        state=state,
    )


class ProductAuditServiceTests(TestCase):
    """3 produk tanpa ``odoo_id`` (1 dipakai bundle CUTTING) + 1 sudah tersinkron."""

    @classmethod
    def setUpTestData(cls):
        cls.product_open = Product.objects.create(code="TS-AUD-1", name="Kaos Audit")
        cls.product_done = Product.objects.create(code="TS-AUD-2", name="Kaos Done")
        cls.product_idle = Product.objects.create(code="TS-AUD-3", name="Kaos Idle")
        cls.product_synced = Product.objects.create(
            code="TS-AUD-4", name="Kaos Synced", odoo_id=801
        )

        cls.bundle_open = bundle_for(cls.product_open, "CUTTING")
        cls.bundle_done = bundle_for(cls.product_done, "DONE")

    # ------------------------------------------------------- missing_odoo_id
    def test_missing_odoo_id_menghitung_produk_tanpa_odoo_id(self):
        result = ProductAuditService().missing_odoo_id()

        self.assertEqual(result["count"], 3)
        self.assertEqual(result["limit"], 100)
        self.assertEqual(
            [row["code"] for row in result["products"]],
            ["TS-AUD-1", "TS-AUD-2", "TS-AUD-3"],
        )
        self.assertEqual(set(result["products"][0]), {"id", "code", "name"})
        self.assertEqual(result["products"][0]["name"], "Kaos Audit")

    def test_produk_sudah_punya_odoo_id_tidak_ikut(self):
        result = ProductAuditService().missing_odoo_id()

        codes = [row["code"] for row in result["products"]]
        ids = [row["id"] for row in result["products"]]
        self.assertNotIn(self.product_synced.code, codes)
        self.assertNotIn(self.product_synced.pk, ids)

    def test_missing_odoo_id_dipotong_di_limit(self):
        with patch(LIMIT_TARGET, 2):
            result = ProductAuditService().missing_odoo_id()

        self.assertEqual(result["count"], 3)  # jumlah sesungguhnya
        self.assertEqual(result["limit"], 2)
        self.assertEqual(len(result["products"]), 2)

    # -------------------------------------------------- used_in_open_bundles
    def test_used_in_open_bundles_hanya_bundle_terbuka(self):
        result = ProductAuditService().used_in_open_bundles()

        self.assertEqual(result["count"], 1)
        self.assertEqual([row["code"] for row in result["products"]], ["TS-AUD-1"])

    def test_bundle_done_dan_tanpa_bundle_tidak_ikut(self):
        result = ProductAuditService().used_in_open_bundles()

        codes = [row["code"] for row in result["products"]]
        self.assertNotIn(self.product_done.code, codes)  # hanya bundle DONE
        self.assertNotIn(self.product_idle.code, codes)  # tanpa bundle sama sekali

    def test_bundle_draft_tidak_dianggap_terbuka(self):
        bundle_for(self.product_idle, "DRAFT")

        result = ProductAuditService().used_in_open_bundles()

        self.assertEqual([row["code"] for row in result["products"]], ["TS-AUD-1"])

    # ------------------------------------------------------------------ audit
    def test_audit_menggabungkan_dua_potret(self):
        result = ProductAuditService().audit()

        self.assertEqual(set(result), {"count", "products", "used_in_open_bundles"})
        self.assertEqual(result["count"], 3)
        self.assertEqual(len(result["products"]), 3)
        self.assertEqual(result["used_in_open_bundles"]["count"], 1)
        self.assertEqual(
            set(result["used_in_open_bundles"]), {"count", "limit", "products"}
        )


class ProductAuditEndpointTests(TestCase):
    """1 produk tanpa ``odoo_id`` yang dipakai bundle SEWING (terbuka)."""

    @classmethod
    def setUpTestData(cls):
        cls.product = Product.objects.create(
            code="TS-AUD-API-1", name="Kaos API Audit"
        )
        cls.bundle = bundle_for(cls.product, "SEWING")

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(
            user=User.objects.create_user(
                username="auditor-produk",
                password="rahasia",  # noqa: S106 - kredensial test
            )
        )

    def test_get_happy_path_struktur(self):
        response = self.api.get(URL)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), {"count", "products", "used_in_open_bundles"})
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["products"][0]["code"], "TS-AUD-API-1")
        self.assertEqual(body["products"][0]["name"], "Kaos API Audit")
        self.assertEqual(body["used_in_open_bundles"]["count"], 1)
        self.assertEqual(
            body["used_in_open_bundles"]["products"][0]["id"], self.product.pk
        )

    def test_get_tanpa_auth_403(self):
        response = APIClient().get(URL)

        self.assertEqual(response.status_code, 403)

    def test_post_method_tidak_diizinkan_405(self):
        response = self.api.post(URL)

        self.assertEqual(response.status_code, 405)
