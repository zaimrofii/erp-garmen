"""Test Sprint C — Number Sequence (``/api/v1/settings/sequences/``).

Cakupan: format ``<PREFIX>-<YEAR>-<SEQ:04d>``, increment **atomic**
(``select_for_update``) & unik, **reset per tahun** (baris baru ``(code, year)``),
pratinjau **tanpa** increment, ``prefix``/``padding`` custom, izin (anonim 403,
tulis ADMIN/OWNER), serta kewajiban Sprint C: ``SyncRecord``
``master.number_sequence``/``MASTER_PUSH`` ber-status **``SKIPPED``** (MES-only) +
``AuditLog`` tiap penomoran/perubahan.

Keputusan Sprint C (STEP 0 — probe Odoo 17 + recon):
  * **MES-only** — ``ir.sequence`` Odoo ADA (19 field, 37 record) **tetapi** itu counter
    internal dokumen Odoo sendiri (``prefix='CHIC1/INT/'``, ``code`` tidak required);
    ``ir.sequence.date_range`` ADA tapi 0 record ⇒ menulis ``number_next`` akan merusak
    penomoran dokumen Odoo ⇒ nomor MES tidak dikirim (ledger ``SKIPPED``), tanpa ``odoo_id``;
  * API di ``garment/api/settings/views.py`` (path ``/settings/…``, konsisten B22);
    service di ``master/sequence_services.py``;
  * ``code`` **tidak** unik global: keunikan = ``(code, year)`` karena baris tahun baru
    dibuat saat reset (spec brief menyebut keduanya — kontradiktif ⇒ intent menang);
  * ``code``/``year``/``last_seq`` **tidak** bisa diubah lewat PUT (400).

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_master_sequences.py -q
"""

from __future__ import annotations

from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from core.audit.models import AuditLog
from core.auth.models import Role, User
from integrations.erp_sync.models import SyncRecord, SyncResource, SyncStage, SyncStatus
from master import sequence_services
from master.models import NumberSequence
from master.sequence_services import MES_ONLY_REASON, SequenceError

LIST_URL = "/api/v1/settings/sequences/"
ENVELOPE_KEYS = {"rows", "total_count", "has_more", "next_cursor"}
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
PREVIEW_KEYS = {
    "code",
    "name",
    "prefix",
    "year",
    "last_seq",
    "padding",
    "is_active",
    "next_number",
}
#: Prefix default hasil seed migration (Sprint C 7 + `ADJ` H2.5 + `TRF` H2.6).
SEEDED_CODES = ("SO", "PO", "WO", "INV", "VB", "PAY", "JE", "ADJ", "TRF")


def preview_url(code: str) -> str:
    """URL pratinjau satu sequence."""
    return f"{LIST_URL}{code}/preview/"


def detail_url(code: str) -> str:
    """URL detail/ubah satu sequence."""
    return f"{LIST_URL}{code}/"


