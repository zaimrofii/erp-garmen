"""Test **H5.4** — Permission Matrix (``/api/v1/settings/permissions/``).

Cakupan: GET amplop (``matrix`` + ``effective`` + ``diverges`` + ``resources`` +
``actions`` + ``roles`` + ``banner``) · snapshot ``ROLE_CAPABILITIES`` (cermin kode) ·
PUT bulk **atomic** per role (bentuk ``updates`` **dan** ``matrix``) · idempotensi
(``unique_together`` role+resource+action ⇒ 2× PUT sel sama = 1 baris, tanpa
ledger/audit baru) · validasi (resource/aksi tak dikenal, ``allowed`` bukan boolean,
body kosong, role tak ada → 404) · ledger ``SyncRecord`` ``core_auth.role_permission``/
``SKIPPED`` + ``AuditLog`` · izin (anonim 403; operator GET 200 / PUT 403) · non-breaking:
``Role`` + B26/B27 + ``_require_admin`` + H5.1–H5.8 tetap hijau + AuditLog writer.

Keputusan STEP 0 (H5.4 — **Opsi A′**): baris ``RolePermission`` = **profil/overlay**
(ber-jejak); **enforcement TIDAK dibaca** dari tabel ini (guard tetap hardcoded di kode)
⇒ endpoint melaporkan ``effective`` (snapshot), ``diverges``, dan ``banner`` peringatan.

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_permission_matrix_crud.py -q
"""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from core.audit.models import AuditLog
from core.auth.models import Role, RolePermission, User
from core.auth.permission_services import (
    ACTIONS,
    BANNER,
    CONFIG_RESOURCE,
    MES_ONLY_REASON,
    RESOURCES,
    ROLE_CAPABILITIES,
)
from integrations.erp_sync.models import SyncRecord, SyncResource, SyncStage, SyncStatus

MATRIX_URL = "/api/v1/settings/permissions/"
ENVELOPE_KEYS = {
    "matrix",
    "effective",
    "diverges",
    "resources",
    "actions",
    "roles",
    "banner",
}


