"""Test CRUD master UoM — ``/api/v1/master/uoms/`` (H1.2).

Cakupan: list (pagination/filter/search), detail, create, update, **soft delete**
(``active=False`` — baris tetap di DB), izin (anon **403**, role bukan ADMIN/OWNER
**403**, admin boleh), validasi **400**, serta kewajiban H1.2: ``SyncRecord``
(``master.uom``/``MASTER_PUSH``) + ``AuditLog`` (``master.create``/``update``/
``delete``) setiap POST/PUT/DELETE dan enqueue task ``erp_sync.push_master_uom``.

Catatan:
  * push Odoo di-enqueue asinkron → ``apply_async`` di-patch (pola
    ``test_master_products_crud.py``) supaya test tidak menyentuh broker/worker;
  * ``DELETE`` = soft delete: yang berubah hanya ``is_active`` (API mengirim ``active``);
  * setiap baris response memuat ``odoo_id`` (kunci sync, ``null`` = belum push);
  * ``category``/``uom_type``/``factor``/``rounding`` WAJIB supaya push ke Odoo
    tidak perlu mengarang data (probe ``fields_get``: semuanya required di ``uom.uom``).

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_master_uoms_crud.py -q
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.audit.models import AuditLog
from core.auth.models import Role, User
from integrations.erp_sync.models import SyncRecord, SyncResource, SyncStage, SyncStatus
from integrations.erp_sync.tasks_master_push import push_master_uom
from master.models import UoM

UOMS_URL = "/api/v1/master/uoms/"
ENVELOPE_KEYS = {"rows", "total_count", "has_more", "next_cursor"}
ROW_KEYS = {
    "id",
    "code",
    "name",
    "category",
    "uom_type",
    "factor",
    "rounding",
    "active",
    "odoo_id",
}
#: Path patch enqueue task (service menulis SyncRecord lalu enqueue).
ENQUEUE = "master.uom_services.push_master_uom.apply_async"

VALID_BODY = {
    "code": "PCS",
    "name": "Pieces",
    "category": "Unit",
    "uom_type": "reference",
    "factor": 1.0,
    "rounding": 0.01,
    "active": True,
}


def detail_url(pk: int) -> str:
    """URL detail UoM."""
    return f"{UOMS_URL}{pk}/"


class MasterUomsCrudTests(TestCase):
    """GET/POST/PUT/DELETE + idempotensi (SyncRecord) + audit + izin."""

    @classmethod
    def setUpTestData(cls):
        """3 user: admin (ADMIN), purchasing (PURCHASING), operator (OPERATOR)."""
        cls.admin_role = Role.objects.get(code=Role.Code.ADMIN)
        cls.purchasing_role = Role.objects.get(code=Role.Code.PURCHASING)
        cls.operator_role = Role.objects.get(code=Role.Code.OPERATOR)

        cls.admin = User.objects.create_user(
            username="admin-uom",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=cls.admin_role,
        )
        cls.purchasing = User.objects.create_user(
            username="beli-uom",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=cls.purchasing_role,
        )
        cls.operator = User.objects.create_user(
            username="op-uom",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=cls.operator_role,
        )

    def setUp(self):
        """Klien admin (utama) + klien operator/purchasing (uji 403)."""
        self.api = APIClient()
        self.api.force_authenticate(self.admin)
        self.operator_api = APIClient()
        self.operator_api.force_authenticate(self.operator)
        self.purchasing_api = APIClient()
        self.purchasing_api.force_authenticate(self.purchasing)

    # ------------------------------------------------------------------ helper
    def post_uom(self, body: dict, client=None):
        """POST UoM dengan enqueue task di-patch → ``(response, mock)``."""
        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-uom-1")) as enqueue:
            response = (client or self.api).post(UOMS_URL, body, format="json")

        return response, enqueue

    def put_uom(self, pk: int, body: dict, client=None):
        """PUT UoM dengan enqueue task di-patch → ``(response, mock)``."""
        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-uom-2")) as enqueue:
            response = (client or self.api).put(detail_url(pk), body, format="json")

        return response, enqueue

    def delete_uom(self, pk: int, client=None):
        """DELETE UoM dengan enqueue task di-patch → ``(response, mock)``."""
        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-uom-3")) as enqueue:
            response = (client or self.api).delete(detail_url(pk))

        return response, enqueue

    # -------------------------------------------------------------------- GET
    def test_list_uoms_pagination(self):
        """ListPage: ``limit``/``cursor`` offset-based + ``has_more``/``next_cursor``."""
        for index in range(3):
            UoM.objects.create(code=f"U{index:03d}", name=f"Unit {index}", category="Unit")

        response = self.api.get(UOMS_URL, {"limit": 2})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), ENVELOPE_KEYS)
        self.assertEqual(body["total_count"], 3)
        self.assertTrue(body["has_more"])
        self.assertEqual(body["next_cursor"], 2)
        self.assertEqual(len(body["rows"]), 2)
        self.assertEqual(set(body["rows"][0]), ROW_KEYS)
        self.assertEqual(body["rows"][0]["code"], "U000")
        self.assertEqual(body["rows"][0]["uom_type"], "reference")
        self.assertEqual(body["rows"][0]["factor"], 1.0)
        self.assertEqual(body["rows"][0]["rounding"], 0.01)
        self.assertIsNone(body["rows"][0]["odoo_id"])

        second = self.api.get(UOMS_URL, {"limit": 2, "cursor": 2}).json()
        self.assertEqual(len(second["rows"]), 1)
        self.assertFalse(second["has_more"])
        self.assertIsNone(second["next_cursor"])

    def test_list_uoms_filter_active(self):
        """``?active=true|false`` menyaring status aktif; nilai ngawur → 400."""
        UoM.objects.create(code="A-1", name="Aktif", category="Unit")
        UoM.objects.create(code="N-1", name="Nonaktif", category="Unit", is_active=False)

        active_only = self.api.get(UOMS_URL, {"active": "true"}).json()
        self.assertEqual([row["code"] for row in active_only["rows"]], ["A-1"])
        self.assertTrue(active_only["rows"][0]["active"])

        inactive_only = self.api.get(UOMS_URL, {"active": "false"}).json()
        self.assertEqual([row["code"] for row in inactive_only["rows"]], ["N-1"])

        self.assertEqual(self.api.get(UOMS_URL, {"active": "kadang"}).status_code, 400)

    def test_list_uoms_search(self):
        """``?search=`` mencari di ``code``, ``name``, dan ``category``."""
        UoM.objects.create(code="PCS", name="Pieces", category="Unit")
        UoM.objects.create(code="KG", name="Kilogram", category="Berat")

        self.assertEqual(
            [row["code"] for row in self.api.get(UOMS_URL, {"search": "pc"}).json()["rows"]],
            ["PCS"],
        )
        self.assertEqual(
            [row["code"] for row in self.api.get(UOMS_URL, {"search": "kilo"}).json()["rows"]],
            ["KG"],
        )
        self.assertEqual(
            [row["code"] for row in self.api.get(UOMS_URL, {"search": "berat"}).json()["rows"]],
            ["KG"],
        )

    def test_auth_required_403_anonymous(self):
        """Anonim: GET/POST/PUT/DELETE semuanya **403** (IsAuthenticated)."""
        uom = UoM.objects.create(code="PCS", name="Pieces", category="Unit")
        anonymous = APIClient()

        self.assertEqual(anonymous.get(UOMS_URL).status_code, 403)
        self.assertEqual(anonymous.get(detail_url(uom.pk)).status_code, 403)
        self.assertEqual(anonymous.post(UOMS_URL, VALID_BODY, format="json").status_code, 403)
        self.assertEqual(
            anonymous.put(detail_url(uom.pk), {"name": "X"}, format="json").status_code, 403
        )
        self.assertEqual(anonymous.delete(detail_url(uom.pk)).status_code, 403)

    # --------------------------------------------------------------- POST create
    def test_create_uom_ok(self):
        """POST admin → 201; field H1.2 lengkap; task push di-enqueue."""
        response, enqueue = self.post_uom(VALID_BODY)

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(set(body), ROW_KEYS | {"sync_record_id", "task_id", "queued"})
        self.assertEqual(body["code"], "PCS")
        self.assertEqual(body["name"], "Pieces")
        self.assertEqual(body["category"], "Unit")
        self.assertEqual(body["uom_type"], "reference")
        self.assertEqual(body["factor"], 1.0)
        self.assertEqual(body["rounding"], 0.01)
        self.assertTrue(body["active"])
        self.assertIsNone(body["odoo_id"])
        self.assertEqual(body["task_id"], "task-uom-1")
        self.assertTrue(body["queued"])

        uom = UoM.objects.get(pk=body["id"])
        self.assertEqual(uom.name, "Pieces")
        self.assertTrue(uom.is_active)

        enqueue.assert_called_once()
        self.assertEqual(enqueue.call_args.kwargs["args"], [uom.pk, body["sync_record_id"]])

    def test_create_uom_defaults_when_optional_fields_omitted(self):
        """``uom_type``/``factor``/``rounding`` opsional saat create → default model."""
        response, _ = self.post_uom({"code": "PCS-D", "name": "Pieces", "category": "Unit"})

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["uom_type"], "reference")
        self.assertEqual(body["factor"], 1.0)
        self.assertEqual(body["rounding"], 0.01)

    def test_create_uom_duplicate_code_400(self):
        """Kode duplikat (beda huruf besar/kecil sekalipun) → 400, tanpa baris baru."""
        UoM.objects.create(code="PCS", name="Pieces", category="Unit")

        response, enqueue = self.post_uom(VALID_BODY)

        self.assertEqual(response.status_code, 400)
        self.assertIn("sudah dipakai", response.json()["detail"])
        self.assertEqual(UoM.objects.filter(code__iexact="PCS").count(), 1)
        enqueue.assert_not_called()

    def test_create_uom_invalid_payload_400(self):
        """Validasi: code/name/category wajib, tipe sah, factor/rounding > 0, active bool."""
        cases = (
            ({"name": "Tanpa Kode", "category": "Unit"}, "code"),
            ({"code": "X-1", "category": "Unit"}, "name"),
            ({"code": "X-2", "name": "Tanpa Kategori"}, "category"),
            (
                {"code": "X-3", "name": "Tipe", "category": "Unit", "uom_type": "besar"},
                "uom_type",
            ),
            ({"code": "X-4", "name": "Faktor", "category": "Unit", "factor": 0}, "factor"),
            ({"code": "X-5", "name": "Bulat", "category": "Unit", "rounding": -1}, "rounding"),
            ({"code": "X-6", "name": "Aktif", "category": "Unit", "active": "kadang"}, "active"),
        )

        for body, needle in cases:
            with self.subTest(body=body):
                response, _ = self.post_uom(body)
                self.assertEqual(response.status_code, 400)
                self.assertIn(needle, response.json()["detail"])

        self.assertEqual(UoM.objects.count(), 0)

    def test_odoo_id_in_response(self):
        """``odoo_id`` muncul di list & detail (``null`` = belum push)."""
        pushed = UoM.objects.create(code="PCS", name="Pieces", category="Unit", odoo_id=10)
        UoM.objects.create(code="KG", name="Kilogram", category="Berat")

        rows = self.api.get(UOMS_URL).json()["rows"]
        by_code = {row["code"]: row for row in rows}
        self.assertEqual(by_code["PCS"]["odoo_id"], 10)
        self.assertIsNone(by_code["KG"]["odoo_id"])

        self.assertEqual(self.api.get(detail_url(pushed.pk)).json()["odoo_id"], 10)

    # ------------------------------------------------------------ PUT / detail
    def test_update_uom_ok(self):
        """PUT mengubah hanya field yang dikirim (200) + audit ``master.update``."""
        uom = UoM.objects.create(code="PCS", name="Pieces", category="Unit")

        response, enqueue = self.put_uom(
            uom.pk,
            {"name": "Pieces (pcs)", "category": "Packaging", "factor": 12, "rounding": 1},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["name"], "Pieces (pcs)")
        self.assertEqual(body["category"], "Packaging")
        self.assertEqual(body["factor"], 12.0)
        self.assertEqual(body["rounding"], 1.0)
        self.assertEqual(body["code"], "PCS")  # tidak dikirim -> tidak berubah
        self.assertEqual(body["uom_type"], "reference")

        uom.refresh_from_db()
        self.assertEqual(uom.name, "Pieces (pcs)")
        self.assertEqual(uom.category, "Packaging")

        enqueue.assert_called_once()
        self.assertTrue(
            AuditLog.objects.filter(
                action="master.update", resource="master.uom", resource_id=str(uom.pk)
            ).exists()
        )

    def test_detail_and_missing_uom_404(self):
        """GET detail → 200; id tak dikenal → 404 untuk GET/PUT/DELETE."""
        uom = UoM.objects.create(code="PCS", name="Pieces", category="Unit")

        detail = self.api.get(detail_url(uom.pk))
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["id"], uom.pk)
        self.assertEqual(set(detail.json()), ROW_KEYS)

        self.assertEqual(self.api.get(detail_url(999999)).status_code, 404)
        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-none")):
            self.assertEqual(
                self.api.put(detail_url(999999), {"name": "X"}, format="json").status_code,
                404,
            )
            self.assertEqual(self.api.delete(detail_url(999999)).status_code, 404)

    # ------------------------------------------------------------ DELETE (soft)
    def test_delete_uom_soft_delete(self):
        """DELETE → 200 soft delete: ``active=False``, baris MASIH ada di DB."""
        uom = UoM.objects.create(code="PCS", name="Pieces", category="Unit")

        response, enqueue = self.delete_uom(uom.pk)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["id"], uom.pk)
        self.assertTrue(body["deleted"])
        self.assertFalse(body["active"])

        uom.refresh_from_db()
        self.assertFalse(uom.is_active)
        self.assertTrue(UoM.objects.filter(pk=uom.pk).exists())

        # Detail masih terbaca (read-only) — UoM nonaktif tidak hilang jejaknya.
        self.assertFalse(self.api.get(detail_url(uom.pk)).json()["active"])
        enqueue.assert_called_once()

    # --------------------------------------------- idempotensi & audit (H1.2)
    def test_syncrecord_written_on_create(self):
        """POST → ``SyncRecord`` PENDING (``master.uom`` / ``MASTER_PUSH``)."""
        response, _ = self.post_uom(VALID_BODY)
        uom_id = response.json()["id"]

        record = SyncRecord.objects.get(
            resource=SyncResource.MASTER_UOM.value,
            resource_id=str(uom_id),
            stage=SyncStage.MASTER_PUSH.value,
        )
        self.assertEqual(record.status, SyncStatus.PENDING)
        self.assertEqual(record.payload["code"], "PCS")
        self.assertEqual(record.payload["category"], "Unit")
        self.assertEqual(record.payload["uom_type"], "reference")
        self.assertEqual(record.payload["factor"], 1.0)
        self.assertIs(record.payload["active"], True)
        self.assertIsNone(record.erp_id)

    def test_auditlog_written_on_create(self):
        """POST → ``AuditLog`` ``master.create`` dengan resource ``master.uom``."""
        response, _ = self.post_uom(VALID_BODY)
        uom_id = response.json()["id"]

        log = AuditLog.objects.get(action="master.create", resource_id=str(uom_id))
        self.assertEqual(log.resource, "master.uom")
        self.assertEqual(log.result, AuditLog.Result.OK)
        self.assertEqual(log.user_id, self.admin.pk)
        self.assertEqual(log.payload["code"], "PCS")

    def test_update_and_delete_reuse_syncrecord_and_write_audit(self):
        """PUT lalu DELETE memakai SATU ``SyncRecord`` + audit keduanya."""
        uom = UoM.objects.create(code="PCS", name="Pieces", category="Unit")

        self.put_uom(uom.pk, {"name": "Pieces 2"})
        response, _ = self.delete_uom(uom.pk)

        records = SyncRecord.objects.filter(
            resource=SyncResource.MASTER_UOM.value, resource_id=str(uom.pk)
        )
        self.assertEqual(records.count(), 1)

        record = records.get()
        self.assertEqual(record.stage, SyncStage.MASTER_PUSH.value)
        self.assertEqual(record.status, SyncStatus.PENDING)
        self.assertIs(record.payload["active"], False)  # payload terbaru = soft delete
        self.assertEqual(record.pk, response.json()["sync_record_id"])

        actions = set(
            AuditLog.objects.filter(resource_id=str(uom.pk)).values_list("action", flat=True)
        )
        self.assertEqual(actions, {"master.update", "master.delete"})

    # ------------------------------------------------------ izin tulis & task
    def test_write_requires_admin_only(self):
        """Hanya ADMIN/OWNER boleh menulis UoM; purchasing & operator **403** (GET tetap 200)."""
        ok, _ = self.post_uom(VALID_BODY, client=self.purchasing_api)
        # purchasing TIDAK boleh menulis master UoM (brief H1.2) — beda dari Product.
        self.assertEqual(ok.status_code, 403)

        rejected, enqueue = self.post_uom(
            {"code": "KG", "name": "Kilogram", "category": "Berat"}, client=self.operator_api
        )
        self.assertEqual(rejected.status_code, 403)
        enqueue.assert_not_called()
        self.assertFalse(UoM.objects.filter(code="KG").exists())

        self.assertEqual(self.purchasing_api.get(UOMS_URL).status_code, 200)
        self.assertEqual(self.operator_api.get(UOMS_URL).status_code, 200)

        admin_ok, _ = self.post_uom(VALID_BODY)
        self.assertEqual(admin_ok.status_code, 201)

    @override_settings(ERP_ADAPTER="null")
    def test_push_task_enqueued_and_null_mode_marks_sent(self):
        """Task ``erp_sync.push_master_uom``: no-op di mode null → SENT + idempotent."""
        response, enqueue = self.post_uom(VALID_BODY)
        body = response.json()
        enqueue.assert_called_once()

        result = push_master_uom.apply(args=[body["id"], body["sync_record_id"]]).get()

        self.assertEqual(result["status"], "sent")
        self.assertTrue(str(result["erp_id"]).startswith("NULL-"))
        self.assertEqual(result["resource"], SyncResource.MASTER_UOM.value)

        record = SyncRecord.objects.get(pk=body["sync_record_id"])
        self.assertEqual(record.status, SyncStatus.SENT)
        self.assertEqual(record.erp_id, result["erp_id"])
        self.assertIsNotNone(record.sent_at)

        # Percobaan push ikut diaudit (pola `integrations/erp_sync/audit.py`).
        self.assertTrue(
            AuditLog.objects.filter(
                action="erp_sync.push_master_uom", resource_id=str(body["id"])
            ).exists()
        )

        again = push_master_uom.apply(args=[body["id"], body["sync_record_id"]]).get()
        self.assertEqual(again["status"], "duplicate-ignored")




