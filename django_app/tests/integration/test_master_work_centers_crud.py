"""Test CRUD master Work Center — ``/api/v1/master/work-centers/`` (H1.7).

Cakupan: list (pagination/filter `search`/`wc_type`/`active`), detail (dengan
``active_bundles_count`` + ``production_lines``), create (code & name wajib),
update (hanya field yang dikirim), **soft delete + guard bundle aktif**, izin
(anon 403, role non-admin 403), validasi 400 (kode duplikat case-insensitive,
tag kapabilitas harus array string ≤ 20 × 32, capacity ≥ 0, wc_type ≤ 64), serta
kewajiban H1.7: ``SyncRecord`` (``master.work_center``/``MASTER_PUSH``, status
**``SKIPPED``** karena MES-only) + ``AuditLog`` tiap POST/PUT/DELETE.

Probe Odoo 17 ``mrp.workcenter`` (STEP 0) → keputusan H1.7 **MES-only**:
  * field wajib create = ``resource_id`` (``resource.resource``, **tanpa default**)
    + ``sequence``; tidak ada padanan ``wc_type``/``capability_tags``/``capacity_per_hour``;
  * jadi TIDAK ada task push & TIDAK ada pull; ledger sync ditandai ``SKIPPED``
    supaya tetap terlihat di ``GET /api/v1/sync/records/?status=SKIPPED``.

Non-breaking: konsumen WC existing (wc_queue, bottleneck_detector,
capability_allocator, production_lines M2M) diuji ulang di test terakhir.

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_master_work_centers_crud.py -q
"""

from __future__ import annotations

from uuid import uuid4

from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.models import Bundle, ProductionLine, WorkCenter
from apps_industry.garment.services.bottleneck_detector import BottleneckDetector
from apps_industry.garment.services.capability_allocator import CapabilityAllocator
from apps_industry.garment.services.wc_queue import WCQueue
from apps_industry.garment.tests.factories import (
    make_line,
    make_routing,
    make_step,
    make_work_order,
)
from core.audit.models import AuditLog
from core.auth.models import Role, User
from integrations.erp_sync.models import SyncRecord, SyncResource, SyncStage, SyncStatus
from master.work_center_services import MES_ONLY_REASON

WORK_CENTERS_URL = "/api/v1/master/work-centers/"
ENVELOPE_KEYS = {"rows", "total_count", "has_more", "next_cursor"}
ROW_KEYS = {
    "id",
    "code",
    "name",
    "wc_type",
    "capability_tags",
    "capacity_per_hour",
    "description",
    "active",
    "config",
    "created_at",
    "updated_at",
}
DETAIL_KEYS = ROW_KEYS | {"active_bundles_count", "production_lines"}


def detail_url(pk: int) -> str:
    """URL detail work center."""
    return f"{WORK_CENTERS_URL}{pk}/"


def make_bundle_at(work_center: WorkCenter, state: str = "DRAFT") -> Bundle:
    """Bundle yang berada di queue `work_center` (dipakai guard soft delete)."""
    return Bundle.objects.create(
        code=f"BND-{uuid4().hex[:8].upper()}",
        work_order=make_work_order(),
        qty=5,
        state=state,
        current_work_center=work_center,
    )


