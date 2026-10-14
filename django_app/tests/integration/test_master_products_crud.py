"""Test CRUD master Product — ``/api/v1/master/products/`` (H1.1).

Cakupan: list (pagination/filter/search), detail, create, update, **soft delete**
(``active=False`` — baris tetap di DB), izin (anon **403**, role bukan penulis
**403**, admin/purchasing boleh), validasi **400**, serta kewajiban H1.1:
``SyncRecord`` (``master.product``/``MASTER_PUSH``) + ``AuditLog``
(``master.create``/``master.update``/``master.delete``) setiap POST/PUT/DELETE.

Catatan:
  * push Odoo di-enqueue asinkron → ``apply_async`` di-patch (pola
    ``integrations/erp_sync/tests/test_sync_endpoint.py``) supaya test tidak
    menyentuh broker/worker;
  * ``DELETE`` = soft delete: yang berubah hanya ``is_active``;
  * setiap baris response memuat ``odoo_id`` (frontend memakainya untuk debug sync).

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_master_products_crud.py -q
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.audit.models import AuditLog
from core.auth.models import Role, User
from integrations.erp_sync.models import SyncRecord, SyncResource, SyncStage, SyncStatus
from integrations.erp_sync.tasks_master_push import push_master_product
from master.models import Product, UoM

PRODUCTS_URL = "/api/v1/master/products/"
ENVELOPE_KEYS = {"rows", "total_count", "has_more", "next_cursor"}
ROW_KEYS = {
    "id",
    "code",
    "name",
    "category",
    "uom_id",
    "uom_code",
    "sale_price",
    "cost_price",
    # H3.5 — jejak audit perubahan harga (aditif).
    "price_updated_at",
    "weight",
    "image_url",
    "active",
    "odoo_id",
    "created_at",
    "updated_at",
}
#: Path patch enqueue task (service menulis SyncRecord lalu enqueue).
ENQUEUE = "master.services.push_master_product.apply_async"


def detail_url(pk: int) -> str:
    """URL detail produk."""
    return f"{PRODUCTS_URL}{pk}/"


class MasterProductsCrudTests(TestCase):
    """GET/POST/PUT/DELETE + idempotensi (SyncRecord) + audit + izin."""

    @classmethod
    def setUpTestData(cls):
        """3 user: admin (ADMIN), purchasing (PURCHASING), operator (OPERATOR)."""
        # Role ADMIN/OPERATOR di-seed `core_auth.0002`; PURCHASING di `core_auth.0004` (H1.1).
        cls.admin_role = Role.objects.get(code=Role.Code.ADMIN)
        cls.purchasing_role = Role.objects.get(code=Role.Code.PURCHASING)
        cls.operator_role = Role.objects.get(code=Role.Code.OPERATOR)

        cls.admin = User.objects.create_user(
            username="admin-master",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=cls.admin_role,
        )
        cls.purchasing = User.objects.create_user(
            username="beli-master",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=cls.purchasing_role,
        )
        cls.operator = User.objects.create_user(
            username="op-master",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=cls.operator_role,
        )

    def setUp(self):
        """Klien admin (utama) + klien operator (uji 403)."""
        self.api = APIClient()
        self.api.force_authenticate(self.admin)
        self.operator_api = APIClient()
        self.operator_api.force_authenticate(self.operator)

    # ------------------------------------------------------------------ helper
    def post_product(self, body: dict, client=None):
        """POST produk dengan enqueue task di-patch → ``(response, mock)``."""
        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-master-1")) as enqueue:
            response = (client or self.api).post(PRODUCTS_URL, body, format="json")

        return response, enqueue

    def put_product(self, pk: int, body: dict, client=None):
        """PUT produk dengan enqueue task di-patch → ``(response, mock)``."""
        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-master-2")) as enqueue:
            response = (client or self.api).put(detail_url(pk), body, format="json")

        return response, enqueue

    def delete_product(self, pk: int, client=None):
        """DELETE produk dengan enqueue task di-patch → ``(response, mock)``."""
        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-master-3")) as enqueue:
            response = (client or self.api).delete(detail_url(pk))

        return response, enqueue

    # -------------------------------------------------------------------- GET
    def test_list_products_pagination(self):
        """ListPage: ``limit``/``cursor`` offset-based + ``has_more``/``next_cursor``."""
        for index in range(3):
            Product.objects.create(code=f"TS-{index:03d}", name=f"Kaos {index}")

        response = self.api.get(PRODUCTS_URL, {"limit": 2})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), ENVELOPE_KEYS)
        self.assertEqual(body["total_count"], 3)
        self.assertTrue(body["has_more"])
        self.assertEqual(body["next_cursor"], 2)
        self.assertEqual(len(body["rows"]), 2)
        self.assertEqual(set(body["rows"][0]), ROW_KEYS)
        self.assertEqual(body["rows"][0]["code"], "TS-000")
        self.assertIsNone(body["rows"][0]["odoo_id"])

        second = self.api.get(PRODUCTS_URL, {"limit": 2, "cursor": 2}).json()
        self.assertEqual(len(second["rows"]), 1)
        self.assertFalse(second["has_more"])
        self.assertIsNone(second["next_cursor"])

    def test_list_products_filter_category(self):
        """``?category=`` menyaring kategori; ``?active=`` menyaring status aktif."""
        Product.objects.create(code="K-001", name="Kain", category="Kain")
        Product.objects.create(code="B-001", name="Benang", category="Benang")
        Product.objects.create(
            code="K-002", name="Kain Mati", category="Kain", is_active=False
        )

        body = self.api.get(PRODUCTS_URL, {"category": "Kain"}).json()
        self.assertEqual([row["code"] for row in body["rows"]], ["K-001", "K-002"])

        active_only = self.api.get(PRODUCTS_URL, {"category": "Kain", "active": "true"}).json()
        self.assertEqual([row["code"] for row in active_only["rows"]], ["K-001"])
        self.assertTrue(active_only["rows"][0]["active"])

        inactive_only = self.api.get(PRODUCTS_URL, {"active": "false"}).json()
        self.assertEqual([row["code"] for row in inactive_only["rows"]], ["K-002"])

        invalid = self.api.get(PRODUCTS_URL, {"active": "kadang-kadang"})
        self.assertEqual(invalid.status_code, 400)

    def test_list_products_search(self):
        """``?search=`` mencari di ``code``, ``name``, dan ``category``."""
        Product.objects.create(code="TS-100", name="Kaos Polos", category="Kain")
        Product.objects.create(code="BJ-200", name="Baju Lengan", category="Atasan")

        by_code = self.api.get(PRODUCTS_URL, {"search": "TS-1"}).json()
        self.assertEqual([row["code"] for row in by_code["rows"]], ["TS-100"])

        by_name = self.api.get(PRODUCTS_URL, {"search": "lengan"}).json()
        self.assertEqual([row["code"] for row in by_name["rows"]], ["BJ-200"])

        by_category = self.api.get(PRODUCTS_URL, {"search": "atasan"}).json()
        self.assertEqual([row["code"] for row in by_category["rows"]], ["BJ-200"])

    def test_auth_required_403_anonymous(self):
        """Anonim: GET/POST/PUT/DELETE semuanya **403** (IsAuthenticated)."""
        product = Product.objects.create(code="TS-300", name="Kaos")
        anonymous = APIClient()

        self.assertEqual(anonymous.get(PRODUCTS_URL).status_code, 403)
        self.assertEqual(anonymous.get(detail_url(product.pk)).status_code, 403)
        self.assertEqual(
            anonymous.post(PRODUCTS_URL, {"code": "X", "name": "X"}, format="json").status_code,
            403,
        )
        self.assertEqual(
            anonymous.put(detail_url(product.pk), {"name": "X"}, format="json").status_code,
            403,
        )
        self.assertEqual(anonymous.delete(detail_url(product.pk)).status_code, 403)

    # --------------------------------------------------------------- POST create
    def test_create_product_ok(self):
        """POST admin → 201; field H1 lengkap; ``odoo_id`` null; task push di-enqueue."""
        uom = UoM.objects.create(code="PCS", name="Pieces")

        response, enqueue = self.post_product(
            {
                "code": "TS-500",
                "name": "Kaos Premium",
                "category": "Atasan",
                "uom_id": uom.pk,
                "sale_price": "15000.50",
                "cost_price": 9000,
                "weight": 0.25,
                "image_url": "https://cdn.klien.com/kaos.png",
                "active": True,
            }
        )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(set(body), ROW_KEYS | {"sync_record_id", "task_id", "queued"})
        self.assertEqual(body["code"], "TS-500")
        self.assertEqual(body["name"], "Kaos Premium")
        self.assertEqual(body["category"], "Atasan")
        self.assertEqual(body["uom_id"], uom.pk)
        self.assertEqual(body["uom_code"], "PCS")
        self.assertEqual(body["sale_price"], 15000.5)
        self.assertEqual(body["cost_price"], 9000.0)
        self.assertEqual(body["weight"], 0.25)
        self.assertEqual(body["image_url"], "https://cdn.klien.com/kaos.png")
        self.assertTrue(body["active"])
        self.assertIsNone(body["odoo_id"])
        self.assertEqual(body["task_id"], "task-master-1")
        self.assertTrue(body["queued"])

        product = Product.objects.get(pk=body["id"])
        self.assertEqual(product.name, "Kaos Premium")
        self.assertTrue(product.is_active)

        enqueue.assert_called_once()
        self.assertEqual(
            enqueue.call_args.kwargs["args"], [product.pk, body["sync_record_id"]]
        )

    def test_create_product_duplicate_code_400(self):
        """Kode duplikat (beda huruf besar/kecil sekalipun) → 400, tanpa baris baru."""
        Product.objects.create(code="TS-600", name="Kaos Awal")

        response, enqueue = self.post_product({"code": "ts-600", "name": "Kaos Duplikat"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("sudah dipakai", response.json()["detail"])
        self.assertEqual(Product.objects.filter(code__iexact="TS-600").count(), 1)
        enqueue.assert_not_called()

    def test_create_product_invalid_payload_400(self):
        """Validasi: code/name wajib, angka jangan negatif, uom harus ada, url http(s)."""
        cases = (
            ({"name": "Tanpa Kode"}, "code"),
            ({"code": "X-001"}, "name"),
            ({"code": "X-002", "name": "Harga", "sale_price": -1}, "sale_price"),
            ({"code": "X-003", "name": "Berat", "weight": "gemuk"}, "weight"),
            ({"code": "X-004", "name": "UoM", "uom_id": 999999}, "UoM"),
            ({"code": "X-005", "name": "URL", "image_url": "bukan-url"}, "image_url"),
            ({"code": "X-006", "name": "Aktif", "active": "kadang"}, "active"),
        )

        for body, needle in cases:
            with self.subTest(body=body):
                response, _ = self.post_product(body)
                self.assertEqual(response.status_code, 400)
                self.assertIn(needle, response.json()["detail"])

        self.assertEqual(Product.objects.count(), 0)

    # ------------------------------------------------------------ PUT / detail
    def test_update_product_ok(self):
        """PUT mengubah hanya field yang dikirim (200) + audit ``master.update``."""
        product = Product.objects.create(code="TS-700", name="Kaos Lama", category="Atasan")

        response, enqueue = self.put_product(
            product.pk, {"name": "Kaos Baru", "sale_price": "20000", "category": "Bawahan"}
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["name"], "Kaos Baru")
        self.assertEqual(body["sale_price"], 20000.0)
        self.assertEqual(body["category"], "Bawahan")
        self.assertEqual(body["code"], "TS-700")  # tidak dikirim -> tidak berubah
        self.assertEqual(body["cost_price"], 0.0)

        product.refresh_from_db()
        self.assertEqual(product.name, "Kaos Baru")
        self.assertEqual(str(product.sale_price), "20000.00")

        enqueue.assert_called_once()
        self.assertTrue(
            AuditLog.objects.filter(
                action="master.update",
                resource="master.product",
                resource_id=str(product.pk),
            ).exists()
        )

    def test_detail_and_missing_product_404(self):
        """GET detail → 200; id tak dikenal → 404 untuk GET/PUT/DELETE."""
        product = Product.objects.create(code="TS-800", name="Kaos Detail")

        detail = self.api.get(detail_url(product.pk))
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["id"], product.pk)
        self.assertEqual(set(detail.json()), ROW_KEYS)

        self.assertEqual(self.api.get(detail_url(999999)).status_code, 404)
        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-none")):
            self.assertEqual(
                self.api.put(detail_url(999999), {"name": "X"}, format="json").status_code,
                404,
            )
            self.assertEqual(self.api.delete(detail_url(999999)).status_code, 404)

    # ------------------------------------------------------------ DELETE (soft)
    def test_delete_product_soft_delete(self):
        """DELETE → 200 soft delete: ``active=False``, baris MASIH ada di DB."""
        product = Product.objects.create(code="TS-900", name="Kaos Dihapus")

        response, enqueue = self.delete_product(product.pk)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["id"], product.pk)
        self.assertTrue(body["deleted"])
        self.assertFalse(body["active"])

        product.refresh_from_db()
        self.assertFalse(product.is_active)
        self.assertTrue(Product.objects.filter(pk=product.pk).exists())

        # Detail masih terbaca (read-only) — produk nonaktif tidak hilang jejaknya.
        self.assertFalse(self.api.get(detail_url(product.pk)).json()["active"])
        enqueue.assert_called_once()

    # --------------------------------------------- idempotensi & audit (H1.1)
    def test_syncrecord_written_on_create(self):
        """POST → ``SyncRecord`` PENDING (``master.product`` / ``MASTER_PUSH``)."""
        response, _ = self.post_product(
            {"code": "TS-950", "name": "Kaos Sync", "sale_price": 1000}
        )
        product_id = response.json()["id"]

        record = SyncRecord.objects.get(
            resource=SyncResource.MASTER_PRODUCT.value,
            resource_id=str(product_id),
            stage=SyncStage.MASTER_PUSH.value,
        )
        self.assertEqual(record.status, SyncStatus.PENDING)
        self.assertEqual(record.payload["code"], "TS-950")
        self.assertEqual(record.payload["sale_price"], 1000.0)
        self.assertIs(record.payload["active"], True)
        self.assertIsNone(record.erp_id)

    def test_auditlog_written_on_create(self):
        """POST → ``AuditLog`` ``master.create`` milik user pemanggil."""
        response, _ = self.post_product({"code": "TS-951", "name": "Kaos Audit"})
        product_id = response.json()["id"]

        log = AuditLog.objects.get(action="master.create", resource_id=str(product_id))
        self.assertEqual(log.resource, "master.product")
        self.assertEqual(log.result, AuditLog.Result.OK)
        self.assertEqual(log.user_id, self.admin.pk)
        self.assertEqual(log.payload["code"], "TS-951")

    def test_update_and_delete_reuse_syncrecord_and_write_audit(self):
        """PUT lalu DELETE memakai SATU ``SyncRecord`` (unique per produk) + audit dua-duanya."""
        product = Product.objects.create(code="TS-952", name="Kaos Siklus")

        self.put_product(product.pk, {"name": "Kaos Siklus 2"})
        response, _ = self.delete_product(product.pk)

        records = SyncRecord.objects.filter(
            resource=SyncResource.MASTER_PRODUCT.value, resource_id=str(product.pk)
        )
        self.assertEqual(records.count(), 1)

        record = records.get()
        self.assertEqual(record.stage, SyncStage.MASTER_PUSH.value)
        self.assertEqual(record.status, SyncStatus.PENDING)
        self.assertIs(record.payload["active"], False)  # payload terbaru = soft delete
        self.assertEqual(record.pk, response.json()["sync_record_id"])

        actions = set(
            AuditLog.objects.filter(resource_id=str(product.pk)).values_list(
                "action", flat=True
            )
        )
        self.assertEqual(actions, {"master.update", "master.delete"})

    # ------------------------------------------------------ izin tulis & task
    def test_write_requires_admin_owner_or_purchasing(self):
        """Purchasing boleh menulis; operator **403** tapi tetap boleh membaca."""
        purchasing_api = APIClient()
        purchasing_api.force_authenticate(self.purchasing)

        allowed, _ = self.post_product(
            {"code": "TS-953", "name": "Kaos Purchasing"}, client=purchasing_api
        )
        self.assertEqual(allowed.status_code, 201)

        rejected, enqueue = self.post_product(
            {"code": "TS-954", "name": "Kaos Operator"}, client=self.operator_api
        )
        self.assertEqual(rejected.status_code, 403)
        enqueue.assert_not_called()
        self.assertFalse(Product.objects.filter(code="TS-954").exists())

        # Operator masih boleh GET (list & detail).
        self.assertEqual(self.operator_api.get(PRODUCTS_URL).status_code, 200)
        self.assertEqual(
            self.operator_api.get(detail_url(allowed.json()["id"])).status_code, 200
        )

    @override_settings(ERP_ADAPTER="null")
    def test_push_task_null_mode_marks_sent(self):
        """``ERP_ADAPTER=null`` → push no-op: ``SyncRecord`` SENT + ``erp_id NULL-<uuid>``."""
        response, _ = self.post_product(
            {"code": "TS-955", "name": "Kaos Push", "sale_price": 5000}
        )
        body = response.json()

        result = push_master_product.apply(args=[body["id"], body["sync_record_id"]]).get()

        self.assertEqual(result["status"], "sent")
        self.assertTrue(str(result["erp_id"]).startswith("NULL-"))

        record = SyncRecord.objects.get(pk=body["sync_record_id"])
        self.assertEqual(record.status, SyncStatus.SENT)
        self.assertEqual(record.erp_id, result["erp_id"])
        self.assertIsNotNone(record.sent_at)

        # Percobaan push ikut diaudit (pola `integrations/erp_sync/audit.py`).
        self.assertTrue(
            AuditLog.objects.filter(
                action="erp_sync.push_master_product", resource_id=str(body["id"])
            ).exists()
        )

        # Enqueue ulang untuk payload yang sama → idempotent (tidak dobel kirim).
        again = push_master_product.apply(args=[body["id"], body["sync_record_id"]]).get()
        self.assertEqual(again["status"], "duplicate-ignored")





