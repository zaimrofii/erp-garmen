"""Service **Company Profile** (H5.1) — **singleton** MES-only (ledger ``SKIPPED``).

Pola **sama** dengan `master/currency_services.py` (H5.2) & `master/tax_services.py`
(H3.6): satu operasi tulis = data + ``SyncRecord`` (``master.company`` /
``MASTER_PUSH``) + ``AuditLog`` (``master.create|update``). **Tanpa** ``task_id`` —
tidak ada push/pull task company.

Keputusan STEP 0 (H5.1) — **MES-only** + **greenfield** (``master.Company`` baru):

  * **tidak ada konsumen** MES yang memakai ``res.company`` Odoo (probe grep: nol
    referensi ``res.company``; ``company_id`` hanya muncul sebagai catatan "Odoo yang
    mengisinya" di payment/journal/warehouse/PO) dan **tidak ada transport** company
    (``odoo_transport`` tanpa ``fetch_company``);
  * ``res.company`` = **konfigurasi akuntansi Odoo** (legal name, NPWP, logo dipakai
    dokumen pajak) ⇒ mengubahnya diam-diam dari MES = risiko tanpa manfaat;
  * jadi identitas perusahaan disimpan **lokal di MES** dan dicatat ``SKIPPED``
    (preseden H5.2/Sprint C). Jejaknya di ``/api/v1/sync/records/?status=SKIPPED``.

**Singleton** (1 baris per instalasi):

  * :func:`get_company` — baris pertama atau ``None`` (dipakai GET → ``{"company": null}``
    **tanpa** efek samping / tanpa seed);
  * :func:`get_or_create_company` — baris **pasti ada** (buat default minimal bila
    kosong); untuk konsumen yang butuh identitas perusahaan (mis. header cetak) —
    **bukan** dipakai view GET supaya GET tidak membuat baris;
  * :func:`update_company` — **create-on-first-PUT** (tanpa POST terpisah): baris
    pertama di-update, dibuat **sekali** bila belum ada ⇒ 2× PUT tetap 1 baris.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator, validate_email

from core.audit.models import AuditLog
from core.audit.services import AuditLogger
from integrations.erp_sync.idempotency import SyncIdempotency
from integrations.erp_sync.models import SyncResource, SyncStage, SyncStatus

from .currency_services import currency_row
from .models import Company, Currency
from .partner_services import MAX_NPWP_LENGTH, NPWP_LENGTHS, normalize_npwp
from .services import ACTION_CREATE, ACTION_UPDATE, parse_bool

logger = logging.getLogger(__name__)

__all__ = (
    "COMPANY_RESOURCE",
    "DEFAULT_COMPANY_NAME",
    "DEFAULT_TIMEZONE",
    "CompanyWriteResult",
    "MAX_ADDRESS_LENGTH",
    "MAX_CITY_LENGTH",
    "MAX_COUNTRY_LENGTH",
    "MAX_EMAIL_LENGTH",
    "MAX_LEGAL_NAME_LENGTH",
    "MAX_LOGO_URL_LENGTH",
    "MAX_NAME_LENGTH",
    "MAX_PHONE_LENGTH",
    "MAX_TIMEZONE_LENGTH",
    "MAX_WEBSITE_LENGTH",
    "MES_ONLY_REASON",
    "company_row",
    "get_company",
    "get_or_create_company",
    "update_company",
    "validate_company_payload",
)

#: Kunci sync Company (jangan diganti string literal di view).
COMPANY_RESOURCE = SyncResource.MASTER_COMPANY.value
STAGE = SyncStage.MASTER_PUSH.value

#: Alasan baku status ``SKIPPED`` (disimpan di ``SyncRecord.last_error``).
MES_ONLY_REASON = (
    "MES-only: profil perusahaan tidak dikirim ke Odoo — tidak ada konsumen MES yang "
    "memakai `res.company`, tidak ada transport company, dan `res.company` = "
    "konfigurasi akuntansi/legal Odoo (dokumen pajak) yang tidak boleh diubah diam-diam."
)

#: Batas panjang teks (selaras kolom model → beda dari DB = 400, bukan 500).
MAX_NAME_LENGTH = 255
MAX_LEGAL_NAME_LENGTH = 255
MAX_ADDRESS_LENGTH = 2000
MAX_CITY_LENGTH = 64
MAX_COUNTRY_LENGTH = 2
MAX_PHONE_LENGTH = 32
MAX_EMAIL_LENGTH = 254
MAX_WEBSITE_LENGTH = 200
MAX_LOGO_URL_LENGTH = 500
MAX_TIMEZONE_LENGTH = 64

#: Nilai default (dipakai `get_or_create_company` & timezone saat create).
DEFAULT_COMPANY_NAME = "MES"
DEFAULT_TIMEZONE = "Asia/Jakarta"

#: Kode negara ISO 3166-1 alpha-2 (2 huruf, auto-upper).
COUNTRY_PATTERN = re.compile(r"^[A-Z]{2}$")

#: Validator URL Django (skema http/https).
_url_validator = URLValidator()


@dataclass
class CompanyWriteResult:
    """Hasil satu operasi tulis Company (dipakai view).

    **Tanpa** ``task_id``/``queued``: H5.1 MES-only → tidak ada task push.
    """

    company: Company | None = None
    error: str | None = None
    sync_record_id: int | None = None

    @property
    def sync_status(self) -> str | None:
        """Status ledger yang ditulis (``SKIPPED``) — ``None`` kalau tak ada tulis."""
        return SyncStatus.SKIPPED.value if self.sync_record_id else None


def _iso(value) -> str | None:
    """ISO-8601 atau ``None`` (datetime kosong)."""
    return value.isoformat() if value else None


def company_row(company: Company) -> dict:
    """Baris Company untuk API — seluruhnya JSON-safe.

    ``currency`` = baris mata uang (bentuk `currency_services.currency_row`, H5.2) atau
    ``None`` — dipakai UI untuk menampilkan kode/simbol tanpa request tambahan.
    """
    return {
        "id": company.pk,
        "name": company.name,
        "legal_name": company.legal_name,
        "address": company.address,
        "city": company.city,
        "country": company.country,
        "phone": company.phone,
        "email": company.email,
        "npwp": company.npwp,
        "website": company.website,
        "logo_url": company.logo_url,
        "currency_id": company.currency_id,
        "currency": currency_row(company.currency) if company.currency_id else None,
        "timezone": company.timezone,
        "is_active": bool(company.is_active),
        "created_at": _iso(company.created_at),
        "updated_at": _iso(company.updated_at),
    }


def _company_payload(company: Company) -> dict:
    """Payload yang disimpan di ``SyncRecord.payload`` (jejak audit MES-only)."""
    row = company_row(company)
    row.pop("currency", None)

    return {**row, "active": row.pop("is_active")}


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
def get_company() -> Company | None:
    """Baris company (baris pertama, ``ordering=("pk",)``) atau ``None``.

    **Tanpa efek samping** — dipakai GET supaya ``{"company": null}`` tidak membuat baris.
    """
    return Company.objects.order_by("pk").first()


def get_or_create_company() -> tuple[Company, bool]:
    """``(company, created)`` — baris **pasti ada** (buat default minimal bila kosong).

    Dipakai konsumen yang butuh identitas perusahaan tanpa payload (mis. header cetak).
    View GET **tidak** memakainya (GET tidak boleh membuat baris — keputusan STEP 0).
    """
    company = get_company()
    if company is not None:
        return company, False

    return (
        Company.objects.create(name=DEFAULT_COMPANY_NAME, timezone=DEFAULT_TIMEZONE),
        True,
    )


# ---------------------------------------------------------------------------
# Ledger (SKIPPED) + audit — pola H5.2 / Sprint C
# ---------------------------------------------------------------------------
def _record_mes_only(company: Company) -> int:
    """Tulis/segarkan ``SyncRecord`` company lalu tandai ``SKIPPED``."""
    payload = _company_payload(company)
    sync = SyncIdempotency()
    record = sync.get_or_create_sync_record(COMPANY_RESOURCE, company.pk, STAGE, payload)

    if dict(record.payload or {}) != payload:
        record.payload = payload
        record.save(update_fields=("payload", "updated_at"))

    sync.mark_skipped(record, MES_ONLY_REASON)

    return record.pk


def _audit(action: str, company: Company, request, metadata: dict | None = None) -> None:
    """Tulis ``AuditLog`` — best-effort (audit tidak boleh menggagalkan CRUD)."""
    try:
        AuditLogger().log(
            user=None,
            action=action,
            resource=COMPANY_RESOURCE,
            resource_id=company.pk,
            request=request,
            payload=_company_payload(company),
            result=AuditLog.Result.OK,
            metadata={"mes_only": True, **(metadata or {})},
        )
    except Exception:  # noqa: BLE001 - audit tidak boleh menggagalkan CRUD
        logger.exception(
            "master.company: gagal menulis audit (%s, Company %s).", action, company.pk
        )


def _record_and_audit(
    company: Company,
    request,
    *,
    metadata: dict | None = None,
    action: str = ACTION_UPDATE,
) -> int:
    """Tulis ledger ``SKIPPED`` + audit lalu kembalikan id ``SyncRecord``."""
    record_id = _record_mes_only(company)
    _audit(action, company, request, metadata)

    return record_id


# ---------------------------------------------------------------------------
# Validasi (PUT — create-on-first-PUT)
# ---------------------------------------------------------------------------
def _text(value, label: str, max_length: int):
    """``(str, error)`` untuk teks opsional dengan batas panjang (di-trim)."""
    text = "" if value is None else str(value).strip()
    if len(text) > max_length:
        return "", f"Field '{label}' maksimal {max_length} karakter."

    return text, None


def _optional_url(value, label: str, max_length: int):
    """``(str, error)`` untuk URL opsional (kosong = ""), skema http/https."""
    text, error = _text(value, label, max_length)
    if error:
        return "", error
    if text:
        try:
            _url_validator(text)
        except ValidationError:
            return "", f"Field '{label}' bukan URL valid: {text!r}."

    return text, None


def validate_company_payload(data, instance: Company | None = None):
    """Validasi body PUT Company → ``(values, error)``.

    **Create-on-first-PUT**: saat ``instance is None`` (belum ada baris) ``name``
    **wajib**; saat baris sudah ada semua field opsional (hanya yang dikirim diubah).
    ``npwp`` dinormalisasi ke digit & wajib 15/16 digit bila diisi (reuse H1.6);
    ``country`` = ISO 2 huruf (auto-upper); ``currency_id`` harus menunjuk mata uang
    yang ada (H5.2, ``null``/``""`` = kosongkan).

    Nilai yang dikembalikan memakai nama kolom model sehingga siap
    ``setattr``/``create``.
    """
    payload = data if isinstance(data, dict) else {}
    values: dict = {}

    if instance is None or "name" in payload:
        name, error = _text(payload.get("name"), "name", MAX_NAME_LENGTH)
        if error:
            return None, error
        if not name:
            return None, "Field 'name' wajib diisi."
        values["name"] = name

    if "legal_name" in payload:
        legal_name, error = _text(
            payload.get("legal_name"), "legal_name", MAX_LEGAL_NAME_LENGTH
        )
        if error:
            return None, error
        values["legal_name"] = legal_name

    if "address" in payload:
        address, error = _text(payload.get("address"), "address", MAX_ADDRESS_LENGTH)
        if error:
            return None, error
        values["address"] = address

    if "city" in payload:
        city, error = _text(payload.get("city"), "city", MAX_CITY_LENGTH)
        if error:
            return None, error
        values["city"] = city

    if "country" in payload:
        country = str(payload.get("country") or "").strip().upper()
        if country and not COUNTRY_PATTERN.match(country):
            return None, (
                "Field 'country' harus 2 huruf kode ISO 3166-1 alpha-2 (mis. ID)."
            )
        values["country"] = country

    if "phone" in payload:
        phone, error = _text(payload.get("phone"), "phone", MAX_PHONE_LENGTH)
        if error:
            return None, error
        values["phone"] = phone

    if "email" in payload:
        email, error = _text(payload.get("email"), "email", MAX_EMAIL_LENGTH)
        if error:
            return None, error
        if email:
            try:
                validate_email(email)
            except ValidationError:
                return None, f"Field 'email' tidak valid: {email!r}."
        values["email"] = email

    if "npwp" in payload:
        npwp, error = _text(payload.get("npwp"), "npwp", MAX_NPWP_LENGTH)
        if error:
            return None, error
        digits = normalize_npwp(npwp)
        if digits and len(digits) not in NPWP_LENGTHS:
            return None, (
                f"Field 'npwp' harus 15 atau 16 digit (diterima: {len(digits)} digit "
                f"dari {npwp!r})."
            )
        values["npwp"] = digits

    if "website" in payload:
        website, error = _optional_url(payload.get("website"), "website", MAX_WEBSITE_LENGTH)
        if error:
            return None, error
        values["website"] = website

    if "logo_url" in payload:
        logo_url, error = _optional_url(
            payload.get("logo_url"), "logo_url", MAX_LOGO_URL_LENGTH
        )
        if error:
            return None, error
        values["logo_url"] = logo_url

    if "currency_id" in payload:
        raw_currency = payload.get("currency_id")
        if raw_currency in (None, ""):
            values["currency"] = None
        else:
            if isinstance(raw_currency, bool):
                return None, "Field 'currency_id' harus berupa id mata uang (angka)."
            try:
                currency_id = int(raw_currency)
            except (TypeError, ValueError):
                return None, "Field 'currency_id' harus berupa id mata uang (angka)."
            currency = Currency.objects.filter(pk=currency_id).first()
            if currency is None:
                return None, f"Mata uang {currency_id} tidak ditemukan."
            values["currency"] = currency

    if "timezone" in payload:
        timezone, error = _text(payload.get("timezone"), "timezone", MAX_TIMEZONE_LENGTH)
        if error:
            return None, error
        values["timezone"] = timezone or DEFAULT_TIMEZONE

    if "active" in payload:
        active = parse_bool(payload.get("active"))
        if active is None:
            return None, "Field 'active' harus true|false."
        values["is_active"] = active

    return values, None


def update_company(data, request=None) -> CompanyWriteResult:
    """PUT profil perusahaan — **create-on-first-PUT** + ledger ``SKIPPED`` + audit.

    Baris pertama di-update; kalau belum ada baris sama sekali, baris **dibuat**
    (``name`` wajib dari ``validate_company_payload``) ⇒ 2× PUT tetap **1 baris**
    (singleton). PUT tanpa perubahan apa pun → 200 tanpa ledger/audit baru.
    """
    company = get_company()
    values, error = validate_company_payload(data, instance=company)
    if error:
        return CompanyWriteResult(company=company, error=error)

    created = company is None
    if created:
        values.setdefault("timezone", DEFAULT_TIMEZONE)
        company = Company.objects.create(**values)
    elif values:
        for field, value in values.items():
            setattr(company, field, value)
        company.save()
    else:
        # Tidak ada perubahan -> tidak ada audit/ledger.
        return CompanyWriteResult(company=company)

    record_id = _record_and_audit(
        company,
        request,
        metadata={"fields": sorted(values), "create": created},
        action=ACTION_CREATE if created else ACTION_UPDATE,
    )

    logger.info(
        "master.company: profil %s (%s) %s (ledger=%s, MES-only).",
        company.pk,
        company.name,
        "dibuat" if created else "diubah",
        record_id,
    )
    return CompanyWriteResult(company=company, sync_record_id=record_id)
