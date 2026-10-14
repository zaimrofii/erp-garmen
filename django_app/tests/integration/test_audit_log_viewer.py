"""Test **H5.5** — Audit Log Viewer (``/api/v1/settings/audit/``) — READ-ONLY.

Cakupan: daftar default (urut terbaru dulu + amplop ListPage) · paginasi offset
(``?limit``/``?cursor``) · filter ``user_id``/``action`` (exact **dan** prefix titik
``master.``)/``resource`` (+alias ``resource_type``)/``resource_id``/``result``
(validasi 400)/``date_from``-``date_to`` (inklusif tanggal-saja)/``search`` · metadata
**preview** di daftar (potong 100 char) · detail ``/<id>/`` (payload+metadata lengkap,
**tetap** masked) + **404** · **mask rekursif** rahasia (``api_key``/``password``/
``secret``/``token``/``key``, nested) · izin **ADMIN/OWNER** (anonim & operator 403) ·
**read-only**: jumlah ``AuditLog`` tidak berubah + write method → 405 · non-breaking:
F9 ``/audit/products-missing-odoo-id/`` + H5.1–H5.8 + model ``AuditLog`` **tidak**
diubah (append-only, ordering & index lama tetap).

Keputusan STEP 0 (H5.5): backend path ``/settings/audit/`` (sesuai brief; frontend
memakai ``/settings/audit-log`` karena ``/settings/audit`` sudah dipakai F9 = audit
produk), GET **ADMIN/OWNER** (audit sensitif, beda dari F9 yang operator-accessible),
**tanpa** index baru, list = preview metadata & detail = lengkap.

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_audit_log_viewer.py -q
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.audit.models import AuditLog
from core.audit.services import MASK_VALUE, mask_sensitive
from core.auth.models import Role, User

AUDIT_URL = "/api/v1/settings/audit/"
ROW_KEYS = {
    "id",
    "timestamp",
    "user_id",
    "username",
    "full_name",
    "action",
    "resource",
    "resource_id",
    "result",
    "request_id",
    "ip_address",
    "metadata_preview",
}

#: Hari ini (lokal) + helper waktu tengah hari supaya filter tanggal deterministik.
TODAY = timezone.localtime(timezone.now()).date()


def noon(day) -> datetime:
    """Waktu lokal 12:00 pada ``day`` (aman dari batas tengah malam)."""
    return timezone.make_aware(
        datetime.combine(day, time(12, 0)), timezone.get_current_timezone()
    )


class AuditLogViewerTestCase(TestCase):
    """Basis bersama: user admin/operator + helper pembuat baris audit."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="admin-audit",
            password="rahasia123",  # noqa: S106 - kredensial test
            first_name="Sari",
            last_name="Admin",
            role=Role.objects.get(code=Role.Code.ADMIN),
        )
        cls.operator = User.objects.create_user(
            username="op-audit",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.OPERATOR),
        )

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.admin)

    def as_user(self, user):
        """Client terautentikasi sebagai ``user`` (anonim kalau ``None``)."""
        client = APIClient()
        if user is not None:
            client.force_authenticate(user)
        return client

    def make_log(
        self,
        *,
        action: str = "master.create",
        resource: str = "master.product",
        resource_id: str = "1",
        user=None,
        result: str = AuditLog.Result.OK,
        payload: dict | None = None,
        metadata: dict | None = None,
        timestamp: datetime | None = None,
        request_id: str = "req-1",
    ) -> AuditLog:
        """Buat satu baris ``AuditLog`` (``timestamp`` di-override setelah create)."""
        log = AuditLog.objects.create(
            user=user if user is not None else self.admin,
            action=action,
            resource=resource,
            resource_id=resource_id,
            result=result,
            payload=payload if payload is not None else {},
            metadata=metadata if metadata is not None else {},
            request_id=request_id,
        )
        if timestamp is not None:
            AuditLog.objects.filter(pk=log.pk).update(timestamp=timestamp)
            log.refresh_from_db()

        return log

    def get(self, **params):
        """GET daftar audit dengan klien admin (+query params)."""
        return self.api.get(AUDIT_URL, params)

    def actions(self, response) -> list[str]:
        """Daftar ``action`` dari baris respons (memudahkan assertion urutan/filter)."""
        return [row["action"] for row in response.json()["rows"]]