class SequenceTestCase(TestCase):
    """Basis bersama: user admin/operator + klien admin siap pakai."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="admin-seq",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.ADMIN),
        )
        cls.operator = User.objects.create_user(
            username="op-seq",
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

    @staticmethod
    def sequence(code: str, year: int | None = None) -> NumberSequence:
        """Baris sequence seed untuk tahun berjalan (dibuat migration 0014)."""
        target_year = sequence_services.current_year() if year is None else year
        return NumberSequence.objects.get(code=code, year=target_year)


class SequenceServiceTests(SequenceTestCase):
    """Service `master/sequence_services.py` — format, increment, reset, preview."""

    def test_next_number_generate_format(self):
        year = sequence_services.current_year()

        number = sequence_services.next_number("SO")

        self.assertEqual(number, f"SO-{year}-0001")
        self.assertEqual(self.sequence("SO").last_seq, 1)

    def test_next_number_increment(self):
        year = sequence_services.current_year()

        pertama = sequence_services.next_number("SO")
        kedua = sequence_services.next_number("SO")
        ketiga = sequence_services.next_number("SO")

        self.assertEqual(
            (pertama, kedua, ketiga),
            (f"SO-{year}-0001", f"SO-{year}-0002", f"SO-{year}-0003"),
        )
        self.assertEqual(self.sequence("SO").last_seq, 3)

    def test_next_number_atomic_unik_antar_prefix(self):
        """Tiap prefix punya counter sendiri; nomor yang dihasilkan tidak bertabrakan."""
        numbers = [
            sequence_services.next_number(code) for code in ("SO", "PO", "SO", "WO", "PO")
        ]

        self.assertEqual(len(set(numbers)), len(numbers))
        self.assertEqual(self.sequence("SO").last_seq, 2)
        self.assertEqual(self.sequence("PO").last_seq, 2)
        self.assertEqual(self.sequence("WO").last_seq, 1)

    def test_preview_tidak_increment(self):
        year = sequence_services.current_year()

        preview = sequence_services.preview_number("SO")

        self.assertEqual(preview["next_number"], f"SO-{year}-0001")
        self.assertEqual(preview["last_seq"], 0)
        self.assertEqual(self.sequence("SO").last_seq, 0)

        sequence_services.next_number("SO")
        self.assertEqual(
            sequence_services.preview_number("SO")["next_number"], f"SO-{year}-0002"
        )

    def test_reset_saat_tahun_berubah(self):
        tahun_lama = sequence_services.current_year()
        tahun_baru = tahun_lama + 1
        sequence_services.next_number("SO")

        with mock.patch.object(sequence_services, "current_year", return_value=tahun_baru):
            nomor = sequence_services.next_number("SO")
            preview = sequence_services.preview_number("SO")
            baris_baru = sequence_services.get_or_create_current_year("SO")
            hasil_reset = sequence_services.reset_if_new_year(self.sequence("SO"))

        self.assertEqual(nomor, f"SO-{tahun_baru}-0001")
        self.assertEqual(preview["next_number"], f"SO-{tahun_baru}-0002")
        self.assertEqual(baris_baru.prefix, "SO")
        self.assertEqual(baris_baru.last_seq, 1)
        self.assertEqual(hasil_reset.year, tahun_baru)
        # baris tahun lama TIDAK diubah (nomor lama tetap bisa dilacak)
        self.assertEqual(self.sequence("SO", tahun_lama).last_seq, 1)
        self.assertEqual(NumberSequence.objects.filter(code="SO").count(), 2)

    def test_prefix_dan_padding_custom(self):
        year = sequence_services.current_year()
        sequence = self.sequence("SO")
        sequence.prefix = "SO-2"
        sequence.padding = 6
        sequence.save(update_fields=("prefix", "padding"))

        self.assertEqual(sequence_services.next_number("SO"), f"SO-2-{year}-000001")
        self.assertEqual(sequence_services.next_number("SO"), f"SO-2-{year}-000002")

    def test_sequence_nonaktif_tidak_bisa_dinomori(self):
        NumberSequence.objects.filter(code="SO").update(is_active=False)

        with self.assertRaises(SequenceError):
            sequence_services.next_number("SO")


class SequencePermissionAndEndpointTests(SequenceTestCase):
    """Endpoint list/preview/PUT (anonim 403, tulis ADMIN/OWNER)."""

    def test_auth_403_anonim(self):
        anonim = self.as_user(None)

        self.assertEqual(anonim.get(LIST_URL).status_code, 403)
        self.assertEqual(anonim.get(preview_url("SO")).status_code, 403)
        self.assertEqual(
            anonim.put(detail_url("SO"), {"prefix": "X"}, format="json").status_code, 403
        )

    def test_list_endpoint(self):
        body = self.api.get(LIST_URL).json()

        self.assertEqual(set(body), ENVELOPE_KEYS)
        self.assertEqual(body["total_count"], len(SEEDED_CODES))
        row = body["rows"][0]
        self.assertEqual(set(row), ROW_KEYS)
        self.assertEqual([baris["code"] for baris in body["rows"]], sorted(SEEDED_CODES))
        self.assertEqual(row["prefix"], row["code"])
        self.assertEqual(row["padding"], 4)
        self.assertTrue(row["next_number"].endswith("-0001"))

    def test_list_filter_search(self):
        body = self.api.get(LIST_URL, {"search": "Sales"}).json()

        self.assertEqual([baris["code"] for baris in body["rows"]], ["SO"])
        self.assertEqual(self.api.get(LIST_URL, {"search": "ZZ"}).json()["total_count"], 0)
        self.assertEqual(self.api.get(LIST_URL, {"active": "bukan-bool"}).status_code, 400)

    def test_preview_endpoint_dan_404(self):
        year = sequence_services.current_year()

        body = self.api.get(preview_url("SO")).json()

        self.assertEqual(set(body), PREVIEW_KEYS)
        self.assertEqual(body["code"], "SO")
        self.assertEqual(body["year"], year)
        self.assertEqual(body["next_number"], f"SO-{year}-0001")
        self.assertEqual(self.sequence("SO").last_seq, 0)

        hilang = self.api.get(preview_url("ZZ"))

        self.assertEqual(hilang.status_code, 404)
        self.assertIn("tidak dikenal", hilang.json()["detail"])

    def test_update_prefix_admin(self):
        year = sequence_services.current_year()

        response = self.api.put(
            detail_url("SO"), {"prefix": "SO-2", "padding": 5}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["prefix"], "SO-2")
        self.assertEqual(body["padding"], 5)
        self.assertEqual(body["last_seq"], 0)
        self.assertEqual(body["next_number"], f"SO-2-{year}-00001")

        # penomoran berikutnya memakai nilai baru
        self.assertEqual(sequence_services.next_number("SO"), f"SO-2-{year}-00001")

    def test_update_guard_404_dan_400(self):
        self.assertEqual(
            self.api.put(detail_url("ZZ"), {"prefix": "X"}, format="json").status_code, 404
        )
        self.assertEqual(
            self.api.put(detail_url("SO"), {"prefix": "  "}, format="json").status_code, 400
        )
        self.assertEqual(
            self.api.put(detail_url("SO"), {"last_seq": 99}, format="json").status_code, 400
        )

    def test_update_prefix_non_admin_403(self):
        response = self.as_user(self.operator).put(
            detail_url("SO"), {"prefix": "SO-2"}, format="json"
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.sequence("SO").prefix, "SO")


class SequenceLedgerTests(SequenceTestCase):
    """Kewajiban Sprint C: SyncRecord SKIPPED (MES-only) + AuditLog."""

    def test_syncrecord_skipped_ditulis(self):
        year = sequence_services.current_year()
        sequence_services.next_number("SO")
        urutan = self.sequence("SO")

        record = SyncRecord.objects.get(
            resource=SyncResource.MASTER_NUMBER_SEQUENCE.value,
            resource_id=str(urutan.pk),
            stage=SyncStage.MASTER_PUSH.value,
        )

        self.assertEqual(record.status, SyncStatus.SKIPPED)
        self.assertEqual(record.last_error, MES_ONLY_REASON)
        self.assertEqual(record.payload["code"], "SO")
        self.assertEqual(record.payload["last_seq"], 1)
        self.assertEqual(record.payload["next_number"], f"SO-{year}-0002")

    def test_auditlog_ditulis(self):
        sequence_services.next_number("SO")
        urutan = self.sequence("SO")
        self.api.put(detail_url("SO"), {"prefix": "SO-2"}, format="json")

        logs = AuditLog.objects.filter(
            resource=SyncResource.MASTER_NUMBER_SEQUENCE.value,
            resource_id=str(urutan.pk),
            action="master.update",
        )

        self.assertEqual(logs.count(), 2)
        self.assertTrue(all(log.metadata["mes_only"] for log in logs))


