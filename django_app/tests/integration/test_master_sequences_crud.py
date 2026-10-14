"""Test **H5.3** — Number Sequence CRUD (``/api/v1/settings/sequences/``).

Extend Sprint C (`tests/integration/test_master_sequences.py` — 16 test, tetap hijau):

  * ``POST   /api/v1/settings/sequences/``  → buat baris ``(code, year)`` baru
    (``last_seq=0``, ``is_active=True``). Guard create: ``code`` ``^[A-Z0-9]{2,16}$``
    (auto-upper), ``prefix`` opsional default = ``code`` ``^[A-Z0-9-]{1,16}$``,
    ``padding`` default 4 (1..10), nama wajib ≤64, duplikat ``(code, year)`` → **400**;
  * ``DELETE /api/v1/settings/sequences/<code>/`` → **soft delete** (``is_active=False``)
    → **204**; guard pemakaian → **400** (9 kode seed terlindungi ATAU ``last_seq > 0``);
  * GET list filter ``?search=&active=&year=`` (verifikasi — sudah ada Sprint C).

Keputusan STEP 0 H5.3:
  * ``PROTECTED_SEQUENCE_CODES`` = **9** (7 Sprint C + ``ADJ`` H2.5 + ``TRF`` H2.6) —
    hanya guard **DELETE**, bukan create (restore seed yang hilang tetap boleh);
  * tanpa ``delete()`` DB — nomor lama tetap bisa dilacak;
  * MES-only: tiap tulis menulis ``SyncRecord`` ``SKIPPED`` + ``AuditLog``
    (``master.create``/``master.delete``).

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_master_sequences_crud.py -q
"""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from core.audit.models import AuditLog
from core.auth.models import Role, User
from integrations.erp_sync.models import SyncRecord, SyncResource, SyncStage, SyncStatus
from master import sequence_services
from master.models import NumberSequence
from master.sequence_services import MES_ONLY_REASON, PROTECTED_SEQUENCE_CODES

LIST_URL = "/api/v1/settings/sequences/"
ROW_KEYS = {
    "id",
    "code",
    "name",
    "prefix",
    "year",
    "last_seq",
    "padding",
    "is_active",
    "next_number",
    "created_at",
    "updated_at",
}
#: Seed nyata (7 Sprint C + ADJ H2.5 + TRF H2.6) — brief menyebut 7 (outdated).
SEEDED_CODES = ("SO", "PO", "WO", "INV", "VB", "PAY", "JE", "ADJ", "TRF")


def detail_url(code: str) -> str:
    """URL detail (PUT/DELETE) satu sequence."""
    return f"{LIST_URL}{code}/"


