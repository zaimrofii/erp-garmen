"""Service CRUD master Tax (H3.6) — MES = source of truth master.

Pola **sama** dengan ``master/uom_services.py`` (H1.2): satu operasi tulis = data +
``SyncRecord`` (``master.tax`` / ``MASTER_PUSH``, kunci idempotensi ``odoo_id``) +
``AuditLog`` (``master.create|update|delete``) + enqueue task Celery
``erp_sync.push_master_tax``. Odoo **tidak** dipanggil di sini (async).

Perbedaan yang disengaja dari UoM:

  * penulis dibatasi **ADMIN/OWNER** (brief H3.6: Tax = master config keuangan,
    konsisten H1.1 Product) — ``purchasing`` hanya membaca (dropdown form SO/PO);
  * ``amount`` **0 diizinkan** (PPN 0% / bebas pajak) tetapi **negatif = 400**
    (pola guard harga H3.5);
  * ``code`` boleh dikosongkan → dibuat otomatis dari ``name`` (kolom ``code``
    ``unique=True`` sehingga baris kedua ber-``code`` kosong akan gagal di DB);
  * ``is_default`` = **keputusan MES** (tidak pernah ditarik dari Odoo) dan dijaga
    tetap tunggal oleh :func:`set_default_tax`;
  * ``tax_group_id`` tidak dikirim ke Odoo — Odoo mengisinya lewat
    ``_compute_tax_group_id`` (probe STEP 0 + sumber ``account/models/account_tax.py``).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.db import transaction

from config.middleware import get_request_id
from core.audit.models import AuditLog
from core.audit.services import AuditLogger
from integrations.erp_sync.idempotency import SyncIdempotency
from integrations.erp_sync.models import SyncRecord, SyncResource, SyncStage, SyncStatus
from integrations.erp_sync.tasks_master_push import push_master_tax, tax_payload

from .models import Tax
from .services import ACTION_CREATE, ACTION_DELETE, ACTION_UPDATE, parse_bool

logger = logging.getLogger(__name__)

__all__ = (
    "TaxWriteResult",
    "create_tax",
    "deactivate_tax",
    "get_default_tax",
    "set_default_tax",
    "tax_row",
    "update_tax",
    "validate_tax_payload",
)

#: Kunci sync Tax (jangan diganti string literal di view).
TAX_RESOURCE = SyncResource.MASTER_TAX.value
STAGE = SyncStage.MASTER_PUSH.value

#: Batas panjang teks (selaras kolom model — beda dari DB = 400, bukan 500).
MAX_CODE_LENGTH = 64
MAX_NAME_LENGTH = 255

#: Tarif maksimum yang masih masuk akal untuk ``DecimalField(max_digits=5, decimal_places=2)``.
MAX_AMOUNT = Decimal("999.99")


def tax_row(tax: Tax) -> dict:
    """Baris Tax untuk API (list & detail) — seluruhnya JSON-safe.

    ``odoo_id`` **wajib** ada di response (kunci sync; ``null`` = belum terkirim ke
    Odoo) dan ``active`` = nama publik dari ``Tax.is_active`` (konsisten H1.1/H1.2).
    """
    return {
        "id": tax.pk,
        "code": tax.code,
        "name": tax.name,
        "amount": float(tax.amount or 0),
        "amount_type": tax.amount_type,
        "type_tax_use": tax.type_tax_use,
        "price_include": bool(tax.price_include),
        "is_default": bool(tax.is_default),
        "active": bool(tax.is_active),
        "odoo_id": tax.odoo_id,
    }


def _generate_code(name: str) -> str:
    """Kode deterministik dari ``name`` (``code`` ``unique=True`` → tidak boleh kosong).

    ``"PPN 11%"`` → ``"PPN-11"``; kalau sudah dipakai ditambah akhiran ``-2``, ``-3``, …
    """
    slug = re.sub(r"[^A-Za-z0-9]+", "-", str(name or "").strip()).strip("-").upper()
    base = (slug or "TAX")[:MAX_CODE_LENGTH]

    code = base
    counter = 1
    while Tax.objects.filter(code__iexact=code).exists():
        counter += 1
        suffix = f"-{counter}"
        code = f"{base[: MAX_CODE_LENGTH - len(suffix)]}{suffix}"

    return code



def _parse_amount(value):
    """``(Decimal|None, error)`` untuk tarif pajak ≥ 0 (0 diizinkan, negatif 400)."""
    if value in (None, ""):
        return None, None
    if isinstance(value, bool):
        return None, "Field 'amount' harus berupa angka ≥ 0."

    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None, "Field 'amount' harus berupa angka ≥ 0."

    if not amount.is_finite():
        return None, "Field 'amount' harus berupa angka ≥ 0."
    if amount < 0:
        return None, "Field 'amount' tidak boleh negatif."
    if amount > MAX_AMOUNT:
        return None, f"Field 'amount' maksimal {MAX_AMOUNT}."

    return amount.quantize(Decimal("0.01")), None


def validate_tax_payload(data, instance: Tax | None = None):
    """Validasi body POST/PUT Tax -> ``(values, error)``.

    Saat create (``instance=None``) ``name`` wajib; saat update semuanya opsional
    (hanya field yang dikirim yang diubah). ``code`` boleh dikosongkan saat create
    (dibuat otomatis dari ``name``). Nilai yang dikembalikan memakai nama kolom
    model sehingga siap ``setattr``/``create``.
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
        code = str(payload.get("code") or "").strip()
        if len(code) > MAX_CODE_LENGTH:
            return None, f"Field 'code' maksimal {MAX_CODE_LENGTH} karakter."
        if code:
            duplicates = Tax.objects.filter(code__iexact=code)
            if instance is not None:
                duplicates = duplicates.exclude(pk=instance.pk)
            if duplicates.exists():
                return None, f"Kode Tax '{code}' sudah dipakai pajak lain."
        elif instance is None:
            code = _generate_code(values.get("name") or payload.get("name") or "")
        values["code"] = code

    if instance is None or "amount" in payload:
        amount, error = _parse_amount(payload.get("amount", 0))
        if error:
            return None, error
        values["amount"] = amount if amount is not None else Decimal("0.00")

    if "amount_type" in payload:
        amount_type = str(payload.get("amount_type") or "").strip().lower()
        if amount_type not in Tax.AmountType.values:
            return None, (
                f"Field 'amount_type' harus salah satu dari {', '.join(Tax.AmountType.values)}."
            )
        values["amount_type"] = amount_type

    if "type_tax_use" in payload:
        type_tax_use = str(payload.get("type_tax_use") or "").strip().lower()
        if type_tax_use not in Tax.TaxUse.values:
            return None, (
                f"Field 'type_tax_use' harus salah satu dari {', '.join(Tax.TaxUse.values)}."
            )
        values["type_tax_use"] = type_tax_use

    if "price_include" in payload:
        price_include = parse_bool(payload.get("price_include"))
        if price_include is None:
            return None, "Field 'price_include' harus true|false."
        values["price_include"] = price_include

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
class TaxWriteResult:
    """Hasil satu operasi tulis master Tax (dipakai view)."""

    tax: Tax | None = None
    error: str | None = None
    sync_record_id: int | None = None
    task_id: str | None = None

    @property
    def queued(self) -> bool:
        """True kalau task push master berhasil di-enqueue (broker hidup)."""
        return self.task_id is not None


