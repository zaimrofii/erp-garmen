"""Test CRUD master Production Line — ``/api/v1/master/production-lines/`` (H1.8).

Cakupan: list (pagination/filter `search`/`capability_tag`/`work_center`/`active`),
detail (dengan ``work_centers[]`` + ``active_bundles_count``), create (code & name
wajib, M2M `work_centers` opsional), update (**replace M2M atomic**), **soft delete +
guard bundle aktif**, izin (anon 403, role non-admin 403), validasi 400 (kode duplikat
case-insensitive, id WC tidak dikenal / bukan angka, tag ≤ 20 × 32), serta kewajiban
H1.8: ``SyncRecord`` (``master.production_line``/``MASTER_PUSH``, status **``SKIPPED``**
karena MES-only) + ``AuditLog`` tiap POST/PUT/DELETE.

Probe Odoo 17 (STEP 0) → keputusan H1.8 **MES-only**:
  * ``mrp.routing`` **tidak ada lagi** (Fault: objek tidak ada — Routing dihapus sejak
    Odoo 15); ``mrp.routing.workcenter`` = **Operation** (wajib ``bom_id`` +
    ``workcenter_id`` + ``name``, tanpa ``code``/``routing_id``) → Odoo tidak punya
    wadah "lini/kumpulan work center";
  * jadi TIDAK ada task push & TIDAK ada pull; ledger sync ditandai ``SKIPPED``.

Non-breaking: `capability_allocator` (alokasi lini superset WC) dan `LineAllocationRule`
diuji ulang di test terakhir memakai lini hasil API.

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_master_production_lines_crud.py -q
"""

from __future__ import annotations

from uuid import uuid4

from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.models import Bundle, LineAllocationRule, ProductionLine, WorkCenter
from apps_industry.garment.services.capability_allocator import CapabilityAllocator
from apps_industry.garment.tests.factories import make_routing, make_step, make_work_order
from core.audit.models import AuditLog
from core.auth.models import Role, User
from integrations.erp_sync.models import SyncRecord, SyncResource, SyncStage, SyncStatus
from master.production_line_services import MES_ONLY_REASON

LINES_URL = "/api/v1/master/production-lines/"
ENVELOPE_KEYS = {"rows", "total_count", "has_more", "next_cursor"}
ROW_KEYS = {
    "id",
    "code",
    "name",
    "description",
    "capability_tags",
    "work_centers_count",
    "work_center_ids",
    "work_center_names",
    "allocation_rules_count",
    "active",
    "created_at",
    "updated_at",
}
DETAIL_KEYS = ROW_KEYS | {"work_centers", "active_bundles_count"}


def detail_url(pk: int) -> str:
    """URL detail production line."""
    return f"{LINES_URL}{pk}/"


def make_bundle_at(production_line: ProductionLine, state: str = "DRAFT") -> Bundle:
    """Bundle yang teratribusi ke lini (dipakai guard soft delete)."""
    return Bundle.objects.create(
        code=f"BND-{uuid4().hex[:8].upper()}",
        work_order=make_work_order(),
        qty=5,
        state=state,
        production_line=production_line,
    )