class AuditListTests(AuditLogViewerTestCase):
    """``GET /settings/audit/`` — daftar default, paginasi, filter."""

    def test_daftar_default_urut_terbaru_dulu(self):
        self.make_log(action="a.lama", timestamp=noon(TODAY - timedelta(days=2)))
        self.make_log(action="b.tengah", timestamp=noon(TODAY - timedelta(days=1)))
        self.make_log(action="c.baru", timestamp=noon(TODAY))

        response = self.get()

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), {"rows", "total_count", "has_more", "next_cursor"})
        self.assertEqual(body["total_count"], 3)
        self.assertFalse(body["has_more"])
        self.assertIsNone(body["next_cursor"])
        # urut terbaru dulu
        self.assertEqual(self.actions(response), ["c.baru", "b.tengah", "a.lama"])

        row = body["rows"][0]

        self.assertEqual(set(row), ROW_KEYS)
        self.assertEqual(row["username"], "admin-audit")
        self.assertEqual(row["full_name"], "Sari Admin")
        self.assertEqual(row["user_id"], self.admin.pk)
        self.assertEqual(row["resource"], "master.product")
        self.assertEqual(row["resource_id"], "1")
        self.assertEqual(row["result"], "OK")
        self.assertEqual(row["request_id"], "req-1")
        self.assertIsNone(row["ip_address"])

    def test_daftar_kosong_valid(self):
        response = self.get()

        self.assertEqual(response.status_code, 200)
        body = response.json()

        self.assertEqual(body["rows"], [])
        self.assertEqual(body["total_count"], 0)
        self.assertFalse(body["has_more"])
        self.assertIsNone(body["next_cursor"])

    def test_paginasi_limit_dan_cursor(self):
        for index in range(5):
            self.make_log(
                action=f"step.{index}", timestamp=noon(TODAY) + timedelta(minutes=index)
            )

        first = self.get(limit=2)

        self.assertEqual(first.json()["total_count"], 5)
        self.assertEqual(self.actions(first), ["step.4", "step.3"])
        self.assertTrue(first.json()["has_more"])
        self.assertEqual(first.json()["next_cursor"], 2)

        second = self.get(limit=2, cursor=2)

        self.assertEqual(self.actions(second), ["step.2", "step.1"])
        self.assertEqual(second.json()["next_cursor"], 4)

        last = self.get(limit=2, cursor=4)

        self.assertEqual(self.actions(last), ["step.0"])
        self.assertFalse(last.json()["has_more"])
        self.assertIsNone(last.json()["next_cursor"])

    def test_paginasi_param_tidak_valid_400(self):
        self.assertEqual(self.get(limit=0).status_code, 400)
        self.assertEqual(self.get(limit=500).status_code, 400)
        self.assertEqual(self.get(limit="abc").status_code, 400)
        self.assertEqual(self.get(cursor=-1).status_code, 400)
        self.assertIn("limit", self.get(limit=0).json()["detail"])

    def test_filter_user_id(self):
        self.make_log(action="lain.1", user=self.operator)
        self.make_log(action="admin.1", user=self.admin)

        only_operator = self.get(user_id=self.operator.pk)

        self.assertEqual(self.actions(only_operator), ["lain.1"])
        self.assertEqual(only_operator.json()["total_count"], 1)

        salah = self.get(user_id="bukan-angka")

        self.assertEqual(salah.status_code, 400)
        self.assertIn("user_id", salah.json()["detail"])

        nol = self.get(user_id=0)

        self.assertEqual(nol.status_code, 400)

    def test_filter_action_exact_dan_prefix(self):
        self.make_log(action="master.create")
        self.make_log(action="master.update")
        self.make_log(action="erp_sync.push_fg")

        prefix = self.get(action="master.")

        self.assertEqual(prefix.json()["total_count"], 2)
        self.assertEqual(self.actions(prefix), ["master.update", "master.create"])

        exact = self.get(action="master.create")

        self.assertEqual(self.actions(exact), ["master.create"])

        case_insensitive = self.get(action="MASTER.CREATE")

        self.assertEqual(self.actions(case_insensitive), ["master.create"])

    def test_filter_resource_resource_id_dan_alias(self):
        self.make_log(resource="master.product", resource_id="11")
        self.make_log(resource="master.wa_config", resource_id="1")

        by_resource = self.get(resource="master.product")

        self.assertEqual(by_resource.json()["total_count"], 1)
        self.assertEqual(by_resource.json()["rows"][0]["resource"], "master.product")

        # alias ramah frontend: `resource_type`
        by_alias = self.get(resource_type="master.wa_config")

        self.assertEqual(by_alias.json()["total_count"], 1)

        by_id = self.get(resource_id="11")

        self.assertEqual(by_id.json()["total_count"], 1)
        self.assertEqual(by_id.json()["rows"][0]["resource_id"], "11")

    def test_filter_result_valid_dan_invalid(self):
        self.make_log(action="ok.1", result=AuditLog.Result.OK)
        self.make_log(action="gagal.1", result=AuditLog.Result.FAILED)
        self.make_log(action="ditolak.1", result=AuditLog.Result.DENIED)

        gagal = self.get(result="FAILED")

        self.assertEqual(self.actions(gagal), ["gagal.1"])
        # case-insensitive
        self.assertEqual(self.actions(self.get(result="failed")), ["gagal.1"])

        salah = self.get(result="NGACO")

        self.assertEqual(salah.status_code, 400)
        self.assertIn("result", salah.json()["detail"])

    def test_filter_date_range_inklusif(self):
        self.make_log(action="h-2", timestamp=noon(TODAY - timedelta(days=2)))
        self.make_log(action="h-1", timestamp=noon(TODAY - timedelta(days=1)))
        self.make_log(action="h-0", timestamp=noon(TODAY))

        from_satu = self.get(date_from=(TODAY - timedelta(days=1)).isoformat())

        self.assertEqual(sorted(self.actions(from_satu)), ["h-0", "h-1"])

        # tanggal-saja `date_to` inklusif sampai AKHIR hari itu
        sampai_satu = self.get(date_to=(TODAY - timedelta(days=1)).isoformat())

        self.assertEqual(sorted(self.actions(sampai_satu)), ["h-1", "h-2"])

        rentang = self.get(
            date_from=(TODAY - timedelta(days=1)).isoformat(),
            date_to=(TODAY - timedelta(days=1)).isoformat(),
        )

        self.assertEqual(self.actions(rentang), ["h-1"])

        salah = self.get(date_from="31-12-2026")

        self.assertEqual(salah.status_code, 400)
        self.assertIn("date_from", salah.json()["detail"])

    def test_search_username_action_resource_dan_batas(self):
        self.make_log(action="master.create", resource="master.product")
        self.make_log(
            action="erp_sync.push_fg",
            resource="bundle",
            user=self.operator,
        )

        by_action = self.get(search="push")

        self.assertEqual(self.actions(by_action), ["erp_sync.push_fg"])

        by_resource = self.get(search="product")

        self.assertEqual(self.actions(by_resource), ["master.create"])

        by_username = self.get(search="op-audit")

        self.assertEqual(self.actions(by_username), ["erp_sync.push_fg"])

        by_full_name = self.get(search="Sari")

        self.assertEqual(self.actions(by_full_name), ["master.create"])

        kepanjangan = self.get(search="x" * 101)

        self.assertEqual(kepanjangan.status_code, 400)
        self.assertIn("search", kepanjangan.json()["detail"])

    def test_filter_gabungan(self):
        self.make_log(
            action="master.create",
            resource="master.product",
            timestamp=noon(TODAY),
        )
        self.make_log(
            action="master.create",
            resource="master.product",
            user=self.operator,
            timestamp=noon(TODAY),
        )
        self.make_log(
            action="master.update",
            resource="master.product",
            timestamp=noon(TODAY - timedelta(days=3)),
        )

        response = self.get(
            action="master.",
            user_id=self.admin.pk,
            date_from=(TODAY - timedelta(days=1)).isoformat(),
        )

        self.assertEqual(response.json()["total_count"], 1)
        self.assertEqual(self.actions(response), ["master.create"])


