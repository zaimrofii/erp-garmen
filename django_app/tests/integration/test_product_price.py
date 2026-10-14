"""Test H3.5 — Product Price (`/api/v1/master/products/<id>/price|price-history/`).

Cakupan: update harga lewat endpoint khusus (`sale_price`/`cost_price` ≥ 0, **0
diizinkan**, negatif ditolak), `price_updated_at` terisi, audit granular
`master.update_price` (metadata nilai lama vs baru) + `master.update` saat lewat PUT
produk umum, `SyncRecord` MASTER_PUSH + enqueue, riwayat harga (paginasi §3), pull
harga dari Odoo (**hanya bila harga MES masih 0** — bootstap, MES = source of truth),
dan non-breaking H1.1 (PUT produk + form) & H2.1/H2.2 (auto-isi `price_unit`).

Prinsip yang di-pin: **MES = source of truth master**. Pull tidak boleh menimpa harga
MES (beat `sync-master-*` harian) — hanya mengisi bila masih 0.
"""

from __future__ import annotations

from decimal import Decimal
from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from core.audit.models import AuditLog
from core.auth.models import Role, User
from integrations.erp_sync.models import SyncRecord, SyncResource, SyncStage, SyncStatus
from integrations.erp_sync.tasks_master import _product_defaults
from master.models import Product
from master.services import ACTION_UPDATE_PRICE, RESOURCE, price_history

PRODUCTS_URL = "/api/v1/master/products/"
ENQUEUE = "master.services.push_master_product.apply_async"
RESOURCE_STAGE = dict(resource=SyncResource.MASTER_PRODUCT.value, stage=SyncStage.MASTER_PUSH)


def price_url(product_id: int) -> str:
    """URL endpoint harga produk (H3.5)."""
    return f"{PRODUCTS_URL}{product_id}/price/"


def history_url(product_id: int) -> str:
    """URL riwayat harga produk (H3.5)."""
    return f"{PRODUCTS_URL}{product_id}/price-history/"


class ProductPriceBase(TestCase):
    """Basis bersama: produk + user admin/simulator."""

    @classmethod
    def setUpTestData(cls):
        cls.product = Product.objects.create(
            code="KAIN-COTTON",
            name="Kain Cotton",
            sale_price=Decimal("50000.00"),
            cost_price=Decimal("30000.00"),
            odoo_id=89,
        )
        cls.product_no_odoo = Product.objects.create(code="KAIN-BARU", name="Kain Baru")
        cls.admin = User.objects.create_user(  # noqa: S106 - kredensial test
            username="admin-h35",
            password="rahasia123",
            role=Role.objects.get(code=Role.Code.ADMIN),
        )
        cls.operator = User.objects.create_user(username="op-h35", password="x")  # noqa: S106

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.admin)

    def as_user(self, user):
        """Client terautentikasi (anonim bila ``user`` None)."""
        client = APIClient()
        if user is not None:
            client.force_authenticate(user)

        return client

    def price_logs(self, product=None):
        """AuditLog perubahan harga untuk satu produk (terbaru dulu)."""
        target = product or self.product

        return AuditLog.objects.filter(
            resource=RESOURCE, resource_id=str(target.pk), action=ACTION_UPDATE_PRICE
        ).order_by("-id")


