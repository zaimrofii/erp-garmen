"""Test CRUD master Warehouse — ``/api/v1/master/warehouses/`` (H1.3).

Cakupan: list (pagination/filter/search), detail, create, update, **soft delete**
(``active=False`` — baris tetap di DB), izin (anon **403**, role bukan ADMIN/OWNER
**403** — operator/qc/purchasing, admin boleh), validasi **400**, serta kewajiban
H1.3: ``SyncRecord`` (``master.warehouse``/``MASTER_PUSH``) + ``AuditLog``
(``master.create``/``update``/``delete``) setiap POST/PUT/DELETE dan enqueue task
``erp_sync.push_master_warehouse``.

Catatan khusus H1.3 (push **create + update** sejak sprint utang
``warehouse-create-mapping``):
  * ``ERP_ADAPTER=null`` → no-op: ``SENT`` + ``erp_id NULL-<uuid>``;
  * ``ERP_ADAPTER=odoo`` TANPA ``odoo_id`` → task memakai **create** (klien di-patch
    fake, jadi test tidak menyentuh jaringan) dan menyimpan ``odoo_id`` hasil create;
  * ``code`` (short_name Odoo, size=5) djaga di task: > 5 karakter → ``FAILED``
    tanpa retry (pesan jelas), sedangkan MES sendiri membolehkan 64 karakter.

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_master_warehouses_crud.py -q
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.audit.models import AuditLog
from core.auth.models import Role, User
from integrations.erp_sync.models import SyncRecord, SyncResource, SyncStage, SyncStatus
from integrations.erp_sync.tasks_master_push import MasterPushError, push_master_warehouse
from master.models import Warehouse

# Sprint utang `warehouse-create-mapping`: fake klien Odoo dipakai bersama test CRUD
# ini & test khusus mapping (satu definisi, tanpa duplikasi).
from tests.integration.test_push_warehouse_mapping import CREATE_CLIENT, FakeOdooClient

WAREHOUSES_URL = "/api/v1/master/warehouses/"
ENVELOPE_KEYS = {"rows", "total_count", "has_more", "next_cursor"}
ROW_KEYS = {
    "id",
    "code",
    "name",
    "reception_steps",
    "delivery_steps",
    "active",
    "odoo_id",
}
#: Path patch enqueue task (service menulis SyncRecord lalu enqueue).
ENQUEUE = "master.warehouse_services.push_master_warehouse.apply_async"

VALID_BODY = {
    "code": "WH",
    "name": "Gudang Utama",
    "reception_steps": "one_step",
    "delivery_steps": "ship_only",
    "active": True,
}


def detail_url(pk: int) -> str:
    """URL detail gudang."""
    return f"{WAREHOUSES_URL}{pk}/"


class MasterWarehousesCrudTests(TestCase):
    """GET/POST/PUT/DELETE + idempotensi (SyncRecord) + audit + izin + push task."""

    @classmethod
    def setUpTestData(cls):
        """4 user: admin, purchasing, operator, qc (uji 403 untuk 3 role terakhir)."""
        cls.admin_role = Role.objects.get(code=Role.Code.ADMIN)
        cls.purchasing_role = Role.objects.get(code=Role.Code.PURCHASING)
        cls.operator_role = Role.objects.get(code=Role.Code.OPERATOR)
        cls.qc_role = Role.objects.get(code=Role.Code.QC)

        cls.admin = User.objects.create_user(
            username="admin-wh",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=cls.admin_role,
        )
        cls.purchasing = User.objects.create_user(
            username="beli-wh",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=cls.purchasing_role,
        )
        cls.operator = User.objects.create_user(
            username="op-wh",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=cls.operator_role,
        )
        cls.qc = User.objects.create_user(
            username="qc-wh",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=cls.qc_role,
        )

    def setUp(self):
        """Klien admin (utama) + klien role lain (uji 403)."""
        self.api = APIClient()
        self.api.force_authenticate(self.admin)

        self.readonly_apis = {}
        for name, user in (
            ("purchasing", self.purchasing),
            ("operator", self.operator),
            ("qc", self.qc),
        ):
            client = APIClient()
            client.force_authenticate(user)
            self.readonly_apis[name] = client

    # ------------------------------------------------------------------ helper
    def post_warehouse(self, body: dict, client=None):
        """POST gudang dengan enqueue task di-patch → ``(response, mock)``."""
        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-wh-1")) as enqueue:
            response = (client or self.api).post(WAREHOUSES_URL, body, format="json")

        return response, enqueue

    def put_warehouse(self, pk: int, body: dict, client=None):
        """PUT gudang dengan enqueue task di-patch → ``(response, mock)``."""
        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-wh-2")) as enqueue:
            response = (client or self.api).put(detail_url(pk), body, format="json")

        return response, enqueue

    def delete_warehouse(self, pk: int, client=None):
        """DELETE gudang dengan enqueue task di-patch → ``(response, mock)``."""
        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-wh-3")) as enqueue:
            response = (client or self.api).delete(detail_url(pk))

        return response, enqueue

    # -------------------------------------------------------------------- GET
    def test_list_warehouses_pagination(self):
        """ListPage: ``limit``/``cursor`` offset-based + ``has_more``/``next_cursor``."""
        for index in range(3):
            Warehouse.objects.create(code=f"W{index:02d}", name=f"Gudang {index}")

        response = self.api.get(WAREHOUSES_URL, {"limit": 2})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), ENVELOPE_KEYS)
        self.assertEqual(body["total_count"], 3)
        self.assertTrue(body["has_more"])
        self.assertEqual(body["next_cursor"], 2)
        self.assertEqual(len(body["rows"]), 2)
        self.assertEqual(set(body["rows"][0]), ROW_KEYS)
        self.assertEqual(body["rows"][0]["code"], "W00")
        self.assertEqual(body["rows"][0]["reception_steps"], "one_step")
        self.assertEqual(body["rows"][0]["delivery_steps"], "ship_only")
        self.assertIsNone(body["rows"][0]["odoo_id"])

        second = self.api.get(WAREHOUSES_URL, {"limit": 2, "cursor": 2}).json()
        self.assertEqual(len(second["rows"]), 1)
        self.assertFalse(second["has_more"])
        self.assertIsNone(second["next_cursor"])

    def test_list_warehouses_filter_active(self):
        """``?active=true|false`` menyaring status aktif; nilai ngawur → 400."""
        Warehouse.objects.create(code="A-1", name="Aktif")
        Warehouse.objects.create(code="N-1", name="Nonaktif", is_active=False)

        active_only = self.api.get(WAREHOUSES_URL, {"active": "true"}).json()
        self.assertEqual([row["code"] for row in active_only["rows"]], ["A-1"])
        self.assertTrue(active_only["rows"][0]["active"])

        inactive_only = self.api.get(WAREHOUSES_URL, {"active": "false"}).json()
        self.assertEqual([row["code"] for row in inactive_only["rows"]], ["N-1"])

        self.assertEqual(self.api.get(WAREHOUSES_URL, {"active": "kadang"}).status_code, 400)

    def test_list_warehouses_search(self):
        """``?search=`` mencari di ``code`` dan ``name``."""
        Warehouse.objects.create(code="WH", name="Gudang Utama")
        Warehouse.objects.create(code="WH2", name="Gudang Bahan")

        self.assertEqual(
            [
                row["code"]
                for row in self.api.get(WAREHOUSES_URL, {"search": "bahan"}).json()["rows"]
            ],
            ["WH2"],
        )
        self.assertEqual(
            [row["code"] for row in self.api.get(WAREHOUSES_URL, {"search": "WH"}).json()["rows"]],
            ["WH", "WH2"],
        )

    def test_auth_required_403_anonymous(self):
        """Anonim: GET/POST/PUT/DELETE semuanya **403** (IsAuthenticated)."""
        warehouse = Warehouse.objects.create(code="WH", name="Gudang Utama")
        anonymous = APIClient()

        self.assertEqual(anonymous.get(WAREHOUSES_URL).status_code, 403)
        self.assertEqual(anonymous.get(detail_url(warehouse.pk)).status_code, 403)
        self.assertEqual(anonymous.post(WAREHOUSES_URL, VALID_BODY, format="json").status_code, 403)
        self.assertEqual(
            anonymous.put(detail_url(warehouse.pk), {"name": "X"}, format="json").status_code,
            403,
        )
        self.assertEqual(anonymous.delete(detail_url(warehouse.pk)).status_code, 403)

    def test_write_requires_admin_only(self):
        """Hanya ADMIN/OWNER boleh menulis; purchasing/operator/qc **403** (GET 200)."""
        for name, client in self.readonly_apis.items():
            with self.subTest(role=name):
                rejected, enqueue = self.post_warehouse(
                    {"code": f"X-{name}", "name": "Tidak boleh"}, client=client
                )
                self.assertEqual(rejected.status_code, 403)
                enqueue.assert_not_called()
                self.assertFalse(Warehouse.objects.filter(code=f"X-{name}").exists())
                self.assertEqual(client.get(WAREHOUSES_URL).status_code, 200)

        allowed, _ = self.post_warehouse(VALID_BODY)
        self.assertEqual(allowed.status_code, 201)

    # --------------------------------------------------------------- POST create
    def test_create_warehouse_ok(self):
        """POST admin → 201; field H1.3 lengkap + info sync; task push di-enqueue."""
        response, enqueue = self.post_warehouse(VALID_BODY)

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(set(body), ROW_KEYS | {"sync_record_id", "task_id", "queued"})
        self.assertEqual(body["code"], "WH")
        self.assertEqual(body["name"], "Gudang Utama")
        self.assertEqual(body["reception_steps"], "one_step")
        self.assertEqual(body["delivery_steps"], "ship_only")
        self.assertTrue(body["active"])
        self.assertIsNone(body["odoo_id"])
        self.assertEqual(body["task_id"], "task-wh-1")
        self.assertTrue(body["queued"])

        warehouse = Warehouse.objects.get(pk=body["id"])
        self.assertEqual(warehouse.name, "Gudang Utama")
        self.assertTrue(warehouse.is_active)

        enqueue.assert_called_once()
        self.assertEqual(enqueue.call_args.kwargs["args"], [warehouse.pk, body["sync_record_id"]])

    def test_create_warehouse_defaults_when_steps_omitted(self):
        """``reception_steps``/``delivery_steps`` opsional saat create → default model."""
        response, _ = self.post_warehouse({"code": "WH3", "name": "Gudang Ketiga"})

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["reception_steps"], "one_step")
        self.assertEqual(body["delivery_steps"], "ship_only")

    def test_create_warehouse_duplicate_code_400(self):
        """Kode duplikat (beda huruf besar/kecil sekalipun) → 400, tanpa baris baru."""
        Warehouse.objects.create(code="WH", name="Gudang Lama")

        response, enqueue = self.post_warehouse(VALID_BODY)

        self.assertEqual(response.status_code, 400)
        self.assertIn("sudah dipakai", response.json()["detail"])
        self.assertEqual(Warehouse.objects.filter(code__iexact="WH").count(), 1)
        enqueue.assert_not_called()

    def test_create_warehouse_invalid_payload_400(self):
        """Validasi: code/name wajib, steps sah, active bool."""
        cases = (
            ({"name": "Tanpa Kode"}, "code"),
            ({"code": "X-1"}, "name"),
            (
                {"code": "X-2", "name": "Steps", "reception_steps": "empat_langkah"},
                "reception_steps",
            ),
            (
                {"code": "X-3", "name": "Steps", "delivery_steps": "kirim_langsung"},
                "delivery_steps",
            ),
            ({"code": "X-4", "name": "Aktif", "active": "kadang"}, "active"),
        )

        for body, needle in cases:
            with self.subTest(body=body):
                response, _ = self.post_warehouse(body)
                self.assertEqual(response.status_code, 400)
                self.assertIn(needle, response.json()["detail"])

        self.assertEqual(Warehouse.objects.count(), 0)

    def test_odoo_id_in_response(self):
        """``odoo_id`` muncul di list & detail (``null`` = belum push)."""
        pushed = Warehouse.objects.create(code="WH", name="Gudang Utama", odoo_id=1)
        Warehouse.objects.create(code="WH2", name="Gudang Bahan")

        rows = self.api.get(WAREHOUSES_URL).json()["rows"]
        by_code = {row["code"]: row for row in rows}
        self.assertEqual(by_code["WH"]["odoo_id"], 1)
        self.assertIsNone(by_code["WH2"]["odoo_id"])

        self.assertEqual(self.api.get(detail_url(pushed.pk)).json()["odoo_id"], 1)

    # ------------------------------------------------------------ PUT / detail
    def test_update_warehouse_ok(self):
        """PUT mengubah hanya field yang dikirim (200) + audit ``master.update``."""
        warehouse = Warehouse.objects.create(code="WH", name="Gudang Lama")

        response, enqueue = self.put_warehouse(
            warehouse.pk,
            {"name": "Gudang Baru", "reception_steps": "two_steps", "delivery_steps": "pick_ship"},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["name"], "Gudang Baru")
        self.assertEqual(body["reception_steps"], "two_steps")
        self.assertEqual(body["delivery_steps"], "pick_ship")
        self.assertEqual(body["code"], "WH")  # tidak dikirim -> tidak berubah

        warehouse.refresh_from_db()
        self.assertEqual(warehouse.name, "Gudang Baru")
        self.assertEqual(warehouse.reception_steps, "two_steps")

        enqueue.assert_called_once()
        self.assertTrue(
            AuditLog.objects.filter(
                action="master.update",
                resource="master.warehouse",
                resource_id=str(warehouse.pk),
            ).exists()
        )

    def test_detail_and_missing_warehouse_404(self):
        """GET detail → 200; id tak dikenal → 404 untuk GET/PUT/DELETE."""
        warehouse = Warehouse.objects.create(code="WH", name="Gudang Utama")

        detail = self.api.get(detail_url(warehouse.pk))
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["id"], warehouse.pk)
        self.assertEqual(set(detail.json()), ROW_KEYS)

        self.assertEqual(self.api.get(detail_url(999999)).status_code, 404)
        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-none")):
            self.assertEqual(
                self.api.put(detail_url(999999), {"name": "X"}, format="json").status_code,
                404,
            )
            self.assertEqual(self.api.delete(detail_url(999999)).status_code, 404)

    # ------------------------------------------------------------ DELETE (soft)
    def test_delete_warehouse_soft_delete(self):
        """DELETE → 200 soft delete: ``active=False``, baris MASIH ada di DB."""
        warehouse = Warehouse.objects.create(code="WH", name="Gudang Utama")

        response, enqueue = self.delete_warehouse(warehouse.pk)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["id"], warehouse.pk)
        self.assertTrue(body["deleted"])
        self.assertFalse(body["active"])

        warehouse.refresh_from_db()
        self.assertFalse(warehouse.is_active)
        self.assertTrue(Warehouse.objects.filter(pk=warehouse.pk).exists())

        # Detail masih terbaca (read-only) — gudang nonaktif tidak hilang jejaknya.
        self.assertFalse(self.api.get(detail_url(warehouse.pk)).json()["active"])
        enqueue.assert_called_once()

    # --------------------------------------------- idempotensi & audit (H1.3)
    def test_syncrecord_written_on_create(self):
        """POST → ``SyncRecord`` PENDING (``master.warehouse`` / ``MASTER_PUSH``)."""
        response, _ = self.post_warehouse(VALID_BODY)
        warehouse_id = response.json()["id"]

        record = SyncRecord.objects.get(
            resource=SyncResource.MASTER_WAREHOUSE.value,
            resource_id=str(warehouse_id),
            stage=SyncStage.MASTER_PUSH.value,
        )
        self.assertEqual(record.status, SyncStatus.PENDING)
        self.assertEqual(record.payload["code"], "WH")
        self.assertEqual(record.payload["reception_steps"], "one_step")
        self.assertEqual(record.payload["delivery_steps"], "ship_only")
        self.assertIs(record.payload["active"], True)
        self.assertIsNone(record.erp_id)

    def test_auditlog_written_on_create(self):
        """POST → ``AuditLog`` ``master.create`` dengan resource ``master.warehouse``."""
        response, _ = self.post_warehouse(VALID_BODY)
        warehouse_id = response.json()["id"]

        log = AuditLog.objects.get(action="master.create", resource_id=str(warehouse_id))
        self.assertEqual(log.resource, "master.warehouse")
        self.assertEqual(log.result, AuditLog.Result.OK)
        self.assertEqual(log.user_id, self.admin.pk)
        self.assertEqual(log.payload["code"], "WH")

    def test_update_and_delete_reuse_syncrecord_and_write_audit(self):
        """PUT lalu DELETE memakai SATU ``SyncRecord`` + audit keduanya."""
        warehouse = Warehouse.objects.create(code="WH", name="Gudang Utama")

        self.put_warehouse(warehouse.pk, {"name": "Gudang Utama 2"})
        response, _ = self.delete_warehouse(warehouse.pk)

        records = SyncRecord.objects.filter(
            resource=SyncResource.MASTER_WAREHOUSE.value, resource_id=str(warehouse.pk)
        )
        self.assertEqual(records.count(), 1)

        record = records.get()
        self.assertEqual(record.stage, SyncStage.MASTER_PUSH.value)
        self.assertEqual(record.status, SyncStatus.PENDING)
        self.assertIs(record.payload["active"], False)  # payload terbaru = soft delete
        self.assertEqual(record.pk, response.json()["sync_record_id"])

        actions = set(
            AuditLog.objects.filter(resource_id=str(warehouse.pk)).values_list("action", flat=True)
        )
        self.assertEqual(actions, {"master.update", "master.delete"})

    # ------------------------------------------------------------- push task
    @override_settings(ERP_ADAPTER="null")
    def test_push_task_enqueued_and_null_mode_marks_sent(self):
        """Task ``erp_sync.push_master_warehouse``: no-op di mode null → SENT + idempotent."""
        response, enqueue = self.post_warehouse(VALID_BODY)
        body = response.json()
        enqueue.assert_called_once()

        result = push_master_warehouse.apply(args=[body["id"], body["sync_record_id"]]).get()

        self.assertEqual(result["status"], "sent")
        self.assertTrue(str(result["erp_id"]).startswith("NULL-"))
        self.assertEqual(result["resource"], SyncResource.MASTER_WAREHOUSE.value)

        record = SyncRecord.objects.get(pk=body["sync_record_id"])
        self.assertEqual(record.status, SyncStatus.SENT)
        self.assertIsNotNone(record.sent_at)

        # Percobaan push ikut diaudit (pola `integrations/erp_sync/audit.py`).
        self.assertTrue(
            AuditLog.objects.filter(
                action="erp_sync.push_master_warehouse", resource_id=str(body["id"])
            ).exists()
        )

        again = push_master_warehouse.apply(args=[body["id"], body["sync_record_id"]]).get()
        self.assertEqual(again["status"], "duplicate-ignored")

    @override_settings(ERP_ADAPTER="odoo")
    def test_push_task_odoo_mode_without_odoo_id_memakai_create(self):
        """Tanpa ``odoo_id`` → task memakai ``create`` (OPSI B) & menyimpan id hasilnya.

        Klien Odoo di-patch (fake transport) supaya test TIDAK menyentuh jaringan;
        payload tetap 6 field (tanpa ``view_location_id``/``lot_stock_id``/``company_id``
        — ketiganya ditangani Odoo sendiri di ``create()``).
        """
        response, _ = self.post_warehouse(VALID_BODY)
        body = response.json()

        fake = FakeOdooClient(created_id=321)
        with patch(CREATE_CLIENT, return_value=fake):
            result = push_master_warehouse.apply(args=[body["id"], body["sync_record_id"]]).get()

        self.assertEqual(result["status"], "sent")
        self.assertEqual(result["erp_id"], "321")

        model_used, payload = fake.created[0]
        self.assertEqual(model_used, "stock.warehouse")
        self.assertEqual(fake.written, [])

        self.assertEqual(
            set(payload), {"name", "code", "reception_steps", "delivery_steps", "active"}
        )
        for forbidden in ("view_location_id", "lot_stock_id", "company_id"):
            self.assertNotIn(forbidden, payload)

        warehouse = Warehouse.objects.get(pk=body["id"])
        self.assertEqual(warehouse.odoo_id, 321)  # odoo_id disimpan dari hasil create

        record = SyncRecord.objects.get(pk=body["sync_record_id"])
        self.assertEqual(record.status, SyncStatus.SENT)
        self.assertEqual(record.erp_id, "321")

    def test_warehouse_odoo_values_guard_code_max_5(self):
        """``code`` (short_name Odoo, size=5) dijaga di task — MES tetap boleh 64 karakter."""
        from integrations.erp_sync.tasks_master_push import _warehouse_odoo_values

        payload = {
            "code": "GUDANGPANJANG",
            "name": "Gudang Panjang",
            "reception_steps": "one_step",
            "delivery_steps": "ship_only",
            "active": True,
        }

        with self.assertRaises(MasterPushError) as ctx:
            _warehouse_odoo_values(payload)

        self.assertIn("maks 5 karakter", str(ctx.exception))

        # Kode pendek & steps sah → nilai siap dikirim.
        payload["code"] = "WH"
        self.assertEqual(
            _warehouse_odoo_values(payload),
            {
                "name": "Gudang Panjang",
                "code": "WH",
                "reception_steps": "one_step",
                "delivery_steps": "ship_only",
                "active": True,
            },
        )