class AuditMaskingDetailTests(AuditLogViewerTestCase):
    """Preview metadata, detail masked, 404, dan mask rekursif (PURE)."""

    def test_metadata_preview_dipotong_dan_di_mask(self):
        kepanjangan = {f"field_{index}": index for index in range(30)}
        self.make_log(action="panjang.1", metadata=kepanjangan)
        self.make_log(
            action="rahasia.1",
            metadata={"odoo_api_key": "kunci-asli", "fields": ["odoo_url"]},
        )

        rows = {row["action"]: row for row in self.get().json()["rows"]}

        preview = rows["panjang.1"]["metadata_preview"]

        self.assertTrue(preview.endswith("…"))
        self.assertLessEqual(len(preview), 101)

        rahasia = rows["rahasia.1"]["metadata_preview"]

        self.assertIn(MASK_VALUE, rahasia)
        self.assertNotIn("kunci-asli", rahasia)
        self.assertIn("odoo_url", rahasia)  # daftar field bukan rahasia

    def test_detail_lengkap_dan_tetap_di_mask(self):
        log = self.make_log(
            action="master.update",
            payload={"wa_api_key": "kunci-wa", "backend": "mock"},
            metadata={"password": "p4ss", "nested": {"access_token": "tok-123"}},
            request_id="req-detail",
        )

        response = self.api.get(f"{AUDIT_URL}{log.pk}/")

        self.assertEqual(response.status_code, 200)
        audit = response.json()["audit"]

        self.assertEqual(set(audit) - ROW_KEYS, {"payload", "metadata", "user_agent"})
        self.assertEqual(audit["payload"]["backend"], "mock")
        self.assertEqual(audit["payload"]["wa_api_key"], MASK_VALUE)
        self.assertEqual(audit["metadata"]["password"], MASK_VALUE)
        self.assertEqual(audit["metadata"]["nested"]["access_token"], MASK_VALUE)
        self.assertEqual(audit["request_id"], "req-detail")
        # tidak ada nilai rahasia yang bocor di seluruh body
        self.assertNotIn("kunci-wa", str(response.json()))
        self.assertNotIn("p4ss", str(response.json()))
        self.assertNotIn("tok-123", str(response.json()))

    def test_detail_tidak_ditemukan_404(self):
        response = self.api.get(f"{AUDIT_URL}999999/")

        self.assertEqual(response.status_code, 404)
        self.assertIn("tidak ditemukan", response.json()["detail"])

    def test_mask_sensitive_pure_rekursif(self):
        masked = mask_sensitive(
            {
                "api_key": "a",
                "X-Api-Key": "b",
                "PASSWORD": "c",
                "client_secret": "d",
                "access_token": "e",
                "key": "f",
                "aman": "g",
                "kosong": "",
                "nested": {"token": "h", "list": [{"secret": "i"}, "j"]},
                "angka": 5,
            }
        )

        self.assertEqual(masked["api_key"], MASK_VALUE)
        self.assertEqual(masked["X-Api-Key"], MASK_VALUE)
        self.assertEqual(masked["PASSWORD"], MASK_VALUE)
        self.assertEqual(masked["client_secret"], MASK_VALUE)
        self.assertEqual(masked["access_token"], MASK_VALUE)
        self.assertEqual(masked["key"], MASK_VALUE)
        self.assertEqual(masked["aman"], "g")
        self.assertEqual(masked["kosong"], "")  # kosong tetap kosong (bukan mask)
        self.assertEqual(masked["nested"]["token"], MASK_VALUE)
        self.assertEqual(masked["nested"]["list"][0]["secret"], MASK_VALUE)
        self.assertEqual(masked["nested"]["list"][1], "j")
        self.assertEqual(masked["angka"], 5)
        # fungsi TIDAK mengubah input
        self.assertEqual(mask_sensitive("teks"), "teks")
        self.assertEqual(mask_sensitive(None), None)


