"""Service **Number Sequence** (Sprint C) — penomoran dokumen MES per tahun.

Pola **sama** dengan `master/work_center_services.py` (H1.7),
`master/production_line_services.py` (H1.8), dan `master/routing_services.py` (H1.9):
setiap operasi tulis = data + ``SyncRecord`` (``master.number_sequence`` /
``MASTER_PUSH``) + ``AuditLog`` (``master.create|update``).

Format nomor: **``<PREFIX>-<YEAR>-<SEQ:04d>``**, ``SEQ`` mulai 1 dan **reset per tahun**
(baris ``(code, year)`` baru dibuat otomatis saat penomoran pertama di tahun itu).

Kekhususan Sprint C — **MES-only** (keputusan pemilik proyek, berbasis probe Odoo 17):

  * ``ir.sequence`` Odoo **ADA** (19 field, 37 record) — berbeda dari kasus H1.8/H1.9 —
    tetapi itu **counter internal dokumen Odoo sendiri** (``name='Chicago 1 Penomoran
    Internal'``, ``prefix='CHIC1/INT/'``, ``padding=5``, ``code`` tidak required);
    ``ir.sequence.date_range`` ADA tapi 0 record (reset-per-tahun tidak dipakai);
  * mengirim ``number_next`` ke sana = **mengubah penomoran dokumen Odoo yang sudah
    berjalan** (tidak reversible) ⇒ nomor MES tidak dikirim: ledger ditulis
    ``SyncStatus.SKIPPED`` (``mark_skipped``, sama H1.7–H1.9), tanpa ``odoo_id``;
  * **tidak** ada task push/pull & **tidak** ada view sync baru — jejaknya terlihat di
    ``/api/v1/sync/records/?status=SKIPPED``;
  * concurrency: increment memakai ``select_for_update()`` di dalam
    ``transaction.atomic`` (satu baris sequence = satu lock) + ``generate_with_retry``
    untuk race saat **membuat baris tahun baru** (``IntegrityError`` pada constraint
    ``(code, year)``);
  * ``preview_number`` **tidak** menaikkan counter (read-only, untuk UI);
  * model ini tidak menggantikan ``Order.code``/``WorkOrder.code`` yang diisi manual —
    H2.1+ yang akan memakai ``next_number('SO')`` saat membuat Order (tanpa breaking);
  * **H5.3** menambah CRUD di atas jalur Sprint C: ``create_sequence`` (POST membuat
    baris ``(code, year)`` baru, ``last_seq=0``) + ``deactivate_sequence`` (DELETE =
    soft delete ``is_active=False``, guard kode seed terlindungi / ``last_seq>0``).
    Semua tetap **MES-only** (ledger ``SKIPPED``) — tanpa task push/pull.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.audit.models import AuditLog
from core.audit.services import AuditLogger
from integrations.erp_sync.idempotency import SyncIdempotency
from integrations.erp_sync.models import SyncResource, SyncStage, SyncStatus

from .models import NumberSequence
from .services import ACTION_CREATE, ACTION_DELETE, ACTION_UPDATE, parse_bool

logger = logging.getLogger(__name__)

__all__ = (
    "CODE_PATTERN",
    "DEFAULT_PADDING",
    "MAX_NAME_LENGTH",
    "MAX_PADDING",
    "MAX_PREFIX_LENGTH",
    "MES_ONLY_REASON",
    "MIN_CODE_LENGTH",
    "MIN_PADDING",
    "MIN_PREFIX_LENGTH",
    "PREFIX_PATTERN",
    "PROTECTED_SEQUENCE_CODES",
    "SequenceError",
    "SequenceWriteResult",
    "create_sequence",
    "current_year",
    "deactivate_sequence",
    "format_number",
    "generate_with_retry",
    "get_or_create_current_year",
    "next_number",
    "preview_number",
    "reset_if_new_year",
    "sequence_row",
    "update_sequence",
    "validate_new_sequence_payload",
    "validate_sequence_payload",
)

#: Resource sync (jangan ganti string literal di view).
SEQUENCE_RESOURCE = SyncResource.MASTER_NUMBER_SEQUENCE.value
STAGE = SyncStage.MASTER_PUSH.value

#: Alasan baku status ``SKIPPED`` (disimpan di ``SyncRecord.last_error``).
MES_ONLY_REASON = (
    "MES-only: Number Sequence tidak dikirim ke Odoo — `ir.sequence` Odoo adalah "
    "counter internal dokumen Odoo sendiri (37 record hidup, prefix/format berbeda); "
    "menulis number_next akan merusak penomoran dokumen Odoo."
)

#: Batas (selaras kolom model → beda dari DB = 400, bukan 500).
MAX_CODE_LENGTH = 16
MAX_NAME_LENGTH = 64
MAX_PREFIX_LENGTH = 16
MIN_PADDING = 1
MAX_PADDING = 10
DEFAULT_PADDING = 4
#: Panjang kode/prefix minimum (H5.3 — melengkapi `MAX_CODE_LENGTH`/`MAX_PREFIX_LENGTH`).
MIN_CODE_LENGTH = 2
MIN_PREFIX_LENGTH = 1

#: Pola kode (H5.3): uppercase A-Z + digit, 2..16 char — input di-``upper()`` dulu.
CODE_PATTERN = re.compile(r"^[A-Z0-9]{2,16}$")

#: Pola prefix (H5.3): uppercase A-Z + digit + dash, 1..16 char (prefix sering pakai dash).
PREFIX_PATTERN = re.compile(r"^[A-Z0-9-]{1,16}$")

#: Guard **DELETE** (H5.3) — kode seed yang TIDAK boleh dinonaktifkan dari UI.
#: 9 kode (bukan 7): 7 Sprint C (SO/PO/WO/INV/VB/PAY/JE) + ``ADJ`` (H2.5, migrasi 0015)
#: + ``TRF`` (H2.6, migrasi 0016). Hanya guard DELETE — create ulang tetap boleh
#: (mis. restore seed yang hilang di tenant baru), dijaga keunikan ``(code, year)``.
PROTECTED_SEQUENCE_CODES = frozenset(
    {"SO", "PO", "WO", "INV", "VB", "PAY", "JE", "ADJ", "TRF"}
)

#: Jumlah percobaan ``generate_with_retry`` (race pembuatan baris tahun baru).
MAX_RETRY = 3


class SequenceError(ValidationError):
    """Error validasi sequence → dipetakan view menjadi **400**."""


class SequenceNotFoundError(SequenceError):
    """Kode sequence tidak dikenal → dipetakan view menjadi **404**."""


@dataclass
class SequenceWriteResult:
    """Hasil satu operasi tulis sequence (dipakai view).

    **Tanpa** ``task_id``/``queued``: Sprint C MES-only → tidak ada task push.
    """

    sequence: NumberSequence | None = None
    error: str | None = None
    sync_record_id: int | None = None

    @property
    def sync_status(self) -> str | None:
        """Status ledger yang ditulis (``SKIPPED``) — ``None`` kalau tak ada tulis."""
        return SyncStatus.SKIPPED.value if self.sync_record_id else None


def current_year() -> int:
    """Tahun berjalan (dipisah supaya mudah di-mock di test)."""
    return timezone.now().year


def format_number(prefix: str, year: int, last_seq: int, padding: int) -> str:
    """PURE — susun nomor ``<PREFIX>-<YEAR>-<SEQ:0{padding}d>``.

    Angka lebih panjang dari ``padding`` **tidak** dipotong (``zfill`` tidak
    memotong) — nomor tetap unik dan terbaca.
    """
    return f"{prefix}-{year}-{str(int(last_seq)).zfill(int(padding))}"


def _iso(value) -> str | None:
    """ISO-8601 atau ``None`` (datetime kosong)."""
    return value.isoformat() if value else None


def sequence_row(sequence: NumberSequence) -> dict:
    """Satu baris sequence untuk API (termasuk ``next_number`` pratinjau)."""
    return {
        "id": sequence.pk,
        "code": sequence.code,
        "name": sequence.name,
        "prefix": sequence.prefix,
        "year": sequence.year,
        "last_seq": sequence.last_seq,
        "padding": sequence.padding,
        "is_active": sequence.is_active,
        "next_number": format_number(
            sequence.prefix, sequence.year, sequence.last_seq + 1, sequence.padding
        ),
        "created_at": _iso(sequence.created_at),
        "updated_at": _iso(sequence.updated_at),
    }


def _sequence_payload(sequence: NumberSequence) -> dict:
    """Payload yang disimpan di ``SyncRecord.payload`` (jejak audit MES-only)."""
    row = sequence_row(sequence)

    return {
        "code": row["code"],
        "name": row["name"],
        "prefix": row["prefix"],
        "year": row["year"],
        "last_seq": row["last_seq"],
        "padding": row["padding"],
        "active": row["is_active"],
        "next_number": row["next_number"],
    }


# ---------------------------------------------------------------------------
# Resolusi baris sequence (termasuk reset per tahun)
# ---------------------------------------------------------------------------
def get_or_create_current_year(
    code: str, year: int | None = None
) -> NumberSequence:
    """Baris sequence ``(code, year)`` — **buat** kalau tahunnya belum ada.

    Reset per tahun: baris tahun baru menyalin ``name``/``prefix``/``padding``/
    ``is_active`` dari tahun terakhir dan memulai ``last_seq=0``. Kode yang belum
    pernah ada sama sekali → ``SequenceNotFoundError`` (view → **404**).

    Bisa melempar ``IntegrityError`` saat dua request membuat baris tahun baru
    bersamaan → ditangani `generate_with_retry`.
    """
    target_year = current_year() if year is None else int(year)

    existing = NumberSequence.objects.filter(code=code, year=target_year).first()
    if existing is not None:
        return existing

    latest = NumberSequence.objects.filter(code=code).order_by("-year").first()
    if latest is None:
        raise SequenceNotFoundError(f"Sequence '{code}' tidak dikenal.")

    logger.info(
        "master.sequence: reset tahun untuk %s → %s (dari %s).", code, target_year, latest.year
    )

    return NumberSequence.objects.create(
        code=code,
        year=target_year,
        name=latest.name,
        prefix=latest.prefix,
        padding=latest.padding,
        last_seq=0,
        is_active=latest.is_active,
    )


def reset_if_new_year(sequence: NumberSequence, year: int | None = None) -> NumberSequence:
    """Kembalikan baris untuk ``year`` (reset) — baris lama dibiarkan utuh.

    Dipanggil ``next_number`` ketika baris yang dipegang berasal dari tahun lain:
    tahun baru = baris baru dengan ``last_seq=0`` (nomor lama tetap bisa dilacak).
    """
    target_year = current_year() if year is None else int(year)
    if sequence.year == target_year:
        return sequence

    return get_or_create_current_year(sequence.code, target_year)


# ---------------------------------------------------------------------------
# Ledger (SKIPPED) + audit — pola H1.7/H1.8/H1.9
# ---------------------------------------------------------------------------
def _record_mes_only(sequence: NumberSequence) -> int:
    """Tulis/segarkan ``SyncRecord`` sequence lalu tandai ``SKIPPED``."""
    payload = _sequence_payload(sequence)
    sync = SyncIdempotency()
    record = sync.get_or_create_sync_record(SEQUENCE_RESOURCE, sequence.pk, STAGE, payload)

    if dict(record.payload or {}) != payload:
        record.payload = payload
        record.save(update_fields=("payload", "updated_at"))

    sync.mark_skipped(record, MES_ONLY_REASON)

    return record.pk


def _audit(
    action: str, sequence: NumberSequence, request, metadata: dict | None = None
) -> None:
    """Tulis ``AuditLog`` — best-effort (audit tidak boleh menggagalkan penomoran)."""
    try:
        AuditLogger().log(
            user=None,
            action=action,
            resource=SEQUENCE_RESOURCE,
            resource_id=sequence.pk,
            request=request,
            payload=_sequence_payload(sequence),
            result=AuditLog.Result.OK,
            metadata={"mes_only": True, **(metadata or {})},
        )
    except Exception:  # noqa: BLE001 - audit tidak boleh menggagalkan penomoran
        logger.exception(
            "master.sequence: gagal menulis audit (%s, sequence %s).", action, sequence.pk
        )


def _record_and_audit(
    sequence: NumberSequence, request, *, metadata: dict | None = None, action: str = ACTION_UPDATE
) -> int:
    """Tulis ledger ``SKIPPED`` + audit lalu kembalikan id ``SyncRecord``."""
    record_id = _record_mes_only(sequence)
    _audit(action, sequence, request, metadata)

    return record_id


# ---------------------------------------------------------------------------
# Generate nomor (atomic + retry) & pratinjau
# ---------------------------------------------------------------------------
def _next_number_once(code: str, year: int, request=None) -> tuple[str, NumberSequence, bool, int]:
    """Satu percobaan ``next_number`` → ``(number, sequence, created_year, record_id)``.

    Lock: ``select_for_update()`` pada baris sequence di dalam ``transaction.atomic``
    (satu baris = satu lock) sehingga dua request bersamaan tidak pernah mendapat
    nomor yang sama.
    """
    with transaction.atomic():
        created = not NumberSequence.objects.filter(code=code, year=year).exists()
        sequence = get_or_create_current_year(code, year)

        if not sequence.is_active:
            raise SequenceError(
                f"Sequence '{code}' nonaktif — aktifkan dulu sebelum menomori dokumen."
            )

        locked = NumberSequence.objects.select_for_update().get(pk=sequence.pk)
        locked.last_seq += 1
        locked.save(update_fields=("last_seq", "updated_at"))

        number = format_number(locked.prefix, locked.year, locked.last_seq, locked.padding)
        record_id = _record_and_audit(
            locked,
            request,
            metadata={
                "number": number,
                "increment": True,
                "new_year": created,
                "last_seq": locked.last_seq,
            },
            action=ACTION_CREATE if created else ACTION_UPDATE,
        )

    logger.info(
        "master.sequence: %s → %s (ledger=%s, MES-only, tahun baru=%s).",
        code,
        number,
        record_id,
        created,
    )

    return number, locked, created, record_id


def generate_with_retry(
    code: str, max_retry: int = MAX_RETRY, *, year: int | None = None, request=None
) -> str:
    """``next_number`` dengan retry saat race **membuat baris tahun baru**.

    ``IntegrityError`` hanya mungkin berasal dari constraint ``(code, year)`` ketika
    dua request membuat baris tahun baru bersamaan; percobaan ulang akan menemukan
    baris itu dan lanjut menomori. Error lain (kode tak dikenal/nonaktif) langsung
    dilempar sebagai ``SequenceError``.
    """
    target_year = current_year() if year is None else int(year)
    last_error: IntegrityError | None = None

    for attempt in range(1, max_retry + 1):
        try:
            number, _, _, _ = _next_number_once(code, target_year, request)
            return number
        except IntegrityError as exc:  # pragma: no cover - race DB, sulit dipaksa di test
            last_error = exc
            logger.warning(
                "master.sequence: race membuat baris %s/%s (percobaan %s/%s).",
                code,
                target_year,
                attempt,
                max_retry,
            )

    raise SequenceError(
        f"Gagal menomori '{code}' setelah {max_retry} percobaan (race tahun baru)."
    ) from last_error


def next_number(code: str, *, year: int | None = None, request=None) -> str:
    """Nomor berikutnya untuk ``code`` — **atomic**, mis. ``SO-2026-0001``.

    Menaikkan ``last_seq`` baris ``(code, current_year)`` di dalam
    ``transaction.atomic`` + ``select_for_update()``, lalu menulis
    ``SyncRecord`` ``SKIPPED`` (MES-only) + ``AuditLog``.
    """
    return generate_with_retry(code, MAX_RETRY, year=year, request=request)


def preview_number(code: str, *, year: int | None = None) -> dict:
    """Nomor berikutnya **tanpa** menaikkan counter (read-only, untuk UI).

    Tanpa efek samping: kalau baris tahun berjalan belum ada, nilainya dihitung dari
    baris tahun terakhir (``last_seq=0`` ⇒ ``<PREFIX>-<TAHUN>-0001``) tanpa menulis
    apa pun. Kode tak dikenal → ``SequenceNotFoundError`` (view → **404**).
    """
    target_year = current_year() if year is None else int(year)

    sequence = NumberSequence.objects.filter(code=code, year=target_year).first()
    if sequence is None:
        latest = NumberSequence.objects.filter(code=code).order_by("-year").first()
        if latest is None:
            raise SequenceNotFoundError(f"Sequence '{code}' tidak dikenal.")

        return {
            "code": code,
            "name": latest.name,
            "prefix": latest.prefix,
            "year": target_year,
            "last_seq": 0,
            "padding": latest.padding,
            "is_active": latest.is_active,
            "next_number": format_number(latest.prefix, target_year, 1, latest.padding),
        }

    return {
        "code": sequence.code,
        "name": sequence.name,
        "prefix": sequence.prefix,
        "year": sequence.year,
        "last_seq": sequence.last_seq,
        "padding": sequence.padding,
        "is_active": sequence.is_active,
        "next_number": format_number(
            sequence.prefix, sequence.year, sequence.last_seq + 1, sequence.padding
        ),
    }


# ---------------------------------------------------------------------------
# Validasi (PUT) + CRUD tambahan (POST/DELETE) — H5.3
# ---------------------------------------------------------------------------
def validate_sequence_payload(data, instance: NumberSequence | None = None):
    """Validasi body PUT sequence → ``(values, error)``.

    Hanya ``name`` / ``prefix`` / ``padding`` / ``active`` yang boleh diubah.
    ``code``, ``year``, dan ``last_seq`` **ditolak** (400) supaya identitas dan
    counter tidak bisa digeser dari UI — counter hanya naik lewat `next_number`.
    """
    payload = data if isinstance(data, dict) else {}
    values: dict = {}

    for forbidden in ("code", "year", "last_seq"):
        if forbidden in payload:
            return None, (
                f"Field '{forbidden}' tidak dapat diubah lewat endpoint ini "
                "(counter hanya naik lewat next_number; identitas/tahun terkunci)."
            )

    if "name" in payload:
        name = str(payload.get("name") or "").strip()
        if not name:
            return None, "Field 'name' wajib diisi."
        if len(name) > MAX_NAME_LENGTH:
            return None, f"Field 'name' maksimal {MAX_NAME_LENGTH} karakter."
        values["name"] = name

    if "prefix" in payload:
        prefix = str(payload.get("prefix") or "").strip()
        if not prefix:
            return None, "Field 'prefix' wajib diisi (tidak boleh kosong)."
        if len(prefix) > MAX_PREFIX_LENGTH:
            return None, f"Field 'prefix' maksimal {MAX_PREFIX_LENGTH} karakter."
        values["prefix"] = prefix

    if "padding" in payload:
        raw_padding = payload.get("padding")
        if isinstance(raw_padding, bool) or not isinstance(raw_padding, int):
            return None, "Field 'padding' harus integer."
        if raw_padding < MIN_PADDING or raw_padding > MAX_PADDING:
            return None, (
                f"Field 'padding' harus antara {MIN_PADDING} dan {MAX_PADDING}."
            )
        values["padding"] = raw_padding

    if "active" in payload:
        active = parse_bool(payload.get("active"))
        if active is None:
            return None, "Field 'active' harus true|false."
        values["is_active"] = active

    return values, None


def update_sequence(
    sequence: NumberSequence, data, request=None
) -> SequenceWriteResult:
    """Ubah ``name``/``prefix``/``padding``/``active`` + ledger ``SKIPPED`` + audit.

    Perubahan **tidak** mengubah ``last_seq`` (nomor berikutnya tetap
    ``last_seq + 1``) dan tidak menyentuh baris tahun lain.
    """
    values, error = validate_sequence_payload(data, instance=sequence)
    if error:
        return SequenceWriteResult(sequence=sequence, error=error)

    if not values:
        return SequenceWriteResult(sequence=sequence)

    for field, value in values.items():
        setattr(sequence, field, value)
    sequence.save()

    record_id = _record_and_audit(
        sequence, request, metadata={"fields": sorted(values)}
    )

    logger.info(
        "master.sequence: %s diperbarui (ledger=%s, MES-only).", sequence.code, record_id
    )

    return SequenceWriteResult(sequence=sequence, sync_record_id=record_id)


# ---------------------------------------------------------------------------
# H5.3 — CRUD tambahan: create (POST) + soft delete (DELETE)
# ---------------------------------------------------------------------------
def validate_new_sequence_payload(data):
    """Validasi body **POST** sequence → ``(values, error)``.

    Aturan H5.3 (keputusan STEP 0):

      * ``code`` — wajib, ``^[A-Z0-9]{2,16}$``, di-``upper()`` otomatis;
      * ``name`` — wajib, maks. ``MAX_NAME_LENGTH``;
      * ``prefix`` — opsional (default = ``code``), ``^[A-Z0-9-]{1,16}$``, di-``upper()``;
      * ``padding`` — opsional (default ``DEFAULT_PADDING``), ``MIN_PADDING..MAX_PADDING``.

    ``year``/``last_seq``/``is_active`` **selalu** diisi service
    (``year`` = tahun berjalan / ``?year=``, ``last_seq=0``, ``is_active=True``).
    ``PROTECTED_SEQUENCE_CODES`` **bukan** guard create — kode terlindungi boleh
    dibuat ulang kalau barisnya hilang; yang dijaga hanya keunikan ``(code, year)``.
    """
    payload = data if isinstance(data, dict) else {}

    code = str(payload.get("code") or "").strip().upper()
    if not code:
        return None, "Field 'code' wajib diisi."
    if not CODE_PATTERN.match(code):
        return None, (
            "Field 'code' hanya boleh huruf A-Z dan angka 0-9, "
            f"{MIN_CODE_LENGTH}-{MAX_CODE_LENGTH} karakter."
        )

    name = str(payload.get("name") or "").strip()
    if not name:
        return None, "Field 'name' wajib diisi."
    if len(name) > MAX_NAME_LENGTH:
        return None, f"Field 'name' maksimal {MAX_NAME_LENGTH} karakter."

    raw_prefix = payload.get("prefix")
    prefix = code if raw_prefix in (None, "") else str(raw_prefix).strip().upper()
    if not PREFIX_PATTERN.match(prefix):
        return None, (
            "Field 'prefix' hanya boleh huruf A-Z, angka 0-9, dan tanda '-' "
            f"({MIN_PREFIX_LENGTH}-{MAX_PREFIX_LENGTH} karakter)."
        )

    raw_padding = payload.get("padding", DEFAULT_PADDING)
    if isinstance(raw_padding, bool) or not isinstance(raw_padding, int):
        return None, "Field 'padding' harus integer."
    if raw_padding < MIN_PADDING or raw_padding > MAX_PADDING:
        return None, f"Field 'padding' harus antara {MIN_PADDING} dan {MAX_PADDING}."

    return {"code": code, "name": name, "prefix": prefix, "padding": raw_padding}, None


def create_sequence(data, request=None, *, year: int | None = None) -> SequenceWriteResult:
    """Buat baris sequence ``(code, year)`` baru + ledger ``SKIPPED`` + audit.

    ``last_seq`` mulai 0 dan ``is_active=True``; ``year`` default tahun berjalan.
    Duplikat ``(code, year)`` → ``SequenceWriteResult.error`` (view → **400**),
    termasuk saat balapan (``IntegrityError`` pada ``uniq_sequence_code_year``).
    """
    values, error = validate_new_sequence_payload(data)
    if error:
        return SequenceWriteResult(error=error)

    target_year = current_year() if year is None else int(year)
    duplicate = f"Sequence '{values['code']}' sudah ada untuk tahun {target_year}."

    try:
        with transaction.atomic():
            if NumberSequence.objects.filter(code=values["code"], year=target_year).exists():
                raise SequenceError(duplicate)

            sequence = NumberSequence.objects.create(
                year=target_year, last_seq=0, is_active=True, **values
            )
            record_id = _record_and_audit(
                sequence,
                request,
                metadata={"fields": sorted(values), "year": target_year, "create": True},
                action=ACTION_CREATE,
            )
    except IntegrityError:
        return SequenceWriteResult(error=duplicate)
    except SequenceError as exc:
        return SequenceWriteResult(error=str(exc))

    logger.info(
        "master.sequence: sequence %s/%s dibuat (ledger=%s, MES-only).",
        values["code"],
        target_year,
        record_id,
    )
    return SequenceWriteResult(sequence=sequence, sync_record_id=record_id)


def deactivate_sequence(sequence: NumberSequence, request=None) -> SequenceWriteResult:
    """Soft delete (``is_active=False``) + ledger ``SKIPPED`` + audit.

    **Guard pemakaian** (keputusan STEP 0) — baris TIDAK dinonaktifkan (view → **400**):

      * ``code`` ada di `PROTECTED_SEQUENCE_CODES` (9 seed: SO/PO/WO/INV/VB/PAY/JE/ADJ/TRF)
        → ``"… masih dipakai (protected seed)"``;
      * atau ``last_seq > 0`` (sudah pernah menomori dokumen) →
        ``"… masih dipakai (last_seq=N)"``.

    Baris **tidak** dihapus dari DB (tanpa ``delete()``): nomor lama tetap bisa dilacak
    dan jejak audit utuh — padanan ``deactivate_routing``/``deactivate_product``.
    Menerima *instance* (view me-resolve ``code`` + ``?year=`` → baris), konsisten
    dengan ``update_sequence``/``deactivate_routing``.
    """
    code = str(sequence.code).upper()

    if code in PROTECTED_SEQUENCE_CODES:
        return SequenceWriteResult(
            sequence=sequence,
            error=(
                f"Sequence '{code}' masih dipakai (protected seed) — "
                "tidak dapat dinonaktifkan."
            ),
        )

    if sequence.last_seq > 0:
        return SequenceWriteResult(
            sequence=sequence,
            error=(
                f"Sequence '{code}' masih dipakai (last_seq={sequence.last_seq}) — "
                "tidak dapat dinonaktifkan."
            ),
        )

    if sequence.is_active:
        sequence.is_active = False
        sequence.save(update_fields=("is_active", "updated_at"))

    record_id = _record_and_audit(
        sequence, request, metadata={"soft_delete": True}, action=ACTION_DELETE
    )

    logger.info(
        "master.sequence: sequence %s/%s dinonaktifkan (ledger=%s, MES-only).",
        sequence.code,
        sequence.year,
        record_id,
    )
    return SequenceWriteResult(sequence=sequence, sync_record_id=record_id)




