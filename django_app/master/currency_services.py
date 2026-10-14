"""Service CRUD master **Currency** (H5.2) — **MES-only** (ledger ``SKIPPED``).

Pola **sama** dengan `master/tax_services.py` (H3.6) & `master/sequence_services.py`
(Sprint C/H5.3): satu operasi tulis = data + ``SyncRecord``
(``master.currency`` / ``MASTER_PUSH``) + ``AuditLog``
(``master.create|update|delete``). **Tanpa** ``task_id``/enqueue — tidak ada push task.

Keputusan STEP 0 (H5.2) — kenapa **MES-only** (bukan push dua arah seperti Tax):

  * **tidak ada konsumen MES** yang mengirim mata uang ke Odoo: ``Payment.currency``
    hanyalah **teks bebas** (``CharField``, MES-only) dan invoice/journal/order secara
    sadar **tidak** mengirim ``currency_id`` (Odoo menghitungnya dari
    ``journal_id``/``company``);
  * ``rate`` di-maintain Odoo (``res.currency.rate``) dan pull harian
    ``erp_sync.sync_master_currencies`` (I1) berpotensi menimpa nilai MES;
  * ``res.currency`` = **konfigurasi akuntansi/company** (mengaktifkan mata uang
    memengaruhi pembukuan) ⇒ tidak diubah diam-diam dari MES — preseden Sprint C /
    H1.7–H1.9: nomor/tulisan dicatat ``SyncStatus.SKIPPED`` tanpa ``odoo_id`` baru.

Jejak tulis terlihat di ``/api/v1/sync/records/?status=SKIPPED`` (resource
``master.currency``). Pull I1 **tidak** diubah (brief H5.2: "cek hanya").

``is_default`` = **keputusan MES** (bukan field Odoo) dan dijaga tetap tunggal oleh
:func:`set_default_currency` (pola ``Tax.is_default`` H3.6).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.db import transaction

from core.audit.models import AuditLog
from core.audit.services import AuditLogger
from integrations.erp_sync.idempotency import SyncIdempotency
from integrations.erp_sync.models import SyncResource, SyncStage, SyncStatus

from .models import Currency
from .services import ACTION_CREATE, ACTION_DELETE, ACTION_UPDATE, parse_bool

logger = logging.getLogger(__name__)

__all__ = (
    "CODE_PATTERN",
    "CurrencyWriteResult",
    "MAX_NAME_LENGTH",
    "MAX_RATE",
    "MAX_SYMBOL_LENGTH",
    "MES_ONLY_REASON",
    "PROTECTED_CURRENCY_CODES",
    "create_currency",
    "currency_row",
    "deactivate_currency",
    "get_default_currency",
    "set_default_currency",
    "update_currency",
    "validate_currency_payload",
)

#: Kunci sync Currency (jangan diganti string literal di view).
CURRENCY_RESOURCE = SyncResource.MASTER_CURRENCY.value
STAGE = SyncStage.MASTER_PUSH.value

#: Alasan baku status ``SKIPPED`` (disimpan di ``SyncRecord.last_error``).
MES_ONLY_REASON = (
    "MES-only: mata uang tidak dikirim ke Odoo — tidak ada konsumen MES yang memakai "
    "`res.currency` (Payment.currency = teks bebas MES-only; invoice/journal TIDAK "
    "mengirim `currency_id`), `rate` di-maintain Odoo, dan `res.currency` = konfigurasi "
    "akuntansi/company (pull harian I1 berpotensi menimpa)."
)

#: Batas (selaras kolom model → beda dari DB = 400, bukan 500).
MAX_NAME_LENGTH = 255
MAX_SYMBOL_LENGTH = 8
#: Kurs maksimum yang muat di ``DecimalField(max_digits=20, decimal_places=6)``.
MAX_RATE = Decimal("99999999999999.999999")

#: Pola kode ISO untuk baris **baru** (``^[A-Z]{3}$``, auto-upper).
#: Baris hasil pull I1 ber-kode ``ODOO-<id>`` → tidak divalidasi ulang saat update
#: (selama nilainya tidak diubah), supaya mirror I1 tetap bisa di-edit dari MES.
CODE_PATTERN = re.compile(r"^[A-Z]{3}$")

#: Guard **DELETE** (keputusan STEP 0) — kode ISO terlindungi.
#: Efektif untuk baris buatan MES; baris hasil pull I1 terjaga lewat guard ``odoo_id``.
PROTECTED_CURRENCY_CODES = frozenset({"IDR", "USD"})


@dataclass
class CurrencyWriteResult:
    """Hasil satu operasi tulis Currency (dipakai view).

    **Tanpa** ``task_id``/``queued``: H5.2 MES-only → tidak ada task push.
    """

    currency: Currency | None = None
    error: str | None = None
    sync_record_id: int | None = None

    @property
    def sync_status(self) -> str | None:
        """Status ledger yang ditulis (``SKIPPED``) — ``None`` kalau tak ada tulis."""
        return SyncStatus.SKIPPED.value if self.sync_record_id else None


def currency_row(currency: Currency) -> dict:
    """Baris Currency untuk API (list & detail) — seluruhnya JSON-safe.

    ``odoo_id`` **wajib** ada (kunci mirror I1; ``null`` = belum/bukan hasil pull) —
    dipakai UI untuk menandai baris mirror & menjelaskan guard penghapusan.
    """
    return {
        "id": currency.pk,
        "code": currency.code,
        "name": currency.name,
        "symbol": currency.symbol,
        "rate": float(currency.rate) if currency.rate is not None else None,
        "is_default": bool(currency.is_default),
        "is_active": bool(currency.is_active),
        "odoo_id": currency.odoo_id,
    }


def _currency_payload(currency: Currency) -> dict:
    """Payload yang disimpan di ``SyncRecord.payload`` (jejak audit MES-only)."""
    return {
        "code": currency.code,
        "name": currency.name,
        "symbol": currency.symbol,
        "rate": float(currency.rate) if currency.rate is not None else None,
        "is_default": bool(currency.is_default),
        "active": bool(currency.is_active),
        "odoo_id": currency.odoo_id,
    }


# ---------------------------------------------------------------------------
# Ledger (SKIPPED) + audit — pola Sprint C / H1.7–H1.9
# ---------------------------------------------------------------------------
def _record_mes_only(currency: Currency) -> int:
    """Tulis/segarkan ``SyncRecord`` currency lalu tandai ``SKIPPED``."""
    payload = _currency_payload(currency)
    sync = SyncIdempotency()
    record = sync.get_or_create_sync_record(CURRENCY_RESOURCE, currency.pk, STAGE, payload)

    if dict(record.payload or {}) != payload:
        record.payload = payload
        record.save(update_fields=("payload", "updated_at"))

    sync.mark_skipped(record, MES_ONLY_REASON)

    return record.pk


def _audit(
    action: str, currency: Currency, request, metadata: dict | None = None
) -> None:
    """Tulis ``AuditLog`` — best-effort (audit tidak boleh menggagalkan CRUD)."""
    try:
        AuditLogger().log(
            user=None,
            action=action,
            resource=CURRENCY_RESOURCE,
            resource_id=currency.pk,
            request=request,
            payload=_currency_payload(currency),
            result=AuditLog.Result.OK,
            metadata={"mes_only": True, **(metadata or {})},
        )
    except Exception:  # noqa: BLE001 - audit tidak boleh menggagalkan CRUD master
        logger.exception(
            "master.currency: gagal menulis audit (%s, Currency %s).", action, currency.pk
        )


def _record_and_audit(
    currency: Currency, request, *, metadata: dict | None = None,
    action: str = ACTION_UPDATE,
) -> int:
    """Tulis ledger ``SKIPPED`` + audit lalu kembalikan id ``SyncRecord``."""
    record_id = _record_mes_only(currency)
    _audit(action, currency, request, metadata)

    return record_id


# ---------------------------------------------------------------------------
# Validasi (POST/PUT)
# ---------------------------------------------------------------------------
def _parse_rate(value):
    """``(Decimal|None, error)`` untuk kurs ≥ 0 (kosong = ``None``, negatif 400)."""
    if value in (None, ""):
        return None, None
    if isinstance(value, bool):
        return None, "Field 'rate' harus berupa angka ≥ 0."

    try:
        rate = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None, "Field 'rate' harus berupa angka ≥ 0."

    if not rate.is_finite():
        return None, "Field 'rate' harus berupa angka ≥ 0."
    if rate < 0:
        return None, "Field 'rate' tidak boleh negatif."
    if rate > MAX_RATE:
        return None, f"Field 'rate' maksimal {MAX_RATE}."

    return rate.quantize(Decimal("0.000001")), None


def validate_currency_payload(data, instance: Currency | None = None):
    """Validasi body POST/PUT Currency → ``(values, error)``.

    Saat create (``instance=None``) ``code`` **wajib** berformat ISO ``^[A-Z]{3}$`` +
    ``name`` wajib; saat update semuanya opsional (hanya field yang dikirim diubah).
    ``code`` pada update hanya divalidasi **kalau nilainya benar-benar berubah** —
    sehingga baris hasil pull I1 ber-kode ``ODOO-<id>`` tetap bisa diedit (name/symbol)
    tanpa 400. ``is_default`` **tidak** di sini (diurus create/update + ``_apply_default``).

    Nilai yang dikembalikan memakai nama kolom model sehingga siap
    ``setattr``/``create``.
    """
    payload = data if isinstance(data, dict) else {}
    values: dict = {}

    if instance is None or "name" in payload:
        name = str(payload.get("name") or "").strip()
        if not name:
            return None, "Field 'name' wajib diisi."
        if len(name) > MAX_NAME_LENGTH:
            return None, f"Field 'name' maksimal {MAX_NAME_LENGTH} karakter."
        values["name"] = name

    if instance is None or "code" in payload:
        code = str(payload.get("code") or "").strip().upper()
        unchanged = instance is not None and code == instance.code

        if not code:
            return None, "Field 'code' wajib diisi (kode ISO 3 huruf, mis. IDR)."
        if not unchanged:
            if not CODE_PATTERN.match(code):
                return None, (
                    "Field 'code' harus 3 huruf A-Z (kode ISO, mis. IDR/USD)."
                )
            duplicates = Currency.objects.filter(code__iexact=code)
            if instance is not None:
                duplicates = duplicates.exclude(pk=instance.pk)
            if duplicates.exists():
                return None, f"Kode mata uang '{code}' sudah dipakai."

        if not unchanged:
            values["code"] = code

    if "symbol" in payload:
        symbol = str(payload.get("symbol") or "").strip()
        if len(symbol) > MAX_SYMBOL_LENGTH:
            return None, f"Field 'symbol' maksimal {MAX_SYMBOL_LENGTH} karakter."
        values["symbol"] = symbol

    if instance is None and "symbol" not in payload:
        values["symbol"] = ""

    if "rate" in payload:
        rate, error = _parse_rate(payload.get("rate"))
        if error:
            return None, error
        values["rate"] = rate

    if "active" in payload:
        active = parse_bool(payload.get("active"))
        if active is None:
            return None, "Field 'active' harus true|false."
        values["is_active"] = active

    return values, None


# ---------------------------------------------------------------------------
# Default MES (is_default bukan field Odoo → tanpa push, hanya audit)
# ---------------------------------------------------------------------------
def _apply_default(currency: Currency | None, request=None) -> None:
    """Jadikan ``currency`` satu-satunya mata uang default aktif (atomik).

    ``is_default`` **bukan** field Odoo (keputusan MES) sehingga operasi ini tidak
    meng-arm push; jejaknya tetap dicatat di ``AuditLog`` (pola ``_apply_default`` Tax).
    """
    if currency is None:
        return

    with transaction.atomic():
        Currency.objects.filter(is_default=True).exclude(pk=currency.pk).update(
            is_default=False
        )
        if not currency.is_default:
            currency.is_default = True
            currency.save(update_fields=("is_default",))

    _audit(ACTION_UPDATE, currency, request, {"is_default": True, "mes_only": True})


# ---------------------------------------------------------------------------
# CRUD (create / update) — MES-only: ledger SKIPPED, tanpa enqueue push
# ---------------------------------------------------------------------------
def create_currency(data, request=None) -> CurrencyWriteResult:
    """Buat Currency baru + ledger ``SKIPPED`` + audit (MES-only, tanpa push)."""
    values, error = validate_currency_payload(data)
    if error:
        return CurrencyWriteResult(error=error)

    payload = data if isinstance(data, dict) else {}
    want_default = parse_bool(payload.get("is_default"))

    currency = Currency.objects.create(**values)
    record_id = _record_and_audit(
        currency,
        request,
        metadata={"fields": sorted(values), "create": True},
        action=ACTION_CREATE,
    )
    if want_default:
        _apply_default(currency, request)

    logger.info(
        "master.currency: Currency %s (%s) dibuat (ledger=%s, MES-only).",
        currency.pk,
        currency.code,
        record_id,
    )
    return CurrencyWriteResult(currency=currency, sync_record_id=record_id)


def update_currency(currency: Currency, data, request=None) -> CurrencyWriteResult:
    """Ubah Currency (hanya field yang dikirim) + ledger ``SKIPPED`` + audit."""
    values, error = validate_currency_payload(data, instance=currency)
    if error:
        return CurrencyWriteResult(currency=currency, error=error)

    payload = data if isinstance(data, dict) else {}
    want_default = parse_bool(payload.get("is_default"))

    if not values and want_default is None:
        # Tidak ada perubahan -> tidak ada audit/ledger.
        return CurrencyWriteResult(currency=currency)

    if values:
        for field, value in values.items():
            setattr(currency, field, value)
        currency.save()

    if want_default is True:
        _apply_default(currency, request)

    if not values:
        # Hanya penanda default yang berubah -> sudah diaudit `_apply_default`.
        return CurrencyWriteResult(currency=currency)

    record_id = _record_and_audit(currency, request, metadata={"fields": sorted(values)})
    logger.info(
        "master.currency: Currency %s (%s) diubah (ledger=%s, MES-only).",
        currency.pk,
        currency.code,
        record_id,
    )
    return CurrencyWriteResult(currency=currency, sync_record_id=record_id)


def deactivate_currency(currency: Currency, request=None) -> CurrencyWriteResult:
    """Soft delete (``is_active=False``) + ledger ``SKIPPED`` + audit.

    **Guard pemakaian** (keputusan STEP 0) → 400, baris TIDAK dinonaktifkan:

      * ``is_default`` → jadikan mata uang lain default dulu;
      * ``code`` ∈ `PROTECTED_CURRENCY_CODES` (IDR/USD) → kode ISO terlindungi;
      * ``odoo_id is not None`` → baris hasil **pull I1** (sync harian akan
        mengaktifkannya kembali, jadi MES tidak boleh "menghapus"nya).

    Baris **tidak** dihapus dari DB (tanpa ``delete()``) — jejak audit & mirror I1
    tetap utuh (padanan ``deactivate_tax``/``deactivate_routing``).
    """
    code = str(currency.code or "").upper()

    if currency.is_default:
        return CurrencyWriteResult(
            currency=currency,
            error=(
                f"Mata uang '{code}' masih dipakai (default MES) — "
                "jadikan mata uang lain default dulu."
            ),
        )

    if code in PROTECTED_CURRENCY_CODES:
        return CurrencyWriteResult(
            currency=currency,
            error=(
                f"Mata uang '{code}' masih dipakai (protected ISO) — "
                "tidak dapat dinonaktifkan."
            ),
        )

    if currency.odoo_id is not None:
        return CurrencyWriteResult(
            currency=currency,
            error=(
                f"Mata uang '{code}' masih dipakai (baris hasil pull Odoo) — "
                "sync harian akan mengaktifkannya kembali."
            ),
        )

    if currency.is_active:
        currency.is_active = False
        currency.save(update_fields=("is_active",))

    record_id = _record_and_audit(
        currency, request, metadata={"soft_delete": True}, action=ACTION_DELETE
    )
    logger.info(
        "master.currency: Currency %s (%s) dinonaktifkan (ledger=%s, MES-only).",
        currency.pk,
        currency.code,
        record_id,
    )
    return CurrencyWriteResult(currency=currency, sync_record_id=record_id)


def set_default_currency(currency: Currency, request=None) -> CurrencyWriteResult:
    """Jadikan ``currency`` satu-satunya mata uang default (atomik) — tanpa push."""
    if not currency.is_active:
        return CurrencyWriteResult(
            currency=currency,
            error="Mata uang nonaktif tidak bisa dijadikan default. Aktifkan dulu.",
        )

    _apply_default(currency, request)
    logger.info(
        "master.currency: Currency %s (%s) dijadikan default MES.",
        currency.pk,
        currency.code,
    )

    return CurrencyWriteResult(currency=currency)


def get_default_currency() -> Currency | None:
    """Mata uang default MES untuk form/dokumen (``None`` kalau tidak ada satu pun).

    Urutan: (1) penanda ``is_default`` berlaku; (2) **fallback** kode ``IDR`` aktif;
    (3) mata uang aktif pertama (``ordering=("code",)``).
    """
    default = (
        Currency.objects.filter(is_default=True, is_active=True).order_by("pk").first()
    )
    if default is not None:
        return default

    fallback = (
        Currency.objects.filter(code__iexact="IDR", is_active=True).order_by("pk").first()
    )
    if fallback is not None:
        return fallback

    return Currency.objects.filter(is_active=True).order_by("pk").first()
