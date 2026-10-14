"""Service CRUD master Partner (H1.6) — MES = source of truth master.

Pola **sama** dengan ``master/services.py`` (H1.1), ``master/location_services.py``
(H1.4), dan ``master/bom_services.py`` (H1.5): satu operasi tulis = data +
``SyncRecord`` (``master.partner`` / ``MASTER_PUSH``, kunci idempotensi ``odoo_id``)
+ ``AuditLog`` (``master.create|update|delete``) + enqueue task Celery
``erp_sync.push_master_partner``. Odoo **tidak** dipanggil di sini (async).

Kekhususan H1.6 (customer + supplier dalam satu model):

  * ``is_customer`` (default True) & ``is_vendor`` (default False) — penanda peran;
    **tidak boleh keduanya False** (partner tanpa peran tidak berguna → 400);
  * ``npwp`` = NPWP Indonesia (Odoo ``vat``): disimpan **ternormalisasi digit**
    dan wajib **15 atau 16 digit** bila diisi (validasi service, bukan DB CHECK);
  * ``address`` (TextField) ↔ Odoo ``street`` (+ ``street2`` saat tarik);
  * ``is_company`` di Odoo field mandiri (perusahaan bisa tanpa NPWP — bukti data
    dev) sehingga disimpan apa adanya, bukan di-derive dari NPWP;
  * ``customer_rank``/``supplier_rank`` = hitungan transaksi Odoo (hasil tarikan);
    saat push **create** LazyMES mengirim 1/0 sebagai penanda peran, sedangkan
    update **tidak** mengirim rank (agar hitungan Odoo tidak turun);
  * DELETE = soft delete **tanpa** guard: ``garment.Order.customer`` memakai
    ``on_delete=PROTECT``, jadi menonaktifkan partner tetap aman — dan semua
    konsumen boleh tetap menampilkan partner nonaktif (jejak order lama).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from config.middleware import get_request_id
from core.audit.models import AuditLog
from core.audit.services import AuditLogger
from integrations.erp_sync.idempotency import SyncIdempotency
from integrations.erp_sync.models import SyncRecord, SyncResource, SyncStage, SyncStatus
from integrations.erp_sync.tasks_master_push import partner_payload, push_master_partner

from .models import Partner
from .services import ACTION_CREATE, ACTION_DELETE, ACTION_UPDATE, parse_bool

logger = logging.getLogger(__name__)

__all__ = (
    "PartnerWriteResult",
    "create_partner",
    "deactivate_partner",
    "generate_partner_code",
    "normalize_npwp",
    "partner_detail_row",
    "partner_row",
    "update_partner",
    "validate_partner_payload",
)

#: Kunci sync Partner (jangan diganti string literal di view).
PARTNER_RESOURCE = SyncResource.MASTER_PARTNER.value
STAGE = SyncStage.MASTER_PUSH.value

#: Batas panjang teks (selaras kolom model — beda dari DB = 400, bukan 500).
MAX_CODE_LENGTH = 64
MAX_NAME_LENGTH = 255
MAX_PHONE_LENGTH = 32
MAX_CITY_LENGTH = 64
MAX_ADDRESS_LENGTH = 2000
MAX_NPWP_LENGTH = 32

#: Panjang NPWP yang diterima (digit setelah normalisasi).
NPWP_LENGTHS = (15, 16)

#: Karakter non-digit pada NPWP (titik, strip, spasi) — dibuang saat normalisasi.
_NON_DIGIT = re.compile(r"\D")

#: Karakter non-alfanumerik pada slug kode partner (spasi/tanda baca → "-").
_NON_DIGIT_SLUG = re.compile(r"[^A-Z0-9]+")


def _iso(value) -> str | None:
    """ISO-8601 atau ``None`` (datetime kosong)."""
    return value.isoformat() if value else None


def normalize_npwp(value) -> str:
    """NPWP → digit saja (``01.234.567.8-901.000`` → ``012345678901000``)."""
    return _NON_DIGIT.sub("", str(value or ""))


def partner_row(partner: Partner) -> dict:
    """Baris partner untuk API (list & detail) — seluruhnya JSON-safe.

    ``active`` adalah nama publik dari ``Partner.is_active`` (konsisten H1.1–H1.5)
    dan ``odoo_id`` selalu ada (``null`` = belum pernah terkirim ke Odoo).
    """
    return {
        "id": partner.pk,
        "code": partner.code,
        "name": partner.name,
        "email": partner.email,
        "phone": partner.phone,
        "city": partner.city,
        "address": partner.address,
        "npwp": partner.npwp,
        "is_customer": bool(partner.is_customer),
        "is_vendor": bool(partner.is_vendor),
        "is_company": bool(partner.is_company),
        "customer_rank": partner.customer_rank,
        "supplier_rank": partner.supplier_rank,
        "active": bool(partner.is_active),
        "odoo_id": partner.odoo_id,
        "created_at": _iso(partner.created_at),
        "updated_at": _iso(partner.updated_at),
    }


def partner_detail_row(partner: Partner) -> dict:
    """Baris detail partner = ``partner_row`` + ``orders_count`` (jejak pemakaian).

    ``orders_count`` = jumlah ``garment.Order`` yang memakai partner ini sebagai
    customer (``Order.customer`` → ``related_name="orders"``). Dipakai UI untuk
    memberi tahu operator sebelum menonaktifkan partner.
    """
    row = partner_row(partner)
    row["orders_count"] = partner.orders.count()

    return row


# ---------------------------------------------------------------------------
# Validasi (PURE — dipakai view & test tanpa HTTP)
# ---------------------------------------------------------------------------
def _text(value, label: str, max_length: int):
    """``(str, error)`` untuk teks opsional dengan batas panjang (di-trim)."""
    text = "" if value is None else str(value).strip()
    if len(text) > max_length:
        return "", f"Field '{label}' maksimal {max_length} karakter."

    return text, None


def generate_partner_code(name: str) -> str:
    """Kode partner unik dari nama: ``PTR-<SLUG-Nama>`` + suffix ``-2``, ``-3``, …

    ``Partner.code`` unik **dan** wajib, sedangkan ``res.partner`` tidak punya kode
    natural (``ref`` hampir selalu kosong) — jadi kode dibangkitkan deterministik
    dari nama, sama seperti pola ``generate_bom_code`` (H1.5).
    """
    slug = _NON_DIGIT_SLUG.sub("-", str(name or "").strip().upper()).strip("-")
    base = f"PTR-{slug}"[:MAX_CODE_LENGTH].rstrip("-") if slug else "PTR"

    candidate = base
    suffix = 2
    while Partner.objects.filter(code__iexact=candidate).exists():
        tail = f"-{suffix}"
        candidate = f"{base[: MAX_CODE_LENGTH - len(tail)]}{tail}"
        suffix += 1

    return candidate


def validate_partner_payload(data, instance: Partner | None = None):
    """Validasi body POST/PUT Partner → ``(values, error)``.

    Saat create (``instance=None``) ``name`` wajib & ``code`` dibangkitkan otomatis
    bila kosong; saat update keduanya opsional (hanya field yang dikirim yang
    diubah). Guard peran: ``is_customer`` & ``is_vendor`` **tidak boleh keduanya
    False**. ``npwp`` dinormalisasi ke digit dan wajib 15/16 digit bila diisi.
    """
    payload = data if isinstance(data, dict) else {}
    values: dict = {}

    # --- peran (customer/vendor) — dicek bersama, termasuk nilai lama saat update
    customer = instance.is_customer if instance is not None else True
    vendor = instance.is_vendor if instance is not None else False
    if instance is None or "is_customer" in payload:
        parsed = parse_bool(payload.get("is_customer", True))
        if parsed is None:
            return None, "Field 'is_customer' harus true|false."
        customer = parsed
    if instance is None or "is_vendor" in payload:
        parsed = parse_bool(payload.get("is_vendor", False))
        if parsed is None:
            return None, "Field 'is_vendor' harus true|false."
        vendor = parsed

    if not customer and not vendor:
        return None, (
            "Partner harus minimal salah satu: pelanggan (is_customer) atau "
            "supplier (is_vendor)."
        )

    if instance is None or "is_customer" in payload:
        values["is_customer"] = customer
    if instance is None or "is_vendor" in payload:
        values["is_vendor"] = vendor

    if instance is None or "name" in payload:
        name = str(payload.get("name") or "").strip()
        if not name:
            return None, "Field 'name' wajib diisi."
        if len(name) > MAX_NAME_LENGTH:
            return None, f"Field 'name' maksimal {MAX_NAME_LENGTH} karakter."
        values["name"] = name

    if instance is None or "code" in payload:
        code, error = _text(payload.get("code"), "code", MAX_CODE_LENGTH)
        if error:
            return None, error
        if code:
            duplicates = Partner.objects.filter(code__iexact=code)
            if instance is not None:
                duplicates = duplicates.exclude(pk=instance.pk)
            if duplicates.exists():
                return None, f"Kode partner '{code}' sudah dipakai partner lain."
            values["code"] = code
        elif instance is None:
            values["code"] = generate_partner_code(values.get("name", ""))

    if instance is None or "is_company" in payload:
        company = parse_bool(payload.get("is_company", True))
        if company is None:
            return None, "Field 'is_company' harus true|false."
        values["is_company"] = company

    if "email" in payload:
        email, error = _text(payload.get("email"), "email", 254)
        if error:
            return None, error
        if email:
            try:
                validate_email(email)
            except ValidationError:
                return None, f"Field 'email' tidak valid: {email!r}."
        values["email"] = email

    if "phone" in payload:
        phone, error = _text(payload.get("phone"), "phone", MAX_PHONE_LENGTH)
        if error:
            return None, error
        values["phone"] = phone

    if "city" in payload:
        city, error = _text(payload.get("city"), "city", MAX_CITY_LENGTH)
        if error:
            return None, error
        values["city"] = city

    if "address" in payload:
        address, error = _text(payload.get("address"), "address", MAX_ADDRESS_LENGTH)
        if error:
            return None, error
        values["address"] = address

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

    if "active" in payload:
        active = parse_bool(payload.get("active"))
        if active is None:
            return None, "Field 'active' harus true|false."
        values["is_active"] = active

    return values, None


# ---------------------------------------------------------------------------
# Tulis (create / update / soft delete) — data + idempotensi + audit
# ---------------------------------------------------------------------------
@dataclass
class PartnerWriteResult:
    """Hasil satu operasi tulis master Partner (dipakai view)."""

    partner: Partner | None = None
    error: str | None = None
    sync_record_id: int | None = None
    task_id: str | None = None

    @property
    def queued(self) -> bool:
        """True kalau task push master berhasil di-enqueue (broker hidup)."""
        return self.task_id is not None


def _arm_push(partner: Partner, payload: dict) -> SyncRecord:
    """Siapkan ``SyncRecord`` MASTER_PUSH partner ini (PENDING + payload terbaru).

    ``unique(resource, resource_id, stage)`` hanya mengizinkan satu baris per
    partner, jadi perubahan berikutnya meng-*update* baris yang sama (pola H1.1–H1.5).
    """
    sync = SyncIdempotency()
    record = sync.get_or_create_sync_record(PARTNER_RESOURCE, partner.pk, STAGE, payload)

    if (
        dict(record.payload or {}) != payload
        or record.status != SyncStatus.PENDING
        or record.last_error
    ):
        record.payload = payload
        record.status = SyncStatus.PENDING
        record.last_error = ""
        record.save(update_fields=("payload", "status", "last_error", "updated_at"))
        logger.info("master.partner: SyncRecord %s di-arm ulang (PENDING).", record.pk)

    return record


def _audit(
    action: str, partner: Partner, payload: dict, request, metadata: dict | None = None
) -> None:
    """Tulis ``AuditLog`` — best-effort (pola ``integrations/erp_sync/audit.py``)."""
    try:
        AuditLogger().log(
            user=None,
            action=action,
            resource=PARTNER_RESOURCE,
            resource_id=partner.pk,
            request=request,
            payload=payload,
            result=AuditLog.Result.OK,
            metadata=metadata or {},
        )
    except Exception:  # noqa: BLE001 - audit tidak boleh menggagalkan CRUD master
        logger.exception(
            "master.partner: gagal menulis audit (%s, partner %s).", action, partner.pk
        )


def _enqueue(partner: Partner, record: SyncRecord) -> str | None:
    """Enqueue task push master; broker mati -> ``None`` (record tetap PENDING)."""
    try:
        async_result = push_master_partner.apply_async(
            args=[partner.pk, record.pk],
            headers={"x-request-id": get_request_id() or ""},
        )
        return str(async_result.id)
    except Exception:  # noqa: BLE001 - CRUD master tidak boleh gagal karena broker
        logger.exception(
            "master.partner: gagal enqueue push partner %s (SyncRecord %s tetap PENDING).",
            partner.pk,
            record.pk,
        )
        return None


def create_partner(data, request=None) -> PartnerWriteResult:
    """Buat partner + ``SyncRecord`` + ``AuditLog`` + enqueue push ke Odoo."""
    values, error = validate_partner_payload(data)
    if error:
        return PartnerWriteResult(error=error)

    partner = Partner.objects.create(**values)
    payload = partner_payload(partner)
    record = _arm_push(partner, payload)
    _audit(
        ACTION_CREATE,
        partner,
        payload,
        request,
        {
            "odoo_id": partner.odoo_id,
            "is_customer": partner.is_customer,
            "is_vendor": partner.is_vendor,
        },
    )
    task_id = _enqueue(partner, record)

    logger.info(
        "master.partner: partner %s (%s) dibuat (sync=%s).",
        partner.pk,
        partner.code,
        record.pk,
    )
    return PartnerWriteResult(partner=partner, sync_record_id=record.pk, task_id=task_id)


def update_partner(partner: Partner, data, request=None) -> PartnerWriteResult:
    """Ubah partner (hanya field yang dikirim) + ``SyncRecord`` + ``AuditLog``."""
    values, error = validate_partner_payload(data, instance=partner)
    if error:
        return PartnerWriteResult(partner=partner, error=error)

    if not values:
        # Tidak ada perubahan -> tidak ada audit/push.
        return PartnerWriteResult(partner=partner)

    for field, value in values.items():
        setattr(partner, field, value)
    partner.save()

    payload = partner_payload(partner)
    record = _arm_push(partner, payload)
    _audit(
        ACTION_UPDATE,
        partner,
        payload,
        request,
        {"odoo_id": partner.odoo_id, "fields": sorted(values)},
    )
    task_id = _enqueue(partner, record)

    logger.info(
        "master.partner: partner %s (%s) diubah (sync=%s).",
        partner.pk,
        partner.code,
        record.pk,
    )
    return PartnerWriteResult(partner=partner, sync_record_id=record.pk, task_id=task_id)


def deactivate_partner(partner: Partner, request=None) -> PartnerWriteResult:
    """Soft delete (``is_active=False``) + ``SyncRecord`` + ``AuditLog`` + enqueue.

    **Tanpa** guard dependensi (keputusan H1.6): ``garment.Order.customer`` memakai
    ``on_delete=PROTECT`` sehingga partner yang dipakai order **tidak boleh dihapus
    keras** — namun kita memang tidak pernah ``delete()``, hanya menonaktifkan, jadi
    order lama tetap utuh dan ``orders_count`` (di detail) memberitahu operator.
    """
    if partner.is_active:
        partner.is_active = False
        partner.save(update_fields=("is_active",))

    payload = partner_payload(partner)
    record = _arm_push(partner, payload)
    _audit(
        ACTION_DELETE,
        partner,
        payload,
        request,
        {"soft_delete": True, "odoo_id": partner.odoo_id},
    )
    task_id = _enqueue(partner, record)

    logger.info(
        "master.partner: partner %s (%s) dinonaktifkan (sync=%s).",
        partner.pk,
        partner.code,
        record.pk,
    )
    return PartnerWriteResult(partner=partner, sync_record_id=record.pk, task_id=task_id)

