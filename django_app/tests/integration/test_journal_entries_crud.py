"""Test CRUD **Journal Entry** manual MES — `/api/v1/finance/journal-entries/` (H3.4).

Cakupan: create **DRAFT** (nomor `JE-…`, baris nested atomic), validasi **400**
(journal wajib/ada, tanggal wajib, ≥ 2 baris, debit XOR credit, bukan keduanya nol,
tidak negatif, Σ debit = Σ kredit + toleransi 0.01, akun ada), update & delete
**DRAFT-only** (baris diganti menyatu), list (pagination/filter state/journal/rentang
tanggal/search), detail (baris jurnal + `allowed_actions`), izin (anon **403**, role
selain ADMIN/OWNER **403**), transisi ``confirm`` → ``done`` → ``cancel`` + **guard
STEP 0** (journal `general` saja, `odoo_id` journal & akun wajib), ledger
``SyncRecord`` (resource **`journal_entry`**, stage **`JOURNAL_ENTRY`** — keduanya
BARU) + ``AuditLog``, task ``erp_sync.push_journal_entry`` (sukses → SENT +
``odoo_id``; gagal → SyncRecord FAILED tapi state tetap CONFIRMED), adapter Odoo
(payload `move_type='entry'` + `line_ids` commands, TANPA `action_post`/
`currency_id`/`company_id`/`display_type`/`narration`), endpoint read-only master
**Account**/**Journal** H3.4, pull `account.account` → `master.Account`
(deprecated → `is_active=False`) + `journal_type` dari pull journal, serta
**non-breaking** ledger jalur lain (H3.1–H3.3 tetap memakai resource/stage-nya).

Catatan:
  * enqueue task di-patch (pola H1.2/H2.1/H3.1–H3.3) supaya test tidak menyentuh broker;
  * adapter di-patch / di-mock untuk menguji payload push nyata (tanpa Odoo);
  * **posting TIDAK diuji** karena memang bukan tanggung jawab MES (keputusan STEP 0).

Jalankan (di dalam container):

    docker compose exec -T django python -m pytest tests/integration/test_journal_entries_crud.py -q
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.models import JournalEntry, JournalEntryLine
from apps_industry.garment.services import journal_entry_services as svc
from core.audit.models import AuditLog
from core.auth.models import Role, User
from integrations.erp_sync.adapters.base import ERPResponse
from integrations.erp_sync.adapters.odoo import (
    STAGE_JOURNAL_ENTRY,
    OdooAdapter,
)
from integrations.erp_sync.idempotency import VALID_STAGES
from integrations.erp_sync.models import SyncRecord, SyncResource, SyncStage, SyncStatus
from integrations.erp_sync.tasks_journal_entry_push import push_journal_entry
from integrations.erp_sync.tasks_master import (
    _account_defaults,
    _journal_defaults,
    sync_master_accounts,
    sync_master_journals,
)
from master.models import Account, Journal, Partner

ENTRIES_URL = "/api/v1/finance/journal-entries/"
ACCOUNTS_URL = "/api/v1/master/accounts/"
JOURNALS_URL = "/api/v1/master/journals/"
ENVELOPE_KEYS = {"rows", "total_count", "has_more", "next_cursor"}
ROW_KEYS = {
    "id",
    "code",
    "journal_id",
    "journal_code",
    "journal_name",
    "journal_type",
    "entry_date",
    "ref",
    "memo",
    "total_debit",
    "total_credit",
    "state",
    "odoo_id",
    "created_at",
    "updated_at",
}
DETAIL_EXTRA_KEYS = {
    "lines",
    "line_count",
    "odoo_sync_status",
    "odoo_sync_error",
    "allowed_actions",
}
LINE_KEYS = {
    "id",
    "account_id",
    "account_code",
    "account_name",
    "partner_id",
    "partner_name",
    "name",
    "debit",
    "credit",
}
#: Info tulis (hanya pada respons POST/PUT/aksi — ``_write_body``).
WRITE_EXTRA_KEYS = {"sync_record_id", "task_id", "queued"}
#: Kunci baris master Account H3.4 (endpoint read-only `/api/v1/master/accounts/`).
ACCOUNT_ROW_KEYS = {
    "id",
    "odoo_id",
    "code",
    "name",
    "account_type",
    "account_type_label",
    "reconcile",
    "active",
}
#: Kunci baris master Journal H3.4 (endpoint read-only `/api/v1/master/journals/`).
JOURNAL_ROW_KEYS = {
    "id",
    "odoo_id",
    "code",
    "name",
    "journal_type",
    "journal_type_label",
    "is_general",
    "active",
}
#: Path patch enqueue task (service meng-enqueue saat confirm/cancel).
ENQUEUE = "integrations.erp_sync.tasks_journal_entry_push.push_journal_entry.apply_async"
#: Path patch adapter di module task (menguji payload & jalur sukses/gagal).
ADAPTER = "integrations.erp_sync.tasks_journal_entry_push.get_adapter"
#: Path patch transport di module task master (uji pull, tanpa jaringan).
GET_TRANSPORT = "integrations.erp_sync.tasks_master.get_transport"
MOVE_ID = 555


def detail_url(pk: int) -> str:
    """URL detail journal entry."""
    return f"{ENTRIES_URL}{pk}/"


def action_url(pk: int, action: str) -> str:
    """URL aksi transisi journal entry."""
    return f"{ENTRIES_URL}{pk}/{action}/"


class FakeAdapter:
    """Adapter palsu: mencatat payload push/cancel tanpa menyentuh Odoo."""

    def __init__(self, ok: bool = True, erp_id: str = str(MOVE_ID), error: str | None = None):
        """Simpan konfigurasi respons + riwayat panggilan."""
        self.ok = ok
        self.erp_id = erp_id
        self.error = error
        self.pushed: list[dict] = []
        self.cancelled: list[str] = []
        self.closed = False

    def push_journal_entry(self, payload: dict) -> ERPResponse:
        """Catat payload push & balas sesuai konfigurasi."""
        self.pushed.append(dict(payload))

        return ERPResponse(
            ok=self.ok,
            erp_id=self.erp_id if self.ok else None,
            raw={"payload": dict(payload)},
            error=None if self.ok else (self.error or "push gagal"),
            stage=STAGE_JOURNAL_ENTRY,
            ref=str(payload.get("ref") or ""),
        )

    def cancel_journal_entry(self, erp_id: str) -> ERPResponse:
        """Catat erp_id yang dibatalkan & balas sesuai konfigurasi."""
        self.cancelled.append(str(erp_id))

        return ERPResponse(
            ok=self.ok,
            erp_id=self.erp_id if self.ok else None,
            raw={"cancelled": erp_id},
            error=None if self.ok else (self.error or "cancel gagal"),
            stage=STAGE_JOURNAL_ENTRY,
            ref=str(erp_id),
        )

    def close(self) -> None:
        """Tandai adapter ditutup (task wajib menutup di ``finally``)."""
        self.closed = True


class JournalEntryBase(TestCase):
    """Fixture bersama: user, journal (general/bank/legacy), akun, partner."""

    @classmethod
    def setUpTestData(cls):
        """Master data H3.4 (journal & chart of accounts hasil pull)."""
        cls.admin = User.objects.create_user(
            username="admin-je",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.ADMIN),
        )
        cls.operator = User.objects.create_user(
            username="op-je",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.OPERATOR),
        )

        cls.journal_general = Journal.objects.create(
            code="MISC", name="Operasi Lain-lain", odoo_id=10, journal_type="general"
        )
        cls.journal_bank = Journal.objects.create(
            code="BNK1", name="Bank", odoo_id=13, journal_type="bank"
        )
        #: Journal tanpa odoo_id (belum pernah di-pull) → guard confirm harus menolak.
        cls.journal_noid = Journal.objects.create(
            code="NOID", name="Belum Sync", odoo_id=None, journal_type="general"
        )
        #: Baris lama: journal_type kosong → guard longgar (keputusan STEP 0).
        cls.journal_legacy = Journal.objects.create(
            code="LEGACY", name="Journal Lama", odoo_id=99, journal_type=""
        )

        cls.account_expense = Account.objects.create(
            code="51000010", name="Cost of Goods Sold", odoo_id=181, account_type="expense"
        )
        cls.account_cash = Account.objects.create(
            code="11120005", name="Bank", odoo_id=223, account_type="asset_cash"
        )
        cls.account_noid = Account.objects.create(
            code="99999999", name="Belum Sync", odoo_id=None, account_type="expense"
        )
        cls.partner = Partner.objects.create(code="PT-JE", name="PT Contoh", odoo_id=10)

    def setUp(self):
        """Klien admin (utama) + operator (uji 403)."""
        self.api = APIClient()
        self.api.force_authenticate(self.admin)
        self.operator_api = APIClient()
        self.operator_api.force_authenticate(self.operator)

    # ------------------------------------------------------------------ helper
    def body(self, **overrides) -> dict:
        """Body create standar: 2 baris seimbang (debit 1500 = kredit 1500)."""
        body: dict = {
            "journal_id": self.journal_general.pk,
            "entry_date": "2026-10-13",
            "ref": "JE-TEST-001",
            "memo": "Jurnal uji",
            "lines": [
                {
                    "account_id": self.account_expense.pk,
                    "name": "Beban pokok",
                    "debit": "1500.00",
                    "credit": "0.00",
                },
                {
                    "account_id": self.account_cash.pk,
                    "name": "Kas keluar",
                    "debit": "0.00",
                    "credit": "1500.00",
                },
            ],
        }
        body.update(overrides)

        return body

    def post_entry(self, body: dict, client=None):
        """POST entry (enqueue di-patch) → ``(response, mock)``."""
        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-je-1")) as enqueue:
            response = (client or self.api).post(ENTRIES_URL, body, format="json")

        return response, enqueue

    def put_entry(self, pk: int, body: dict, client=None):
        """PUT entry (enqueue di-patch) → ``(response, mock)``."""
        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-je-put")) as enqueue:
            response = (client or self.api).put(detail_url(pk), body, format="json")

        return response, enqueue

    def act(self, pk: int, action: str, client=None):
        """POST aksi transisi (enqueue di-patch) → ``(response, mock)``."""
        with patch(ENQUEUE, return_value=SimpleNamespace(id=f"task-je-{action}")) as enqueue:
            response = (client or self.api).post(action_url(pk, action), {}, format="json")

        return response, enqueue

    def make_entry(self, **overrides) -> JournalEntry:
        """Buat entry DRAFT lewat service (tanpa enqueue)."""
        result = svc.create_entry(self.body(**overrides))

        self.assertIsNone(result.error, result.error)
        return result.entry

    def confirm_service(self, pk: int):
        """CONFIRM entry lewat service (enqueue di-patch) → ``(entry, result)``."""
        entry = JournalEntry.objects.get(pk=pk)
        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-je-confirm")):
            result = svc.confirm_entry(entry)

        self.assertIsNone(result.error, result.error)
        entry.refresh_from_db()
        return entry, result


class JournalEntryCrudTests(JournalEntryBase):
    """Create entry + validasi double-entry + izin."""

    def test_create_entry_draft_dengan_baris_nested(self):
        """POST → 201 (`JE-…`), 2 baris tersimpan, ledger `journal_entry`/`JOURNAL_ENTRY`."""
        response, enqueue = self.post_entry(self.body())

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertTrue(body["code"].startswith("JE-"))
        self.assertEqual(body["state"], "DRAFT")
        self.assertEqual(body["journal_id"], self.journal_general.pk)
        self.assertEqual(body["journal_code"], "MISC")
        self.assertEqual(body["journal_type"], "general")
        self.assertEqual(body["total_debit"], "1500.00")
        self.assertEqual(body["total_credit"], "1500.00")
        self.assertEqual(body["line_count"], 2)
        self.assertEqual(len(body["lines"]), 2)
        self.assertEqual(set(body["lines"][0]), LINE_KEYS)
        self.assertIsNone(body["odoo_id"])
        self.assertFalse(body["queued"])
        enqueue.assert_not_called()

        entry = JournalEntry.objects.get(pk=body["id"])
        self.assertEqual(entry.lines.count(), 2)
        self.assertEqual(entry.lines.filter(debit__gt=0).count(), 1)
        self.assertEqual(entry.lines.filter(credit__gt=0).count(), 1)

        record = SyncRecord.objects.get(pk=body["sync_record_id"])
        self.assertEqual(record.resource, SyncResource.JOURNAL_ENTRY.value)
        self.assertEqual(record.stage, SyncStage.JOURNAL_ENTRY.value)
        self.assertEqual(record.status, SyncStatus.PENDING)
        self.assertTrue(
            AuditLog.objects.filter(action=svc.ACTION_CREATE, resource_id=str(entry.pk)).exists()
        )

    def test_create_line_partner_opsional_terisi(self):
        """`partner_id` di baris bersifat opsional & di-*flatten* di detail."""
        lines = self.body()["lines"]
        lines[0]["partner_id"] = self.partner.pk
        response, _ = self.post_entry(self.body(lines=lines))

        self.assertEqual(response.status_code, 201)
        first = response.json()["lines"][0]
        self.assertEqual(first["partner_id"], self.partner.pk)
        self.assertEqual(first["partner_name"], "PT Contoh")
        self.assertIsNone(response.json()["lines"][1]["partner_id"])

    def test_create_tanpa_journal_400(self):
        """Journal wajib diisi."""
        response, _ = self.post_entry(self.body(journal_id=None))

        self.assertEqual(response.status_code, 400)
        self.assertIn("journal_id", response.json()["detail"])

    def test_create_journal_tidak_ada_400(self):
        """Journal id tak dikenal → 400 (bukan 404 resource)."""
        response, _ = self.post_entry(self.body(journal_id=999999))

        self.assertEqual(response.status_code, 400)
        self.assertIn("tidak ditemukan", response.json()["detail"])

    def test_create_tanggal_wajib_dan_iso_400(self):
        """`entry_date` wajib (Odoo `date` required) & harus ISO YYYY-MM-DD."""
        kosong, _ = self.post_entry(self.body(entry_date=""))
        salah_format, _ = self.post_entry(self.body(entry_date="13-10-2026"))

        self.assertEqual(kosong.status_code, 400)
        self.assertIn("entry_date", kosong.json()["detail"])
        self.assertEqual(salah_format.status_code, 400)
        self.assertIn("ISO", salah_format.json()["detail"])

    def test_create_lines_kurang_dua_400(self):
        """Minimal 2 baris (double-entry)."""
        satu = [dict(self.body()["lines"][0], credit="0.00")]
        response, _ = self.post_entry(self.body(lines=satu))

        self.assertEqual(response.status_code, 400)
        self.assertIn("minimal 2 baris", response.json()["detail"])

    def test_create_line_debit_dan_credit_sekaligus_400(self):
        """XOR: satu baris tidak boleh debit DAN credit > 0."""
        lines = self.body()["lines"]
        lines[0]["credit"] = "10.00"
        response, _ = self.post_entry(self.body(lines=lines))

        self.assertEqual(response.status_code, 400)
        self.assertIn("debit ATAU credit", response.json()["detail"])

    def test_create_line_debit_credit_tidak_valid_400(self):
        """Baris tanpa nilai (0/0) & nilai negatif ditolak."""
        nol = self.body()["lines"]
        nol[1]["credit"] = "0.00"
        nol[1]["debit"] = "0.00"
        kosong, _ = self.post_entry(self.body(lines=nol))

        negatif = self.body()["lines"]
        negatif[0]["debit"] = "-1500.00"
        minus, _ = self.post_entry(self.body(lines=negatif))

        self.assertEqual(kosong.status_code, 400)
        self.assertIn("wajib > 0", kosong.json()["detail"])
        self.assertEqual(minus.status_code, 400)
        self.assertIn("tidak boleh negatif", minus.json()["detail"])

    def test_create_tidak_seimbang_400(self):
        """Σ debit != Σ kredit (di luar toleransi) ditolak."""
        lines = self.body()["lines"]
        lines[1]["credit"] = "1400.00"
        response, _ = self.post_entry(self.body(lines=lines))

        self.assertEqual(response.status_code, 400)
        self.assertIn("tidak seimbang", response.json()["detail"])

    def test_create_selisih_0_01_diterima(self):
        """Selisih tepat 0.01 masih dalam toleransi (keputusan STEP 0)."""
        lines = self.body()["lines"]
        lines[1]["credit"] = "1499.99"
        response, _ = self.post_entry(self.body(lines=lines))

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["total_debit"], "1500.00")
        self.assertEqual(body["total_credit"], "1499.99")

    def test_create_account_tidak_ada_400(self):
        """Akun baris wajib ada di master Account."""
        lines = self.body()["lines"]
        lines[0]["account_id"] = 999999
        response, _ = self.post_entry(self.body(lines=lines))

        self.assertEqual(response.status_code, 400)
        self.assertIn("Account 999999 tidak ditemukan", response.json()["detail"])

    def test_create_anonim_403_dan_operator_403(self):
        """Anon 403 (IsAuthenticated) & role non-ADMIN/OWNER 403."""
        anon = APIClient().post(ENTRIES_URL, self.body(), format="json")
        operator, _ = self.post_entry(self.body(), client=self.operator_api)

        self.assertEqual(anon.status_code, 403)
        self.assertEqual(operator.status_code, 403)


class JournalEntryDraftGuardTests(JournalEntryBase):
    """Update/delete hanya boleh saat DRAFT (baris diganti menyatu)."""

    def test_update_draft_mengganti_baris(self):
        """PUT DRAFT → baris lama terhapus & total ikut berubah."""
        entry = self.make_entry()
        body = self.body(
            ref="JE-TEST-002",
            lines=[
                {
                    "account_id": self.account_cash.pk,
                    "name": "Kas masuk",
                    "debit": "250.00",
                    "credit": "0.00",
                },
                {
                    "account_id": self.account_expense.pk,
                    "name": "Beban",
                    "debit": "0.00",
                    "credit": "250.00",
                },
            ],
        )

        response, _ = self.put_entry(entry.pk, body)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["ref"], "JE-TEST-002")
        self.assertEqual(payload["total_debit"], "250.00")
        self.assertEqual(payload["line_count"], 2)
        entry.refresh_from_db()
        self.assertEqual(entry.lines.count(), 2)
        self.assertEqual(entry.lines.filter(debit="250.00").count(), 1)
        self.assertTrue(
            AuditLog.objects.filter(action=svc.ACTION_UPDATE, resource_id=str(entry.pk)).exists()
        )

    def test_update_parsial_dan_setelah_confirm_400(self):
        """PUT hanya `memo` mempertahankan baris; setelah CONFIRMED semua PUT/DELETE 400."""
        entry = self.make_entry()
        partial, _ = self.put_entry(entry.pk, {"memo": "memo baru"})

        self.assertEqual(partial.status_code, 200)
        self.assertEqual(partial.json()["memo"], "memo baru")
        self.assertEqual(partial.json()["line_count"], 2)

        entry.refresh_from_db()
        self.confirm_service(entry.pk)

        locked = self.put_entry(entry.pk, {"memo": "x"})[0]
        deleted = self.api.delete(detail_url(entry.pk))

        self.assertEqual(locked.status_code, 400)
        self.assertIn("DRAFT", locked.json()["detail"])
        self.assertEqual(deleted.status_code, 400)
        self.assertTrue(JournalEntry.objects.filter(pk=entry.pk).exists())

    def test_delete_draft_menghapus_baris(self):
        """DELETE DRAFT → 200 + baris ikut terhapus (CASCADE)."""
        entry = self.make_entry()
        line_ids = list(entry.lines.values_list("pk", flat=True))

        response = self.api.delete(detail_url(entry.pk))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"id": entry.pk, "deleted": True})
        self.assertFalse(JournalEntry.objects.filter(pk=entry.pk).exists())
        self.assertEqual(JournalEntryLine.objects.filter(pk__in=line_ids).count(), 0)

    def test_update_tidak_seimbang_400(self):
        """PUT dengan baris tidak seimbang → 400 (entry tidak berubah)."""
        entry = self.make_entry()
        body = self.body()
        body["lines"][1]["credit"] = "1000.00"
        response, _ = self.put_entry(entry.pk, body)

        self.assertEqual(response.status_code, 400)
        self.assertIn("tidak seimbang", response.json()["detail"])
        entry.refresh_from_db()
        self.assertEqual(str(entry.total_credit), "1500.00")


class JournalEntryListDetailTests(JournalEntryBase):
    """List (envelope/filter/paging/search) + detail (baris & aksi)."""

    def test_list_envelope_dan_kunci_baris(self):
        """GET list → amplop ListPage + kunci baris sesuai kontrak H3.4."""
        self.make_entry()

        response = self.api.get(ENTRIES_URL)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), ENVELOPE_KEYS)
        self.assertEqual(body["total_count"], 1)
        self.assertEqual(set(body["rows"][0]), ROW_KEYS)
        self.assertFalse(body["has_more"])
        self.assertIsNone(body["next_cursor"])

    def test_list_filter_state_dan_journal(self):
        """`?state=` & `?journal_id=` menyaring baris."""
        entry = self.make_entry()
        self.confirm_service(entry.pk)

        draft = self.api.get(ENTRIES_URL, {"state": "DRAFT"}).json()
        confirmed = self.api.get(ENTRIES_URL, {"state": "CONFIRMED"}).json()
        by_journal = self.api.get(ENTRIES_URL, {"journal_id": self.journal_general.pk}).json()
        other_journal = self.api.get(ENTRIES_URL, {"journal_id": self.journal_bank.pk}).json()

        self.assertEqual(draft["total_count"], 0)
        self.assertEqual(confirmed["total_count"], 1)
        self.assertEqual(by_journal["total_count"], 1)
        self.assertEqual(other_journal["total_count"], 0)

        invalid = self.api.get(ENTRIES_URL, {"state": "HAPUS"})
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(self.api.get(ENTRIES_URL, {"journal_id": "abc"}).status_code, 400)

    def test_list_filter_rentang_tanggal(self):
        """`?date_from`/`?date_to` (ISO) menyaring `entry_date`."""
        self.make_entry()

        within = self.api.get(ENTRIES_URL, {"date_from": "2026-10-01", "date_to": "2026-10-31"})
        outside = self.api.get(ENTRIES_URL, {"date_from": "2026-11-01"})
        invalid = self.api.get(ENTRIES_URL, {"date_from": "01-11-2026"})

        self.assertEqual(within.json()["total_count"], 1)
        self.assertEqual(outside.json()["total_count"], 0)
        self.assertEqual(invalid.status_code, 400)

    def test_list_search_dan_pagination(self):
        """`?search=` (kode/ref/journal) + `?limit`/`?cursor` (envelope has_more)."""
        self.make_entry(ref="CARI-INIDIA")
        self.make_entry()

        found = self.api.get(ENTRIES_URL, {"search": "CARI-INIDIA"}).json()
        by_journal = self.api.get(ENTRIES_URL, {"search": "MISC"}).json()
        page1 = self.api.get(ENTRIES_URL, {"limit": 1}).json()
        page2 = self.api.get(ENTRIES_URL, {"limit": 1, "cursor": 1}).json()

        self.assertEqual(found["total_count"], 1)
        self.assertEqual(by_journal["total_count"], 2)
        self.assertTrue(page1["has_more"])
        self.assertEqual(page1["next_cursor"], 1)
        self.assertEqual(len(page1["rows"]), 1)
        self.assertEqual(len(page2["rows"]), 1)
        self.assertFalse(page2["has_more"])

    def test_list_state_tidak_dikenal_400(self):
        """State di luar enum → 400."""
        response = self.api.get(ENTRIES_URL, {"state": "HAPUS"})

        self.assertEqual(response.status_code, 400)

    def test_detail_berisi_baris_dan_allowed_actions(self):
        """GET detail → `lines` + `line_count` + `allowed_actions` DRAFT."""
        entry = self.make_entry()

        response = self.api.get(detail_url(entry.pk))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), ROW_KEYS | DETAIL_EXTRA_KEYS)
        self.assertEqual(body["line_count"], 2)
        self.assertEqual(set(body["lines"][0]), LINE_KEYS)
        self.assertEqual(body["allowed_actions"], ["CONFIRMED", "CANCELLED"])
        # Create sudah meng-arm ledger (PENDING) — belum ada error.
        self.assertEqual(body["odoo_sync_status"], SyncStatus.PENDING.value)
        self.assertIsNone(body["odoo_sync_error"])

    def test_detail_404(self):
        """Detail id tak ada → 404."""
        response = self.api.get(detail_url(999999))

        self.assertEqual(response.status_code, 404)


class JournalEntryTransitionTests(JournalEntryBase):
    """Transisi + guard STEP 0 H3.4 (journal general, odoo_id journal & akun)."""

    def test_confirm_ok_enqueue_push(self):
        """confirm → CONFIRMED + SyncRecord di-arm + task ter-enqueue."""
        entry = self.make_entry()

        response, enqueue = self.act(entry.pk, "confirm")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["state"], "CONFIRMED")
        self.assertTrue(body["queued"])
        self.assertEqual(body["task_id"], "task-je-confirm")
        enqueue.assert_called_once()
        args = enqueue.call_args.kwargs["args"]
        self.assertEqual(args[0], entry.pk)
        self.assertEqual(args[2], "push")

        record = SyncRecord.objects.get(
            resource=SyncResource.JOURNAL_ENTRY.value, resource_id=str(entry.pk)
        )
        self.assertEqual(record.status, SyncStatus.PENDING)
        self.assertEqual(record.payload["action"], "push")
        self.assertEqual(record.payload["journal_odoo_id"], self.journal_general.odoo_id)
        self.assertEqual(len(record.payload["lines"]), 2)
        self.assertTrue(
            AuditLog.objects.filter(action=svc.ACTION_CONFIRM, resource_id=str(entry.pk)).exists()
        )

    def test_confirm_journal_tanpa_odoo_id_400(self):
        """Journal belum punya odoo_id → 400 (belum di-pull)."""
        entry = self.make_entry(journal_id=self.journal_noid.pk)

        response, _ = self.act(entry.pk, "confirm")

        self.assertEqual(response.status_code, 400)
        self.assertIn("belum punya odoo_id", response.json()["detail"])
        entry.refresh_from_db()
        self.assertEqual(entry.state, "DRAFT")

    def test_confirm_journal_guard_general_dan_longgar(self):
        """Guard STEP 0: non-general → 400; `journal_type` kosong → longgar (Odoo putuskan)."""
        bank = self.make_entry(journal_id=self.journal_bank.pk)
        legacy = self.make_entry(journal_id=self.journal_legacy.pk)

        blocked, _ = self.act(bank.pk, "confirm")
        allowed, _ = self.act(legacy.pk, "confirm")

        self.assertEqual(blocked.status_code, 400)
        detail = blocked.json()["detail"]
        self.assertIn("hanya boleh di journal general", detail)
        self.assertIn("BNK1 = bank", detail)
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.json()["state"], "CONFIRMED")

    def test_confirm_akun_tanpa_odoo_id_400(self):
        """Akun baris belum punya odoo_id → 400 + daftar akun yang kurang."""
        lines = self.body()["lines"]
        lines[0]["account_id"] = self.account_noid.pk
        entry = self.make_entry(lines=lines)

        response, _ = self.act(entry.pk, "confirm")

        self.assertEqual(response.status_code, 400)
        self.assertIn("99999999", response.json()["detail"])
        entry.refresh_from_db()
        self.assertEqual(entry.state, "DRAFT")

    def test_done_setelah_sent(self):
        """CONFIRMED → sync_complete (SENT) → done → DONE."""
        entry = self.make_entry()
        entry, _ = self.confirm_service(entry.pk)
        svc.sync_complete(entry, str(MOVE_ID))
        entry.refresh_from_db()
        self.assertEqual(entry.state, "SENT")
        self.assertEqual(entry.odoo_id, MOVE_ID)

        response, _ = self.act(entry.pk, "done")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], "DONE")
        self.assertEqual(response.json()["allowed_actions"], [])

    def test_cancel_draft_tanpa_enqueue_dan_sent_enqueue_cancel(self):
        """DRAFT → CANCELLED tanpa task; SENT (punya `odoo_id`) → CANCELLED + task cancel."""
        draft = self.make_entry()
        draft_response, draft_enqueue = self.act(draft.pk, "cancel")

        self.assertEqual(draft_response.status_code, 200)
        self.assertEqual(draft_response.json()["state"], "CANCELLED")
        draft_enqueue.assert_not_called()

        sent = self.make_entry()
        sent, _ = self.confirm_service(sent.pk)
        svc.sync_complete(sent, str(MOVE_ID))
        sent.refresh_from_db()

        response, enqueue = self.act(sent.pk, "cancel")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], "CANCELLED")
        self.assertTrue(response.json()["queued"])
        self.assertEqual(enqueue.call_args.kwargs["args"][2], "cancel")


class JournalEntryTaskTests(JournalEntryBase):
    """Task ``erp_sync.push_journal_entry`` — push & cancel (+ ledger/audit)."""

    def _confirmed(self, **overrides) -> JournalEntry:
        """Entry DRAFT → CONFIRMED lewat service (SyncRecord ter-arm, enqueue di-patch)."""
        entry = self.make_entry(**overrides)
        entry, _ = self.confirm_service(entry.pk)

        return entry

    def _record(self, entry: JournalEntry) -> SyncRecord:
        """SyncRecord ``journal_entry``/``JOURNAL_ENTRY`` milik entry ini."""
        return SyncRecord.objects.get(
            resource=SyncResource.JOURNAL_ENTRY.value, resource_id=str(entry.pk)
        )

    def test_task_push_sukses_state_sent_dan_payload(self):
        """Push sukses → SENT + ``odoo_id``; payload STEP 0 tanpa posting/currency/company."""
        entry = self._confirmed()
        record = self._record(entry)
        adapter = FakeAdapter()

        with patch(ADAPTER, return_value=adapter):
            result = push_journal_entry.apply(args=[entry.pk, record.pk, "push"]).get()

        self.assertEqual(result["status"], "sent")
        self.assertEqual(result["erp_id"], str(MOVE_ID))
        self.assertEqual(result["state"], "SENT")

        entry.refresh_from_db()
        self.assertEqual(entry.state, "SENT")
        self.assertEqual(entry.odoo_id, MOVE_ID)

        record.refresh_from_db()
        self.assertEqual(record.status, SyncStatus.SENT)
        self.assertEqual(record.erp_id, str(MOVE_ID))
        self.assertEqual(record.payload["action"], "push")

        payload = adapter.pushed[0]
        self.assertEqual(
            set(payload),
            {
                "code",
                "ref",
                "memo",
                "journal_odoo_id",
                "journal_code",
                "date",
                "total_debit",
                "total_credit",
                "lines",
            },
        )
        self.assertEqual(payload["code"], entry.code)
        self.assertEqual(payload["ref"], "JE-TEST-001")
        self.assertEqual(payload["journal_odoo_id"], self.journal_general.odoo_id)
        self.assertEqual(payload["journal_code"], "MISC")
        self.assertEqual(payload["date"], "2026-10-13")
        self.assertEqual(payload["total_debit"], "1500.00")
        self.assertEqual(len(payload["lines"]), 2)
        self.assertEqual(
            set(payload["lines"][0]),
            {"account_odoo_id", "account_code", "name", "debit", "credit", "partner_odoo_id"},
        )
        # Keputusan STEP 0: MES tidak mem-posting & tidak mengirim currency/company/narration.
        for forbidden in ("action", "action_post", "currency_id", "company_id", "narration"):
            self.assertNotIn(forbidden, payload)
        self.assertTrue(adapter.closed)
        self.assertTrue(
            AuditLog.objects.filter(
                action="erp_sync.push_journal_entry", resource_id=str(entry.pk)
            ).exists()
        )

    def test_task_push_gagal_record_failed_state_tetap_confirmed(self):
        """Odoo menolak → SyncRecord FAILED + audit; state entry **tetap CONFIRMED** (retry-able)."""
        entry = self._confirmed()
        record = self._record(entry)
        adapter = FakeAdapter(ok=False, error="Journal entry is not balanced.")

        with patch(ADAPTER, return_value=adapter):
            result = push_journal_entry.apply(args=[entry.pk, record.pk, "push"]).get()

        self.assertEqual(result["status"], "failed")
        self.assertIn("not balanced", result["error"])

        entry.refresh_from_db()
        self.assertEqual(entry.state, "CONFIRMED")
        self.assertIsNone(entry.odoo_id)

        record.refresh_from_db()
        self.assertEqual(record.status, SyncStatus.FAILED)
        self.assertIn("not balanced", record.last_error)
        self.assertTrue(adapter.closed)

    def test_task_cancel_panggil_button_cancel_dan_skip_tanpa_odoo_id(self):
        """SENT → cancel task menyentuh Odoo; entry CANCELLED tanpa ``odoo_id`` → skip."""
        entry = self._confirmed()
        svc.sync_complete(entry, str(MOVE_ID))
        entry.refresh_from_db()
        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-je-cancel")):
            cancelled = svc.cancel_entry(entry)

        self.assertIsNone(cancelled.error, cancelled.error)
        record = self._record(entry)
        adapter = FakeAdapter()

        with patch(ADAPTER, return_value=adapter):
            sent = push_journal_entry.apply(args=[entry.pk, record.pk, "cancel"]).get()

        self.assertEqual(sent["status"], "sent")
        self.assertEqual(adapter.cancelled, [str(MOVE_ID)])
        record.refresh_from_db()
        self.assertEqual(record.status, SyncStatus.SENT)

        plain = self.make_entry()
        response, _ = self.act(plain.pk, "cancel")
        self.assertEqual(response.json()["state"], "CANCELLED")

        with patch(ADAPTER, return_value=adapter):
            skipped = push_journal_entry.apply(args=[plain.pk, None, "cancel"]).get()

        self.assertEqual(skipped["status"], "skipped")
        self.assertEqual(skipped["reason"], "tanpa-odoo-id")
        self.assertEqual(adapter.cancelled, [str(MOVE_ID)])


class JournalEntryAdapterTests(TestCase):
    """Payload push nyata `OdooAdapter` (`move_type='entry'`, **tanpa** `action_post`)."""

    def setUp(self):
        """Klien Odoo palsu: ``account.move.create`` mengembalikan id move."""
        self.client = MagicMock()
        self.client.execute_kw.return_value = [MOVE_ID]
        self.adapter = OdooAdapter(client=self.client)

    def _payload(self) -> dict:
        """Payload push standar (2 baris seimbang, baris ke-2 pakai partner)."""
        return {
            "code": "JE-2026-0001",
            "ref": "JE-2026-0001",
            "journal_odoo_id": 10,
            "date": "2026-10-13",
            "lines": [
                {
                    "account_odoo_id": 181,
                    "name": "Beban pokok",
                    "debit": "1500.00",
                    "credit": "0.00",
                },
                {
                    "account_odoo_id": 223,
                    "name": "Kas keluar",
                    "debit": "0.00",
                    "credit": "1500.00",
                    "partner_odoo_id": 10,
                },
            ],
        }

    def test_push_journal_entry_membangun_nilai_account_move(self):
        """`create` dipanggil pada `account.move` dengan `move_type='entry'` + `line_ids`."""
        response = self.adapter.push_journal_entry(self._payload())

        self.assertTrue(response.ok)
        self.assertEqual(response.erp_id, str(MOVE_ID))
        self.assertEqual(response.stage, STAGE_JOURNAL_ENTRY)

        model, method, args = self.client.execute_kw.call_args.args
        self.assertEqual(model, "account.move")
        self.assertEqual(method, "create")

        values = args[0][0]
        self.assertEqual(
            set(values), {"move_type", "journal_id", "date", "ref", "line_ids"}
        )
        self.assertEqual(values["move_type"], "entry")
        self.assertEqual(values["journal_id"], 10)
        self.assertEqual(values["date"], "2026-10-13")
        self.assertEqual(values["ref"], "JE-2026-0001")
        self.assertEqual(
            values["line_ids"][0],
            (0, 0, {"account_id": 181, "name": "Beban pokok", "debit": 1500.0, "credit": 0.0}),
        )
        self.assertEqual(values["line_ids"][1][2]["partner_id"], 10)
        # Baris tidak membawa `display_type`/`currency_id` (default Odoo).
        for forbidden in ("display_type", "currency_id"):
            self.assertNotIn(forbidden, values["line_ids"][0][2])
        # Entry dibiarkan DRAFT: posting adalah pekerjaan akuntan di Odoo.
        called_methods = [call.args[1] for call in self.client.execute_kw.call_args_list]
        self.assertNotIn("action_post", called_methods)

    def test_push_journal_entry_validasi_payload_dan_cancel(self):
        """Payload kurang / baris tanpa akun / < 2 baris → ok=False; cancel → `button_cancel`."""
        kurang = self.adapter.push_journal_entry({"ref": "JE-X"})
        self.assertFalse(kurang.ok)
        self.assertIn("tidak lengkap", kurang.error)
        for field in ("journal_odoo_id", "date", "lines"):
            self.assertIn(field, kurang.error)
        self.assertEqual(kurang.stage, STAGE_JOURNAL_ENTRY)
        self.client.execute_kw.assert_not_called()

        tanpa_akun = self._payload()
        tanpa_akun["lines"][1]["account_odoo_id"] = None
        no_account = self.adapter.push_journal_entry(tanpa_akun)
        self.assertFalse(no_account.ok)
        self.assertIn("Baris #2", no_account.error)
        self.assertIn("account_odoo_id", no_account.error)

        satu_baris = self.adapter.push_journal_entry(
            self._payload() | {"lines": [self._payload()["lines"][0]]}
        )
        self.assertFalse(satu_baris.ok)
        self.assertIn("minimal 2 baris", satu_baris.error)

        cancelled = self.adapter.cancel_journal_entry(str(MOVE_ID))
        self.assertTrue(cancelled.ok)
        self.assertEqual(cancelled.erp_id, str(MOVE_ID))
        model, method, args = self.client.execute_kw.call_args.args
        self.assertEqual((model, method), ("account.move", "button_cancel"))
        self.assertEqual(args[0], [MOVE_ID])


class MasterH34EndpointTests(JournalEntryBase):
    """Endpoint **read-only** master Account/Journal H3.4 (`/api/v1/master/...`)."""

    def test_master_accounts_readonly_list_detail_dan_405(self):
        """List (amplop+filter) & detail akun read-only: tulis 405, anon 403, detail 404."""
        response = self.api.get(ACCOUNTS_URL)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), ENVELOPE_KEYS)
        self.assertEqual(body["total_count"], Account.objects.count())
        self.assertEqual(set(body["rows"][0]), ACCOUNT_ROW_KEYS)
        self.assertEqual(
            [row["code"] for row in body["rows"]],
            sorted(Account.objects.values_list("code", flat=True)),
        )

        by_type = self.api.get(ACCOUNTS_URL, {"account_type": "asset_cash"}).json()
        by_search = self.api.get(ACCOUNTS_URL, {"search": "Bank"}).json()
        nonaktif = self.api.get(ACCOUNTS_URL, {"active": "false"}).json()

        self.assertEqual(by_type["total_count"], 1)
        self.assertEqual(by_type["rows"][0]["code"], "11120005")
        self.assertIn("account_type_label", by_type["rows"][0])
        self.assertEqual(by_search["total_count"], 1)
        self.assertEqual(by_search["rows"][0]["name"], "Bank")
        self.assertEqual(nonaktif["total_count"], 0)

        invalid = self.api.get(ACCOUNTS_URL, {"account_type": "kas-aneh"})
        self.assertEqual(invalid.status_code, 400)
        self.assertIn("account_type", invalid.json()["detail"])

        posted = self.api.post(ACCOUNTS_URL, {"code": "X"}, format="json")
        anon = APIClient().get(ACCOUNTS_URL)
        self.assertEqual(posted.status_code, 405)
        self.assertEqual(anon.status_code, 403)

        detail = self.api.get(f"{ACCOUNTS_URL}{self.account_cash.pk}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(set(detail.json()), ACCOUNT_ROW_KEYS)
        self.assertEqual(detail.json()["odoo_id"], self.account_cash.odoo_id)
        self.assertTrue(detail.json()["active"])
        self.assertEqual(self.api.get(f"{ACCOUNTS_URL}999999/").status_code, 404)
        self.assertEqual(
            self.api.put(f"{ACCOUNTS_URL}{self.account_cash.pk}/", {}, format="json").status_code,
            405,
        )

    def test_master_journals_readonly_filter_type_dan_405(self):
        """List journal (filter `?type=general`) & detail read-only; tulis 405."""
        response = self.api.get(JOURNALS_URL)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), ENVELOPE_KEYS)
        self.assertEqual(body["total_count"], Journal.objects.count())
        self.assertEqual(set(body["rows"][0]), JOURNAL_ROW_KEYS)

        general = self.api.get(JOURNALS_URL, {"type": "general"}).json()
        bank = self.api.get(JOURNALS_URL, {"type": "bank"}).json()
        invalid = self.api.get(JOURNALS_URL, {"type": "kas-aneh"})

        self.assertEqual(general["total_count"], Journal.objects.filter(journal_type="general").count())
        self.assertTrue(all(row["is_general"] for row in general["rows"]))
        self.assertEqual(bank["total_count"], 1)
        self.assertFalse(bank["rows"][0]["is_general"])
        self.assertEqual(invalid.status_code, 400)
        self.assertIn("type", invalid.json()["detail"])
        self.assertEqual(self.api.post(JOURNALS_URL, {}, format="json").status_code, 405)
        self.assertEqual(APIClient().get(JOURNALS_URL).status_code, 403)

        detail = self.api.get(f"{JOURNALS_URL}{self.journal_general.pk}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(set(detail.json()), JOURNAL_ROW_KEYS)
        self.assertEqual(detail.json()["code"], "MISC")
        self.assertEqual(detail.json()["journal_type"], "general")
        self.assertTrue(detail.json()["is_general"])
        self.assertEqual(detail.json()["journal_type_label"], Journal.JournalType.GENERAL.label)
        self.assertEqual(self.api.get(f"{JOURNALS_URL}999999/").status_code, 404)


class FakePullTransport:
    """Transport pull palsu: menyajikan baris `account.account`/`account.journal`."""

    def __init__(self, accounts=None, journals=None) -> None:
        """Simpan baris yang akan dibalas + flag ``closed``."""
        self.accounts = accounts or []
        self.journals = journals or []
        self.closed = False

    def fetch_accounts(self, since=None):
        """Baris `account.account` (field minimal seperti `ACCOUNT_FIELDS`)."""
        return list(self.accounts)

    def fetch_journals(self, since=None):
        """Baris `account.journal` (field minimal seperti `JOURNAL_FIELDS`)."""
        return list(self.journals)

    def close(self) -> None:
        """Tandai transport ditutup (task wajib menutup di ``finally``)."""
        self.closed = True


class MasterH34SyncTests(JournalEntryBase):
    """Pull `account.account`/`account.journal` (H3.4) + ledger non-breaking."""

    def test_pull_accounts_deprecated_dan_endpoint_sync_queued(self):
        """`deprecated` Odoo → `is_active=False`; task upsert `odoo_id`; endpoint enqueue."""
        defaults = _account_defaults(
            {
                "id": 500,
                "code": "11120005",
                "name": "Bank",
                "account_type": "Asset_Cash",
                "reconcile": True,
                "deprecated": True,
            }
        )

        self.assertEqual(defaults["code"], "11120005")
        self.assertEqual(defaults["account_type"], "asset_cash")
        self.assertTrue(defaults["reconcile"])
        # Odoo 17 `account.account` tidak punya `active` → nonaktif ditandai `deprecated`.
        self.assertFalse(defaults["is_active"])

        transport = FakePullTransport(
            accounts=[
                {
                    "id": 500,
                    "code": "11129998",
                    "name": "Bank Baru",
                    "account_type": "asset_cash",
                    "reconcile": True,
                    "deprecated": True,
                },
                {
                    "id": 501,
                    "code": "61000001",
                    "name": "Beban Listrik",
                    "account_type": "expense",
                    "reconcile": False,
                    "deprecated": False,
                },
            ]
        )
        with patch(GET_TRANSPORT, return_value=transport):
            result = sync_master_accounts.apply(kwargs={"since": None}).get()

        self.assertEqual(result, {"created": 2, "updated": 0, "skipped": 0})
        self.assertTrue(transport.closed)
        bank = Account.objects.get(odoo_id=500)
        self.assertEqual(bank.name, "Bank Baru")
        self.assertEqual(bank.account_type, "asset_cash")
        self.assertFalse(bank.is_active)
        self.assertTrue(Account.objects.get(odoo_id=501).is_active)

        with patch(
            "integrations.erp_sync.api.sync_master_accounts.delay",
            return_value=SimpleNamespace(id="task-pull-accounts"),
        ) as delay:
            response = self.api.post("/api/v1/sync/master/accounts/", {}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "queued", "task_id": "task-pull-accounts"})
        delay.assert_called_once()

    def test_pull_journals_journal_type_dan_non_breaking_ledger(self):
        """`type` Odoo → `journal_type` (tak dikenal → ""); ledger H3.1–H3.4 tidak bertabrakan."""
        general = _journal_defaults({"id": 10, "code": "MISC", "name": "Operasi", "type": "general"})
        unknown = _journal_defaults({"id": 11, "code": "X", "name": "Y", "type": "aneh"})
        kosong = _journal_defaults({"id": 12, "code": "Z", "name": "W"})

        self.assertEqual(general["journal_type"], "general")
        self.assertEqual(general["code"], "MISC")
        # Tak dikenal/kosong → "" = guard H3.4 longgar (diserahkan ke Odoo).
        self.assertEqual(unknown["journal_type"], "")
        self.assertEqual(kosong["journal_type"], "")

        transport = FakePullTransport(
            journals=[{"id": 77, "code": "UMUM", "name": "Umum", "type": "general"}]
        )
        with patch(GET_TRANSPORT, return_value=transport):
            result = sync_master_journals.apply(kwargs={"since": None}).get()

        self.assertEqual(result["created"], 1)
        self.assertTrue(transport.closed)
        journal = Journal.objects.get(odoo_id=77)
        self.assertEqual(journal.journal_type, Journal.JournalType.GENERAL.value)
        self.assertEqual(journal.name, "Umum")

        # Non-breaking: resource/stage H3.4 hidup berdampingan dengan H3.1–H3.3.
        self.assertEqual(SyncResource.JOURNAL_ENTRY.value, "journal_entry")
        self.assertEqual(SyncResource.PAYMENT.value, "payment")
        self.assertEqual(SyncStage.JOURNAL_ENTRY.value, "JOURNAL_ENTRY")
        for stage in (
            SyncStage.INVOICE.value,
            SyncStage.VENDOR_BILL.value,
            SyncStage.PAYMENT.value,
            SyncStage.JOURNAL_ENTRY.value,
        ):
            self.assertIn(stage, VALID_STAGES)
        self.assertEqual(len(set(VALID_STAGES)), len(VALID_STAGES))
