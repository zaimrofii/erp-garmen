"""Service CRUD master Warehouse (H1.3) — MES = source of truth master.

Pola **sama** dengan ``master/services.py`` (H1.1 Product) dan
``master/uom_services.py`` (H1.2 UoM): satu operasi tulis = data + ``SyncRecord``
(``master.warehouse`` / ``MASTER_PUSH``, kunci idempotensi ``odoo_id``) +
``AuditLog`` (``master.create|update|delete``) + enqueue task Celery
``erp_sync.push_master_warehouse``. Odoo **tidak** dipanggil di sini (async).

Catatan H1.3:

  * field yang disimpan = yang **benar ada** di ``stock.warehouse`` hasil probe
    ``fields_get`` (``reception_steps`` & ``delivery_steps``); field ``usage``
    TIDAK ditambahkan di Warehouse karena itu milik ``stock.location`` (H1.4);
  * push ke Odoo **create + update** (sprint utang `warehouse-create-mapping`):
    ``view_location_id``/``lot_stock_id`` dibuat sendiri oleh Odoo di ``create()``
    (sumber ``stock/models/stock_warehouse.py`` baris 109–126) dan ``company_id``
    ``readonly`` ⇒ MES tidak mengirim ketiganya (tidak mengarang id lokasi/company);
  * penulis dibatasi **ADMIN/OWNER** (brief H1.3).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from config.middleware import get_request_id
from core.audit.models import AuditLog
from core.audit.services import AuditLogger
from integrations.erp_sync.idempotency import SyncIdempotency
from integrations.erp_sync.models import SyncRecord, SyncResource, SyncStage, SyncStatus
from integrations.erp_sync.tasks_master_push import push_master_warehouse, warehouse_payload

from .models import Warehouse
from .services import ACTION_CREATE, ACTION_DELETE, ACTION_UPDATE, parse_bool

logger = logging.getLogger(__name__)

__all__ = (
    "WarehouseWriteResult",
    "create_warehouse",
    "deactivate_warehouse",
    "update_warehouse",
    "validate_warehouse_payload",
    "warehouse_row",
)

#: Kunci sync Warehouse (jangan diganti string literal di view).
WAREHOUSE_RESOURCE = SyncResource.MASTER_WAREHOUSE.value
STAGE = SyncStage.MASTER_PUSH.value

#: Batas panjang teks (selaras kolom model — beda dari DB = 400, bukan 500).
MAX_CODE_LENGTH = 64
MAX_NAME_LENGTH = 255


def warehouse_row(warehouse: Warehouse) -> dict:
    """Baris Warehouse untuk API (list & detail) — seluruhnya JSON-safe.

    ``odoo_id`` **wajib** ada di response (kunci sync; ``null`` = belum terkirim
    ke Odoo). ``active`` = nama publik dari ``Warehouse.is_active``. Field
    ``usage`` TIDAK ada di sini (lihat docstring modul — milik Location/H1.4).
    """
    return {
        "id": warehouse.pk,
        "code": warehouse.code,
        "name": warehouse.name,
        "reception_steps": warehouse.reception_steps,
        "delivery_steps": warehouse.delivery_steps,
        "active": bool(warehouse.is_active),
        "odoo_id": warehouse.odoo_id,
    }


def _choice_or_error(value, allowed: tuple[str, ...], label: str):
    """``(value, error)`` untuk field selection: case-insensitive, harus dikenal."""
    candidate = str(value or "").strip().lower()
    if candidate not in allowed:
        return None, f"Field '{label}' harus salah satu dari {', '.join(allowed)}."

    return candidate, None


def validate_warehouse_payload(data, instance: Warehouse | None = None):
    """Validasi body POST/PUT Warehouse -> ``(values, error)``.

    Saat create (``instance=None``) ``code`` & ``name`` wajib; saat update keduanya
    opsional (hanya field yang dikirim yang diubah). Nilai yang dikembalikan siap
    ``setattr``/``create`` (memakai nama kolom model).
    """
    payload = data if isinstance(data, dict) else {}
    values: dict = {}

    if instance is None or "code" in payload:
        code = str(payload.get("code") or "").strip()
        if not code:
            return None, "Field 'code' wajib diisi."
        if len(code) > MAX_CODE_LENGTH:
            return None, f"Field 'code' maksimal {MAX_CODE_LENGTH} karakter."

        duplicates = Warehouse.objects.filter(code__iexact=code)
        if instance is not None:
            duplicates = duplicates.exclude(pk=instance.pk)
        if duplicates.exists():
            return None, f"Kode gudang '{code}' sudah dipakai gudang lain."
        values["code"] = code

    if instance is None or "name" in payload:
        name = str(payload.get("name") or "").strip()
        if not name:
            return None, "Field 'name' wajib diisi."
        if len(name) > MAX_NAME_LENGTH:
            return None, f"Field 'name' maksimal {MAX_NAME_LENGTH} karakter."
        values["name"] = name

    if "reception_steps" in payload:
        reception, error = _choice_or_error(
            payload.get("reception_steps"), Warehouse.ReceptionSteps.values, "reception_steps"
        )
        if error:
            return None, error
        values["reception_steps"] = reception

    if "delivery_steps" in payload:
        delivery, error = _choice_or_error(
            payload.get("delivery_steps"), Warehouse.DeliverySteps.values, "delivery_steps"
        )
        if error:
            return None, error
        values["delivery_steps"] = delivery

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
class WarehouseWriteResult:
    """Hasil satu operasi tulis master Warehouse (dipakai view)."""

    warehouse: Warehouse | None = None
    error: str | None = None
    sync_record_id: int | None = None
    task_id: str | None = None

    @property
    def queued(self) -> bool:
        """True kalau task push master berhasil di-enqueue (broker hidup)."""
        return self.task_id is not None


def _arm_push(warehouse: Warehouse, payload: dict) -> SyncRecord:
    """Siapkan ``SyncRecord`` MASTER_PUSH gudang ini (PENDING + payload terbaru).

    ``unique(resource, resource_id, stage)`` hanya mengizinkan satu baris per
    gudang, jadi perubahan berikutnya meng-*update* baris yang sama (pola H1.1/H1.2).
    """
    sync = SyncIdempotency()
    record = sync.get_or_create_sync_record(WAREHOUSE_RESOURCE, warehouse.pk, STAGE, payload)

    if (
        dict(record.payload or {}) != payload
        or record.status != SyncStatus.PENDING
        or record.last_error
    ):
        record.payload = payload
        record.status = SyncStatus.PENDING
        record.last_error = ""
        record.save(update_fields=("payload", "status", "last_error", "updated_at"))
        logger.info("master.warehouse: SyncRecord %s di-arm ulang (PENDING).", record.pk)

    return record


def _audit(
    action: str, warehouse: Warehouse, payload: dict, request, metadata: dict | None = None
) -> None:
    """Tulis ``AuditLog`` — best-effort (pola ``integrations/erp_sync/audit.py``)."""
    try:
        AuditLogger().log(
            user=None,
            action=action,
            resource=WAREHOUSE_RESOURCE,
            resource_id=warehouse.pk,
            request=request,
            payload=payload,
            result=AuditLog.Result.OK,
            metadata=metadata or {},
        )
    except Exception:  # noqa: BLE001 - audit tidak boleh menggagalkan CRUD master
        logger.exception(
            "master.warehouse: gagal menulis audit (%s, gudang %s).", action, warehouse.pk
        )


def _enqueue(warehouse: Warehouse, record: SyncRecord) -> str | None:
    """Enqueue task push master; broker mati -> ``None`` (record tetap PENDING)."""
    try:
        async_result = push_master_warehouse.apply_async(
            args=[warehouse.pk, record.pk],
            headers={"x-request-id": get_request_id() or ""},
        )
        return str(async_result.id)
    except Exception:  # noqa: BLE001 - CRUD master tidak boleh gagal karena broker
        logger.exception(
            "master.warehouse: gagal enqueue push gudang %s (SyncRecord %s tetap PENDING).",
            warehouse.pk,
            record.pk,
        )
        return None


def create_warehouse(data, request=None) -> WarehouseWriteResult:
    """Buat gudang baru + ``SyncRecord`` + ``AuditLog`` + enqueue push ke Odoo."""
    values, error = validate_warehouse_payload(data)
    if error:
        return WarehouseWriteResult(error=error)

    warehouse = Warehouse.objects.create(**values)
    payload = warehouse_payload(warehouse)
    record = _arm_push(warehouse, payload)
    _audit(ACTION_CREATE, warehouse, payload, request, {"odoo_id": warehouse.odoo_id})
    task_id = _enqueue(warehouse, record)

    logger.info(
        "master.warehouse: gudang %s (%s) dibuat (sync=%s).",
        warehouse.pk,
        warehouse.code,
        record.pk,
    )
    return WarehouseWriteResult(warehouse=warehouse, sync_record_id=record.pk, task_id=task_id)


def update_warehouse(warehouse: Warehouse, data, request=None) -> WarehouseWriteResult:
    """Ubah gudang (hanya field yang dikirim) + ``SyncRecord`` + ``AuditLog`` + enqueue."""
    values, error = validate_warehouse_payload(data, instance=warehouse)
    if error:
        return WarehouseWriteResult(warehouse=warehouse, error=error)

    if not values:
        # Tidak ada perubahan -> tidak ada audit/push.
        return WarehouseWriteResult(warehouse=warehouse)

    for field, value in values.items():
        setattr(warehouse, field, value)
    warehouse.save()

    payload = warehouse_payload(warehouse)
    record = _arm_push(warehouse, payload)
    _audit(
        ACTION_UPDATE,
        warehouse,
        payload,
        request,
        {"odoo_id": warehouse.odoo_id, "fields": sorted(values)},
    )
    task_id = _enqueue(warehouse, record)

    logger.info(
        "master.warehouse: gudang %s (%s) diubah (sync=%s).",
        warehouse.pk,
        warehouse.code,
        record.pk,
    )
    return WarehouseWriteResult(warehouse=warehouse, sync_record_id=record.pk, task_id=task_id)


def deactivate_warehouse(warehouse: Warehouse, request=None) -> WarehouseWriteResult:
    """Soft delete (``is_active=False``) + ``SyncRecord`` + ``AuditLog`` + enqueue.

    Baris **tidak** dihapus dari DB (tidak ada ``delete()``) supaya relasi
    (lokasi/transaksi yang menunjuk gudang) dan jejak audit tetap utuh; Odoo
    menerima ``active=False`` lewat push yang sama (stage ``MASTER_PUSH``).
    """
    if warehouse.is_active:
        warehouse.is_active = False
        warehouse.save(update_fields=("is_active",))

    payload = warehouse_payload(warehouse)
    record = _arm_push(warehouse, payload)
    _audit(
        ACTION_DELETE,
        warehouse,
        payload,
        request,
        {"soft_delete": True, "odoo_id": warehouse.odoo_id},
    )
    task_id = _enqueue(warehouse, record)

    logger.info(
        "master.warehouse: gudang %s (%s) dinonaktifkan (sync=%s).",
        warehouse.pk,
        warehouse.code,
        record.pk,
    )
    return WarehouseWriteResult(warehouse=warehouse, sync_record_id=record.pk, task_id=task_id)