class PermissionMatrixTestCase(TestCase):
    """Basis bersama: role seeding + user admin/operator + klien admin."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="admin-perm",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.ADMIN),
        )
        cls.operator = User.objects.create_user(
            username="op-perm",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.OPERATOR),
        )
        cls.owner = Role.objects.get(code=Role.Code.OWNER)
        cls.operator_role = Role.objects.get(code=Role.Code.OPERATOR)

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.admin)

    def as_user(self, user):
        """Client terautentikasi sebagai ``user`` (anonim kalau ``None``)."""
        client = APIClient()
        if user is not None:
            client.force_authenticate(user)
        return client

    def get(self):
        """GET amplop matrix dengan klien admin."""
        return self.api.get(MATRIX_URL)

    def put(self, role_id, **body):
        """PUT profil izin satu role dengan klien admin."""
        return self.api.put(f"{MATRIX_URL}{role_id}/", body, format="json")

    def matrix(self, role_id: int) -> dict:
        """Sel matrix satu role dari GET terbaru."""
        return self.get().json()["matrix"][str(role_id)]

    def sync_records(self, role: Role):
        """Ledger ``SyncRecord`` milik satu role."""
        return SyncRecord.objects.filter(
            resource=SyncResource.ROLE_PERMISSION_MATRIX.value,
            resource_id=str(role.pk),
            stage=SyncStage.MASTER_PUSH.value,
        )

    def audit_logs(self, role: Role):
        """AuditLog milik satu role (resource matrix izin)."""
        return AuditLog.objects.filter(
            resource=CONFIG_RESOURCE, resource_id=str(role.pk)
        )

    def update_cell(self, role: Role, resource: str, action: str, allowed: bool):
        """PUT satu sel matrix (bentuk ``updates``)."""
        return self.put(
            role.pk,
            updates=[{"resource": resource, "action": action, "allowed": allowed}],
        )


class PermissionMatrixGetTests(PermissionMatrixTestCase):
    """``GET /settings/permissions/`` — amplop, snapshot efektif, daftar statis."""

    def test_get_amplop_bentuk_lengkap(self):
        response = self.get()

        self.assertEqual(response.status_code, 200)
        body = response.json()

        self.assertEqual(set(body), ENVELOPE_KEYS)
        self.assertEqual(body["resources"], list(RESOURCES))
        self.assertEqual(body["actions"], list(ACTIONS))
        self.assertEqual(body["banner"], BANNER)
        self.assertIn("Enforcement", body["banner"])

    def test_get_tanpa_baris_semua_false_dan_tidak_membuat_baris(self):
        response = self.get()
        body = response.json()

        # 6 role seeding: ADMIN/OWNER/SUPERVISOR/QC/OPERATOR/PURCHASING
        self.assertEqual(len(body["roles"]), 6)
        self.assertEqual(len(body["matrix"]), 6)

        for cell in body["matrix"].values():
            self.assertEqual(set(cell), set(RESOURCES))
            for actions in cell.values():
                self.assertEqual(set(actions), set(ACTIONS))
                self.assertEqual(set(actions.values()), {False})

        # GET tidak boleh membuat baris profil
        self.assertEqual(RolePermission.objects.count(), 0)

    def test_effective_snapshot_mengikuti_guard_kode(self):
        body = self.get().json()
        effective = body["effective"]
        admin_id = str(self.admin.role_id)
        operator_id = str(self.operator_role.pk)
        owner_id = str(self.owner.pk)

        # ADMIN: settings read True (SETTINGS_ROLES) …
        self.assertTrue(effective[admin_id]["settings"]["read"])
        # … dan OPERATOR: settings read False.
        self.assertFalse(effective[operator_id]["settings"]["read"])

        # OPERATOR boleh baca bundles (PRODUCTION_ROLES), tapi tidak laporan.
        self.assertTrue(effective[operator_id]["bundles"]["read"])
        self.assertFalse(effective[operator_id]["reports"]["read"])

        # Dashboard terbuka untuk semua role; reports read-only (tanpa create).
        self.assertTrue(effective[operator_id]["dashboard"]["read"])
        self.assertTrue(effective[owner_id]["dashboard"]["read"])
        self.assertFalse(effective[admin_id]["reports"]["create"])

    def test_roles_baris_kontrak_b27(self):
        roles = {row["code"]: row for row in self.get().json()["roles"]}

        self.assertEqual(
            set(roles),
            {"ADMIN", "OWNER", "SUPERVISOR", "QC", "OPERATOR", "PURCHASING"},
        )
        admin_row = roles["ADMIN"]

        self.assertEqual(set(admin_row), {"id", "code", "label", "is_active"})
        self.assertEqual(admin_row["label"], "Administrator")
        self.assertTrue(admin_row["is_active"])

    def test_diverges_hanya_sel_yang_beda(self):
        body = self.get().json()
        admin_id = str(self.admin.role_id)

        # Default profil False vs efektif True ⇒ sel itu MUNCUL di diverges.
        self.assertEqual(
            body["diverges"][admin_id]["settings"]["read"],
            {"profile": False, "effective": True},
        )

        # Set profil = efektif ⇒ sel (settings, read) itu HILANG dari diverges
        # (resource lain/aksi lain tetap bisa beda — makanya dicek per-aksi).
        self.update_cell(self.admin.role, "settings", "read", True)

        after = self.get().json()

        self.assertNotIn(
            "read", after["diverges"].get(admin_id, {}).get("settings", {})
        )


class PermissionMatrixPutTests(PermissionMatrixTestCase):
    """``PUT /settings/permissions/<role_id>/`` — bulk atomic + ledger + audit."""

    def test_put_updates_daftar_membuat_baris(self):
        response = self.put(
            self.operator_role.pk,
            updates=[
                {"resource": "qc", "action": "create", "allowed": True},
                {"resource": "qc", "action": "delete", "allowed": False},
            ],
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()

        self.assertEqual(
            set(body) - ENVELOPE_KEYS,
            {"role_id", "updated_count", "sync_record_id", "sync_status"},
        )
        self.assertEqual(body["role_id"], self.operator_role.pk)
        self.assertEqual(body["updated_count"], 2)
        self.assertEqual(body["sync_status"], "SKIPPED")
        self.assertTrue(body["matrix"][str(self.operator_role.pk)]["qc"]["create"])
        self.assertFalse(body["matrix"][str(self.operator_role.pk)]["qc"]["delete"])
        self.assertEqual(RolePermission.objects.filter(role=self.operator_role).count(), 2)

    def test_put_bentuk_matrix_objek(self):
        response = self.put(
            self.owner.pk,
            matrix={"reports": {"read": True, "delete": True}},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()

        self.assertEqual(body["updated_count"], 2)
        self.assertTrue(body["matrix"][str(self.owner.pk)]["reports"]["delete"])
        self.assertTrue(
            RolePermission.objects.filter(
                role=self.owner, resource="reports", action="delete", allowed=True
            ).exists()
        )

    def test_put_idempotent_tidak_duplikasi_dan_tanpa_ledger_baru(self):
        first = self.update_cell(self.operator_role, "orders", "read", True)

        self.assertEqual(first.json()["updated_count"], 1)
        self.assertEqual(self.sync_records(self.operator_role).count(), 1)

        record_id = first.json()["sync_record_id"]
        before = self.audit_logs(self.operator_role).count()

        second = self.update_cell(self.operator_role, "orders", "read", True)

        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["updated_count"], 0)
        self.assertIsNone(second.json()["sync_record_id"])
        self.assertIsNone(second.json()["sync_status"])
        # 1 baris (unique_together) + ledger tidak bertambah + audit tidak bertambah
        self.assertEqual(
            RolePermission.objects.filter(
                role=self.operator_role, resource="orders", action="read"
            ).count(),
            1,
        )
        self.assertEqual(self.sync_records(self.operator_role).count(), 1)
        self.assertEqual(self.sync_records(self.operator_role).get().pk, record_id)
        self.assertEqual(self.audit_logs(self.operator_role).count(), before)

    def test_put_mengubah_nilai_existing(self):
        self.update_cell(self.operator_role, "reports", "read", True)

        response = self.update_cell(self.operator_role, "reports", "read", False)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["updated_count"], 1)
        self.assertFalse(
            response.json()["matrix"][str(self.operator_role.pk)]["reports"]["read"]
        )

        row = RolePermission.objects.get(
            role=self.operator_role, resource="reports", action="read"
        )

        self.assertFalse(row.allowed)

    def test_put_role_tidak_ada_404(self):
        response = self.put(
            999999, updates=[{"resource": "qc", "action": "read", "allowed": True}]
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn("tidak ditemukan", response.json()["detail"])
        self.assertEqual(RolePermission.objects.count(), 0)

    def test_put_resource_dan_aksi_tak_dikenal_400(self):
        salah_resource = self.put(
            self.owner.pk, updates=[{"resource": "odoo", "action": "read", "allowed": True}]
        )

        self.assertEqual(salah_resource.status_code, 400)
        self.assertIn("odoo", salah_resource.json()["detail"])

        salah_aksi = self.put(
            self.owner.pk, updates=[{"resource": "qc", "action": "print", "allowed": True}]
        )

        self.assertEqual(salah_aksi.status_code, 400)
        self.assertIn("print", salah_aksi.json()["detail"])
        self.assertEqual(RolePermission.objects.count(), 0)

    def test_put_allowed_bukan_boolean_400(self):
        salah = self.put(
            self.owner.pk, updates=[{"resource": "qc", "action": "read", "allowed": "ya"}]
        )

        self.assertEqual(salah.status_code, 400)
        self.assertIn("true|false", salah.json()["detail"])

        matrix_salah = self.put(self.owner.pk, matrix={"qc": {"read": 1}})

        self.assertEqual(matrix_salah.status_code, 400)
        self.assertEqual(RolePermission.objects.count(), 0)

    def test_put_body_kosong_dan_bentuk_salah_400(self):
        kosong = self.put(self.owner.pk)

        self.assertEqual(kosong.status_code, 400)
        self.assertIn("Tidak ada perubahan", kosong.json()["detail"])

        bentuk = self.put(self.owner.pk, updates="bukan daftar")

        self.assertEqual(bentuk.status_code, 400)
        self.assertIn("daftar", bentuk.json()["detail"])

        matrix_bukan_objek = self.put(self.owner.pk, matrix=[1, 2])

        self.assertEqual(matrix_bukan_objek.status_code, 400)
        self.assertEqual(RolePermission.objects.count(), 0)

    def test_put_atomic_tidak_menulis_saat_ada_entri_invalid(self):
        response = self.put(
            self.owner.pk,
            updates=[
                {"resource": "qc", "action": "read", "allowed": True},
                {"resource": "tidak-ada", "action": "read", "allowed": True},
            ],
        )

        self.assertEqual(response.status_code, 400)
        # validasi gagal SEBELUM menulis ⇒ tidak ada baris tersisa (atomic)
        self.assertEqual(RolePermission.objects.count(), 0)

    def test_put_ledger_skipped_dan_audit(self):
        response = self.update_cell(self.operator_role, "bundles", "delete", True)

        self.assertEqual(response.status_code, 200)

        record = self.sync_records(self.operator_role).get()

        self.assertEqual(record.status, SyncStatus.SKIPPED)
        self.assertEqual(record.last_error, MES_ONLY_REASON)
        self.assertEqual(record.payload["role_code"], "OPERATOR")
        self.assertEqual(
            record.payload["updates"],
            [{"resource": "bundles", "action": "delete", "allowed": True}],
        )

        logs = self.audit_logs(self.operator_role)

        self.assertEqual(logs.count(), 1)

        log = logs.get()

        self.assertEqual(log.action, "core_auth.permission.update")
        self.assertEqual(log.result, AuditLog.Result.OK)
        self.assertTrue(log.metadata["mes_only"])
        self.assertEqual(log.metadata["created"], 1)
        self.assertEqual(log.metadata["updated"], 0)

    def test_auth_anonim_403_dan_operator_baca_saja(self):
        anonim = self.as_user(None)

        self.assertEqual(anonim.get(MATRIX_URL).status_code, 403)
        self.assertEqual(
            anonim.put(f"{MATRIX_URL}{self.owner.pk}/", {}, format="json").status_code,
            403,
        )

        operator = self.as_user(self.operator)

        # baca matrix boleh (transparansi) — tulis hanya ADMIN/OWNER
        self.assertEqual(operator.get(MATRIX_URL).status_code, 200)
        self.assertEqual(
            operator.put(
                f"{MATRIX_URL}{self.owner.pk}/",
                {"updates": [{"resource": "qc", "action": "read", "allowed": True}]},
                format="json",
            ).status_code,
            403,
        )
        self.assertEqual(RolePermission.objects.count(), 0)


class PermissionMatrixNonBreakingTests(PermissionMatrixTestCase):
    """Snapshot konsisten + non-breaking (Role, B26/B27, guard, H5.1–H5.8)."""

    def test_snapshot_capabilities_konsisten(self):
        # setiap resource dikenal & setiap action dikenal (tidak ada salah tulis)
        self.assertEqual(set(ROLE_CAPABILITIES), set(RESOURCES))

        known_codes = {
            "ADMIN",
            "OWNER",
            "SUPERVISOR",
            "QC",
            "OPERATOR",
            "PURCHASING",
            "INVENTORY",
        }

        for resource, actions in ROLE_CAPABILITIES.items():
            self.assertEqual(set(actions), set(ACTIONS), resource)
            for action, codes in actions.items():
                self.assertLessEqual(set(codes), known_codes, f"{resource}.{action}")
                # tidak ada duplikat kode role di satu sel
                self.assertEqual(len(codes), len(set(codes)), f"{resource}.{action}")

    def test_non_breaking_role_b26_b27_guard_dan_h5_lain(self):
        # Role model TIDAK diubah (H5.4 hanya menambah model baru)
        role_fields = {field.name for field in Role._meta.get_fields()}

        self.assertTrue({"code", "name", "description", "is_active"}.issubset(role_fields))

        # B27 roles: masih GET-only + bentuk baris sama
        roles = self.api.get("/api/v1/settings/roles/")

        self.assertEqual(roles.status_code, 200)
        self.assertEqual(
            set(roles.json()["rows"][0]),
            {"id", "code", "label", "description", "is_active", "user_count"},
        )
        self.assertEqual(
            self.api.put("/api/v1/settings/roles/", {}, format="json").status_code, 405
        )

        # B26 users tetap hijau
        self.assertEqual(self.api.get("/api/v1/settings/users/").status_code, 200)

        # endpoint H5.1/H5.5/H5.6/H5.7/H5.8 tetap hijau
        for url in (
            "/api/v1/settings/company/",
            "/api/v1/settings/audit/",
            "/api/v1/settings/integration/",
            "/api/v1/settings/wa/",
            "/api/v1/settings/printer/",
        ):
            self.assertEqual(self.api.get(url).status_code, 200, url)

        # `_require_admin` TIDAK berubah: operator tetap 403 di endpoint tulis Settings,
        # tetapi tetap boleh GET (perilaku lama) — H5.4 tidak menyentuh guard mana pun.
        operator = self.as_user(self.operator)

        self.assertEqual(operator.get("/api/v1/settings/roles/").status_code, 200)
        self.assertEqual(
            operator.put("/api/v1/settings/integration/", {}, format="json").status_code,
            403,
        )
        self.assertEqual(
            operator.put("/api/v1/settings/wa/", {}, format="json").status_code, 403
        )
        self.assertEqual(
            operator.put("/api/v1/settings/printer/", {}, format="json").status_code, 403
        )




