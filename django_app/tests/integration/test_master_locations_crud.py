"""Test CRUD master Location — ``/api/v1/master/locations/`` (H1.4).

Cakupan: list (pagination/filter usage/warehouse/parent/search), detail (dengan
``children_count`` + nama induk/gudang + ``complete_name`` derived), create, update,
**soft delete** (ditolak 400 kalau masih punya anak aktif), izin (anon **403**, role
bukan ADMIN/OWNER **403**), validasi **400** (duplikat kode, usage bohong, induk
tidak ada, induk = diri sendiri / turunannya, gudang tidak ada), serta kewajiban
H1.4: ``SyncRecord`` (``master.location``/``MASTER_PUSH``) + ``AuditLog``
(``master.create``/``update``/``delete``) setiap POST/PUT/DELETE dan enqueue task
``erp_sync.push_master_location``.

Catatan khusus H1.4 (hierarki + push):
  * ``parent``/``warehouse`` = FK tanpa akhiran ``_id`` → API tetap mengirim
    ``parent_id``/``warehouse_id`` (pk) + ``parent_name``/``warehouse_name``;
  * ``complete_name`` DERIVED (tidak ada kolomnya di DB);
  * ``ERP_ADAPTER=null`` → no-op: ``SENT`` + ``erp_id NULL-<uuid>``;
  * ``ERP_ADAPTER=odoo`` + induk **belum** punya ``odoo_id`` → ``FAILED`` dengan
    pesan jelas (lokasi tidak boleh dipindah ke root Odoo). Test tidak menyentuh
    jaringan karena ``MasterPushError`` dilempar sebelum transport dipakai;
  * ``create`` lokasi **boleh** (Odoo hanya wajib ``name``+``usage``) — pemetaan
    nilainya diuji langsung di ``_location_odoo_values`` tanpa memanggil Odoo.

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_master_locations_crud.py -q
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.audit.models import AuditLog
from core.auth.models import Role, User
from integrations.erp_sync.models import SyncRecord, SyncResource, SyncStage, SyncStatus
from integrations.erp_sync.tasks_master_push import (
    MasterPushError,
    _location_odoo_values,
    location_payload,
    push_master_location,
)
from master.models import Location, Warehouse

LOCATIONS_URL = "/api/v1/master/locations/"
ENVELOPE_KEYS = {"rows", "total_count", "has_more", "next_cursor"}
ROW_KEYS = {
    "id",
    "code",
    "name",
    "usage",
    "parent_id",
    "parent_name",
    "warehouse_id",
    "warehouse_name",
    "active",
    "odoo_id",
    "children_count",
    "complete_name",
}
#: Path patch enqueue task (service menulis SyncRecord lalu enqueue).
ENQUEUE = "master.location_services.push_master_location.apply_async"

VALID_BODY = {
    "code": "WH/STOCK",
    "name": "Stok",
    "usage": "internal",
    "active": True,
}


def detail_url(pk: int) -> str:
    """URL detail lokasi."""
    return f"{LOCATIONS_URL}{pk}/"


class MasterLocationsCrudTests(TestCase):
    """GET/POST/PUT/DELETE + hierarki + idempotensi (SyncRecord) + audit + push task."""

    @classmethod
    def setUpTestData(cls):
        """4 user: admin, purchasing, operator, qc (uji 403 untuk 3 role terakhir)."""
        cls.admin_role = Role.objects.get(code=Role.Code.ADMIN)
        cls.purchasing_role = Role.objects.get(code=Role.Code.PURCHASING)
        cls.operator_role = Role.objects.get(code=Role.Code.OPERATOR)
        cls.qc_role = Role.objects.get(code=Role.Code.QC)

        cls.admin = User.objects.create_user(
            username="admin-loc",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=cls.admin_role,
        )
        cls.purchasing = User.objects.create_user(
            username="beli-loc",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=cls.purchasing_role,
        )
        cls.operator = User.objects.create_user(
            username="op-loc",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=cls.operator_role,
        )
        cls.qc = User.objects.create_user(
            username="qc-loc",
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
    def post_location(self, body: dict, client=None):
        """POST lokasi dengan enqueue task di-patch → ``(response, mock)``."""
        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-loc-1")) as enqueue:
            response = (client or self.api).post(LOCATIONS_URL, body, format="json")

        return response, enqueue

    def put_location(self, pk: int, body: dict, client=None):
        """PUT lokasi dengan enqueue task di-patch → ``(response, mock)``."""
        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-loc-2")) as enqueue:
            response = (client or self.api).put(detail_url(pk), body, format="json")

        return response, enqueue

    def delete_location(self, pk: int, client=None):
        """DELETE lokasi dengan enqueue task di-patch → ``(response, mock)``."""
        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-loc-3")) as enqueue:
            response = (client or self.api).delete(detail_url(pk))

        return response, enqueue

    # ------------------------------------------------------------ POST / create
    def test_create_location_ok(self):
        """POST → 201: baris lokasi + info sync; baris tersimpan di DB."""
        response, enqueue = self.post_location(VALID_BODY)

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertTrue(ROW_KEYS <= set(body))
        self.assertEqual(body["code"], "WH/STOCK")
        self.assertEqual(body["name"], "Stok")
        self.assertEqual(body["usage"], "internal")
        self.assertEqual(body["complete_name"], "Stok")
        self.assertIsNone(body["parent_id"])
        self.assertIsNone(body["parent_name"])
        self.assertIsNone(body["warehouse_id"])
        self.assertIsNone(body["odoo_id"])
        self.assertEqual(body["children_count"], 0)
        self.assertIs(body["active"], True)

        self.assertIsNotNone(body["sync_record_id"])
        self.assertEqual(body["task_id"], "task-loc-1")
        self.assertIs(body["queued"], True)

        location = Location.objects.get(pk=body["id"])
        self.assertEqual(location.code, "WH/STOCK")
        self.assertEqual(location.usage, Location.Usage.INTERNAL)
        enqueue.assert_called_once()
        self.assertEqual(enqueue.call_args.kwargs["args"], [location.pk, body["sync_record_id"]])

    def test_create_location_with_parent_and_warehouse(self):
        """POST dengan ``parent_id``/``warehouse_id`` → FK terisi + nama di response."""
        parent = Location.objects.create(code="WH", name="Gudang Utama", usage=Location.Usage.VIEW)
        warehouse = Warehouse.objects.create(code="WH", name="Gudang Utama")

        response, _ = self.post_location(
            {
                "code": "WH/STOCK",
                "name": "Stok",
                "usage": "internal",
                "parent_id": parent.pk,
                "warehouse_id": warehouse.pk,
            }
        )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["parent_id"], parent.pk)
        self.assertEqual(body["parent_name"], "Gudang Utama")
        self.assertEqual(body["warehouse_id"], warehouse.pk)
        self.assertEqual(body["warehouse_name"], "Gudang Utama")
        self.assertEqual(body["complete_name"], "Gudang Utama/Stok")

    def test_create_location_default_usage_internal(self):
        """``usage`` opsional saat create → default ``internal``."""
        response, _ = self.post_location({"code": "WH/DEFAULT", "name": "Default"})

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["usage"], "internal")

    def test_create_location_duplicate_code_400(self):
        """Kode duplikat (beda huruf besar/kecil sekalipun) → 400, tanpa baris baru."""
        Location.objects.create(code="WH/STOCK", name="Stok Lama")

        response, enqueue = self.post_location(VALID_BODY)

        self.assertEqual(response.status_code, 400)
        self.assertIn("sudah dipakai", response.json()["detail"])
        self.assertEqual(Location.objects.filter(code__iexact="WH/STOCK").count(), 1)
        enqueue.assert_not_called()

    def test_create_location_invalid_payload_400(self):
        """Validasi: code/name wajib, usage sah, parent/gudang nyata, active bool."""
        cases = (
            ({"name": "Tanpa Kode"}, "code"),
            ({"code": "X-1"}, "name"),
            ({"code": "X-2", "name": "Usage", "usage": "melayang"}, "usage"),
            ({"code": "X-3", "name": "Induk", "parent_id": 999999}, "tidak ditemukan"),
            ({"code": "X-4", "name": "Gudang", "warehouse_id": 999999}, "tidak ditemukan"),
            ({"code": "X-5", "name": "Aktif", "active": "kadang"}, "active"),
            ({"code": "X" * 65, "name": "Panjang"}, "maksimal"),
        )

        for body, needle in cases:
            with self.subTest(body=body):
                response, _ = self.post_location(body)
                self.assertEqual(response.status_code, 400)
                self.assertIn(needle, response.json()["detail"])

        self.assertEqual(Location.objects.count(), 0)

    # ------------------------------------------------------- GET detail & hierarki
    def test_detail_and_missing_location_404(self):
        """GET detail → 200; id tak dikenal → 404 untuk GET/PUT/DELETE."""
        location = Location.objects.create(code="WH/STOCK", name="Stok")

        detail = self.api.get(detail_url(location.pk))
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["id"], location.pk)
        self.assertTrue(ROW_KEYS <= set(detail.json()))

        self.assertEqual(self.api.get(detail_url(999999)).status_code, 404)
        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-none")):
            self.assertEqual(
                self.api.put(detail_url(999999), {"name": "X"}, format="json").status_code,
                404,
            )
            self.assertEqual(self.api.delete(detail_url(999999)).status_code, 404)

    def test_detail_children_count_and_hierarchy(self):
        """``children_count`` + ``complete_name`` derived dari rantai 3 level."""
        root = Location.objects.create(code="WH", name="Gudang Utama", usage=Location.Usage.VIEW)
        stock = Location.objects.create(code="WH/STOCK", name="Stok", parent=root)
        Location.objects.create(code="WH/STOCK/A", name="Rak A", parent=stock)

        detail = self.api.get(detail_url(stock.pk)).json()
        self.assertEqual(detail["children_count"], 1)
        self.assertEqual(detail["complete_name"], "Gudang Utama/Stok")
        self.assertEqual(detail["parent_name"], "Gudang Utama")

        self.assertEqual(self.api.get(detail_url(root.pk)).json()["children_count"], 1)

    def test_odoo_id_in_response(self):
        """``odoo_id`` muncul di list & detail (``null`` = belum push)."""
        pushed = Location.objects.create(code="WH", name="Gudang Utama", odoo_id=7)
        Location.objects.create(code="WH/STOCK", name="Stok")

        rows = self.api.get(LOCATIONS_URL).json()["rows"]
        by_code = {row["code"]: row for row in rows}
        self.assertEqual(by_code["WH"]["odoo_id"], 7)
        self.assertIsNone(by_code["WH/STOCK"]["odoo_id"])

        self.assertEqual(self.api.get(detail_url(pushed.pk)).json()["odoo_id"], 7)

    # ------------------------------------------------------------ PUT / detail
    def test_update_location_ok(self):
        """PUT mengubah hanya field yang dikirim (200) + audit ``master.update``."""
        location = Location.objects.create(code="WH/STOCK", name="Stok Lama")
        parent = Location.objects.create(code="WH", name="Gudang Utama", usage=Location.Usage.VIEW)

        response, enqueue = self.put_location(
            location.pk,
            {"name": "Stok Baru", "usage": "view", "parent_id": parent.pk, "active": False},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["name"], "Stok Baru")
        self.assertEqual(body["usage"], "view")
        self.assertEqual(body["parent_id"], parent.pk)
        self.assertIs(body["active"], False)
        self.assertEqual(body["code"], "WH/STOCK")  # tidak dikirim -> tidak berubah

        location.refresh_from_db()
        self.assertEqual(location.name, "Stok Baru")
        self.assertEqual(location.usage, Location.Usage.VIEW)
        self.assertEqual(location.parent, parent)
        self.assertFalse(location.is_active)

        enqueue.assert_called_once()
        self.assertTrue(
            AuditLog.objects.filter(
                action="master.update",
                resource="master.location",
                resource_id=str(location.pk),
            ).exists()
        )

    def test_update_location_can_detach_parent(self):
        """``parent_id: null`` → lokasi kembali jadi akar (lokasi global)."""
        root = Location.objects.create(code="WH", name="Gudang Utama", usage=Location.Usage.VIEW)
        location = Location.objects.create(code="WH/STOCK", name="Stok", parent=root)

        response, _ = self.put_location(location.pk, {"parent_id": None})

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["parent_id"])
        self.assertEqual(response.json()["complete_name"], "Stok")
        location.refresh_from_db()
        self.assertIsNone(location.parent)

    def test_update_location_parent_self_400(self):
        """Induk = dirinya sendiri → 400 (hierarki tidak boleh siklus)."""
        location = Location.objects.create(code="WH", name="Gudang Utama")

        response, enqueue = self.put_location(location.pk, {"parent_id": location.pk})

        self.assertEqual(response.status_code, 400)
        self.assertIn("dirinya sendiri", response.json()["detail"])
        enqueue.assert_not_called()
        location.refresh_from_db()
        self.assertIsNone(location.parent)

    def test_update_location_parent_cycle_400(self):
        """Induk = turunannya sendiri → 400 (mencegah siklus tak berujung)."""
        root = Location.objects.create(code="WH", name="Gudang Utama")
        child = Location.objects.create(code="WH/STOCK", name="Stok", parent=root)

        response, _ = self.put_location(root.pk, {"parent_id": child.pk})

        self.assertEqual(response.status_code, 400)
        self.assertIn("siklus", response.json()["detail"])

    def test_update_location_empty_body_no_syncrecord(self):
        """PUT tanpa satu pun field → 200 tanpa ``SyncRecord``/audit/push (pola H1.1–H1.3)."""
        location = Location.objects.create(code="WH/STOCK", name="Stok")

        response, enqueue = self.put_location(location.pk, {})

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["sync_record_id"])
        self.assertIsNone(response.json()["task_id"])
        self.assertFalse(response.json()["queued"])
        enqueue.assert_not_called()
        self.assertFalse(
            SyncRecord.objects.filter(resource=SyncResource.MASTER_LOCATION.value).exists()
        )

    # ---------------------------------------------------------- DELETE (soft)
    def test_delete_location_soft_delete(self):
        """DELETE → 200 soft delete: ``active=False``, baris MASIH ada di DB."""
        location = Location.objects.create(code="WH/STOCK", name="Stok")

        response, enqueue = self.delete_location(location.pk)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["id"], location.pk)
        self.assertTrue(body["deleted"])
        self.assertFalse(body["active"])

        location.refresh_from_db()
        self.assertFalse(location.is_active)
        self.assertTrue(Location.objects.filter(pk=location.pk).exists())

        # Detail masih terbaca (read-only) — lokasi nonaktif tidak hilang jejaknya.
        self.assertFalse(self.api.get(detail_url(location.pk)).json()["active"])
        enqueue.assert_called_once()

    def test_delete_location_with_active_children_400(self):
        """DELETE induk yang masih punya anak AKTIF → 400, induk tetap aktif."""
        parent = Location.objects.create(code="WH", name="Gudang Utama")
        child = Location.objects.create(code="WH/STOCK", name="Stok", parent=parent)

        response, enqueue = self.delete_location(parent.pk)

        self.assertEqual(response.status_code, 400)
        self.assertIn("anak aktif", response.json()["detail"])
        self.assertIn("WH/STOCK", response.json()["detail"])
        enqueue.assert_not_called()

        parent.refresh_from_db()
        self.assertTrue(parent.is_active)

        # Setelah anaknya dinonaktifkan, induk boleh dinonaktifkan.
        child.is_active = False
        child.save(update_fields=("is_active",))

        ok, _ = self.delete_location(parent.pk)
        self.assertEqual(ok.status_code, 200)
        parent.refresh_from_db()
        self.assertFalse(parent.is_active)
        self.assertTrue(Location.objects.filter(pk=child.pk).exists())

    # ------------------------------------------------------------------- GET list
    def test_list_locations_pagination_and_envelope(self):
        """Envelope ListPage + pagination ``limit``/``cursor`` + baris ber-``annotate``."""
        for index in range(3):
            Location.objects.create(code=f"WH/L{index}", name=f"Lokasi {index}")

        first = self.api.get(LOCATIONS_URL, {"limit": 2}).json()
        self.assertEqual(set(first), ENVELOPE_KEYS)
        self.assertEqual(first["total_count"], 3)
        self.assertEqual(len(first["rows"]), 2)
        self.assertTrue(first["has_more"])
        self.assertEqual(first["next_cursor"], 2)
        self.assertTrue(ROW_KEYS <= set(first["rows"][0]))
        self.assertEqual(first["rows"][0]["children_count"], 0)

        second = self.api.get(LOCATIONS_URL, {"limit": 2, "cursor": 2}).json()
        self.assertEqual(len(second["rows"]), 1)
        self.assertFalse(second["has_more"])
        self.assertIsNone(second["next_cursor"])

    def test_list_locations_filters(self):
        """Filter ``usage``/``warehouse_id``/``parent_id``/``active``/``search``."""
        warehouse = Warehouse.objects.create(code="WH", name="Gudang Utama")
        root = Location.objects.create(code="WH", name="Gudang Utama", usage=Location.Usage.VIEW)
        stock = Location.objects.create(
            code="WH/STOCK", name="Stok", parent=root, warehouse=warehouse
        )
        Location.objects.create(code="WH/LOST", name="Kehilangan", usage=Location.Usage.INVENTORY)
        Location.objects.create(code="WH/OFF", name="Nonaktif", is_active=False)

        by_usage = self.api.get(LOCATIONS_URL, {"usage": "inventory"}).json()
        self.assertEqual([row["code"] for row in by_usage["rows"]], ["WH/LOST"])

        by_warehouse = self.api.get(LOCATIONS_URL, {"warehouse_id": warehouse.pk}).json()
        self.assertEqual([row["code"] for row in by_warehouse["rows"]], ["WH/STOCK"])

        by_parent = self.api.get(LOCATIONS_URL, {"parent_id": root.pk}).json()
        self.assertEqual([row["code"] for row in by_parent["rows"]], ["WH/STOCK"])

        by_active = self.api.get(LOCATIONS_URL, {"active": "false"}).json()
        self.assertEqual([row["code"] for row in by_active["rows"]], ["WH/OFF"])

        by_search = self.api.get(LOCATIONS_URL, {"search": "stock"}).json()
        self.assertEqual([row["code"] for row in by_search["rows"]], ["WH/STOCK"])

        self.assertEqual(self.api.get(LOCATIONS_URL, {"usage": "internal"}).json()["total_count"], 2)
        self.assertEqual(stock.usage, Location.Usage.INTERNAL)  # default

    def test_list_locations_invalid_params_400(self):
        """Parameter list ngawur → 400 (bukan 500)."""
        cases = (
            {"limit": "nol"},
            {"limit": "0"},
            {"limit": "201"},
            {"cursor": "-1"},
            {"warehouse_id": "gudang"},
            {"parent_id": "induk"},
            {"active": "kadang"},
        )

        for params in cases:
            with self.subTest(params=params):
                response = self.api.get(LOCATIONS_URL, params)
                self.assertEqual(response.status_code, 400)
                self.assertIn("detail", response.json())

    # -------------------------------------------------------------------- izin
    def test_anonymous_forbidden(self):
        """Tanpa kredensial → 403 untuk semua metode (GET/POST/PUT/DELETE)."""
        location = Location.objects.create(code="WH/STOCK", name="Stok")
        client = APIClient()

        self.assertEqual(client.get(LOCATIONS_URL).status_code, 403)
        self.assertEqual(client.post(LOCATIONS_URL, VALID_BODY, format="json").status_code, 403)
        self.assertEqual(client.get(detail_url(location.pk)).status_code, 403)
        self.assertEqual(
            client.put(detail_url(location.pk), {"name": "X"}, format="json").status_code, 403
        )
        self.assertEqual(client.delete(detail_url(location.pk)).status_code, 403)

    def test_non_admin_roles_read_only(self):
        """Role non-ADMIN/OWNER: GET 200, tapi POST/PUT/DELETE 403 (tanpa efek)."""
        location = Location.objects.create(code="WH/STOCK", name="Stok")

        for name, client in self.readonly_apis.items():
            with self.subTest(role=name):
                self.assertEqual(client.get(LOCATIONS_URL).status_code, 200)

                self.assertEqual(
                    client.post(LOCATIONS_URL, VALID_BODY, format="json").status_code, 403
                )
                self.assertEqual(
                    client.put(detail_url(location.pk), {"name": "X"}, format="json").status_code,
                    403,
                )
                self.assertEqual(client.delete(detail_url(location.pk)).status_code, 403)

        self.assertEqual(Location.objects.count(), 1)
        location.refresh_from_db()
        self.assertEqual(location.name, "Stok")
        self.assertTrue(location.is_active)

    # --------------------------------------------- idempotensi & audit (H1.4)
    def test_syncrecord_written_on_create(self):
        """POST → ``SyncRecord`` PENDING (``master.location`` / ``MASTER_PUSH``)."""
        response, _ = self.post_location(VALID_BODY)
        location_id = response.json()["id"]

        record = SyncRecord.objects.get(
            resource=SyncResource.MASTER_LOCATION.value,
            resource_id=str(location_id),
            stage=SyncStage.MASTER_PUSH.value,
        )
        self.assertEqual(record.status, SyncStatus.PENDING)
        self.assertEqual(record.payload["code"], "WH/STOCK")
        self.assertEqual(record.payload["usage"], "internal")
        self.assertIsNone(record.payload["parent_id"])
        self.assertIsNone(record.payload["warehouse_id"])
        self.assertIs(record.payload["active"], True)
        self.assertIsNone(record.erp_id)

    def test_auditlog_written_on_create(self):
        """POST → ``AuditLog`` ``master.create`` dengan resource ``master.location``."""
        response, _ = self.post_location(VALID_BODY)
        location_id = response.json()["id"]

        log = AuditLog.objects.get(action="master.create", resource_id=str(location_id))
        self.assertEqual(log.resource, "master.location")
        self.assertEqual(log.result, AuditLog.Result.OK)
        self.assertEqual(log.user_id, self.admin.pk)
        self.assertEqual(log.payload["code"], "WH/STOCK")

    def test_update_and_delete_reuse_syncrecord_and_write_audit(self):
        """PUT lalu DELETE memakai SATU ``SyncRecord`` + audit keduanya."""
        location = Location.objects.create(code="WH/STOCK", name="Stok")

        self.put_location(location.pk, {"name": "Stok Baru"})
        response, _ = self.delete_location(location.pk)

        records = SyncRecord.objects.filter(
            resource=SyncResource.MASTER_LOCATION.value, resource_id=str(location.pk)
        )
        self.assertEqual(records.count(), 1)

        record = records.get()
        self.assertEqual(record.stage, SyncStage.MASTER_PUSH.value)
        self.assertEqual(record.status, SyncStatus.PENDING)
        self.assertIs(record.payload["active"], False)  # payload terbaru = soft delete
        self.assertEqual(record.payload["name"], "Stok Baru")
        self.assertEqual(record.pk, response.json()["sync_record_id"])

        actions = set(
            AuditLog.objects.filter(resource_id=str(location.pk)).values_list("action", flat=True)
        )
        self.assertEqual(actions, {"master.update", "master.delete"})

    # --------------------------------------------------------------- push task
    @override_settings(ERP_ADAPTER="null")
    def test_push_task_enqueued_and_null_mode_marks_sent(self):
        """Task ``erp_sync.push_master_location``: no-op mode null → SENT + idempotent."""
        response, enqueue = self.post_location(VALID_BODY)
        body = response.json()
        enqueue.assert_called_once()

        result = push_master_location.apply(args=[body["id"], body["sync_record_id"]]).get()

        self.assertEqual(result["status"], "sent")
        self.assertTrue(str(result["erp_id"]).startswith("NULL-"))
        self.assertEqual(result["resource"], SyncResource.MASTER_LOCATION.value)

        record = SyncRecord.objects.get(pk=body["sync_record_id"])
        self.assertEqual(record.status, SyncStatus.SENT)
        self.assertIsNotNone(record.sent_at)

        # Percobaan push ikut diaudit (pola `integrations/erp_sync/audit.py`).
        self.assertTrue(
            AuditLog.objects.filter(
                action="erp_sync.push_master_location", resource_id=str(body["id"])
            ).exists()
        )

        again = push_master_location.apply(args=[body["id"], body["sync_record_id"]]).get()
        self.assertEqual(again["status"], "duplicate-ignored")

    @override_settings(ERP_ADAPTER="odoo")
    def test_push_task_odoo_mode_parent_without_odoo_id_marks_failed(self):
        """Induk belum punya ``odoo_id`` → **FAILED** dengan pesan jelas (tanpa jaringan).

        ``MasterPushError`` dilempar di ``_location_odoo_values`` sebelum transport
        dipakai (klien Odoo dibuat lazy, tanpa login), jadi test tidak menyentuh Odoo
        nyata dan tidak di-retry (bukan error transport).
        """
        parent = Location.objects.create(code="WH", name="Gudang Utama")
        child = Location.objects.create(code="WH/STOCK", name="Stok", parent=parent)

        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-loc-4")):
            response = self.api.post(
                LOCATIONS_URL,
                {"code": "WH/STOCK/A", "name": "Rak A", "parent_id": child.pk},
                format="json",
            )
        body = response.json()
        self.assertEqual(response.status_code, 201)

        with self.assertRaises(MasterPushError) as ctx:
            push_master_location.apply(args=[body["id"], body["sync_record_id"]]).get()

        self.assertIn("odoo_id", str(ctx.exception))

        record = SyncRecord.objects.get(pk=body["sync_record_id"])
        self.assertEqual(record.status, SyncStatus.FAILED)
        self.assertEqual(record.attempts, 1)
        self.assertIsNone(record.erp_id)

    def test_location_odoo_values_mapping(self):
        """Pemetaan payload → ``stock.location``: wajib name+usage, ``warehouse_id`` TIDAK dikirim."""
        warehouse = Warehouse.objects.create(code="WH", name="Gudang Utama")
        parent = Location.objects.create(code="WH", name="Gudang Utama", odoo_id=7)
        location = Location.objects.create(
            code="WH/STOCK",
            name="Stok",
            usage=Location.Usage.INTERNAL,
            parent=parent,
            warehouse=warehouse,
        )

        values = _location_odoo_values(location, location_payload(location))

        self.assertEqual(values, {"name": "Stok", "usage": "internal", "active": True, "location_id": 7})
        self.assertNotIn("warehouse_id", values)  # diturunkan Odoo dari hierarki

        # Tanpa induk: lokasi dibuat di root Odoo (sah) — tanpa `location_id`.
        location.parent = None
        location.save(update_fields=("parent",))
        self.assertNotIn("location_id", _location_odoo_values(location, location_payload(location)))

        # ``usage`` bohong ditolak sebelum menyentuh Odoo.
        with self.assertRaises(MasterPushError):
            _location_odoo_values(location, {"name": "Stok", "usage": "melayang"})

        # ``name`` kosong ditolak (field wajib Odoo).
        with self.assertRaises(MasterPushError):
            _location_odoo_values(location, {"name": "  ", "usage": "internal"})

