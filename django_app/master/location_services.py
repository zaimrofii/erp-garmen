"""Service CRUD master Location (H1.4) — MES = source of truth master.

Pola **sama** dengan ``master/services.py`` (H1.1), ``master/uom_services.py`` (H1.2),
dan ``master/warehouse_services.py`` (H1.3): satu operasi tulis = data +
``SyncRecord`` (``master.location`` / ``MASTER_PUSH``, kunci idempotensi ``odoo_id``)
+ ``AuditLog`` (``master.create|update|delete``) + enqueue task Celery
``erp_sync.push_master_location``. Odoo **tidak** dipanggil di sini (async).

Kekhususan H1.4 (hierarki):

  * ``parent`` = self-FK (kolom ``parent_id``) & ``warehouse`` = FK (kolom
    ``warehouse_id``) — nama field TANPA akhiran ``_id`` mengikuti konvensi repo
    (lihat docstring ``master.Location``), sehingga ``location.parent_id`` = **pk**;
  * guard hierarki: induk tidak boleh dirinya sendiri, tidak boleh turunannya
    sendiri (mencegah siklus yang merusak ``complete_name``);
  * DELETE = soft delete, **ditolak (400)** kalau lokasi masih punya anak aktif —
    hierarki Odoo tidak boleh ditinggalkan setengah aktif;
  * ``complete_name`` TIDAK disimpan: di-*derive* lewat ``complete_name()`` saat
    serialisasi (rantai induk), sesuai keputusan STEP 0.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from config.middleware import get_request_id
from core.audit.models import AuditLog
from core.audit.services import AuditLogger
from integrations.erp_sync.idempotency import SyncIdempotency
from integrations.erp_sync.models import SyncRecord, SyncResource, SyncStage, SyncStatus
from integrations.erp_sync.tasks_master_push import location_payload, push_master_location

from .models import Location, Warehouse
from .services import ACTION_CREATE, ACTION_DELETE, ACTION_UPDATE, parse_bool

logger = logging.getLogger(__name__)

__all__ = (
    "LocationWriteResult",
    "complete_name",
    "create_location",
    "deactivate_location",
    "location_row",
    "update_location",
    "validate_location_payload",
)

#: Kunci sync Location (jangan diganti string literal di view).
LOCATION_RESOURCE = SyncResource.MASTER_LOCATION.value
STAGE = SyncStage.MASTER_PUSH.value

#: Batas panjang teks (selaras kolom model — beda dari DB = 400, bukan 500).
MAX_CODE_LENGTH = 64
MAX_NAME_LENGTH = 255

#: Batas kedalaman rantai induk (mencegah loop tak berujung).
MAX_PARENT_DEPTH = 32


def complete_name(location: Location) -> str:
    """``complete_name`` DERIVED: ``Induk/Anak/Cucu`` (tanpa kolom tambahan).

    Rantai disusun dengan menelusuri ``parent`` (memakai cache ``select_related``
    kalau ada); kedalaman dibatasi ``MAX_PARENT_DEPTH`` sebagai jaring pengaman.
    """
    names: list[str] = []
    node: Location | None = location
    seen: set[int] = set()
    depth = 0

    while node is not None and depth < MAX_PARENT_DEPTH:
        if node.pk in seen:  # pragma: no cover - jaring pengaman anti-siklus
            break
        seen.add(node.pk)
        names.append(node.name)
        node = node.parent
        depth += 1

    return "/".join(reversed(names))


def location_row(location: Location, children_count: int = 0) -> dict:
    """Baris Location untuk API (list & detail) — seluruhnya JSON-safe.

    ``parent_id``/``warehouse_id`` = **pk** (atau ``null``), plus nama induk/gudang
    supaya UI tidak perlu request tambahan. ``children_count`` diisi pemanggil
    (list memakai satu ``annotate(Count)``, detail memakai ``.count()``).
    ``complete_name`` di-*derive* (tidak ada kolomnya di DB).
    """
    parent = location.parent if location.parent_id else None
    warehouse = location.warehouse if location.warehouse_id else None

    return {
        "id": location.pk,
        "code": location.code,
        "name": location.name,
        "usage": location.usage,
        "parent_id": location.parent_id,
        "parent_name": parent.name if parent is not None else None,
        "warehouse_id": location.warehouse_id,
        "warehouse_name": warehouse.name if warehouse is not None else None,
        "active": bool(location.is_active),
        "odoo_id": location.odoo_id,
        "children_count": children_count,
        "complete_name": complete_name(location),
    }


def _choice_or_error(value, allowed: tuple[str, ...], label: str):
    """``(value, error)`` untuk field selection: case-insensitive, harus dikenal."""
    candidate = str(value or "").strip().lower()
    if candidate not in allowed:
        return None, f"Field '{label}' harus salah satu dari {', '.join(allowed)}."

    return candidate, None


def _fk_or_error(value, model, label: str):
    """``(instance|None, error)`` untuk FK opsional; kosong → ``None``."""
    if value in (None, ""):
        return None, None

    try:
        pk = int(value)
    except (TypeError, ValueError):
        return None, f"Field '{label}' harus berupa id (angka)."

    instance = model.objects.filter(pk=pk).first()
    if instance is None:
        return None, f"{label} {pk} tidak ditemukan."

    return instance, None


def _is_descendant(candidate: Location, node: Location) -> bool:
    """True kalau ``candidate`` berada di bawah ``node`` (jalan naik dari kandidat)."""
    current: Location | None = candidate
    depth = 0
    seen: set[int] = set()

    while current is not None and depth < MAX_PARENT_DEPTH:
        if current.pk in seen:  # pragma: no cover - jaring pengaman anti-siklus
            break
        if current.pk == node.pk:
            return True
        seen.add(current.pk)
        current = current.parent
        depth += 1

    return False


def validate_location_payload(data, instance: Location | None = None):
    """Validasi body POST/PUT Location -> ``(values, error)``.

    Saat create (``instance=None``) ``code`` & ``name`` wajib; saat update keduanya
    opsional (hanya field yang dikirim yang diubah). Nilai yang dikembalikan siap
    ``setattr``/``create`` (memakai nama kolom/atribut model).
    """
    payload = data if isinstance(data, dict) else {}
    values: dict = {}

    if instance is None or "code" in payload:
        code = str(payload.get("code") or "").strip()
        if not code:
            return None, "Field 'code' wajib diisi."
        if len(code) > MAX_CODE_LENGTH:
            return None, f"Field 'code' maksimal {MAX_CODE_LENGTH} karakter."

        duplicates = Location.objects.filter(code__iexact=code)
        if instance is not None:
            duplicates = duplicates.exclude(pk=instance.pk)
        if duplicates.exists():
            return None, f"Kode lokasi '{code}' sudah dipakai lokasi lain."
        values["code"] = code

    if instance is None or "name" in payload:
        name = str(payload.get("name") or "").strip()
        if not name:
            return None, "Field 'name' wajib diisi."
        if len(name) > MAX_NAME_LENGTH:
            return None, f"Field 'name' maksimal {MAX_NAME_LENGTH} karakter."
        values["name"] = name

    if "usage" in payload:
        usage, error = _choice_or_error(payload.get("usage"), Location.Usage.values, "usage")
        if error:
            return None, error
        values["usage"] = usage

    if "parent_id" in payload:
        parent, error = _fk_or_error(payload.get("parent_id"), Location, "Induk (parent_id)")
        if error:
            return None, error
        if parent is not None and instance is not None:
            if parent.pk == instance.pk:
                return None, "Lokasi tidak boleh menjadi induk dirinya sendiri."
            if _is_descendant(parent, instance):
                return None, (
                    "Induk tidak boleh berupa turunan lokasi ini "
                    "(akan membentuk siklus hierarki)."
                )
        values["parent"] = parent

    if "warehouse_id" in payload:
        warehouse, error = _fk_or_error(
            payload.get("warehouse_id"), Warehouse, "Gudang (warehouse_id)"
        )
        if error:
            return None, error
        values["warehouse"] = warehouse

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
class LocationWriteResult:
    """Hasil satu operasi tulis master Location (dipakai view)."""

    location: Location | None = None
    error: str | None = None
    sync_record_id: int | None = None
    task_id: str | None = None

    @property
    def queued(self) -> bool:
        """True kalau task push master berhasil di-enqueue (broker hidup)."""
        return self.task_id is not None


def _arm_push(location: Location, payload: dict) -> SyncRecord:
    """Siapkan ``SyncRecord`` MASTER_PUSH lokasi ini (PENDING + payload terbaru).

    ``unique(resource, resource_id, stage)`` hanya mengizinkan satu baris per lokasi,
    jadi perubahan berikutnya meng-*update* baris yang sama (pola H1.1–H1.3).
    """
    sync = SyncIdempotency()
    record = sync.get_or_create_sync_record(LOCATION_RESOURCE, location.pk, STAGE, payload)

    if (
        dict(record.payload or {}) != payload
        or record.status != SyncStatus.PENDING
        or record.last_error
    ):
        record.payload = payload
        record.status = SyncStatus.PENDING
        record.last_error = ""
        record.save(update_fields=("payload", "status", "last_error", "updated_at"))
        logger.info("master.location: SyncRecord %s di-arm ulang (PENDING).", record.pk)

    return record


def _audit(
    action: str, location: Location, payload: dict, request, metadata: dict | None = None
) -> None:
    """Tulis ``AuditLog`` — best-effort (pola ``integrations/erp_sync/audit.py``)."""
    try:
        AuditLogger().log(
            user=None,
            action=action,
            resource=LOCATION_RESOURCE,
            resource_id=location.pk,
            request=request,
            payload=payload,
            result=AuditLog.Result.OK,
            metadata=metadata or {},
        )
    except Exception:  # noqa: BLE001 - audit tidak boleh menggagalkan CRUD master
        logger.exception(
            "master.location: gagal menulis audit (%s, lokasi %s).", action, location.pk
        )


def _enqueue(location: Location, record: SyncRecord) -> str | None:
    """Enqueue task push master; broker mati -> ``None`` (record tetap PENDING)."""
    try:
        async_result = push_master_location.apply_async(
            args=[location.pk, record.pk],
            headers={"x-request-id": get_request_id() or ""},
        )
        return str(async_result.id)
    except Exception:  # noqa: BLE001 - CRUD master tidak boleh gagal karena broker
        logger.exception(
            "master.location: gagal enqueue push lokasi %s (SyncRecord %s tetap PENDING).",
            location.pk,
            record.pk,
        )
        return None


def create_location(data, request=None) -> LocationWriteResult:
    """Buat lokasi baru + ``SyncRecord`` + ``AuditLog`` + enqueue push ke Odoo."""
    values, error = validate_location_payload(data)
    if error:
        return LocationWriteResult(error=error)

    location = Location.objects.create(**values)
    payload = location_payload(location)
    record = _arm_push(location, payload)
    _audit(ACTION_CREATE, location, payload, request, {"odoo_id": location.odoo_id})
    task_id = _enqueue(location, record)

    logger.info(
        "master.location: lokasi %s (%s) dibuat (sync=%s).",
        location.pk,
        location.code,
        record.pk,
    )
    return LocationWriteResult(location=location, sync_record_id=record.pk, task_id=task_id)


def update_location(location: Location, data, request=None) -> LocationWriteResult:
    """Ubah lokasi (hanya field yang dikirim) + ``SyncRecord`` + ``AuditLog`` + enqueue."""
    values, error = validate_location_payload(data, instance=location)
    if error:
        return LocationWriteResult(location=location, error=error)

    if not values:
        # Tidak ada perubahan -> tidak ada audit/push.
        return LocationWriteResult(location=location)

    for field, value in values.items():
        setattr(location, field, value)
    location.save()

    payload = location_payload(location)
    record = _arm_push(location, payload)
    _audit(
        ACTION_UPDATE,
        location,
        payload,
        request,
        {"odoo_id": location.odoo_id, "fields": sorted(values)},
    )
    task_id = _enqueue(location, record)

    logger.info(
        "master.location: lokasi %s (%s) diubah (sync=%s).",
        location.pk,
        location.code,
        record.pk,
    )
    return LocationWriteResult(location=location, sync_record_id=record.pk, task_id=task_id)


def deactivate_location(location: Location, request=None) -> LocationWriteResult:
    """Soft delete (``is_active=False``) + ``SyncRecord`` + ``AuditLog`` + enqueue.

    **Ditolak** (``error`` → 400 di view) kalau lokasi masih punya anak **aktif**:
    hierarki akan rusak kalau induk dinonaktifkan sementara anaknya masih dipakai —
    operator diminta menonaktifkan/memindahkan anak dulu. Baris **tidak** dihapus dari
    DB (tidak ada ``delete()``) supaya relasi & jejak audit tetap utuh.
    """
    active_children = location.children.filter(is_active=True)
    if active_children.exists():
        codes = list(active_children.values_list("code", flat=True)[:5])
        return LocationWriteResult(
            location=location,
            error=(
                f"Lokasi '{location.code}' masih punya {active_children.count()} anak aktif "
                f"({', '.join(codes)}) — nonaktifkan atau pindahkan anaknya dulu."
            ),
        )

    if location.is_active:
        location.is_active = False
        location.save(update_fields=("is_active",))

    payload = location_payload(location)
    record = _arm_push(location, payload)
    _audit(
        ACTION_DELETE,
        location,
        payload,
        request,
        {"soft_delete": True, "odoo_id": location.odoo_id},
    )
    task_id = _enqueue(location, record)

    logger.info(
        "master.location: lokasi %s (%s) dinonaktifkan (sync=%s).",
        location.pk,
        location.code,
        record.pk,
    )
    return LocationWriteResult(location=location, sync_record_id=record.pk, task_id=task_id)