class ProductPriceUpdateTests(ProductPriceBase):
    """`PUT /master/products/<id>/price/` — update harga + audit + push."""

    def test_update_sale_price_ok_set_price_updated_at(self):
        with mock.patch(ENQUEUE, return_value=mock.Mock(id="task-price-1")) as enqueue:
            response = self.api.put(price_url(self.product.pk), {"sale_price": "75000"}, format="json")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["sale_price"], 75000.0)
        self.assertEqual(body["cost_price"], 30000.0)
        self.assertEqual(body["task_id"], "task-price-1")
        self.assertTrue(body["queued"])
        self.assertIsNotNone(body["price_updated_at"])
        enqueue.assert_called_once()

        self.product.refresh_from_db()
        self.assertEqual(self.product.sale_price, Decimal("75000.00"))
        self.assertIsNotNone(self.product.price_updated_at)

    def test_update_cost_price_ok_dan_harga_nol_diizinkan(self):
        pertama = self.api.put(price_url(self.product.pk), {"cost_price": "0"}, format="json")
        kedua = self.api.put(price_url(self.product.pk), {"sale_price": "0"}, format="json")

        self.assertEqual(pertama.status_code, 200)
        self.assertEqual(pertama.json()["cost_price"], 0.0)
        self.assertEqual(kedua.status_code, 200)
        self.assertEqual(kedua.json()["sale_price"], 0.0)

    def test_update_harga_negatif_400(self):
        before = Product.objects.get(pk=self.product.pk).sale_price

        response = self.api.put(price_url(self.product.pk), {"sale_price": "-1"}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("negatif", response.json()["detail"])
        self.assertEqual(Product.objects.get(pk=self.product.pk).sale_price, before)

    def test_update_harga_bukan_angka_400_dan_tanpa_field_400(self):
        bukan_angka = self.api.put(price_url(self.product.pk), {"sale_price": "mahal"}, format="json")
        kosong = self.api.put(price_url(self.product.pk), {}, format="json")

        self.assertEqual(bukan_angka.status_code, 400)
        self.assertIn("angka", bukan_angka.json()["detail"])
        self.assertEqual(kosong.status_code, 400)
        self.assertIn("minimal satu", kosong.json()["detail"])

    def test_update_harga_sama_tidak_menulis_audit(self):
        response = self.api.put(
            price_url(self.product.pk), {"sale_price": "50000.00"}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["task_id"])
        self.assertEqual(self.price_logs().count(), 0)

    def test_audit_granular_nilai_lama_vs_baru(self):
        self.api.put(price_url(self.product.pk), {"sale_price": "61000"}, format="json")

        log = self.price_logs().first()
        self.assertIsNotNone(log)
        self.assertEqual(log.action, "master.update_price")
        self.assertEqual(log.metadata["source"], "price_endpoint")
        self.assertEqual(log.metadata["fields"], ["sale_price"])
        self.assertEqual(log.metadata["before"], {"sale_price": "50000.00"})
        self.assertEqual(log.metadata["after"], {"sale_price": "61000.00"})

    def test_sync_record_master_push_ditulis_dan_diarm(self):
        with mock.patch(ENQUEUE, return_value=mock.Mock(id="task-price-2")):
            self.api.put(price_url(self.product.pk), {"sale_price": "51000"}, format="json")

        record = SyncRecord.objects.get(**RESOURCE_STAGE)
        self.assertEqual(record.status, SyncStatus.PENDING)
        self.assertEqual(record.payload["sale_price"], 51000.0)
        self.assertEqual(record.payload["cost_price"], 30000.0)

    def test_produk_tidak_ada_404_dan_anonim_403(self):
        hilang = self.api.put(price_url(999_999), {"sale_price": "1"}, format="json")
        anonim = self.as_user(None).put(price_url(self.product.pk), {"sale_price": "1"}, format="json")

        self.assertEqual(hilang.status_code, 404)
        self.assertEqual(anonim.status_code, 403)

    def test_operator_tanpa_role_tidak_boleh_menulis(self):
        response = self.as_user(self.operator).put(
            price_url(self.product.pk), {"sale_price": "12345"}, format="json"
        )

        self.assertEqual(response.status_code, 403)

    def test_put_produk_umum_dengan_harga_juga_menulis_audit_harga(self):
        response = self.api.put(
            PRODUCTS_URL + f"{self.product.pk}/",
            {"sale_price": "52000", "name": "Kain Cotton Premium"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        log = self.price_logs().first()
        self.assertIsNotNone(log)
        self.assertEqual(log.metadata["source"], "product_update")
        self.assertEqual(log.metadata["after"], {"sale_price": "52000.00"})
        # Audit umum H1.1 tetap ditulis (non-breaking).
        self.assertTrue(
            AuditLog.objects.filter(
                resource=RESOURCE, resource_id=str(self.product.pk), action="master.update"
            ).exists()
        )


class ProductPriceHistoryTests(ProductPriceBase):
    """`GET /master/products/<id>/price-history/` — riwayat dari AuditLog."""

    def test_riwayat_kosong_envelope_sek3(self):
        response = self.api.get(history_url(self.product.pk))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), {"rows", "total_count", "has_more", "next_cursor"})
        self.assertEqual(body["total_count"], 0)
        self.assertEqual(body["rows"], [])

    def test_riwayat_terisi_terbaru_dulu_dengan_diff(self):
        self.api.put(price_url(self.product.pk), {"sale_price": "60000"}, format="json")
        self.api.put(price_url(self.product.pk), {"cost_price": "40000"}, format="json")

        body = self.api.get(history_url(self.product.pk)).json()

        self.assertEqual(body["total_count"], 2)
        terbaru = body["rows"][0]
        self.assertEqual(terbaru["fields"], ["cost_price"])
        self.assertEqual(terbaru["before"], {"cost_price": "30000.00"})
        self.assertEqual(terbaru["after"], {"cost_price": "40000.00"})
        self.assertEqual(body["rows"][1]["fields"], ["sale_price"])

    def test_riwayat_paginasi_dan_limit_invalid(self):
        for nilai in ("60000", "61000", "62000"):
            self.api.put(price_url(self.product.pk), {"sale_price": nilai}, format="json")

        halaman = self.api.get(history_url(self.product.pk), {"limit": 2, "cursor": 0}).json()

        self.assertEqual(len(halaman["rows"]), 2)
        self.assertTrue(halaman["has_more"])
        self.assertEqual(halaman["next_cursor"], 2)

        invalid = self.api.get(history_url(self.product.pk), {"limit": 0})
        self.assertEqual(invalid.status_code, 400)

    def test_riwayat_produk_tidak_ada_404_dan_anonim_403(self):
        hilang = self.api.get(history_url(999_999))
        anonim = self.as_user(None).get(history_url(self.product.pk))

        self.assertEqual(hilang.status_code, 404)
        self.assertEqual(anonim.status_code, 403)


class ProductPricePullTests(ProductPriceBase):
    """Pull harga Odoo → MES: **hanya bila harga MES masih 0** (bootstap)."""

    def test_pull_mengisi_harga_kosong(self):
        defaults = _product_defaults(
            {
                "id": 77,
                "default_code": "PRODUK-BARU",
                "name": "Produk Baru",
                "active": True,
                "list_price": 12500.5,
                "standard_price": 8000,
            }
        )

        self.assertEqual(defaults["sale_price"], Decimal("12500.50"))
        self.assertEqual(defaults["cost_price"], Decimal("8000.00"))

    def test_pull_tidak_menimpa_harga_mes_yang_sudah_ada(self):
        defaults = _product_defaults(
            {
                "id": self.product.odoo_id,
                "default_code": self.product.code,
                "name": self.product.name,
                "active": True,
                "list_price": 1.0,
                "standard_price": 0.0,
            }
        )

        self.assertNotIn("sale_price", defaults)
        self.assertNotIn("cost_price", defaults)

    def test_pull_sebagian_menimpa_hanya_yang_nol(self):
        # Kasus data dev: sale_price terisi, cost_price 0 -> hanya cost_price yang diisi.
        produk = Product.objects.create(
            code="KAIN-HARGA-SEBAGIAN",
            name="Kain Harga Sebagian",
            sale_price=Decimal("40000.00"),
            cost_price=Decimal("0.00"),
            odoo_id=91,
        )

        defaults = _product_defaults(
            {
                "id": produk.odoo_id,
                "default_code": produk.code,
                "name": produk.name,
                "active": True,
                "list_price": 999999.0,
                "standard_price": 33000,
            }
        )

        self.assertNotIn("sale_price", defaults)
        self.assertEqual(defaults["cost_price"], Decimal("33000.00"))

    def test_pull_harga_tidak_valid_dilewati_tanpa_galat(self):
        defaults = _product_defaults(
            {
                "id": 78,
                "default_code": "ANEh",
                "name": "Aneh",
                "active": True,
                "list_price": "bukan-angka",
                "standard_price": None,
            }
        )

        self.assertNotIn("sale_price", defaults)
        self.assertNotIn("cost_price", defaults)
        self.assertEqual(defaults["code"], "ANEh")

    def test_pull_tanpa_field_harga_tetap_aman(self):
        defaults = _product_defaults({"id": 79, "default_code": "MINIMAL", "name": "Minimal"})

        self.assertNotIn("sale_price", defaults)
        self.assertNotIn("cost_price", defaults)


class ProductPriceNonBreakingTests(ProductPriceBase):
    """Konsumen existing tetap jalan (H1.1 PUT/form, H2.1 & H2.2 auto-isi harga, push H1.1)."""

    def test_put_produk_h1_1_tetap_200_dan_field_lama_utuh(self):
        with mock.patch(ENQUEUE, return_value=mock.Mock(id="task-umum")):
            response = self.api.put(
                PRODUCTS_URL + f"{self.product.pk}/",
                {"name": "Kain Cotton Baru", "weight": "0.2"},
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["name"], "Kain Cotton Baru")
        self.assertEqual(body["sale_price"], 50000.0)
        self.assertIn("price_updated_at", body)

    def test_product_row_memuat_price_updated_at(self):
        body = self.api.get(PRODUCTS_URL + f"{self.product.pk}/").json()

        self.assertIn("price_updated_at", body)
        self.assertIsNone(body["price_updated_at"])

    def test_price_history_service_mengembalikan_total(self):
        self.api.put(price_url(self.product.pk), {"sale_price": "70000"}, format="json")

        history = price_history(self.product, limit=10, offset=0)

        self.assertEqual(history["total_count"], 1)
        self.assertEqual(history["rows"][0]["after"], {"sale_price": "70000.00"})

    def test_order_line_price_unit_auto_fill_masih_dari_sale_price(self):
        from apps_industry.garment.services.order_services import validate_line_payload

        values, error = validate_line_payload({"product_id": self.product.pk, "qty": 2})

        self.assertIsNone(error)
        self.assertEqual(values["price_unit"], Decimal("50000.00"))

    def test_purchase_order_line_auto_fill_masih_dari_cost_price(self):
        from apps_industry.garment.services.purchase_order_services import (
            validate_line_payload as po_validate_line,
        )

        values, error = po_validate_line({"product_id": self.product.pk, "qty": 3})

        self.assertIsNone(error)
        self.assertEqual(values["price_unit"], Decimal("30000.00"))

    def test_push_payload_produk_masih_memuat_harga(self):
        from integrations.erp_sync.tasks_master_push import product_payload

        payload = product_payload(self.product)

        self.assertEqual(payload["sale_price"], 50000.0)
        self.assertEqual(payload["cost_price"], 30000.0)