def _arm_push(tax: Tax, payload: dict) -> SyncRecord:
    """Siapkan ``SyncRecord`` MASTER_PUSH Tax ini (PENDING + payload terbaru).

    ``unique(resource, resource_id, stage)`` hanya mengizinkan satu baris per Tax,
    jadi perubahan berikutnya meng-*update* baris yang sama (pola H1.1/H1.2).
    """
    sync = SyncIdempotency()
    record = sync.get_or_create_sync_record(TAX_RESOURCE, tax.pk, STAGE, payload)

    if (
        dict(record.payload or {}) != payload
        or record.status != SyncStatus.PENDING
        or record.last_error
    ):
        record.payload = payload
        record.status = SyncStatus.PENDING
        record.last_error = ""
        record.save(update_fields=("payload", "status", "last_error", "updated_at"))
        logger.info("master.tax: SyncRecord %s di-arm ulang (PENDING).", record.pk)

    return record


def _audit(action: str, tax: Tax, payload: dict, request, metadata: dict | None = None) -> None:
    """Tulis ``AuditLog`` — best-effort (pola ``integrations/erp_sync/audit.py``)."""
    try:
        AuditLogger().log(
            user=None,
            action=action,
            resource=TAX_RESOURCE,
            resource_id=tax.pk,
            request=request,
            payload=payload,
            result=AuditLog.Result.OK,
            metadata=metadata or {},
        )
    except Exception:  # noqa: BLE001 - audit tidak boleh menggagalkan CRUD master
        logger.exception("master.tax: gagal menulis audit (%s, Tax %s).", action, tax.pk)


def _enqueue(tax: Tax, record: SyncRecord) -> str | None:
    """Enqueue task push master; broker mati -> ``None`` (record tetap PENDING)."""
    try:
        async_result = push_master_tax.apply_async(
            args=[tax.pk, record.pk],
            headers={"x-request-id": get_request_id() or ""},
        )
        return str(async_result.id)
    except Exception:  # noqa: BLE001 - CRUD master tidak boleh gagal karena broker
        logger.exception(
            "master.tax: gagal enqueue push Tax %s (SyncRecord %s tetap PENDING).",
            tax.pk,
            record.pk,
        )
        return None


def _push(tax: Tax, request=None, action: str = ACTION_UPDATE, metadata: dict | None = None):
    """Push satu Tax ke Odoo (SyncRecord + audit + enqueue) — dipakai create/update."""
    payload = tax_payload(tax)
    record = _arm_push(tax, payload)
    _audit(action, tax, payload, request, metadata)

    return record, _enqueue(tax, record)