class MasterWorkCentersCrudTests(TestCase):
    """GET/POST/PUT/DELETE + validasi + ledger sync SKIPPED (MES-only) + guard bundle."""

    @classmethod
    def setUpTestData(cls):
        """4 user: admin, operator, qc, purchasing (uji 403 untuk 3 role terakhir)."""
        cls.admin = User.objects.create_user(
            username="admin-wc",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.ADMIN),
        )
        cls.operator = User.objects.create_user(
            username="op-wc",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.OPERATOR),
        )
        cls.qc = User.objects.create_user(
            username="qc-wc",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.QC),
        )
        cls.purchasing = User.objects.create_user(
            username="beli-wc",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.PURCHASING),
        )

    def setUp(self):
        """Klien admin (utama) + klien role lain (uji 403)."""
        self.api = APIClient()
        self.api.force_authenticate(self.admin)

        self.readonly_apis = {}
        for name, user in (
            ("operator", self.operator),
            ("qc", self.qc),
            ("purchasing", self.purchasing),
        ):
            client = APIClient()
            client.force_authenticate(user)
            self.readonly_apis[name] = client

    # ------------------------------------------------------------------ helper
    def work_center_body(self, **overrides) -> dict:
        """Body create/update WC valid (default: stasiun jahit)."""
        body = {
            "code": "SEWING-1",
            "name": "Stasiun Jahit 1",
            "wc_type": "SEWING",
            "capability_tags": ["JAHIT_LURUS", "OBRAS"],
            "capacity_per_hour": "40.50",
            "description": "Meja jahit utama",
            "active": True,
        }
        body.update(overrides)

        return body

    def make_work_center(self, code: str = "WC-EXISTING", **overrides) -> WorkCenter:
        """WC tersimpan langsung (tanpa API) untuk test non-create."""
        return WorkCenter.objects.create(
            code=code,
            name=overrides.pop("name", "Stasiun Existing"),
            **overrides,
        )

    def post_work_center(self, body: dict, client=None):
        """POST work center (tidak ada enqueue — H1.7 MES-only)."""
        return (client or self.api).post(WORK_CENTERS_URL, body, format="json")

    def put_work_center(self, pk: int, body: dict, client=None):
        """PUT work center."""
        return (client or self.api).put(detail_url(pk), body, format="json")

    # ------------------------------------------------------------ POST / create
    def test_create_work_center_ok(self):
        """POST → 201 + field H1.7 tersimpan + ledger SKIPPED (tanpa task push)."""
        response = self.post_work_center(self.work_center_body())

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertTrue(ROW_KEYS <= set(body))
        self.assertTrue(DETAIL_KEYS <= set(body))
        self.assertEqual(body["code"], "SEWING-1")
        self.assertEqual(body["wc_type"], "SEWING")
        self.assertEqual(body["capability_tags"], ["JAHIT_LURUS", "OBRAS"])
        self.assertEqual(body["capacity_per_hour"], 40.5)  # desimal 2 angka → float
        self.assertIs(body["active"], True)
        self.assertEqual(body["active_bundles_count"], 0)
        self.assertEqual(body["production_lines"], [])

        # MES-only: ledger ada tapi SKIPPED, tanpa task/queue.
        self.assertIsNotNone(body["sync_record_id"])
        self.assertEqual(body["sync_status"], "SKIPPED")
        self.assertIsNone(body["task_id"])
        self.assertIs(body["queued"], False)
        self.assertIs(body["mes_only"], True)

        work_center = WorkCenter.objects.get(pk=body["id"])
        self.assertEqual(str(work_center.capacity_per_hour), "40.50")
        self.assertEqual(work_center.config, {})  # field lama tetap

    def test_create_work_center_no_push_module(self):
        """Tidak ada fungsi push/pull WC sama sekali (keputusan MES-only)."""
        from integrations.erp_sync import tasks_master, tasks_master_push

        self.assertFalse(hasattr(tasks_master_push, "push_master_work_center"))
        self.assertFalse(hasattr(tasks_master, "_work_center_defaults"))
        self.assertFalse(hasattr(tasks_master, "sync_master_work_centers"))

    def test_create_work_center_code_name_wajib_400(self):
        """``code`` & ``name`` wajib (kode TIDAK dibangkitkan otomatis seperti BOM/Partner)."""
        for overrides, needle in (({"code": "   "}, "code' wajib"), ({"name": ""}, "name' wajib")):
            with self.subTest(overrides=overrides):
                response = self.post_work_center(self.work_center_body(**overrides))
                self.assertEqual(response.status_code, 400)
                self.assertIn(needle, response.json()["detail"])

        self.assertEqual(WorkCenter.objects.count(), 0)

    def test_create_work_center_duplicate_code_400_case_insensitive(self):
        """Kode duplikat (beda kapitalisasi) → 400, tanpa baris baru & tanpa ledger."""
        self.make_work_center(code="WC-JAHIT")

        response = self.post_work_center(self.work_center_body(code="wc-jahit"))

        self.assertEqual(response.status_code, 400)
        self.assertIn("sudah dipakai", response.json()["detail"])
        self.assertEqual(WorkCenter.objects.count(), 1)
        self.assertFalse(
            SyncRecord.objects.filter(resource=SyncResource.MASTER_WORK_CENTER.value).exists()
        )

    def test_create_work_center_invalid_payload_400(self):
        """Validasi: tag bukan array/elemen non-string, capacity negatif/ngawur, dll."""
        cases = (
            ({"capability_tags": "OBRAS"}, "array string"),
            ({"capability_tags": [1, 2]}, "array string"),
            ({"capability_tags": ["X" * 33]}, "maksimal 32 karakter"),
            ({"capability_tags": [f"TAG{i}" for i in range(21)]}, "maksimal 20 buah"),
            ({"capacity_per_hour": "-1"}, "angka >= 0"),
            ({"capacity_per_hour": "empat puluh"}, "angka >= 0"),
            ({"capacity_per_hour": "999999999.99"}, "maksimal"),
            ({"capacity_per_hour": True}, "angka >= 0"),
            ({"wc_type": "T" * 65}, "maksimal 64 karakter"),
            ({"active": "kadang"}, "active"),
            ({"name": "N" * 151}, "maksimal"),
            ({"code": "C" * 65}, "maksimal"),
            ({"description": "D" * 2001}, "maksimal"),
        )

        for overrides, needle in cases:
            with self.subTest(overrides=overrides):
                response = self.post_work_center(self.work_center_body(**overrides))
                self.assertEqual(response.status_code, 400)
                self.assertIn(needle, response.json()["detail"])

        self.assertEqual(WorkCenter.objects.count(), 0)

    def test_create_work_center_tags_trim_dedup_case_insensitive(self):
        """Tag di-trim, dedupe case-insensitive (yang pertama menang), huruf dipertahankan."""
        response = self.post_work_center(
            self.work_center_body(capability_tags=["  OBRAS ", "obras", "", "  ", "Overdeck"])
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["capability_tags"], ["OBRAS", "Overdeck"])

    # ------------------------------------------------------------ PUT / detail
    def test_update_work_center_ok(self):
        """PUT mengubah hanya field yang dikirim (200) + audit ``master.update``."""
        work_center = self.make_work_center(wc_type="SEWING", capacity_per_hour=10)

        response = self.put_work_center(
            work_center.pk,
            {"wc_type": "FINISHING", "capacity_per_hour": "12.75", "description": "Meja packing"},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["wc_type"], "FINISHING")
        self.assertEqual(body["capacity_per_hour"], 12.75)
        self.assertEqual(body["description"], "Meja packing")
        self.assertEqual(body["code"], "WC-EXISTING")  # tidak dikirim → tetap
        self.assertEqual(body["name"], "Stasiun Existing")
        self.assertEqual(body["sync_status"], "SKIPPED")

        work_center.refresh_from_db()
        self.assertEqual(work_center.wc_type, "FINISHING")
        self.assertEqual(str(work_center.capacity_per_hour), "12.75")
        self.assertTrue(
            AuditLog.objects.filter(
                action="master.update",
                resource="master.work_center",
                resource_id=str(work_center.pk),
            ).exists()
        )

    def test_update_work_center_duplicate_code_400(self):
        """Ganti kode ke kode WC lain (case-insensitive) → 400, tidak berubah."""
        first = self.make_work_center(code="SEWING-1")
        second = self.make_work_center(code="SEWING-2")

        response = self.put_work_center(second.pk, {"code": "sewing-1"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("sudah dipakai", response.json()["detail"])
        second.refresh_from_db()
        self.assertEqual(second.code, "SEWING-2")
        first.refresh_from_db()
        self.assertEqual(first.code, "SEWING-1")

    def test_update_work_center_same_code_ok(self):
        """Mengirim kode sendiri (tidak berubah) bukan duplikat → 200 + ledger ditulis."""
        work_center = self.make_work_center(code="SEWING-1")

        response = self.put_work_center(work_center.pk, {"code": "SEWING-1"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["sync_status"], "SKIPPED")

    def test_update_work_center_empty_body_no_syncrecord(self):
        """PUT tanpa satu pun field → 200 tanpa ledger/audit."""
        work_center = self.make_work_center()

        response = self.put_work_center(work_center.pk, {})

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["sync_record_id"])
        self.assertIsNone(response.json()["sync_status"])
        self.assertFalse(
            SyncRecord.objects.filter(resource=SyncResource.MASTER_WORK_CENTER.value).exists()
        )
        self.assertFalse(AuditLog.objects.filter(resource_id=str(work_center.pk)).exists())

    def test_detail_and_missing_work_center_404(self):
        """GET detail → 200 (+ ``active_bundles_count``); id tak dikenal → 404."""
        work_center = self.make_work_center(wc_type="QC", capability_tags=["INSPECT"])

        detail = self.api.get(detail_url(work_center.pk))
        self.assertEqual(detail.status_code, 200)
        body = detail.json()
        self.assertTrue(DETAIL_KEYS <= set(body))
        self.assertEqual(body["wc_type"], "QC")
        self.assertEqual(body["capability_tags"], ["INSPECT"])
        self.assertEqual(body["active_bundles_count"], 0)
        self.assertEqual(body["production_lines"], [])

        self.assertEqual(self.api.get(detail_url(999999)).status_code, 404)
        self.assertEqual(
            self.api.put(detail_url(999999), {"name": "X"}, format="json").status_code, 404
        )
        self.assertEqual(self.api.delete(detail_url(999999)).status_code, 404)

    def test_detail_menampilkan_line_produksi_dan_bundle_aktif(self):
        """Detail memuat M2M ``production_lines`` + jumlah bundle aktif (non-breaking)."""
        work_center = self.make_work_center(code="SEWING-1")
        line = make_line(code="LINE-A", work_centers=[work_center])
        bundle = make_bundle_at(work_center)  # state DRAFT = aktif
        bundle.state = "DONE"
        bundle.save(update_fields=("state",))
        make_bundle_at(work_center)  # satu bundle aktif tersisa

        body = self.api.get(detail_url(work_center.pk)).json()

        self.assertEqual(body["active_bundles_count"], 1)
        self.assertEqual(
            body["production_lines"], [{"id": line.pk, "code": "LINE-A", "name": "LINE-A"}]
        )
        self.assertEqual(ProductionLine.objects.count(), 1)

    # ------------------------------------------------------- DELETE (soft + guard)
    def test_delete_work_center_soft_delete(self):
        """DELETE tanpa bundle aktif → 200 soft delete; baris MASIH ada di DB."""
        work_center = self.make_work_center()

        response = self.api.delete(detail_url(work_center.pk))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["id"], work_center.pk)
        self.assertTrue(body["deleted"])
        self.assertFalse(body["active"])
        self.assertEqual(body["sync_status"], "SKIPPED")
        self.assertIs(body["mes_only"], True)

        work_center.refresh_from_db()
        self.assertFalse(work_center.is_active)
        self.assertTrue(WorkCenter.objects.filter(pk=work_center.pk).exists())
        self.assertTrue(
            AuditLog.objects.filter(
                action="master.delete",
                resource="master.work_center",
                resource_id=str(work_center.pk),
            ).exists()
        )

    def test_delete_work_center_blocked_by_active_bundle(self):
        """Guard: bundle aktif (state bukan DONE/CANCELLED) → 400, WC tetap aktif."""
        work_center = self.make_work_center(code="SEWING-1")
        make_bundle_at(work_center, state="IN_PROGRESS")

        response = self.api.delete(detail_url(work_center.pk))

        self.assertEqual(response.status_code, 400)
        self.assertIn("bundle aktif", response.json()["detail"])

        work_center.refresh_from_db()
        self.assertTrue(work_center.is_active)
        self.assertFalse(
            AuditLog.objects.filter(
                action="master.delete", resource_id=str(work_center.pk)
            ).exists()
        )

    def test_delete_work_center_allowed_when_bundles_done(self):
        """Bundle historis (DONE/CANCELLED) TIDAK menghalangi soft delete."""
        work_center = self.make_work_center()
        make_bundle_at(work_center, state="DONE")
        make_bundle_at(work_center, state="CANCELLED")

        response = self.api.delete(detail_url(work_center.pk))

        self.assertEqual(response.status_code, 200)
        work_center.refresh_from_db()
        self.assertFalse(work_center.is_active)

    # ------------------------------------------------------------------- GET list
    def test_list_work_centers_pagination_and_envelope(self):
        """Envelope ListPage + pagination + urut ``code``."""
        for index in range(3):
            self.make_work_center(code=f"WC-{index}", name=f"Stasiun {index}")

        first = self.api.get(WORK_CENTERS_URL, {"limit": 2}).json()
        self.assertEqual(set(first), ENVELOPE_KEYS)
        self.assertEqual(first["total_count"], 3)
        self.assertEqual([row["code"] for row in first["rows"]], ["WC-0", "WC-1"])
        self.assertTrue(first["has_more"])
        self.assertEqual(first["next_cursor"], 2)
        self.assertTrue(ROW_KEYS <= set(first["rows"][0]))
        self.assertNotIn("active_bundles_count", first["rows"][0])  # hanya di detail

        second = self.api.get(WORK_CENTERS_URL, {"limit": 2, "cursor": 2}).json()
        self.assertEqual(len(second["rows"]), 1)
        self.assertFalse(second["has_more"])
        self.assertIsNone(second["next_cursor"])

    def test_list_work_centers_filters(self):
        """Filter ``search`` (code/name/wc_type), ``wc_type`` (iexact), ``active``."""
        self.make_work_center(code="SEWING-1", name="Stasiun Jahit", wc_type="SEWING")
        self.make_work_center(code="CUTTING-1", name="Meja Potong", wc_type="CUTTING")
        self.make_work_center(code="QC-1", name="Inspeksi", wc_type="QC", is_active=False)

        by_name = self.api.get(WORK_CENTERS_URL, {"search": "potong"}).json()
        self.assertEqual([row["code"] for row in by_name["rows"]], ["CUTTING-1"])

        by_code = self.api.get(WORK_CENTERS_URL, {"search": "qc-1"}).json()
        self.assertEqual([row["code"] for row in by_code["rows"]], ["QC-1"])

        by_type_search = self.api.get(WORK_CENTERS_URL, {"search": "sewing"}).json()
        self.assertEqual([row["code"] for row in by_type_search["rows"]], ["SEWING-1"])

        by_type = self.api.get(WORK_CENTERS_URL, {"wc_type": "sewing"}).json()
        self.assertEqual([row["code"] for row in by_type["rows"]], ["SEWING-1"])

        inactive = self.api.get(WORK_CENTERS_URL, {"active": "false"}).json()
        self.assertEqual([row["code"] for row in inactive["rows"]], ["QC-1"])

        active = self.api.get(WORK_CENTERS_URL, {"active": "true"}).json()
        self.assertEqual([row["code"] for row in active["rows"]], ["CUTTING-1", "SEWING-1"])

    def test_list_work_centers_invalid_params_400(self):
        """Parameter list ngawur → 400 (bukan 500)."""
        cases = (
            {"limit": "nol"},
            {"limit": "0"},
            {"limit": "201"},
            {"cursor": "-1"},
            {"active": "kadang"},
        )

        for params in cases:
            with self.subTest(params=params):
                response = self.api.get(WORK_CENTERS_URL, params)
                self.assertEqual(response.status_code, 400)
                self.assertIn("detail", response.json())

    # -------------------------------------------------------------------- izin
    def test_anonymous_forbidden(self):
        """Tanpa kredensial → 403 untuk semua metode (GET/POST/PUT/DELETE)."""
        work_center = self.make_work_center()
        client = APIClient()

        self.assertEqual(client.get(WORK_CENTERS_URL).status_code, 403)
        self.assertEqual(
            client.post(WORK_CENTERS_URL, self.work_center_body(), format="json").status_code, 403
        )
        self.assertEqual(client.get(detail_url(work_center.pk)).status_code, 403)
        self.assertEqual(
            client.put(detail_url(work_center.pk), {"name": "X"}, format="json").status_code, 403
        )
        self.assertEqual(client.delete(detail_url(work_center.pk)).status_code, 403)

    def test_non_admin_roles_read_only(self):
        """Role non-ADMIN/OWNER: GET 200, tapi POST/PUT/DELETE 403 (tanpa efek)."""
        work_center = self.make_work_center()

        for name, client in self.readonly_apis.items():
            with self.subTest(role=name):
                self.assertEqual(client.get(WORK_CENTERS_URL).status_code, 200)
                self.assertEqual(
                    client.post(
                        WORK_CENTERS_URL, self.work_center_body(code="WC-BARU"), format="json"
                    ).status_code,
                    403,
                )
                self.assertEqual(
                    client.put(detail_url(work_center.pk), {"name": "X"}, format="json").status_code,
                    403,
                )
                self.assertEqual(client.delete(detail_url(work_center.pk)).status_code, 403)

        self.assertEqual(WorkCenter.objects.count(), 1)
        work_center.refresh_from_db()
        self.assertEqual(work_center.name, "Stasiun Existing")
        self.assertTrue(work_center.is_active)

    # --------------------------------------------- ledger sync (SKIPPED) & audit
    def test_syncrecord_written_as_skipped_on_create(self):
        """POST → ``SyncRecord`` ``master.work_center``/``MASTER_PUSH`` status SKIPPED."""
        response = self.post_work_center(self.work_center_body())

        record = SyncRecord.objects.get(
            resource=SyncResource.MASTER_WORK_CENTER.value,
            resource_id=str(response.json()["id"]),
            stage=SyncStage.MASTER_PUSH.value,
        )
        self.assertEqual(record.status, SyncStatus.SKIPPED)
        self.assertEqual(record.last_error, MES_ONLY_REASON)
        self.assertIsNone(record.erp_id)
        self.assertIsNone(record.sent_at)
        self.assertEqual(record.payload["code"], "SEWING-1")
        self.assertEqual(record.payload["capability_tags"], ["JAHIT_LURUS", "OBRAS"])
        self.assertEqual(record.payload["capacity_per_hour"], 40.5)

    def test_auditlog_written_on_create(self):
        """POST → ``AuditLog`` ``master.create`` resource ``master.work_center``."""
        response = self.post_work_center(self.work_center_body())

        log = AuditLog.objects.get(action="master.create", resource_id=str(response.json()["id"]))
        self.assertEqual(log.resource, "master.work_center")
        self.assertEqual(log.user_id, self.admin.pk)
        self.assertIs(log.metadata["mes_only"], True)
        self.assertEqual(log.payload["code"], "SEWING-1")

    def test_update_and_delete_reuse_syncrecord_and_write_audit(self):
        """PUT lalu DELETE memakai SATU ``SyncRecord`` (SKIPPED) + audit keduanya."""
        work_center = self.make_work_center()

        self.put_work_center(work_center.pk, {"capacity_per_hour": "7.25"})
        response = self.api.delete(detail_url(work_center.pk))

        records = SyncRecord.objects.filter(
            resource=SyncResource.MASTER_WORK_CENTER.value, resource_id=str(work_center.pk)
        )
        self.assertEqual(records.count(), 1)

        record = records.get()
        self.assertEqual(record.status, SyncStatus.SKIPPED)
        self.assertIs(record.payload["active"], False)  # payload terbaru = soft delete
        self.assertEqual(record.payload["capacity_per_hour"], 7.25)
        self.assertEqual(record.pk, response.json()["sync_record_id"])

        actions = set(
            AuditLog.objects.filter(resource_id=str(work_center.pk)).values_list(
                "action", flat=True
            )
        )
        self.assertEqual(actions, {"master.update", "master.delete"})

    def test_sync_status_skipped_enum_dan_mark_skipped(self):
        """``SyncStatus.SKIPPED`` resmi ada; ``mark_skipped`` menyimpan alasan."""
        self.assertIn("SKIPPED", list(SyncStatus.values))

        from integrations.erp_sync.idempotency import SyncIdempotency

        record = SyncRecord.objects.create(
            resource=SyncResource.MASTER_WORK_CENTER.value,
            resource_id="123",
            stage=SyncStage.MASTER_PUSH.value,
        )
        SyncIdempotency().mark_skipped(record, "alasan uji")

        record.refresh_from_db()
        self.assertEqual(record.status, SyncStatus.SKIPPED)
        self.assertEqual(record.last_error, "alasan uji")
        self.assertFalse(SyncIdempotency().is_already_sent(record))

    def test_sync_records_filter_status_skipped(self):
        """Ledger WC terlihat di endpoint monitor: ``?status=SKIPPED``."""
        self.post_work_center(self.work_center_body())

        response = self.api.get("/api/v1/sync/records/", {"status": "SKIPPED"})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total_count"], 1)
        self.assertEqual(body["rows"][0]["status"], "SKIPPED")
        self.assertEqual(body["rows"][0]["resource"], "master.work_center")

    # ---------------------------------------------- non-breaking konsumen existing
    def test_non_breaking_konsumen_wc_existing(self):
        """WC hasil API tetap bisa dipakai queue/detector/allocator (field baru aditif)."""
        response = self.post_work_center(self.work_center_body(code="SEWING-1"))
        work_center = WorkCenter.objects.get(pk=response.json()["id"])

        # wc_queue: enqueue bundle ke WC ini → queue berisi 1 bundle.
        bundle = make_bundle_at(work_center)
        self.assertEqual(WCQueue().count(work_center), 1)
        self.assertEqual(list(WCQueue().get_queue(work_center)), [bundle])

        # bottleneck_detector: queue depth terbaca (read-only).
        report = BottleneckDetector().detect(work_center)
        self.assertEqual(report.work_center.pk, work_center.pk)
        self.assertEqual(report.queue_depth, 1)
        self.assertFalse(report.is_bottleneck)

        # capability_allocator: line yang memuat WC ini jadi kandidat routing-nya.
        line = make_line(code="LINE-A", work_centers=[work_center])
        routing = make_routing(code="ROUTE-A")
        make_step(routing, "CUT", 1, work_center=work_center)
        work_order = make_work_order()
        candidates = CapabilityAllocator().candidates(work_order, routing)
        self.assertEqual([candidate.pk for candidate in candidates], [line.pk])

        # Field baru tidak mengganggu pembacaan lama (config tetap tersedia).
        self.assertEqual(work_center.config, {})
        self.assertTrue(WorkCenter.objects.filter(is_active=True, code="SEWING-1").exists())