class MasterProductionLinesCrudTests(TestCase):
    """GET/POST/PUT/DELETE + M2M atomic + validasi + ledger SKIPPED (MES-only)."""

    @classmethod
    def setUpTestData(cls):
        """4 user: admin, operator, qc, purchasing (uji 403 untuk 3 role terakhir)."""
        cls.admin = User.objects.create_user(
            username="admin-line",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.ADMIN),
        )
        cls.operator = User.objects.create_user(
            username="op-line",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.OPERATOR),
        )
        cls.qc = User.objects.create_user(
            username="qc-line",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.QC),
        )
        cls.purchasing = User.objects.create_user(
            username="beli-line",
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
    def make_work_center(self, code: str) -> WorkCenter:
        """Work center langsung (tanpa API) untuk anggota lini."""
        return WorkCenter.objects.create(code=code, name=f"Stasiun {code}")

    def line_body(self, **overrides) -> dict:
        """Body create/update line valid (default: lini jahit tanpa anggota)."""
        body = {
            "code": "LINE-A",
            "name": "Lini Jahit A",
            "description": "Lini utama jahit",
            "capability_tags": ["JAHIT", "OBRAS"],
            "work_center_ids": [],
            "active": True,
        }
        body.update(overrides)

        return body

    def make_line(self, code: str = "LINE-EXISTING", **overrides) -> ProductionLine:
        """Lini tersimpan langsung (tanpa API) untuk test non-create."""
        return ProductionLine.objects.create(
            code=code,
            name=overrides.pop("name", "Lini Existing"),
            **overrides,
        )

    def post_line(self, body: dict, client=None):
        """POST production line (tidak ada enqueue — H1.8 MES-only)."""
        return (client or self.api).post(LINES_URL, body, format="json")

    def put_line(self, pk: int, body: dict, client=None):
        """PUT production line."""
        return (client or self.api).put(detail_url(pk), body, format="json")

    # ------------------------------------------------------------ POST / create
    def test_create_production_line_tanpa_work_center_ok(self):
        """POST tanpa anggota WC → 201 (M2M kosong sah) + ledger SKIPPED."""
        response = self.post_line(self.line_body())

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertTrue(ROW_KEYS <= set(body))
        self.assertTrue(DETAIL_KEYS <= set(body))
        self.assertEqual(body["code"], "LINE-A")
        self.assertEqual(body["capability_tags"], ["JAHIT", "OBRAS"])
        self.assertEqual(body["work_centers_count"], 0)
        self.assertEqual(body["work_center_ids"], [])
        self.assertEqual(body["work_center_names"], [])
        self.assertEqual(body["work_centers"], [])
        self.assertEqual(body["allocation_rules_count"], 0)
        self.assertEqual(body["active_bundles_count"], 0)
        self.assertIs(body["active"], True)

        self.assertIsNotNone(body["sync_record_id"])
        self.assertEqual(body["sync_status"], "SKIPPED")
        self.assertIsNone(body["task_id"])
        self.assertIs(body["queued"], False)
        self.assertIs(body["mes_only"], True)

    def test_create_production_line_dengan_work_centers_ok(self):
        """POST dengan anggota WC → M2M terisi & terekspor (ids + names)."""
        cutting = self.make_work_center("CUTTING-1")
        sewing = self.make_work_center("SEWING-1")

        response = self.post_line(
            self.line_body(work_center_ids=[sewing.pk, cutting.pk])
        )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["work_centers_count"], 2)
        self.assertEqual(body["work_center_names"], ["CUTTING-1", "SEWING-1"])  # urut kode
        self.assertEqual(sorted(body["work_center_ids"]), sorted([cutting.pk, sewing.pk]))
        self.assertEqual(
            body["work_centers"],
            [
                {"id": cutting.pk, "code": "CUTTING-1", "name": "Stasiun CUTTING-1"},
                {"id": sewing.pk, "code": "SEWING-1", "name": "Stasiun SEWING-1"},
            ],
        )

        production_line = ProductionLine.objects.get(pk=body["id"])
        self.assertEqual(production_line.work_centers.count(), 2)
        self.assertEqual(production_line.capability_tags, ["JAHIT", "OBRAS"])

    def test_create_production_line_no_push_module(self):
        """Tidak ada fungsi push/pull Production Line (keputusan MES-only)."""
        from integrations.erp_sync import tasks_master, tasks_master_push

        self.assertFalse(hasattr(tasks_master_push, "push_master_production_line"))
        self.assertFalse(hasattr(tasks_master, "_production_line_defaults"))
        self.assertFalse(hasattr(tasks_master, "sync_master_production_lines"))

    def test_create_production_line_code_name_wajib_400(self):
        """``code`` & ``name`` wajib (kode TIDAK dibangkitkan otomatis)."""
        for overrides, needle in (({"code": "  "}, "code' wajib"), ({"name": ""}, "name' wajib")):
            with self.subTest(overrides=overrides):
                response = self.post_line(self.line_body(**overrides))
                self.assertEqual(response.status_code, 400)
                self.assertIn(needle, response.json()["detail"])

        self.assertEqual(ProductionLine.objects.count(), 0)

    def test_create_production_line_duplicate_code_400_case_insensitive(self):
        """Kode duplikat (beda kapitalisasi) → 400, tanpa baris baru & tanpa ledger."""
        self.make_line(code="LINE-A")

        response = self.post_line(self.line_body(code="line-a"))

        self.assertEqual(response.status_code, 400)
        self.assertIn("sudah dipakai", response.json()["detail"])
        self.assertEqual(ProductionLine.objects.count(), 1)
        self.assertFalse(
            SyncRecord.objects.filter(resource=SyncResource.MASTER_PRODUCTION_LINE.value).exists()
        )

    def test_create_production_line_work_center_invalid_400(self):
        """Id WC tidak dikenal / bukan angka → 400 tanpa membuat lini (atomic)."""
        work_center = self.make_work_center("SEWING-1")

        cases = (
            ([work_center.pk, 999999], "tidak ditemukan"),
            (["bukan-angka"], "tidak valid"),
            ([0], "harus > 0"),
            ({"id": 1}, "harus array"),
        )

        for raw, needle in cases:
            with self.subTest(raw=raw):
                response = self.post_line(self.line_body(work_center_ids=raw))
                self.assertEqual(response.status_code, 400)
                self.assertIn(needle, response.json()["detail"])

        self.assertEqual(ProductionLine.objects.count(), 0)
        self.assertEqual(work_center.production_lines.count(), 0)

    def test_create_production_line_invalid_payload_400(self):
        """Validasi tag & teks (array string ≤ 20 × 32, panjang field)."""
        cases = (
            ({"capability_tags": "JAHIT"}, "array string"),
            ({"capability_tags": [1]}, "array string"),
            ({"capability_tags": ["X" * 33]}, "maksimal 32 karakter"),
            ({"capability_tags": [f"T{i}" for i in range(21)]}, "maksimal 20 buah"),
            ({"active": "kadang"}, "active"),
            ({"name": "N" * 151}, "maksimal"),
            ({"code": "C" * 65}, "maksimal"),
            ({"description": "D" * 2001}, "maksimal"),
        )

        for overrides, needle in cases:
            with self.subTest(overrides=overrides):
                response = self.post_line(self.line_body(**overrides))
                self.assertEqual(response.status_code, 400)
                self.assertIn(needle, response.json()["detail"])

        self.assertEqual(ProductionLine.objects.count(), 0)

    # ------------------------------------------------------------ PUT / detail
    def test_update_production_line_scalar_ok(self):
        """PUT mengubah field skalar (200) + audit ``master.update``."""
        production_line = self.make_line(capability_tags=["JAHIT"])

        response = self.put_line(
            production_line.pk, {"name": "Lini Baru", "capability_tags": ["JAHIT", "QC"]}
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["name"], "Lini Baru")
        self.assertEqual(body["capability_tags"], ["JAHIT", "QC"])
        self.assertEqual(body["code"], "LINE-EXISTING")  # tidak dikirim → tetap
        self.assertEqual(body["sync_status"], "SKIPPED")

        production_line.refresh_from_db()
        self.assertEqual(production_line.name, "Lini Baru")
        self.assertTrue(
            AuditLog.objects.filter(
                action="master.update",
                resource="master.production_line",
                resource_id=str(production_line.pk),
            ).exists()
        )

    def test_update_production_line_replace_m2m_work_centers(self):
        """PUT ``work_center_ids`` = replace penuh anggota lini (set())."""
        cutting = self.make_work_center("CUTTING-1")
        sewing = self.make_work_center("SEWING-1")
        qc = self.make_work_center("QC-1")
        production_line = self.make_line()
        production_line.work_centers.set([cutting, sewing])

        # 1) Ganti sebagian: buang CUTTING-1, tambah QC-1.
        first = self.put_line(production_line.pk, {"work_center_ids": [sewing.pk, qc.pk]})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["work_center_names"], ["QC-1", "SEWING-1"])
        self.assertEqual(
            sorted(production_line.work_centers.values_list("code", flat=True)),
            ["QC-1", "SEWING-1"],  # CUTTING-1 keluar dari line
        )

        # 2) Kosongkan anggota (list kosong tetap "dikirim" → replace jadi kosong).
        second = self.put_line(production_line.pk, {"work_center_ids": []})
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["work_centers_count"], 0)
        self.assertEqual(production_line.work_centers.count(), 0)

        # 3) Field M2M TIDAK dikirim -> anggota tidak disentuh.
        third = self.put_line(production_line.pk, {"name": "Lini Tetap"})
        self.assertEqual(third.status_code, 200)
        self.assertEqual(production_line.work_centers.count(), 0)
        self.assertEqual(cutting.production_lines.count(), 0)

    def test_update_production_line_m2m_invalid_atomic_rollback(self):
        """Id WC ngawur pada PUT → 400 dan M2M lama TIDAK berubah (rollback)."""
        sewing = self.make_work_center("SEWING-1")
        production_line = self.make_line()
        production_line.work_centers.set([sewing])

        response = self.put_line(
            production_line.pk, {"name": "Nama Baru", "work_center_ids": [999999]}
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("tidak ditemukan", response.json()["detail"])

        production_line.refresh_from_db()
        self.assertEqual(production_line.name, "Lini Existing")  # nama juga tidak berubah
        self.assertEqual(
            list(production_line.work_centers.values_list("code", flat=True)), ["SEWING-1"]
        )

    def test_update_production_line_duplicate_code_400(self):
        """Ganti kode ke kode lini lain (case-insensitive) → 400."""
        self.make_line(code="LINE-A")
        second = self.make_line(code="LINE-B")

        response = self.put_line(second.pk, {"code": "line-a"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("sudah dipakai", response.json()["detail"])
        second.refresh_from_db()
        self.assertEqual(second.code, "LINE-B")

    def test_update_production_line_empty_body_no_syncrecord(self):
        """PUT tanpa perubahan (skalar & M2M sama) → 200 tanpa ledger/audit."""
        production_line = self.make_line()

        response = self.put_line(production_line.pk, {})

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["sync_record_id"])
        self.assertIsNone(response.json()["sync_status"])
        self.assertFalse(
            SyncRecord.objects.filter(resource=SyncResource.MASTER_PRODUCTION_LINE.value).exists()
        )
        self.assertFalse(AuditLog.objects.filter(resource_id=str(production_line.pk)).exists())

    def test_detail_dan_missing_404(self):
        """GET detail → 200 (+ ``work_centers[]``); id tak dikenal → 404 GET/PUT/DELETE."""
        sewing = self.make_work_center("SEWING-1")
        production_line = self.make_line(capability_tags=["JAHIT"])
        production_line.work_centers.set([sewing])

        detail = self.api.get(detail_url(production_line.pk))
        self.assertEqual(detail.status_code, 200)
        body = detail.json()
        self.assertTrue(DETAIL_KEYS <= set(body))
        self.assertEqual(body["capability_tags"], ["JAHIT"])
        self.assertEqual(
            body["work_centers"],
            [{"id": sewing.pk, "code": "SEWING-1", "name": "Stasiun SEWING-1"}],
        )
        self.assertEqual(body["active_bundles_count"], 0)

        self.assertEqual(self.api.get(detail_url(999999)).status_code, 404)
        self.assertEqual(
            self.api.put(detail_url(999999), {"name": "X"}, format="json").status_code, 404
        )
        self.assertEqual(self.api.delete(detail_url(999999)).status_code, 404)

    def test_detail_bundle_aktif_dan_allocation_rule(self):
        """Detail melaporkan bundle aktif + jumlah allocation rule (info, non-blocking)."""
        production_line = self.make_line()
        make_bundle_at(production_line, state="DONE")  # historis: tidak dihitung
        make_bundle_at(production_line)
        LineAllocationRule.objects.create(name="Aturan QC", wc_type="QC", line=production_line)

        body = self.api.get(detail_url(production_line.pk)).json()

        self.assertEqual(body["active_bundles_count"], 1)
        self.assertEqual(body["allocation_rules_count"], 1)

    # ------------------------------------------------------- DELETE (soft + guard)
    def test_delete_production_line_soft_delete(self):
        """DELETE tanpa bundle aktif → 200 soft delete; baris MASIH ada di DB."""
        production_line = self.make_line()

        response = self.api.delete(detail_url(production_line.pk))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["id"], production_line.pk)
        self.assertTrue(body["deleted"])
        self.assertFalse(body["active"])
        self.assertEqual(body["sync_status"], "SKIPPED")
        self.assertIs(body["mes_only"], True)

        production_line.refresh_from_db()
        self.assertFalse(production_line.is_active)
        self.assertTrue(ProductionLine.objects.filter(pk=production_line.pk).exists())
        self.assertTrue(
            AuditLog.objects.filter(
                action="master.delete",
                resource="master.production_line",
                resource_id=str(production_line.pk),
            ).exists()
        )

    def test_delete_production_line_blocked_by_active_bundle(self):
        """Guard: bundle aktif (state bukan DONE/CANCELLED) → 400, lini tetap aktif."""
        production_line = self.make_line(code="LINE-A")
        make_bundle_at(production_line, state="IN_PROGRESS")

        response = self.api.delete(detail_url(production_line.pk))

        self.assertEqual(response.status_code, 400)
        self.assertIn("bundle aktif", response.json()["detail"])

        production_line.refresh_from_db()
        self.assertTrue(production_line.is_active)
        self.assertFalse(
            AuditLog.objects.filter(
                action="master.delete", resource_id=str(production_line.pk)
            ).exists()
        )

    def test_delete_production_line_allowed_when_bundles_done(self):
        """Bundle historis (DONE/CANCELLED) TIDAK menghalangi soft delete."""
        production_line = self.make_line()
        make_bundle_at(production_line, state="DONE")
        make_bundle_at(production_line, state="CANCELLED")

        response = self.api.delete(detail_url(production_line.pk))

        self.assertEqual(response.status_code, 200)
        production_line.refresh_from_db()
        self.assertFalse(production_line.is_active)

    def test_delete_production_line_tidak_diblokir_allocation_rule(self):
        """``LineAllocationRule`` (CASCADE) TIDAK memblokir soft delete (keputusan H1.8)."""
        production_line = self.make_line()
        LineAllocationRule.objects.create(name="Aturan Sewing", wc_type="SEWING", line=production_line)

        response = self.api.delete(detail_url(production_line.pk))

        self.assertEqual(response.status_code, 200)
        production_line.refresh_from_db()
        self.assertFalse(production_line.is_active)
        self.assertEqual(LineAllocationRule.objects.filter(line=production_line).count(), 1)

    # ------------------------------------------------------------------- GET list
    def test_list_pagination_dan_envelope(self):
        """Envelope ListPage + pagination + urut ``code`` + hitungan annotate."""
        sewing = self.make_work_center("SEWING-1")
        for index in range(3):
            line = self.make_line(code=f"LINE-{index}", name=f"Lini {index}")
            if index == 0:
                line.work_centers.set([sewing])

        first = self.api.get(LINES_URL, {"limit": 2}).json()
        self.assertEqual(set(first), ENVELOPE_KEYS)
        self.assertEqual(first["total_count"], 3)
        self.assertEqual([row["code"] for row in first["rows"]], ["LINE-0", "LINE-1"])
        self.assertTrue(first["has_more"])
        self.assertEqual(first["next_cursor"], 2)
        self.assertTrue(ROW_KEYS <= set(first["rows"][0]))
        self.assertEqual(first["rows"][0]["work_centers_count"], 1)
        self.assertEqual(first["rows"][0]["work_center_names"], ["SEWING-1"])
        self.assertNotIn("work_centers", first["rows"][0])  # nested hanya di detail

        second = self.api.get(LINES_URL, {"limit": 2, "cursor": 2}).json()
        self.assertEqual(len(second["rows"]), 1)
        self.assertFalse(second["has_more"])
        self.assertIsNone(second["next_cursor"])

    def test_list_filters(self):
        """Filter ``search`` (code/name), ``capability_tag``, ``work_center``, ``active``."""
        sewing = self.make_work_center("SEWING-1")
        cutting = self.make_work_center("CUTTING-1")

        sewing_line = self.make_line(code="LINE-SEW", name="Lini Jahit", capability_tags=["SEWING"])
        sewing_line.work_centers.set([sewing])
        cutting_line = self.make_line(
            code="LINE-CUT", name="Meja Potong", capability_tags=["CUTTING"]
        )
        cutting_line.work_centers.set([cutting])
        self.make_line(code="LINE-OFF", name="Lini Nonaktif", is_active=False)

        by_name = self.api.get(LINES_URL, {"search": "potong"}).json()
        self.assertEqual([row["code"] for row in by_name["rows"]], ["LINE-CUT"])

        by_code = self.api.get(LINES_URL, {"search": "line-sew"}).json()
        self.assertEqual([row["code"] for row in by_code["rows"]], ["LINE-SEW"])

        by_tag = self.api.get(LINES_URL, {"capability_tag": "sewing"}).json()  # case-insensitive
        self.assertEqual([row["code"] for row in by_tag["rows"]], ["LINE-SEW"])

        by_work_center = self.api.get(LINES_URL, {"work_center": cutting.pk}).json()
        self.assertEqual([row["code"] for row in by_work_center["rows"]], ["LINE-CUT"])

        inactive = self.api.get(LINES_URL, {"active": "false"}).json()
        self.assertEqual([row["code"] for row in inactive["rows"]], ["LINE-OFF"])

        active = self.api.get(LINES_URL, {"active": "true"}).json()
        self.assertEqual([row["code"] for row in active["rows"]], ["LINE-CUT", "LINE-SEW"])

    def test_list_invalid_params_400(self):
        """Parameter list ngawur → 400 (bukan 500)."""
        cases = (
            {"limit": "nol"},
            {"limit": "0"},
            {"limit": "201"},
            {"cursor": "-1"},
            {"active": "kadang"},
            {"work_center": "abc"},
            {"work_center": "0"},
        )

        for params in cases:
            with self.subTest(params=params):
                response = self.api.get(LINES_URL, params)
                self.assertEqual(response.status_code, 400)
                self.assertIn("detail", response.json())

    # -------------------------------------------------------------------- izin
    def test_anonymous_forbidden(self):
        """Tanpa kredensial → 403 untuk semua metode (GET/POST/PUT/DELETE)."""
        production_line = self.make_line()
        client = APIClient()

        self.assertEqual(client.get(LINES_URL).status_code, 403)
        self.assertEqual(
            client.post(LINES_URL, self.line_body(), format="json").status_code, 403
        )
        self.assertEqual(client.get(detail_url(production_line.pk)).status_code, 403)
        self.assertEqual(
            client.put(detail_url(production_line.pk), {"name": "X"}, format="json").status_code,
            403,
        )
        self.assertEqual(client.delete(detail_url(production_line.pk)).status_code, 403)

    def test_non_admin_roles_read_only(self):
        """Role non-ADMIN/OWNER: GET 200, tapi POST/PUT/DELETE 403 (tanpa efek)."""
        production_line = self.make_line()

        for name, client in self.readonly_apis.items():
            with self.subTest(role=name):
                self.assertEqual(client.get(LINES_URL).status_code, 200)
                self.assertEqual(
                    client.post(
                        LINES_URL, self.line_body(code="LINE-BARU"), format="json"
                    ).status_code,
                    403,
                )
                self.assertEqual(
                    client.put(
                        detail_url(production_line.pk), {"name": "X"}, format="json"
                    ).status_code,
                    403,
                )
                self.assertEqual(client.delete(detail_url(production_line.pk)).status_code, 403)

        self.assertEqual(ProductionLine.objects.count(), 1)
        production_line.refresh_from_db()
        self.assertEqual(production_line.name, "Lini Existing")
        self.assertTrue(production_line.is_active)

    # --------------------------------------------- ledger sync (SKIPPED) & audit
    def test_syncrecord_skipped_ditulis_saat_create(self):
        """POST → ``SyncRecord`` ``master.production_line``/``MASTER_PUSH`` SKIPPED."""
        sewing = self.make_work_center("SEWING-1")
        response = self.post_line(self.line_body(work_center_ids=[sewing.pk]))

        record = SyncRecord.objects.get(
            resource=SyncResource.MASTER_PRODUCTION_LINE.value,
            resource_id=str(response.json()["id"]),
            stage=SyncStage.MASTER_PUSH.value,
        )
        self.assertEqual(record.status, SyncStatus.SKIPPED)
        self.assertEqual(record.last_error, MES_ONLY_REASON)
        self.assertIsNone(record.erp_id)
        self.assertIsNone(record.sent_at)
        self.assertEqual(record.payload["code"], "LINE-A")
        self.assertEqual(record.payload["capability_tags"], ["JAHIT", "OBRAS"])
        self.assertEqual(record.payload["work_center_ids"], [sewing.pk])

    def test_auditlog_ditulis_saat_create(self):
        """POST → ``AuditLog`` ``master.create`` resource ``master.production_line``."""
        response = self.post_line(self.line_body())

        log = AuditLog.objects.get(
            action="master.create", resource_id=str(response.json()["id"])
        )
        self.assertEqual(log.resource, "master.production_line")
        self.assertEqual(log.user_id, self.admin.pk)
        self.assertIs(log.metadata["mes_only"], True)
        self.assertEqual(log.payload["code"], "LINE-A")

    def test_update_delete_reuse_syncrecord_dan_audit(self):
        """PUT lalu DELETE memakai SATU ``SyncRecord`` (SKIPPED) + audit keduanya."""
        production_line = self.make_line()

        self.put_line(production_line.pk, {"capability_tags": ["QC"]})
        response = self.api.delete(detail_url(production_line.pk))

        records = SyncRecord.objects.filter(
            resource=SyncResource.MASTER_PRODUCTION_LINE.value,
            resource_id=str(production_line.pk),
        )
        self.assertEqual(records.count(), 1)

        record = records.get()
        self.assertEqual(record.status, SyncStatus.SKIPPED)
        self.assertIs(record.payload["active"], False)  # payload terbaru
        self.assertEqual(record.payload["capability_tags"], ["QC"])
        self.assertEqual(record.pk, response.json()["sync_record_id"])

        actions = set(
            AuditLog.objects.filter(resource_id=str(production_line.pk)).values_list(
                "action", flat=True
            )
        )
        self.assertEqual(actions, {"master.update", "master.delete"})

    def test_sync_records_filter_status_skipped(self):
        """Ledger Production Line terlihat di monitor: ``?status=SKIPPED``."""
        self.post_line(self.line_body())

        body = self.api.get("/api/v1/sync/records/", {"status": "SKIPPED"}).json()

        self.assertEqual(body["total_count"], 1)
        self.assertEqual(body["rows"][0]["resource"], "master.production_line")
        self.assertEqual(body["rows"][0]["status"], "SKIPPED")

    # ---------------------------------------------- non-breaking konsumen existing
    def test_non_breaking_capability_allocator_dan_allocation_rule(self):
        """Lini hasil API tetap dipakai capability_allocator & LineAllocationRule."""
        cutting = self.make_work_center("CUTTING-1")
        sewing = self.make_work_center("SEWING-1")

        response = self.post_line(
            self.line_body(
                code="LINE-FULL",
                capability_tags=["JAHIT"],
                work_center_ids=[cutting.pk, sewing.pk],
            )
        )
        production_line = ProductionLine.objects.get(pk=response.json()["id"])

        # capability_allocator: routing yang butuh kedua WC → line ini kandidat.
        routing = make_routing(code="ROUTE-A")
        make_step(routing, "CUT", 1, work_center=cutting)
        make_step(routing, "SEW", 2, work_center=sewing)
        candidates = CapabilityAllocator().candidates(make_work_order(), routing)
        self.assertEqual([candidate.pk for candidate in candidates], [production_line.pk])
        self.assertEqual(
            CapabilityAllocator().allocate(make_work_order(), routing).pk, production_line.pk
        )

        # LineAllocationRule tetap bisa menunjuk lini ini (settings API F3A.2).
        rule = LineAllocationRule.objects.create(
            name="Aturan Sewing", wc_type="SEWING", line=production_line
        )
        self.assertEqual(list(production_line.allocation_rules.all()), [rule])

        # Field lama (config-free) tidak berubah perilaku: filter is_active tetap jalan.
        self.assertTrue(
            ProductionLine.objects.filter(is_active=True, work_centers__in=[sewing.pk]).exists()
        )