def _apply_default(tax: Tax | None, request=None) -> None:
    """Jadikan ``tax`` satu-satunya pajak default aktif (atomik).

    ``is_default`` **bukan** field Odoo (keputusan MES) sehingga operasi ini tidak
    meng-arm push; jejak tetap dicatat di ``AuditLog``.
    """
    if tax is None:
        return

    with transaction.atomic():
        Tax.objects.filter(is_default=True).exclude(pk=tax.pk).update(is_default=False)
        if not tax.is_default:
            tax.is_default = True
            tax.save(update_fields=("is_default",))

    _audit(
        ACTION_UPDATE,
        tax,
        tax_payload(tax),
        request,
        {"is_default": True, "mes_only": True},
    )



def create_tax(data, request=None) -> TaxWriteResult:
    """Buat Tax baru + ``SyncRecord`` + ``AuditLog`` + enqueue push ke Odoo."""
    values, error = validate_tax_payload(data)
    if error:
        return TaxWriteResult(error=error)

    payload = data if isinstance(data, dict) else {}
    want_default = parse_bool(payload.get("is_default"))

    tax = Tax.objects.create(**values)
    record, task_id = _push(
        tax, request, ACTION_CREATE, {"odoo_id": tax.odoo_id, "fields": sorted(values)}
    )
    if want_default:
        _apply_default(tax, request)

    logger.info("master.tax: Tax %s (%s) dibuat (sync=%s).", tax.pk, tax.code, record.pk)

    return TaxWriteResult(tax=tax, sync_record_id=record.pk, task_id=task_id)


def update_tax(tax: Tax, data, request=None) -> TaxWriteResult:
    """Ubah Tax (hanya field yang dikirim) + ``SyncRecord`` + ``AuditLog`` + enqueue."""
    values, error = validate_tax_payload(data, instance=tax)
    if error:
        return TaxWriteResult(tax=tax, error=error)

    payload = data if isinstance(data, dict) else {}
    want_default = parse_bool(payload.get("is_default"))

    if not values and want_default is None:
        # Tidak ada perubahan -> tidak ada audit/push.
        return TaxWriteResult(tax=tax)

    if values:
        for field, value in values.items():
            setattr(tax, field, value)
        tax.save()

    if want_default is True:
        _apply_default(tax, request)

    if not values:
        # Hanya penanda default yang berubah (mes-only) -> tanpa push.
        return TaxWriteResult(tax=tax)

    record, task_id = _push(
        tax, request, ACTION_UPDATE, {"odoo_id": tax.odoo_id, "fields": sorted(values)}
    )
    logger.info("master.tax: Tax %s (%s) diubah (sync=%s).", tax.pk, tax.code, record.pk)

    return TaxWriteResult(tax=tax, sync_record_id=record.pk, task_id=task_id)


def deactivate_tax(tax: Tax, request=None) -> TaxWriteResult:
    """Soft delete (``is_active=False``) + ``SyncRecord`` + ``AuditLog`` + enqueue.

    Baris **tidak** dihapus dari DB supaya relasi (``OrderLine.tax_ids`` H2.1 /
    ``PurchaseOrderLine.tax_ids`` H2.2) dan jejak audit tetap utuh; Odoo menerima
    ``active=False`` lewat push yang sama (stage ``MASTER_PUSH``). Penanda
    ``is_default`` dilepas supaya default tidak menunjuk pajak nonaktif.
    """
    if tax.is_active:
        tax.is_active = False
        tax.save(update_fields=("is_active",))

    if tax.is_default:
        tax.is_default = False
        tax.save(update_fields=("is_default",))

    record, task_id = _push(
        tax,
        request,
        ACTION_DELETE,
        {"soft_delete": True, "odoo_id": tax.odoo_id},
    )
    logger.info(
        "master.tax: Tax %s (%s) dinonaktifkan (sync=%s).", tax.pk, tax.code, record.pk
    )

    return TaxWriteResult(tax=tax, sync_record_id=record.pk, task_id=task_id)


def set_default_tax(tax: Tax, request=None) -> TaxWriteResult:
    """Jadikan ``tax`` satu-satunya pajak default (atomik) — tanpa push ke Odoo."""
    if not tax.is_active:
        return TaxWriteResult(
            tax=tax,
            error="Pajak nonaktif tidak bisa dijadikan default. Aktifkan dulu.",
        )

    _apply_default(tax, request)
    logger.info("master.tax: Tax %s (%s) dijadikan default MES.", tax.pk, tax.code)

    return TaxWriteResult(tax=tax)


def get_default_tax() -> Tax | None:
    """Pajak default MES untuk form order/invoice (``None`` kalau tidak ada satu pun).

    Urutan: (1) penanda ``is_default`` berlaku; (2) **fallback** PPN 11% penjualan
    (seed ``master.0019``, dicari lewat ``type_tax_use`` + ``amount`` — bukan nama,
    karena label dev Odoo tidak konsisten); (3) pajak aktif pertama.
    """
    default = Tax.objects.filter(is_default=True, is_active=True).order_by("pk").first()
    if default is not None:
        return default

    fallback = (
        Tax.objects.filter(
            is_active=True,
            type_tax_use=Tax.TaxUse.SALE,
            amount=Decimal("11.00"),
        )
        .order_by("pk")
        .first()
    )
    if fallback is not None:
        return fallback

    return Tax.objects.filter(is_active=True).order_by("pk").first()

