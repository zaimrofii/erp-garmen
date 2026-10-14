"""Service CRUD master UoM (H1.2) — MES = source of truth master.

Pola **sama** dengan ``master/services.py`` (H1.1 Product): satu operasi tulis =
data + ``SyncRecord`` (``master.uom`` / ``MASTER_PUSH``, kunci idempotensi
``odoo_id``) + ``AuditLog`` (``master.create|update|delete``) + enqueue task
Celery ``erp_sync.push_master_uom``. Odoo **tidak** dipanggil di sini (async).

Perbedaan yang disengaja dari Product:

  * penulis dibatasi **ADMIN/OWNER** (brief H1.2); Product juga menerima
    ``purchasing``;
  * ``category`` **wajib saat create** — Odoo menolak ``uom.uom`` tanpa
    ``category_id``/``uom_type``/``factor``, jadi lebih baik MES menahan (400)
    daripada push-nya berakhir FAILED;
  * ``factor``/``rounding`` harus **> 0** (Odoo menolak rasio/presisi 0).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from config.middleware import get_request_id
from core.audit.models import AuditLog
from core.audit.services import AuditLogger
from integrations.erp_sync.idempotency import SyncIdempotency
from integrations.erp_sync.models import SyncRecord, SyncResource, SyncStage, SyncStatus
from integrations.erp_sync.tasks_master_push import push_master_uom, uom_payload

from .models import UoM
from .services import ACTION_CREATE, ACTION_DELETE, ACTION_UPDATE, parse_bool

logger = logging.getLogger(__name__)

__all__ = (
    "UomWriteResult",
    "create_uom",
    "deactivate_uom",
    "uom_row",
    "update_uom",
    "validate_uom_payload",
)

#: Kunci sync UoM (jangan diganti string literal di view).
UOM_RESOURCE = SyncResource.MASTER_UOM.value
STAGE = SyncStage.MASTER_PUSH.value

#: Batas panjang teks (selaras kolom model — beda dari DB = 400, bukan 500).
MAX_CODE_LENGTH = 64
MAX_NAME_LENGTH = 255
MAX_CATEGORY_LENGTH = 64


def uom_row(uom: UoM) -> dict:
    """Baris UoM untuk API (list & detail) — seluruhnya JSON-safe.

    ``odoo_id`` **wajib** ada di response (kunci sync; ``null`` = belum terkirim
    ke Odoo). ``active`` = nama publik dari ``UoM.is_active`` (konsisten H1.1).
    """
    return {
        "id": uom.pk,
        "code": uom.code,
        "name": uom.name,
        "category": uom.category,
        "uom_type": uom.uom_type,
        "factor": float(uom.factor or 0),
        "rounding": float(uom.rounding or 0),
        "active": bool(uom.is_active),
        "odoo_id": uom.odoo_id,
    }


def _parse_positive_float(value, label: str):
    """``(float|None, error)`` untuk nilai yang wajib > 0; kosong = tidak diubah."""
    if value in (None, ""):
        return None, None
    if isinstance(value, bool):
        return None, f"Field '{label}' harus berupa angka > 0."

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None, f"Field '{label}' harus berupa angka > 0."

    if number != number or number in (float("inf"), float("-inf")):
        return None, f"Field '{label}' harus berupa angka > 0."
    if number <= 0:
        return None, f"Field '{label}' harus lebih besar dari 0."

    return number, None


def validate_uom_payload(data, instance: UoM | None = None):
    """Validasi body POST/PUT UoM -> ``(values, error)``.

    Saat create (``instance=None``) ``code``/``name``/``category`` wajib; saat
    update semuanya opsional (hanya field yang dikirim yang diubah). Nilai yang
    dikembalikan siap ``setattr``/``create`` (memakai nama kolom model).
    """
    payload = data if isinstance(data, dict) else {}
    values: dict = {}

    if instance is None or "code" in payload:
        code = str(payload.get("code") or "").strip()
        if not code:
            return None, "Field 'code' wajib diisi."
        if len(code) > MAX_CODE_LENGTH:
            return None, f"Field 'code' maksimal {MAX_CODE_LENGTH} karakter."

        duplicates = UoM.objects.filter(code__iexact=code)
        if instance is not None:
            duplicates = duplicates.exclude(pk=instance.pk)
        if duplicates.exists():
            return None, f"Kode UoM '{code}' sudah dipakai UoM lain."
        values["code"] = code

    if instance is None or "name" in payload:
        name = str(payload.get("name") or "").strip()
        if not name:
            return None, "Field 'name' wajib diisi."
        if len(name) > MAX_NAME_LENGTH:
            return None, f"Field 'name' maksimal {MAX_NAME_LENGTH} karakter."
        values["name"] = name

    if instance is None or "category" in payload:
        category = str(payload.get("category") or "").strip()
        if instance is None and not category:
            return None, (
                "Field 'category' wajib diisi (kategori Odoo menentukan unit "
                "referensi & rasio)."
            )
        if len(category) > MAX_CATEGORY_LENGTH:
            return None, f"Field 'category' maksimal {MAX_CATEGORY_LENGTH} karakter."
        values["category"] = category

    if "uom_type" in payload:
        uom_type = str(payload.get("uom_type") or "").strip().lower()
        if uom_type not in UoM.UomType.values:
            return None, (
                f"Field 'uom_type' harus salah satu dari {', '.join(UoM.UomType.values)}."
            )
        values["uom_type"] = uom_type

    for field in ("factor", "rounding"):
        if field in payload:
            number, error = _parse_positive_float(payload.get(field), field)
            if error:
                return None, error
            if number is not None:
                values[field] = number

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
class UomWriteResult:
    """Hasil satu operasi tulis master UoM (dipakai view)."""

    uom: UoM | None = None
    error: str | None = None
    sync_record_id: int | None = None
    task_id: str | None = None

    @property
    def queued(self) -> bool:
        """True kalau task push master berhasil di-enqueue (broker hidup)."""
        return self.task_id is not None


def _arm_push(uom: UoM, payload: dict) -> SyncRecord:
    """Siapkan ``SyncRecord`` MASTER_PUSH UoM ini (PENDING + payload terbaru).

    ``unique(resource, resource_id, stage)`` hanya mengizinkan satu baris per UoM,
    jadi perubahan berikutnya meng-*update* baris yang sama (pola H1.1).
    """
    sync = SyncIdempotency()
    record = sync.get_or_create_sync_record(UOM_RESOURCE, uom.pk, STAGE, payload)

    if (
        dict(record.payload or {}) != payload
        or record.status != SyncStatus.PENDING
        or record.last_error
    ):
        record.payload = payload
        record.status = SyncStatus.PENDING
        record.last_error = ""
        record.save(update_fields=("payload", "status", "last_error", "updated_at"))
        logger.info("master.uom: SyncRecord %s di-arm ulang (PENDING).", record.pk)

    return record


def _audit(action: str, uom: UoM, payload: dict, request, metadata: dict | None = None) -> None:
    """Tulis ``AuditLog`` — best-effort (pola ``integrations/erp_sync/audit.py``)."""
    try:
        AuditLogger().log(
            user=None,
            action=action,
            resource=UOM_RESOURCE,
            resource_id=uom.pk,
            request=request,
            payload=payload,
            result=AuditLog.Result.OK,
            metadata=metadata or {},
        )
    except Exception:  # noqa: BLE001 - audit tidak boleh menggagalkan CRUD master
        logger.exception("master.uom: gagal menulis audit (%s, UoM %s).", action, uom.pk)


def _enqueue(uom: UoM, record: SyncRecord) -> str | None:
    """Enqueue task push master; broker mati -> ``None`` (record tetap PENDING)."""
    try:
        async_result = push_master_uom.apply_async(
            args=[uom.pk, record.pk],
            headers={"x-request-id": get_request_id() or ""},
        )
        return str(async_result.id)
    except Exception:  # noqa: BLE001 - CRUD master tidak boleh gagal karena broker
        logger.exception(
            "master.uom: gagal enqueue push UoM %s (SyncRecord %s tetap PENDING).",
            uom.pk,
            record.pk,
        )
        return None


def create_uom(data, request=None) -> UomWriteResult:
    """Buat UoM baru + ``SyncRecord`` + ``AuditLog`` + enqueue push ke Odoo."""
    values, error = validate_uom_payload(data)
    if error:
        return UomWriteResult(error=error)

    uom = UoM.objects.create(**values)
    payload = uom_payload(uom)
    record = _arm_push(uom, payload)
    _audit(ACTION_CREATE, uom, payload, request, {"odoo_id": uom.odoo_id})
    task_id = _enqueue(uom, record)

    logger.info("master.uom: UoM %s (%s) dibuat (sync=%s).", uom.pk, uom.code, record.pk)
    return UomWriteResult(uom=uom, sync_record_id=record.pk, task_id=task_id)


def update_uom(uom: UoM, data, request=None) -> UomWriteResult:
    """Ubah UoM (hanya field yang dikirim) + ``SyncRecord`` + ``AuditLog`` + enqueue."""
    values, error = validate_uom_payload(data, instance=uom)
    if error:
        return UomWriteResult(uom=uom, error=error)

    if not values:
        # Tidak ada perubahan -> tidak ada audit/push.
        return UomWriteResult(uom=uom)

    for field, value in values.items():
        setattr(uom, field, value)
    uom.save()

    payload = uom_payload(uom)
    record = _arm_push(uom, payload)
    _audit(
        ACTION_UPDATE,
        uom,
        payload,
        request,
        {"odoo_id": uom.odoo_id, "fields": sorted(values)},
    )
    task_id = _enqueue(uom, record)

    logger.info("master.uom: UoM %s (%s) diubah (sync=%s).", uom.pk, uom.code, record.pk)
    return UomWriteResult(uom=uom, sync_record_id=record.pk, task_id=task_id)


def deactivate_uom(uom: UoM, request=None) -> UomWriteResult:
    """Soft delete (``is_active=False``) + ``SyncRecord`` + ``AuditLog`` + enqueue.

    Baris **tidak** dihapus dari DB (tidak ada ``delete()``) supaya relasi
    (``Product.uom``) dan jejak audit tetap utuh; Odoo menerima ``active=False``
    lewat push yang sama (stage ``MASTER_PUSH``).
    """
    if uom.is_active:
        uom.is_active = False
        uom.save(update_fields=("is_active",))

    payload = uom_payload(uom)
    record = _arm_push(uom, payload)
    _audit(
        ACTION_DELETE,
        uom,
        payload,
        request,
        {"soft_delete": True, "odoo_id": uom.odoo_id},
    )
    task_id = _enqueue(uom, record)

    logger.info(
        "master.uom: UoM %s (%s) dinonaktifkan (sync=%s).", uom.pk, uom.code, record.pk
    )
    return UomWriteResult(uom=uom, sync_record_id=record.pk, task_id=task_id)