class AuditSecurityReadOnlyTests(AuditLogViewerTestCase):
    """Izin ADMIN/OWNER, bukti read-only, dan non-breaking."""

    def test_anonim_dan_operator_403(self):
        log = self.make_log()

        anonim = self.as_user(None)

        self.assertEqual(anonim.get(AUDIT_URL).status_code, 403)
        self.assertEqual(anonim.get(f"{AUDIT_URL}{log.pk}/").status_code, 403)

        operator = self.as_user(self.operator)

        self.assertEqual(operator.get(AUDIT_URL).status_code, 403)
        self.assertEqual(operator.get(f"{AUDIT_URL}{log.pk}/").status_code, 403)

    def test_viewer_tidak_pernah_menulis_dan_write_405(self):
        self.make_log()
        sebelum = AuditLog.objects.count()

        # list + detail (berulang) tidak boleh menambah/mengubah baris audit
        self.assertEqual(self.get().status_code, 200)
        self.get(action="master.")
        detail = self.api.get(f"{AUDIT_URL}{AuditLog.objects.first().pk}/")

        self.assertEqual(detail.status_code, 200)
        self.assertEqual(AuditLog.objects.count(), sebelum)

        # tidak ada endpoint tulis pada viewer
        self.assertEqual(self.api.post(AUDIT_URL, {}, format="json").status_code, 405)
        self.assertEqual(self.api.put(AUDIT_URL, {}, format="json").status_code, 405)
        self.assertEqual(self.api.delete(AUDIT_URL).status_code, 405)

    def test_non_breaking_f9_dan_h5_lain(self):
        # F9 (audit produk tanpa odoo_id) TIDAK berubah & tetap punya endpoint sendiri
        produk = self.api.get("/api/v1/audit/products-missing-odoo-id/")

        self.assertEqual(produk.status_code, 200)
        self.assertIn("count", produk.json())

        # endpoint Settings H5.1/H5.6/H5.8 + monitoring sync tetap hijau
        self.assertEqual(self.api.get("/api/v1/settings/company/").status_code, 200)
        self.assertEqual(self.api.get("/api/v1/settings/integration/").status_code, 200)
        self.assertEqual(self.api.get("/api/v1/settings/wa/").status_code, 200)
        self.assertEqual(self.api.get("/api/v1/sync/records/").status_code, 200)

    def test_writer_auditlog_masih_normal(self):
        from core.audit.services import AuditLogger

        before = AuditLog.objects.count()
        record = AuditLogger().log(
            user=self.admin,
            action="master.create",
            resource="master.product",
            resource_id=99,
            payload={"api_key": "rahasia-writer"},
            metadata={"fields": ["code"]},
        )

        self.assertEqual(AuditLog.objects.count(), before + 1)
        self.assertEqual(record.result, AuditLog.Result.OK)

        # baris BARU itu langsung bisa dibaca viewer + rahasianya di-mask
        response = self.get(search="master.create")
        rows = [row for row in response.json()["rows"] if row["id"] == record.pk]

        self.assertEqual(len(rows), 1)

        detail = self.api.get(f"{AUDIT_URL}{record.pk}/").json()["audit"]

        self.assertEqual(detail["payload"]["api_key"], MASK_VALUE)
        self.assertNotIn("rahasia-writer", str(detail))

    def test_model_auditlog_tidak_diubah(self):
        # APPEND-ONLY: H5.5 hanya membaca — ordering & index lama harus tetap sama
        self.assertEqual(AuditLog._meta.ordering, ("-timestamp", "-id"))

        index_names = {index.name for index in AuditLog._meta.indexes}

        self.assertEqual(
            index_names, {"audit_resource_idx", "audit_user_ts_idx"}
        )

        field_names = {field.name for field in AuditLog._meta.get_fields()}

        self.assertTrue(
            {
                "timestamp",
                "user",
                "action",
                "resource",
                "resource_id",
                "request_id",
                "ip_address",
                "user_agent",
                "payload",
                "result",
                "metadata",
            }.issubset(field_names)
        )




