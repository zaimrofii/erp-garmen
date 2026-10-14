"""Service Journal Entry manual (H3.4) — transaksi satu arah MES → Odoo.

Pola **persis** `payment_services.py` (H3.3) / `vendor_bill_services.py` (H3.2):
dokumen transaksi MES yang di-push ke Odoo **saat state kritis** (`CONFIRMED`),
dengan ledger `SyncRecord` + `AuditLog` setiap operasi.

Perbedaan yang berasal dari STEP 0 H3.4:

  * **Greenfield**: `JournalEntry`/`JournalEntryLine` BARU (MES belum punya jurnal
    manual; H3.1–H3.3 membuat `account.move`/`account.payment` lewat dokumennya
    sendiri, jadi jalur ini **terpisah**);
  * **Resource BARU `journal_entry` + STAGE BARU `JOURNAL_ENTRY`** (tidak menimpa
    ledger `INVOICE`/`VENDOR_BILL`/`PAYMENT` milik dokumen dagang);
  * **Double-entry**: minimal 2 baris, tiap baris debit **XOR** kredit, dan
    **Σ debit = Σ kredit** (toleransi 0.01). Balance dihitung murni di MES
    (deterministik, tanpa Odoo) dan disimpan sebagai `total_debit`/`total_credit`
    (denormalisasi untuk audit + guard);
  * **Hanya journal `general`** yang boleh (keputusan STEP 0): journal
    sale/purchase/bank/cash dipakai Odoo untuk invoice/bill/payment. Bila
    `journal.journal_type` **kosong** (baris lama yang belum pernah di-pull),
    guard **longgar** — keputusan diserahkan ke Odoo;
  * payload push memakai `move_type='entry'` (eksplisit) + `journal_id` + `date` +
    `ref` + `line_ids` command one2many. `currency_id`/`company_id`/`narration`
    **tidak** dikirim (dihitung Odoo — probe STEP 0);
  * **Posting BUKAN tanggung jawab MES**: entry dibuat **draft** & akuntan Odoo
    yang mem-posting (`action_post` tidak pernah dipanggil).

Guard sebelum `CONFIRMED`: journal punya `odoo_id` & (bila diketahui) general;
≥ 2 baris; Σ debit = Σ kredit; setiap akun punya `odoo_id`. Kegagalan push
**bukan** state model — tercatat di `SyncRecord.status=FAILED` (entry tetap
`CONFIRMED`, bisa di-retry).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.dateparse import parse_date

from config.middleware import get_request_id
from core.audit.models import AuditLog
from core.audit.services import AuditLogger
from integrations.erp_sync.idempotency import SyncIdempotency
from integrations.erp_sync.models import (
    SyncRecord,
    SyncResource,
    SyncStage,
    SyncStatus,
)
from master.models import Account, Journal, Partner
from master.sequence_services import SequenceError, next_number

from ..models import JournalEntry, JournalEntryLine

logger = logging.getLogger(__name__)

__all__ = (
    "ACTION_CANCEL",
    "ACTION_CONFIRM",
    "ACTION_CREATE",
    "ACTION_DELETE",
    "ACTION_DONE",
    "ACTION_SYNC_COMPLETE",
    "ACTION_SYNC_FAILED",
    "ACTION_UPDATE",
    "ALLOWED_TRANSITIONS",
    "BALANCE_TOLERANCE",
    "JOURNAL_ENTRY_RESOURCE",
    "JOURNAL_ENTRY_STAGE",
    "JOURNAL_ENTRY_STATES",
    "JournalEntryError",
    "JournalEntryWriteResult",
    "cancel_entry",
    "confirm_entry",
    "create_entry",
    "delete_entry",
    "done_entry",
    "entry_detail_row",
    "entry_line_rows",
    "entry_payload",
    "entry_row",
    "journal_entry_push_payload",
    "sync_complete",
    "sync_failed",
    "update_entry",
    "validate_entry_payload",
)

#: Resource & stage ledger H3.4 (KEDUANYA baru).
JOURNAL_ENTRY_RESOURCE = SyncResource.JOURNAL_ENTRY.value
JOURNAL_ENTRY_STAGE = SyncStage.JOURNAL_ENTRY.value

#: State bisnis journal entry (§14 + keputusan H3.4, pola H3.1–H3.3).
JOURNAL_ENTRY_STATES: tuple[str, ...] = ("DRAFT", "CONFIRMED", "SENT", "DONE", "CANCELLED")
ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "DRAFT": ("CONFIRMED", "CANCELLED"),
    "CONFIRMED": ("DONE", "CANCELLED"),
    "SENT": ("DONE", "CANCELLED"),
    "DONE": (),
    "CANCELLED": (),
}

#: Minimal baris jurnal (debit + kredit) — keputusan STEP 0 H3.4.
MIN_LINES = 2
#: Toleransi keseimbangan (Σ debit vs Σ kredit) — keputusan STEP 0 H3.4.
#: Catatan: toleransi ini **tidak** "menyeimbangkan" nilai; Odoo tetap menolak
#: entry yang benar-benar tidak seimbang (muncul sebagai `SyncRecord` FAILED).
BALANCE_TOLERANCE = Decimal("0.01")

MAX_REF_LENGTH = 64
MAX_MEMO_LENGTH = 2000
MAX_NOTES_LENGTH = 2000
MAX_LINE_NAME_LENGTH = 255
#: Journal type yang boleh dipakai entry manual (keputusan STEP 0 H3.4).
GENERAL_JOURNAL_TYPE = Journal.JournalType.GENERAL.value

#: Action ``AuditLog`` (namespace transaksi, analog `payment.*` H3.3).
ACTION_CREATE = "journal_entry.create"
ACTION_UPDATE = "journal_entry.update"
ACTION_DELETE = "journal_entry.delete"
ACTION_CONFIRM = "journal_entry.confirm"
ACTION_DONE = "journal_entry.done"
ACTION_CANCEL = "journal_entry.cancel"
#: Jejak kegagalan push (state model tetap CONFIRMED) — ditulis task.
ACTION_SYNC_FAILED = "journal_entry.sync_failed"
#: Jejak push sukses (CONFIRMED → SENT + `odoo_id`) — ditulis task.
ACTION_SYNC_COMPLETE = "journal_entry.sync_complete"


class JournalEntryError(ValidationError):
    """Error validasi/transisi journal entry → dipetakan view menjadi **400**."""


@dataclass
class JournalEntryWriteResult:
    """Hasil satu operasi tulis/transisi journal entry (dipakai view)."""

    entry: JournalEntry | None = None
    error: str | None = None
    sync_record_id: int | None = None
    task_id: str | None = None
    deleted: bool = False
    missing_accounts: list = field(default_factory=list)

    @property
    def queued(self) -> bool:
        """True kalau task push/cancel berhasil di-enqueue (broker hidup)."""
        return self.task_id is not None


def _iso(value) -> str | None:
    """ISO-8601 atau ``None`` (date/datetime kosong)."""
    return value.isoformat() if value else None


def _decimal(value) -> Decimal:
    """Konversi aman ke ``Decimal`` (gagal → 0)."""
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


#: Kuantum uang 2 desimal (bentuk API & kolom model konsisten).
_MONEY = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    """Bulatkan nilai uang ke 2 desimal (``ROUND_HALF_UP``)."""
    return value.quantize(_MONEY, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Validasi payload (header, baris, keseimbangan)
# ---------------------------------------------------------------------------
def _resolve_journal(raw):
    """``(journal, error)`` — journal wajib ada & dikenal MES."""
    if raw in (None, ""):
        return None, "Field 'journal_id' wajib diisi (buku besar tujuan)."
    try:
        journal_id = int(raw)
    except (TypeError, ValueError):
        return None, "Field 'journal_id' harus berupa angka."

    journal = Journal.objects.filter(pk=journal_id).first()
    if journal is None:
        return None, f"Journal {journal_id} tidak ditemukan."

    return journal, None


def _resolve_date(raw, field: str, *, required: bool = False):
    """``(date, error)`` — tanggal opsional/wajib (ISO ``YYYY-MM-DD``)."""
    if raw in (None, ""):
        if required:
            return None, f"Field '{field}' wajib diisi."
        return None, None
    if isinstance(raw, str):
        parsed = parse_date(raw)
        if parsed is None:
            return None, f"Field '{field}' harus format tanggal ISO (YYYY-MM-DD)."
        return parsed, None

    return raw, None


def _resolve_account(raw, index: int):
    """``(account, error)`` — akun baris wajib ada & dikenal MES."""
    if raw in (None, ""):
        return None, f"Baris #{index}: field 'account_id' wajib diisi."
    try:
        account_id = int(raw)
    except (TypeError, ValueError):
        return None, f"Baris #{index}: field 'account_id' harus berupa angka."

    account = Account.objects.filter(pk=account_id).first()
    if account is None:
        return None, f"Baris #{index}: Account {account_id} tidak ditemukan."

    return account, None


def _resolve_line_partner(raw, index: int):
    """``(partner, error)`` — partner baris opsional (``None`` kalau kosong)."""
    if raw in (None, ""):
        return None, None
    try:
        partner_id = int(raw)
    except (TypeError, ValueError):
        return None, f"Baris #{index}: field 'partner_id' harus berupa angka."

    partner = Partner.objects.filter(pk=partner_id).first()
    if partner is None:
        return None, f"Baris #{index}: Partner {partner_id} tidak ditemukan."

    return partner, None


def _line_amounts(raw_line: dict, index: int):
    """``((debit, credit), error)`` — nilai baris >= 0, XOR, minimal satu > 0."""
    debit = _money(_decimal(raw_line.get("debit") or 0))
    credit = _money(_decimal(raw_line.get("credit") or 0))

    if debit < 0 or credit < 0:
        return None, f"Baris #{index}: debit/credit tidak boleh negatif."
    if debit > 0 and credit > 0:
        return None, (
            f"Baris #{index}: isi debit ATAU credit saja (tidak boleh keduanya > 0)."
        )
    if debit == 0 and credit == 0:
        return None, f"Baris #{index}: debit atau credit wajib > 0."

    return (debit, credit), None


def _resolve_lines(raw_lines):
    """``(lines, error)`` — validasi seluruh baris jurnal (>= 2, XOR, nominal)."""
    if not isinstance(raw_lines, (list, tuple)) or not raw_lines:
        return None, "Field 'lines' wajib diisi (minimal 2 baris: debit & kredit)."
    if len(raw_lines) < MIN_LINES:
        return None, f"Journal entry butuh minimal {MIN_LINES} baris (debit & kredit)."

    lines: list[dict] = []
    for index, raw_line in enumerate(raw_lines, start=1):
        if not isinstance(raw_line, dict):
            return None, f"Baris #{index}: bentuk baris harus object JSON."

        account, error = _resolve_account(raw_line.get("account_id"), index)
        if error:
            return None, error
        partner, error = _resolve_line_partner(raw_line.get("partner_id"), index)
        if error:
            return None, error
        amounts, error = _line_amounts(raw_line, index)
        if error:
            return None, error

        name = str(raw_line.get("name") or "")
        if len(name) > MAX_LINE_NAME_LENGTH:
            return None, f"Baris #{index}: 'name' maksimal {MAX_LINE_NAME_LENGTH} karakter."

        debit, credit = amounts
        lines.append(
            {
                "account": account,
                "partner": partner,
                "name": name,
                "debit": debit,
                "credit": credit,
            }
        )

    return lines, None


def totals_for(lines) -> tuple[Decimal, Decimal]:
    """``(total_debit, total_credit)`` — PURE, dari daftar baris tervalidasi."""
    total_debit = _money(sum((line["debit"] for line in lines), Decimal("0")))
    total_credit = _money(sum((line["credit"] for line in lines), Decimal("0")))

    return total_debit, total_credit


def validate_balance(lines):
    """``(None)`` kalau Σ debit = Σ kredit (toleransi 0.01), else pesan error."""
    total_debit, total_credit = totals_for(lines)
    if abs(total_debit - total_credit) > BALANCE_TOLERANCE:
        return (
            f"Journal entry tidak seimbang: total debit {total_debit} != "
            f"total credit {total_credit} (selisih "
            f"{_money(abs(total_debit - total_credit))}, toleransi {BALANCE_TOLERANCE})."
        )

    return None


def validate_entry_payload(data) -> tuple[dict, list, str | None]:
    """Validasi lengkap payload tulis → ``(values, lines, error)``.

    ``values`` = field header untuk model; ``lines`` = daftar baris tervalidasi
    (belum disimpan). Semua kegagalan dikembalikan sebagai *error* (dipetakan view
    menjadi **400**) — service tidak melempar exception untuk input pengguna.
    """
    payload = data if isinstance(data, dict) else {}

    journal, error = _resolve_journal(payload.get("journal_id"))
    if error:
        return {}, [], error

    entry_date, error = _resolve_date(payload.get("entry_date"), "entry_date", required=True)
    if error:
        return {}, [], error

    ref = str(payload.get("ref") or "").strip()
    if len(ref) > MAX_REF_LENGTH:
        return {}, [], f"Field 'ref' maksimal {MAX_REF_LENGTH} karakter."

    memo = str(payload.get("memo") or "")
    if len(memo) > MAX_MEMO_LENGTH:
        return {}, [], f"Field 'memo' maksimal {MAX_MEMO_LENGTH} karakter."

    notes = str(payload.get("notes") or "")
    if len(notes) > MAX_NOTES_LENGTH:
        return {}, [], f"Field 'notes' maksimal {MAX_NOTES_LENGTH} karakter."

    lines, error = _resolve_lines(payload.get("lines"))
    if error:
        return {}, [], error

    error = validate_balance(lines)
    if error:
        return {}, [], error

    total_debit, total_credit = totals_for(lines)
    values = {
        "journal": journal,
        "entry_date": entry_date,
        "ref": ref,
        "memo": memo,
        "notes": notes,
        "total_debit": total_debit,
        "total_credit": total_credit,
    }

    return values, lines, None


# ---------------------------------------------------------------------------
# Serialisasi + payload push
# ---------------------------------------------------------------------------
def _line_row(line: JournalEntryLine) -> dict:
    """Satu baris jurnal untuk API (account/partner di-*flatten*)."""
    return {
        "id": line.pk,
        "account_id": line.account_id,
        "account_code": getattr(line.account, "code", None),
        "account_name": getattr(line.account, "name", None),
        "partner_id": line.partner_id,
        "partner_name": getattr(line.partner, "name", None),
        "name": line.name,
        "debit": str(_decimal(line.debit)),
        "credit": str(_decimal(line.credit)),
    }


def entry_line_rows(entry: JournalEntry) -> list[dict]:
    """Semua baris jurnal (urut ``id``) — dipakai detail & payload push."""
    return [_line_row(line) for line in entry.lines.all()]


def entry_row(entry: JournalEntry) -> dict:
    """Baris list journal entry (kontrak API H3.4)."""
    return {
        "id": entry.pk,
        "code": entry.code,
        "journal_id": entry.journal_id,
        "journal_code": getattr(entry.journal, "code", None),
        "journal_name": getattr(entry.journal, "name", None),
        "journal_type": getattr(entry.journal, "journal_type", "") or "",
        "entry_date": _iso(entry.entry_date),
        "ref": entry.ref,
        "memo": entry.memo,
        "total_debit": str(_decimal(entry.total_debit)),
        "total_credit": str(_decimal(entry.total_credit)),
        "state": entry.state,
        "odoo_id": entry.odoo_id,
        "created_at": _iso(entry.created_at),
        "updated_at": _iso(entry.updated_at),
    }


def entry_detail_row(entry: JournalEntry) -> dict:
    """Detail = baris list + daftar baris jurnal + info sync Odoo + aksi yang boleh."""
    record = SyncRecord.objects.filter(
        resource=JOURNAL_ENTRY_RESOURCE, resource_id=str(entry.pk), stage=JOURNAL_ENTRY_STAGE
    ).first()
    row = entry_row(entry)
    row.update(
        {
            "lines": entry_line_rows(entry),
            "line_count": entry.lines.count(),
            "odoo_sync_status": None if record is None else record.status,
            "odoo_sync_error": None if record is None else (record.last_error or None),
            "allowed_actions": list(ALLOWED_TRANSITIONS.get(entry.state, ())),
        }
    )

    return row


def entry_payload(entry: JournalEntry) -> dict:
    """Payload ledger/jejak sync (memakai pk MES) — ditulis ke `SyncRecord`/`AuditLog`."""
    return {
        "code": entry.code,
        "journal_id": entry.journal_id,
        "journal_odoo_id": getattr(entry.journal, "odoo_id", None),
        "journal_type": getattr(entry.journal, "journal_type", "") or "",
        "entry_date": _iso(entry.entry_date),
        "ref": entry.ref,
        "memo": entry.memo,
        "total_debit": str(_decimal(entry.total_debit)),
        "total_credit": str(_decimal(entry.total_credit)),
        "line_count": entry.lines.count(),
        "state": entry.state,
        "odoo_id": entry.odoo_id,
    }


def journal_entry_push_payload(entry: JournalEntry) -> dict:
    """Payload push **ke adapter** (`push_journal_entry`, H3.4).

    Memakai id **Odoo** (`journal_odoo_id`/`account_odoo_id`/`partner_odoo_id`) karena
    langsung dikirim. Pemetaan keputusan STEP 0: `move_type='entry'` (eksplisit),
    `journal_id` + `date` wajib, baris = `lines` (one2many command), `ref` = referensi
    MES (fallback kode `JE-…`), `memo` MES jadi fallback label baris —
    `narration`/`currency_id`/`company_id` **tidak** dikirim (dihitung Odoo).
    """
    ref = entry.ref or entry.code
    lines = [
        {
            "account_odoo_id": getattr(line.account, "odoo_id", None),
            "account_code": getattr(line.account, "code", None),
            "name": line.name or entry.memo or ref,
            "debit": str(_decimal(line.debit)),
            "credit": str(_decimal(line.credit)),
            "partner_odoo_id": getattr(line.partner, "odoo_id", None) if line.partner_id else None,
        }
        for line in entry.lines.all()
    ]

    return {
        "code": entry.code,
        "ref": ref,
        "memo": entry.memo,
        "journal_odoo_id": getattr(entry.journal, "odoo_id", None),
        "journal_code": getattr(entry.journal, "code", None),
        "date": _iso(entry.entry_date),
        "total_debit": str(_decimal(entry.total_debit)),
        "total_credit": str(_decimal(entry.total_credit)),
        "lines": lines,
    }


# ---------------------------------------------------------------------------
# Ledger (SyncRecord) + audit + enqueue task push
# ---------------------------------------------------------------------------
def _arm_push(entry: JournalEntry, action: str = "push") -> SyncRecord:
    """Siapkan ``SyncRecord`` entry ini (PENDING, payload terbaru).

    ``unique(resource, resource_id, stage)`` hanya mengizinkan satu baris per entry ⇒
    perubahan berikutnya meng-*update* baris yang sama (idempoten). Payload yang
    disimpan = **payload push** + kunci ``action`` (``push``/``cancel``).
    """
    payload = journal_entry_push_payload(entry) | {"action": action}
    sync = SyncIdempotency()
    record = sync.get_or_create_sync_record(
        JOURNAL_ENTRY_RESOURCE, entry.pk, JOURNAL_ENTRY_STAGE, payload
    )

    if (
        dict(record.payload or {}) != payload
        or record.status != SyncStatus.PENDING
        or record.last_error
    ):
        record.payload = payload
        record.status = SyncStatus.PENDING
        record.last_error = ""
        record.save(update_fields=("payload", "status", "last_error", "updated_at"))
        logger.info("journal_entry: SyncRecord %s di-arm ulang (%s).", record.pk, action)

    return record


def _audit(action: str, entry: JournalEntry, request, metadata: dict | None = None) -> None:
    """Tulis ``AuditLog`` — best-effort (tidak boleh menggagalkan transaksi)."""
    try:
        AuditLogger().log(
            user=None,
            action=action,
            resource=JOURNAL_ENTRY_RESOURCE,
            resource_id=entry.pk,
            request=request,
            payload=entry_payload(entry),
            result=AuditLog.Result.OK,
            metadata=metadata or {},
        )
    except Exception:  # noqa: BLE001 - audit tidak boleh menggagalkan transaksi entry
        logger.exception("journal_entry: gagal menulis audit (%s, %s).", action, entry.pk)


def _enqueue_push(entry: JournalEntry, record: SyncRecord, action: str) -> str | None:
    """Enqueue push/cancel entry ke Odoo; broker mati → ``None`` (record PENDING)."""
    try:
        # Import lazy: `tasks_journal_entry_push` mengimpor modul ini (payload).
        from integrations.erp_sync.tasks_journal_entry_push import push_journal_entry

        async_result = push_journal_entry.apply_async(
            args=[entry.pk, record.pk, action],
            headers={"x-request-id": get_request_id() or ""},
        )
        return str(async_result.id)
    except Exception:  # noqa: BLE001 - CRUD entry tidak boleh gagal karena broker
        logger.exception(
            "journal_entry: gagal enqueue %s entry %s (SyncRecord %s tetap PENDING).",
            action,
            entry.pk,
            record.pk,
        )
        return None


# ---------------------------------------------------------------------------
# Helper transisi + guard STEP 0 H3.4
# ---------------------------------------------------------------------------
def _assert_transition(entry: JournalEntry, target: str) -> str | None:
    """``None`` kalau transisi ``entry.state → target`` diizinkan, else pesan error."""
    if target not in JOURNAL_ENTRY_STATES:
        return f"State '{target}' tidak dikenal."

    allowed = ALLOWED_TRANSITIONS.get(entry.state, ())
    if target not in allowed:
        return (
            f"Journal Entry {entry.code} berstatus {entry.state}; transisi ke {target} "
            f"tidak diizinkan (yang boleh: {', '.join(allowed) or 'tidak ada'})."
        )

    return None


def _assert_draft(entry: JournalEntry, verb: str) -> str | None:
    """Guard: hanya DRAFT yang boleh diubah/dihapus (pola H1/H2/H3.1–H3.3)."""
    if entry.state != "DRAFT":
        return (
            f"Journal Entry {entry.code} berstatus {entry.state}; {verb} hanya boleh saat DRAFT."
        )

    return None


def _journal_guard(journal) -> str | None:
    """Guard journal: wajib punya ``odoo_id`` & (bila diketahui) bertipe **general**.

    Pesan non-general disusun sesuai keputusan STEP 0 H3.4. Bila ``journal_type``
    kosong (belum pernah di-pull) ⇒ **longgar**, keputusan diserahkan ke Odoo.
    """
    if not getattr(journal, "odoo_id", None):
        return (
            f"Journal {getattr(journal, 'code', journal.pk)} belum punya odoo_id "
            "(pull master journal dulu dari Odoo)."
        )
    journal_type = (getattr(journal, "journal_type", "") or "").strip().lower()
    if journal_type and journal_type != GENERAL_JOURNAL_TYPE:
        return (
            "Journal entry manual hanya boleh di journal general "
            f"(saat ini: {getattr(journal, 'code', journal.pk)} = {journal_type}). "
            "Pilih journal general atau pull dulu dari Odoo."
        )

    return None


def _accounts_guard(entry: JournalEntry) -> tuple[list, str | None]:
    """``(missing, error)`` — cek setiap akun baris punya ``odoo_id``."""
    missing = [
        {"line_id": line.pk, "account_id": line.account_id, "account_code": line.account.code}
        for line in entry.lines.select_related("account")
        if not getattr(line.account, "odoo_id", None)
    ]
    if missing:
        codes = ", ".join(str(item["account_code"] or item["account_id"]) for item in missing)
        return missing, (
            f"Akun berikut belum punya odoo_id: {codes} "
            "(pull chart of accounts dulu dari Odoo)."
        )

    return [], None


def _current_header(entry: JournalEntry) -> dict:
    """Header entry dalam bentuk payload (dipakai update parsial)."""
    return {
        "journal_id": entry.journal_id,
        "entry_date": _iso(entry.entry_date),
        "ref": entry.ref,
        "memo": entry.memo,
        "notes": entry.notes,
        "lines": [
            {
                "account_id": line.account_id,
                "partner_id": line.partner_id,
                "name": line.name,
                "debit": str(_decimal(line.debit)),
                "credit": str(_decimal(line.credit)),
            }
            for line in entry.lines.all()
        ],
    }


def _write_lines(entry: JournalEntry, lines) -> None:
    """Ganti seluruh baris entry (atomic) — dipakai create & update DRAFT."""
    entry.lines.all().delete()
    JournalEntryLine.objects.bulk_create(
        [
            JournalEntryLine(
                entry=entry,
                account=line["account"],
                partner=line["partner"],
                name=line["name"],
                debit=line["debit"],
                credit=line["credit"],
            )
            for line in lines
        ]
    )


# ---------------------------------------------------------------------------
# CRUD (DRAFT-only untuk perubahan) — menulis SyncRecord + AuditLog
# ---------------------------------------------------------------------------
def create_entry(data, request=None) -> JournalEntryWriteResult:
    """Buat journal entry (nomor ``JE-<TAHUN>-<SEQ>``, Sprint C) — **DRAFT** (MES-only).

    Validasi lengkap (journal, tanggal, ≥ 2 baris, XOR, Σ debit = Σ kredit) sebelum
    header + baris ditulis atomik. Entry lahir `DRAFT`; push ke Odoo terjadi saat
    `CONFIRMED`.
    """
    values, lines, error = validate_entry_payload(data if isinstance(data, dict) else {})
    if error:
        return JournalEntryWriteResult(error=error)

    with transaction.atomic():
        try:
            code = next_number("JE")
        except SequenceError as exc:
            return JournalEntryWriteResult(error=f"Penomoran journal entry gagal: {exc}")

        entry = JournalEntry.objects.create(code=code, state="DRAFT", **values)
        _write_lines(entry, lines)

    record = _arm_push(entry)
    _audit(
        ACTION_CREATE,
        entry,
        request,
        {
            "code": entry.code,
            "journal": getattr(entry.journal, "code", None),
            "total_debit": str(_decimal(entry.total_debit)),
            "total_credit": str(_decimal(entry.total_credit)),
            "line_count": len(lines),
        },
    )

    logger.info(
        "journal_entry: entry %s (%s) dibuat: %s baris, debit %s / credit %s (ledger=%s, DRAFT).",
        entry.pk,
        entry.code,
        len(lines),
        entry.total_debit,
        entry.total_credit,
        record.pk,
    )

    return JournalEntryWriteResult(entry=entry, sync_record_id=record.pk)


def update_entry(entry: JournalEntry, data, request=None) -> JournalEntryWriteResult:
    """Ubah journal entry **DRAFT-only** (baris diganti menyatu, atomik)."""
    error = _assert_draft(entry, "perubahan")
    if error:
        return JournalEntryWriteResult(entry=entry, error=error)

    payload = data if isinstance(data, dict) else {}
    values, lines, error = validate_entry_payload({**_current_header(entry), **payload})
    if error:
        return JournalEntryWriteResult(entry=entry, error=error)

    with transaction.atomic():
        for field, value in values.items():
            setattr(entry, field, value)
        entry.save()
        _write_lines(entry, lines)

    record = _arm_push(entry)
    _audit(
        ACTION_UPDATE,
        entry,
        request,
        {
            "code": entry.code,
            "journal": getattr(entry.journal, "code", None),
            "total_debit": str(_decimal(entry.total_debit)),
            "total_credit": str(_decimal(entry.total_credit)),
            "line_count": len(lines),
        },
    )

    logger.info(
        "journal_entry: entry %s (%s) diubah (%s baris, ledger=%s).",
        entry.pk,
        entry.code,
        len(lines),
        record.pk,
    )

    return JournalEntryWriteResult(entry=entry, sync_record_id=record.pk)


def delete_entry(entry: JournalEntry, request=None) -> JournalEntryWriteResult:
    """Hapus journal entry **DRAFT-only** (hard delete; baris ikut terhapus/CASCADE)."""
    error = _assert_draft(entry, "hapus")
    if error:
        return JournalEntryWriteResult(entry=entry, error=error)

    pk = entry.pk
    code = entry.code
    _audit(ACTION_DELETE, entry, request, {"code": code, "hard_delete": True})
    entry.delete()
    logger.info("journal_entry: entry %s (%s) dihapus (DRAFT).", pk, code)

    return JournalEntryWriteResult(entry=None, deleted=True)


# ---------------------------------------------------------------------------
# Transisi (confirm → SENT → DONE, cancel) — guard STEP 0 H3.4
# ---------------------------------------------------------------------------
def confirm_entry(entry: JournalEntry, request=None) -> JournalEntryWriteResult:
    """``DRAFT → CONFIRMED`` + enqueue push Odoo (draft `account.move` entry).

    Guard (semua → **400**, bukan push cacat):

      * journal punya ``odoo_id`` dan (bila tipenya diketahui) bertipe **general**;
      * **≥ 2 baris** dan **Σ debit = Σ kredit** (diulang, defensive — keputusan STEP 0);
      * setiap akun baris punya ``odoo_id``.
    """
    error = _assert_transition(entry, "CONFIRMED")
    if error:
        return JournalEntryWriteResult(entry=entry, error=error)

    error = _journal_guard(entry.journal)
    if error:
        return JournalEntryWriteResult(entry=entry, error=error)

    lines = list(entry.lines.all())
    if len(lines) < MIN_LINES:
        return JournalEntryWriteResult(
            entry=entry,
            error=f"Journal entry butuh minimal {MIN_LINES} baris (debit & kredit).",
        )

    total_debit = _money(sum((_decimal(line.debit) for line in lines), Decimal("0")))
    total_credit = _money(sum((_decimal(line.credit) for line in lines), Decimal("0")))
    if abs(total_debit - total_credit) > BALANCE_TOLERANCE:
        return JournalEntryWriteResult(
            entry=entry,
            error=(
                f"Journal entry tidak seimbang: total debit {total_debit} != "
                f"total credit {total_credit} (toleransi {BALANCE_TOLERANCE})."
            ),
        )

    missing, error = _accounts_guard(entry)
    if error:
        return JournalEntryWriteResult(entry=entry, error=error, missing_accounts=missing)

    entry.total_debit = total_debit
    entry.total_credit = total_credit
    entry.state = "CONFIRMED"
    entry.save(update_fields=("total_debit", "total_credit", "state", "updated_at"))

    record = _arm_push(entry, action="push")
    task_id = _enqueue_push(entry, record, "push")
    _audit(
        ACTION_CONFIRM,
        entry,
        request,
        {
            "code": entry.code,
            "journal": getattr(entry.journal, "code", None),
            "total_debit": str(total_debit),
            "total_credit": str(total_credit),
            "line_count": len(lines),
            "queued": task_id is not None,
        },
    )

    logger.info(
        "journal_entry: entry %s (%s) CONFIRMED (ledger=%s, queued=%s).",
        entry.pk,
        entry.code,
        record.pk,
        task_id is not None,
    )

    return JournalEntryWriteResult(entry=entry, sync_record_id=record.pk, task_id=task_id)


def sync_complete(entry: JournalEntry, erp_id) -> JournalEntryWriteResult:
    """``CONFIRMED → SENT``: simpan ``odoo_id`` + tandai ``SyncRecord`` = SENT.

    Dipanggil **task** setelah adapter sukses (``erp_id`` = id ``account.move``).
    """
    if entry.state == "CONFIRMED" and erp_id:
        entry.state = "SENT"
        update_fields = ["state", "updated_at"]
        if str(erp_id).isdigit():
            entry.odoo_id = int(erp_id)
            update_fields.append("odoo_id")
        entry.save(update_fields=tuple(update_fields))

    record = SyncRecord.objects.filter(
        resource=JOURNAL_ENTRY_RESOURCE, resource_id=str(entry.pk), stage=JOURNAL_ENTRY_STAGE
    ).first()
    if record is not None and erp_id:
        SyncIdempotency().mark_sent(record, erp_id)

    _audit(
        ACTION_SYNC_COMPLETE,
        entry,
        None,
        {"code": entry.code, "erp_id": str(erp_id), "state": entry.state},
    )

    return JournalEntryWriteResult(
        entry=entry, sync_record_id=None if record is None else record.pk
    )


def sync_failed(entry: JournalEntry, error, request=None) -> JournalEntryWriteResult:
    """Push gagal: ``SyncRecord`` = FAILED + audit; **state model tetap CONFIRMED**.

    Entry sengaja **tidak** dipindah ke state gagal (keputusan H3.4 = H3.1–H3.3: state
    model = state bisnis; kegagalan push = state sync) supaya bisa di-retry.
    """
    record = SyncRecord.objects.filter(
        resource=JOURNAL_ENTRY_RESOURCE, resource_id=str(entry.pk), stage=JOURNAL_ENTRY_STAGE
    ).first()
    if record is not None:
        SyncIdempotency().mark_failed(record, error)

    _audit(
        ACTION_SYNC_FAILED,
        entry,
        request,
        {"code": entry.code, "error": str(error), "state": entry.state},
    )

    return JournalEntryWriteResult(
        entry=entry, error=str(error), sync_record_id=None if record is None else record.pk
    )


def done_entry(entry: JournalEntry, request=None) -> JournalEntryWriteResult:
    """``CONFIRMED|SENT → DONE`` (murni MES — akuntan sudah selesai di Odoo)."""
    error = _assert_transition(entry, "DONE")
    if error:
        return JournalEntryWriteResult(entry=entry, error=error)

    entry.state = "DONE"
    entry.save(update_fields=("state", "updated_at"))
    _audit(ACTION_DONE, entry, request, {"code": entry.code})

    logger.info("journal_entry: entry %s (%s) DONE.", entry.pk, entry.code)

    return JournalEntryWriteResult(entry=entry)


def cancel_entry(entry: JournalEntry, request=None) -> JournalEntryWriteResult:
    """``DRAFT|CONFIRMED|SENT → CANCELLED``; kalau sudah punya ``odoo_id`` → push cancel.

    Odoo: `account.move.button_cancel` — kegagalan cancel **tidak** membatalkan
    pembatalan di MES, hanya tercatat di `SyncRecord` (pola `cancel_vendor_bill`).
    """
    error = _assert_transition(entry, "CANCELLED")
    if error:
        return JournalEntryWriteResult(entry=entry, error=error)

    odoo_id = entry.odoo_id
    entry.state = "CANCELLED"
    entry.save(update_fields=("state", "updated_at"))

    record = None
    task_id = None
    if odoo_id:
        record = _arm_push(entry, action="cancel")
        task_id = _enqueue_push(entry, record, "cancel")

    _audit(
        ACTION_CANCEL,
        entry,
        request,
        {"code": entry.code, "odoo_id": odoo_id, "queued": task_id is not None},
    )

    logger.info(
        "journal_entry: entry %s (%s) CANCELLED (odoo_id=%s, queued=%s).",
        entry.pk,
        entry.code,
        odoo_id,
        task_id is not None,
    )

    return JournalEntryWriteResult(
        entry=entry, sync_record_id=None if record is None else record.pk, task_id=task_id
    )
