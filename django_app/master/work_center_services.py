"""Service CRUD master Work Center (H1.7) — model **garment**, resource master.

Pola **sama** dengan ``master/product_services.py`` (H1.1) … ``master/partner_services.py``
(H1.6): satu operasi tulis = data + ``SyncRecord`` (``master.work_center`` /
``MASTER_PUSH``) + ``AuditLog`` (``master.create|update|delete``).

Kekhususan H1.7 — **MES-only** (keputusan pemilik proyek, berbasis probe Odoo 17):

  * `WorkCenter` milik app ``garment`` (bukan master) karena sudah dipakai bundle,
    routing step, device profile, scrap accumulator, dan M2M ``ProductionLine``;
  * Odoo ``mrp.workcenter`` **bukan** padanan WC MES: field wajib saat create =
    ``resource_id`` (many2one ``resource.resource``, **tanpa default**) + ``sequence``,
    dan tidak ada padanan ``wc_type``/``capability_tags``/``capacity_per_hour``
    (yang ada: ``default_capacity``/``capacity_ids``/``time_efficiency``/``costs_hour``/
    ``tag_ids`` — semantiknya beda). Push berarti MES harus **mengarang**
    ``resource.resource`` → ditolak;
  * Karena itu **tidak ada task push & tidak ada pull**. Aturan "setiap CUD master →
    SyncRecord" tetap dipenuhi lewat status baru ``SyncStatus.SKIPPED``
    (``SyncIdempotency.mark_skipped``) sehingga jejaknya terlihat di monitor sync
    (``GET /api/v1/sync/records/?status=SKIPPED``) tanpa antrean palsu;
  * ``WC.production_line`` **tidak** ditambahkan (bertabrakan dengan M2M existing
    ``ProductionLine.work_centers`` — jalur ``capability_allocator``); H1.8 mengelola M2M itu;
  * ``wc_type`` free-form (tanpa enum, konsisten ``LineAllocationRule.wc_type``);
    ``capability_tags`` list string (≤ 20 tag, tiap tag ≤ 32 karakter);
    ``capacity_per_hour`` desimal ≥ 0.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from apps_industry.garment.models import WorkCenter
from apps_industry.garment.services.wc_queue import WCQueue
from core.audit.models import AuditLog
from core.audit.services import AuditLogger
from integrations.erp_sync.idempotency import SyncIdempotency
from integrations.erp_sync.models import SyncResource, SyncStage, SyncStatus

from .services import ACTION_CREATE, ACTION_DELETE, ACTION_UPDATE, parse_bool

logger = logging.getLogger(__name__)

__all__ = (
    "WorkCenterWriteResult",
    "create_work_center",
    "deactivate_work_center",
    "active_bundles_count",
    "MES_ONLY_REASON",
    "normalize_tags",
    "update_work_center",
    "validate_work_center_payload",
    "work_center_detail_row",
    "work_center_row",
)

#: Resource sync (jangan ganti string literal di view).
WORK_CENTER_RESOURCE = SyncResource.MASTER_WORK_CENTER.value
STAGE = SyncStage.MASTER_PUSH.value

#: Alasan baku status ``SKIPPED`` (disimpan di ``SyncRecord.last_error``).
MES_ONLY_REASON = (
    "MES-only: Work Center tidak dikirim ke Odoo — mrp.workcenter mewajibkan "
    "resource_id (resource.resource) yang tidak ada di MES."
)

#: Batas panjang (selaras kolom model — beda dari DB = 400, bukan 500).
MAX_CODE_LENGTH = 64
MAX_NAME_LENGTH = 150
MAX_WC_TYPE_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 2000

#: Batas tag kapabilitas.
MAX_TAGS = 20
MAX_TAG_LENGTH = 32

#: Batas ``capacity_per_hour`` = ``DecimalField(max_digits=10, decimal_places=2)``.
MAX_CAPACITY = Decimal("99999999.99")


def _iso(value) -> str | None:
    """ISO-8601 atau ``None`` (datetime kosong)."""
    return value.isoformat() if value else None


def work_center_row(work_center: WorkCenter) -> dict:
    """Baris work center untuk API (list & detail) — JSON-safe.

    ``active`` = nama publik ``is_active`` (konsisten H1.1–H1.6) dan
    ``capacity_per_hour`` dikirim sebagai **float** (kolom desimal 2 angka di baliknya)
    supaya form bisa langsung memakainya.
    """
    return {
        "id": work_center.pk,
        "code": work_center.code,
        "name": work_center.name,
        "wc_type": work_center.wc_type,
        "capability_tags": list(work_center.capability_tags or []),
        "capacity_per_hour": float(work_center.capacity_per_hour or 0),
        "description": work_center.description,
        "active": bool(work_center.is_active),
        "config": dict(work_center.config or {}),
        "created_at": _iso(work_center.created_at),
        "updated_at": _iso(work_center.updated_at),
    }


def active_bundles_count(work_center: WorkCenter) -> int:
    """Jumlah bundle AKTIF di WC ini (state di luar ``WCQueue.EXCLUDED_STATES``).

    Definisi "aktif" memakai konstanta resmi ``WCQueue.EXCLUDED_STATES`` = bundle
    yang belum/sudah keluar queue (``DONE``/``CANCELLED``) → satu sumber kebenaran,
    sama seperti endpoint monitoring.
    """
    return (
        work_center.bundles.exclude(state__in=WCQueue.EXCLUDED_STATES).count()
        if work_center.pk
        else 0
    )


def work_center_detail_row(work_center: WorkCenter) -> dict:
    """Baris detail = ``work_center_row`` + jejak pemakaian.

    * ``active_bundles_count`` — dasar guard soft delete (dan info operator);
    * ``production_lines`` — daftar lini yang memuat WC ini (M2M existing
      ``ProductionLine.work_centers``; dikelola di H1.8).
    """
    row = work_center_row(work_center)
    row["active_bundles_count"] = active_bundles_count(work_center)
    row["production_lines"] = [
        {"id": line.pk, "code": line.code, "name": line.name}
        for line in work_center.production_lines.all().order_by("code")
    ]

    return row


# ---------------------------------------------------------------------------
# Validasi (PURE — dipakai view & test tanpa HTTP)
# ---------------------------------------------------------------------------
def normalize_tags(value):
    """Tag kapabilitas → ``(list[str], error)``.

    Aturan (tanpa mengarang nilai): harus **list**; setiap item string di-trim,
    item kosong dibuang, duplikat (case-insensitive) diambil yang pertama, panjang
    ≤ ``MAX_TAG_LENGTH``, jumlah ≤ ``MAX_TAGS``. Huruf **tidak** diubah supaya
    operator bebas memakai konvensi sendiri (konsisten ``LineAllocationRule.wc_type``
    yang juga disimpan apa adanya).
    """
    if value is None:
        return [], None
    if not isinstance(value, list):
        return None, "Field 'capability_tags' harus array string."

    tags: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            return None, "Field 'capability_tags' harus array string."
        tag = item.strip()
        if not tag:
            continue
        if len(tag) > MAX_TAG_LENGTH:
            return None, f"Tag kapabilitas '{tag}' maksimal {MAX_TAG_LENGTH} karakter."
        key = tag.lower()
        if key in seen:
            continue
        seen.add(key)
        tags.append(tag)

    if len(tags) > MAX_TAGS:
        return None, f"Tag kapabilitas maksimal {MAX_TAGS} buah."

    return tags, None


def _capacity(value):
    """``(Decimal, error)`` untuk ``capacity_per_hour`` (≥ 0, maks 10 digit/2 desimal)."""
    if isinstance(value, bool):
        return None, "Field 'capacity_per_hour' harus angka >= 0."
    try:
        capacity = Decimal(str(value).strip()) if not isinstance(value, Decimal) else value
    except (InvalidOperation, ValueError, AttributeError):
        return None, "Field 'capacity_per_hour' harus angka >= 0."
    if capacity.is_nan() or capacity < 0:
        return None, "Field 'capacity_per_hour' harus angka >= 0."
    if capacity > MAX_CAPACITY:
        return None, f"Field 'capacity_per_hour' maksimal {MAX_CAPACITY}."

    return capacity, None


def validate_work_center_payload(data, instance: WorkCenter | None = None):
    """Validasi body POST/PUT Work Center → ``(values, error)``.

    Saat create (``instance=None``): ``code`` & ``name`` **wajib**. Saat update:
    hanya field yang dikirim yang divalidasi/diubah.

    * ``code`` unik **case-insensitive** (mode = kode identitas operasional, bukan
      dibangkitkan otomatis seperti BOM/Partner);
    * ``wc_type`` opsional (free-form, ≤ 64);
    * ``capability_tags`` list string (lihat ``normalize_tags``);
    * ``capacity_per_hour`` ≥ 0 (lihat ``_capacity``);
    * ``active`` → ``is_active`` (nama publik).
    """
    payload = data if isinstance(data, dict) else {}
    values: dict = {}

    if instance is None or "code" in payload:
        code = str(payload.get("code") or "").strip()
        if not code:
            return None, "Field 'code' wajib diisi."
        if len(code) > MAX_CODE_LENGTH:
            return None, f"Field 'code' maksimal {MAX_CODE_LENGTH} karakter."
        duplicates = WorkCenter.objects.filter(code__iexact=code)
        if instance is not None:
            duplicates = duplicates.exclude(pk=instance.pk)
        if duplicates.exists():
            return None, f"Kode work center '{code}' sudah dipakai work center lain."
        values["code"] = code

    if instance is None or "name" in payload:
        name = str(payload.get("name") or "").strip()
        if not name:
            return None, "Field 'name' wajib diisi."
        if len(name) > MAX_NAME_LENGTH:
            return None, f"Field 'name' maksimal {MAX_NAME_LENGTH} karakter."
        values["name"] = name

    if "wc_type" in payload:
        wc_type = str(payload.get("wc_type") or "").strip()
        if len(wc_type) > MAX_WC_TYPE_LENGTH:
            return None, f"Field 'wc_type' maksimal {MAX_WC_TYPE_LENGTH} karakter."
        values["wc_type"] = wc_type

    if "capability_tags" in payload:
        tags, error = normalize_tags(payload.get("capability_tags"))
        if error:
            return None, error
        values["capability_tags"] = tags

    if "capacity_per_hour" in payload:
        capacity, error = _capacity(payload.get("capacity_per_hour"))
        if error:
            return None, error
        values["capacity_per_hour"] = capacity

    if "description" in payload:
        description = str(payload.get("description") or "").strip()
        if len(description) > MAX_DESCRIPTION_LENGTH:
            return None, f"Field 'description' maksimal {MAX_DESCRIPTION_LENGTH} karakter."
        values["description"] = description

    if "active" in payload:
        active = parse_bool(payload.get("active"))
        if active is None:
            return None, "Field 'active' harus true|false."
        values["is_active"] = active

    return values, None


# ---------------------------------------------------------------------------
# Tulis (create / update / soft delete) — data + ledger sync (SKIPPED) + audit
# ---------------------------------------------------------------------------
@dataclass
class WorkCenterWriteResult:
    """Hasil satu operasi tulis Work Center (dipakai view).

    **Tanpa** ``task_id``/``queued``: H1.7 MES-only → tidak ada task push yang
    di-enqueue; jejak sync cukup ditandai ``SyncStatus.SKIPPED``.
    """

    work_center: WorkCenter | None = None
    error: str | None = None
    sync_record_id: int | None = None

    @property
    def sync_status(self) -> str | None:
        """Status ledger yang ditulis (``SKIPPED``) — ``None`` kalau tak ada tulis."""
        return SyncStatus.SKIPPED.value if self.sync_record_id else None


def work_center_payload(work_center: WorkCenter) -> dict:
    """Payload yang disimpan di ``SyncRecord.payload`` (jejak audit master)."""
    return work_center_row(work_center)


def _record_mes_only(work_center: WorkCenter) -> int:
    """Tulis/segarkan ``SyncRecord`` lalu tandai ``SKIPPED``; kembalikan PK-nya.

    Satu baris per (resource, id, stage) seperti H1.1–H1.6, tetapi statusnya
    langsung ``SKIPPED`` + alasan baku di ``last_error`` sehingga monitor sync bisa
    menjelaskan kenapa Work Center tidak dikirim ke Odoo.
    """
    payload = work_center_payload(work_center)
    sync = SyncIdempotency()
    record = sync.get_or_create_sync_record(WORK_CENTER_RESOURCE, work_center.pk, STAGE, payload)

    if dict(record.payload or {}) != payload:
        record.payload = payload
        record.save(update_fields=("payload", "updated_at"))

    sync.mark_skipped(record, MES_ONLY_REASON)

    return record.pk


def _audit(
    action: str,
    work_center: WorkCenter,
    request,
    metadata: dict | None = None,
) -> None:
    """Tulis ``AuditLog`` — best-effort (audit tidak boleh menggagalkan CRUD)."""
    try:
        AuditLogger().log(
            user=None,
            action=action,
            resource=WORK_CENTER_RESOURCE,
            resource_id=work_center.pk,
            request=request,
            payload=work_center_payload(work_center),
            result=AuditLog.Result.OK,
            metadata={"mes_only": True, **(metadata or {})},
        )
    except Exception:  # noqa: BLE001 - audit tidak boleh menggagalkan CRUD master
        logger.exception(
            "master.work_center: gagal menulis audit (%s, wc %s).", action, work_center.pk
        )


def create_work_center(data, request=None) -> WorkCenterWriteResult:
    """Buat work center + ledger sync (SKIPPED, MES-only) + ``AuditLog``."""
    values, error = validate_work_center_payload(data)
    if error:
        return WorkCenterWriteResult(error=error)

    work_center = WorkCenter.objects.create(**values)
    record_id = _record_mes_only(work_center)
    _audit(ACTION_CREATE, work_center, request, {"code": work_center.code})

    logger.info(
        "master.work_center: WC %s (%s) dibuat (ledger=%s, MES-only).",
        work_center.pk,
        work_center.code,
        record_id,
    )
    return WorkCenterWriteResult(work_center=work_center, sync_record_id=record_id)


def update_work_center(work_center: WorkCenter, data, request=None) -> WorkCenterWriteResult:
    """Ubah work center (hanya field yang dikirim) + ledger sync (SKIPPED) + audit."""
    values, error = validate_work_center_payload(data, instance=work_center)
    if error:
        return WorkCenterWriteResult(work_center=work_center, error=error)

    if not values:
        # Tidak ada perubahan -> tidak ada ledger/audit.
        return WorkCenterWriteResult(work_center=work_center)

    for field, value in values.items():
        setattr(work_center, field, value)
    work_center.save()

    record_id = _record_mes_only(work_center)
    _audit(ACTION_UPDATE, work_center, request, {"fields": sorted(values)})

    logger.info(
        "master.work_center: WC %s (%s) diubah (ledger=%s, MES-only).",
        work_center.pk,
        work_center.code,
        record_id,
    )
    return WorkCenterWriteResult(work_center=work_center, sync_record_id=record_id)


def deactivate_work_center(work_center: WorkCenter, request=None) -> WorkCenterWriteResult:
    """Soft delete (``is_active=False``) + ledger sync (SKIPPED) + audit.

    **Guard dependensi**: 400 kalau WC masih memegang **bundle aktif**
    (``bundles`` yang state-nya di luar ``WCQueue.EXCLUDED_STATES``) — bundle yang
    sedang di queue/kerja harus dipindah lebih dulu supaya queue tidak menggantung.
    Bundle historis (DONE/CANCELLED) tidak menghalangi soft delete.
    """
    active = active_bundles_count(work_center)
    if active > 0:
        return WorkCenterWriteResult(
            work_center=work_center,
            error=(
                f"Work center '{work_center.code}' masih dipakai {active} bundle aktif; "
                "pindahkan/selesaikan bundle itu dulu (state bukan DONE/CANCELLED)."
            ),
        )

    if work_center.is_active:
        work_center.is_active = False
        work_center.save(update_fields=("is_active",))

    record_id = _record_mes_only(work_center)
    _audit(ACTION_DELETE, work_center, request, {"soft_delete": True})

    logger.info(
        "master.work_center: WC %s (%s) dinonaktifkan (ledger=%s, MES-only).",
        work_center.pk,
        work_center.code,
        record_id,
    )
    return WorkCenterWriteResult(work_center=work_center, sync_record_id=record_id)