class SequenceCrudTestCase(TestCase):
    """Basis bersama: user admin/operator + klien admin siap pakai."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="admin-seq-crud",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.ADMIN),
        )
        cls.operator = User.objects.create_user(
            username="op-seq-crud",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.OPERATOR),
        )

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.admin)
        self.year = sequence_services.current_year()

    def as_user(self, user):
        """Client terautentikasi sebagai ``user`` (anonim kalau ``None``)."""
        client = APIClient()
        if user is not None:
            client.force_authenticate(user)
        return client

    def create(self, **body):
        """POST create dengan klien admin."""
        return self.api.post(LIST_URL, body, format="json")

    def sequence(self, code: str, year: int | None = None) -> NumberSequence:
        """Baris sequence tahun berjalan (atau ``year`` eksplisit)."""
        return NumberSequence.objects.get(
            code=code, year=self.year if year is None else year
        )

    def sync_records(self, sequence: NumberSequence):
        """Ledger ``SyncRecord`` milik satu baris sequence."""
        return SyncRecord.objects.filter(
            resource=SyncResource.MASTER_NUMBER_SEQUENCE.value,
            resource_id=str(sequence.pk),
            stage=SyncStage.MASTER_PUSH.value,
        )

    def audit_logs(self, sequence: NumberSequence, action: str | None = None):
        """AuditLog milik satu baris sequence (opsional difilter action)."""
        queryset = AuditLog.objects.filter(
            resource=SyncResource.MASTER_NUMBER_SEQUENCE.value,
            resource_id=str(sequence.pk),
        )

        return queryset.filter(action=action) if action else queryset


class SequenceCreateTests(SequenceCrudTestCase):
    """``POST /settings/sequences/`` — create + validasi + ledger/audit."""

    def test_create_sequence_ok(self):
        response = self.create(code="CUSTOM1", name="Custom Satu", prefix="CUS", padding=6)

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(set(body), ROW_KEYS)
        self.assertEqual(body["code"], "CUSTOM1")
        self.assertEqual(body["name"], "Custom Satu")
        self.assertEqual(body["prefix"], "CUS")
        self.assertEqual(body["year"], self.year)
        self.assertEqual(body["last_seq"], 0)
        self.assertEqual(body["padding"], 6)
        self.assertTrue(body["is_active"])
        self.assertEqual(body["next_number"], f"CUS-{self.year}-000001")
        self.assertEqual(self.sequence("CUSTOM1").last_seq, 0)

    def test_create_default_prefix_padding_dan_tahun_param(self):
        response = self.create(code="CUSTOM2", name="Custom Dua")

        self.assertEqual(response.status_code, 201)
        body = response.json()
        # prefix default = code, padding default = 4
        self.assertEqual(body["prefix"], "CUSTOM2")
        self.assertEqual(body["padding"], 4)
        self.assertEqual(body["next_number"], f"CUSTOM2-{self.year}-0001")

        # ?year=<tahun> mengarahkan baris ke tahun lain (default tahun berjalan)
        lain = self.api.post(
            f"{LIST_URL}?year={self.year + 1}",
            {"code": "CUSTOM2", "name": "Custom Dua"},
            format="json",
        )

        self.assertEqual(lain.status_code, 201)
        self.assertEqual(lain.json()["year"], self.year + 1)

    def test_create_code_auto_upper_dan_trim(self):
        response = self.create(code=" custom3 ", name="  Custom Tiga  ", prefix=" cst-3 ")

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["code"], "CUSTOM3")
        self.assertEqual(body["name"], "Custom Tiga")
        self.assertEqual(body["prefix"], "CST-3")

    def test_create_duplicate_400(self):
        # `SO` adalah kode seed tahun berjalan → duplikat (code, year)
        response = self.create(code="SO", name="Sales Order")

        self.assertEqual(response.status_code, 400)
        self.assertIn("sudah ada", response.json()["detail"])
        self.assertEqual(NumberSequence.objects.filter(code="SO").count(), 1)

        # duplikat kode yang baru dibuat juga ditolak
        self.assertEqual(self.create(code="CUSTOM4", name="X").status_code, 201)
        kedua = self.create(code="CUSTOM4", name="X")

        self.assertEqual(kedua.status_code, 400)
        self.assertIn("sudah ada", kedua.json()["detail"])

    def test_create_kode_invalid_400(self):
        for code in ("", "   ", "A", "A" * 17, "AB CD", "AB!", "AB-CD", "AB_CD"):
            with self.subTest(code=code):
                response = self.create(code=code, name="X")

                self.assertEqual(response.status_code, 400)
                self.assertIn("code", response.json()["detail"])

    def test_create_prefix_invalid_400(self):
        for prefix in ("AB CD", "CST_1", "CST/1", "X" * 17):
            with self.subTest(prefix=prefix):
                response = self.create(code="CUSTOM5", name="X", prefix=prefix)

                self.assertEqual(response.status_code, 400)
                self.assertIn("prefix", response.json()["detail"])

    def test_create_padding_invalid_400(self):
        for padding in (0, 11, "4", 2.5, True):
            with self.subTest(padding=padding):
                response = self.create(code="CUSTOM6", name="X", padding=padding)

                self.assertEqual(response.status_code, 400)
                self.assertIn("padding", response.json()["detail"])

    def test_create_name_wajib_dan_maks(self):
        kosong = self.create(code="CUSTOM7")

        self.assertEqual(kosong.status_code, 400)
        self.assertIn("name", kosong.json()["detail"])

        panjang = self.create(code="CUSTOM7", name="X" * 65)

        self.assertEqual(panjang.status_code, 400)
        self.assertIn("name", panjang.json()["detail"])

    def test_create_abaikan_year_last_seq_is_active_dari_body(self):
        """``year``/``last_seq``/``is_active`` SELALU diisi service (body diabaikan)."""
        response = self.create(
            code="CUSTOM8", name="X", year=1999, last_seq=99, is_active=False
        )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["year"], self.year)
        self.assertEqual(body["last_seq"], 0)
        self.assertTrue(body["is_active"])

    def test_create_protected_code_boleh_kalau_belum_ada(self):
        """``PROTECTED_SEQUENCE_CODES`` HANYA guard DELETE — create ulang boleh."""
        NumberSequence.objects.filter(code="SO").delete()

        response = self.create(code="so", name="Sales Order")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["code"], "SO")
        self.assertEqual(NumberSequence.objects.filter(code="SO").count(), 1)

    def test_create_ledger_skipped_dan_audit(self):
        self.create(code="CUSTOM9", name="Custom Sembilan")
        sequence = self.sequence("CUSTOM9")

        record = self.sync_records(sequence).get()

        self.assertEqual(record.status, SyncStatus.SKIPPED)
        self.assertEqual(record.last_error, MES_ONLY_REASON)
        self.assertEqual(record.payload["code"], "CUSTOM9")
        self.assertEqual(record.payload["last_seq"], 0)

        log = self.audit_logs(sequence, "master.create").get()

        self.assertTrue(log.metadata["mes_only"])
        self.assertEqual(log.metadata["year"], self.year)

    def test_create_non_admin_dan_anonim_403(self):
        body = {"code": "CUSTOM10", "name": "X"}

        self.assertEqual(
            self.as_user(self.operator).post(LIST_URL, body, format="json").status_code,
            403,
        )
        self.assertEqual(
            self.as_user(None).post(LIST_URL, body, format="json").status_code, 403
        )
        self.assertFalse(NumberSequence.objects.filter(code="CUSTOM10").exists())


class SequenceDeleteTests(SequenceCrudTestCase):
    """``DELETE /settings/sequences/<code>/`` — soft delete + guard + ledger/audit."""

    def test_delete_sequence_ok_soft_delete(self):
        self.create(code="CUSTOM1", name="X")
        sequence = self.sequence("CUSTOM1")

        response = self.api.delete(detail_url("CUSTOM1"))

        self.assertEqual(response.status_code, 204)
        sequence.refresh_from_db()
        self.assertFalse(sequence.is_active)
        self.assertEqual(sequence.last_seq, 0)
        # baris TIDAK dihapus dari DB (soft delete) — nomor lama tetap bisa dilacak
        self.assertTrue(NumberSequence.objects.filter(pk=sequence.pk).exists())

        record = self.sync_records(sequence).get()

        self.assertEqual(record.status, SyncStatus.SKIPPED)
        logs = self.audit_logs(sequence, "master.delete")

        self.assertEqual(logs.count(), 1)
        self.assertTrue(logs.first().metadata["soft_delete"])

    def test_delete_protected_seed_400(self):
        response = self.api.delete(detail_url("SO"))

        self.assertEqual(response.status_code, 400)
        self.assertIn("protected seed", response.json()["detail"])
        self.assertTrue(self.sequence("SO").is_active)

        for code in sorted(PROTECTED_SEQUENCE_CODES):
            with self.subTest(code=code):
                self.assertEqual(self.api.delete(detail_url(code)).status_code, 400)
                self.assertTrue(self.sequence(code).is_active)

    def test_delete_last_seq_gt_0_400(self):
        self.create(code="CUSTOM2", name="X")
        sequence_services.next_number("CUSTOM2")

        response = self.api.delete(detail_url("CUSTOM2"))

        self.assertEqual(response.status_code, 400)
        self.assertIn("last_seq=1", response.json()["detail"])
        self.assertTrue(self.sequence("CUSTOM2").is_active)

    def test_delete_kode_dikenal_tapi_tahun_lain(self):
        self.assertEqual(self.api.delete(detail_url("ZZ")).status_code, 404)

        dibuat = self.api.post(
            f"{LIST_URL}?year={self.year + 1}",
            {"code": "CUSTOM3", "name": "X"},
            format="json",
        )

        self.assertEqual(dibuat.status_code, 201)
        self.assertEqual(
            self.api.delete(f"{detail_url('CUSTOM3')}?year={self.year + 1}").status_code,
            204,
        )

    def test_delete_non_admin_dan_anonim_403(self):
        self.create(code="CUSTOM4", name="X")

        self.assertEqual(
            self.as_user(self.operator).delete(detail_url("CUSTOM4")).status_code, 403
        )
        self.assertEqual(
            self.as_user(None).delete(detail_url("CUSTOM4")).status_code, 403
        )
        self.assertTrue(self.sequence("CUSTOM4").is_active)


class SequenceNonBreakingTests(SequenceCrudTestCase):
    """Sprint C TIDAK boleh rusak: seed list, filter, ``next_number``."""

    def test_list_seed_filter_dan_next_number_tetap_jalan(self):
        body = self.api.get(LIST_URL).json()

        self.assertEqual(body["total_count"], len(SEEDED_CODES))
        self.assertEqual([row["code"] for row in body["rows"]], sorted(SEEDED_CODES))
        self.assertEqual(sequence_services.next_number("SO"), f"SO-{self.year}-0001")

        self.create(code="CUSTOM5", name="Custom Lima")

        cocok = self.api.get(LIST_URL, {"search": "Custom Lima"}).json()["rows"]

        self.assertEqual([row["code"] for row in cocok], ["CUSTOM5"])

        semua = self.api.get(LIST_URL, {"year": "all"}).json()["rows"]

        self.assertIn("CUSTOM5", [row["code"] for row in semua])

        self.assertEqual(self.api.delete(detail_url("CUSTOM5")).status_code, 204)
        nonaktif = self.api.get(LIST_URL, {"active": "false"}).json()["rows"]

        self.assertEqual([row["code"] for row in nonaktif], ["CUSTOM5"])


