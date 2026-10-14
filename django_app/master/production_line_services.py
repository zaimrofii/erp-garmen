"""Service CRUD master Production Line (H1.8) — model **garment**, resource master.

Pola **sama** dengan ``master/work_center_services.py`` (H1.7): satu operasi tulis =
data + ``SyncRecord`` (``master.production_line`` / ``MASTER_PUSH``) + ``AuditLog``
(``master.create|update|delete``).

Kekhususan H1.8 — **MES-only** (keputusan pemilik proyek, berbasis probe Odoo 17):

  * `ProductionLine` milik app ``garment`` dan sudah dipakai `capability_allocator`
    (line mampu kalau **superset** work center routing), `Bundle.production_line`,
    serta `LineAllocationRule.line`;
  * probe: model ``mrp.routing`` **tidak ada lagi** di Odoo 17 (Routing dihapus sejak
    Odoo 15) dan ``mrp.routing.workcenter`` = **Operation** yang wajib menempel ke
    ``bom_id`` + satu ``workcenter_id`` (tanpa ``code``/``routing_id``) → Odoo tidak
    punya wadah "lini/kumpulan work center" ⇒ MES-only;
  * maka **tidak ada task push & tidak ada pull**; aturan "setiap CUD master →
    SyncRecord" tetap dipenuhi lewat ``SyncStatus.SKIPPED`` (``mark_skipped``, sama
    seperti H1.7) sehingga jejaknya terlihat di
    `/api/v1/sync/records/?status=SKIPPED` tanpa antrean palsu (tanpa view baru);
  * ``odoo_id`` **tidak** ditambahkan (tidak ada id ERP = tidak ada field mati);
  * M2M ``work_centers`` = **satu jalur tulis** (``ProductionLine.work_centers``);
    reverse ``WorkCenter.production_lines`` read-only; penulisan selalu
    ``work_centers.set()`` di dalam ``transaction.atomic`` setelah id WC divalidasi
    (tanpa state separuh kalau ada id ngawur);
  * guard soft delete = **bundle aktif** yang teratribusi line
    (``Bundle.production_line``, state di luar ``WCQueue.EXCLUDED_STATES``) —
    `WorkOrder` **tidak** punya FK ke line, dan `LineAllocationRule` (CASCADE) tidak
    memblokir karena soft delete tidak pernah menghapus baris (hanya dihitung sebagai info).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.db import transaction
from django.db.models import Count

from apps_industry.garment.models import ProductionLine, WorkCenter
from apps_industry.garment.services.wc_queue import WCQueue
from core.audit.models import AuditLog
from core.audit.services import AuditLogger
from integrations.erp_sync.idempotency import SyncIdempotency
from integrations.erp_sync.models import SyncResource, SyncStage, SyncStatus

from .services import ACTION_CREATE, ACTION_DELETE, ACTION_UPDATE, parse_bool
from .work_center_services import normalize_tags

logger = logging.getLogger(__name__)

__all__ = (
    "MES_ONLY_REASON",
    "ProductionLineWriteResult",
    "active_bundles_count",
    "create_production_line",
    "deactivate_production_line",
    "list_queryset",
    "production_line_detail_row",
    "production_line_row",
    "resolve_work_centers",
    "update_production_line",
    "validate_production_line_payload",
    "work_center_refs",
)

#: Resource sync (jangan ganti string literal di view).
PRODUCTION_LINE_RESOURCE = SyncResource.MASTER_PRODUCTION_LINE.value
STAGE = SyncStage.MASTER_PUSH.value

#: Alasan baku status ``SKIPPED`` (disimpan di ``SyncRecord.last_error``).
MES_ONLY_REASON = (
    "MES-only: Production Line tidak dikirim ke Odoo — Odoo 17 tidak punya wadah "
    "lini (model mrp.routing sudah dihapus; mrp.routing.workcenter = Operation per-BoM)."
)

#: Batas panjang (selaras kolom model — beda dari DB = 400, bukan 500).
MAX_CODE_LENGTH = 64
MAX_NAME_LENGTH = 150
MAX_DESCRIPTION_LENGTH = 2000


def _iso(value) -> str | None:
    """ISO-8601 atau ``None`` (datetime kosong)."""
    return value.isoformat() if value else None


def active_bundles_count(production_line: ProductionLine) -> int:
    """Jumlah bundle AKTIF yang teratribusi line (dasar guard soft delete).

    Definisi "aktif" memakai konstanta resmi ``WCQueue.EXCLUDED_STATES``
    (``DONE``/``CANCELLED``) → konsisten dengan queue & bottleneck detector.
    """
    return (
        production_line.bundles.exclude(state__in=WCQueue.EXCLUDED_STATES).count()
        if production_line.pk
        else 0
    )


def work_center_refs(production_line: ProductionLine) -> list[dict]:
    """Daftar work center anggota lini (urut kode) sebagai ``{id, code, name}``."""
    return [
        {"id": work_center.pk, "code": work_center.code, "name": work_center.name}
        for work_center in production_line.work_centers.all().order_by("code")
    ]


def _count_or_query(production_line: ProductionLine, attr: str, fallback) -> int:
    """Hasil ``annotate`` kalau ada (list view), else hitung lewat query (detail)."""
    annotated = getattr(production_line, attr, None)
    if annotated is not None:
        return int(annotated)

    return int(fallback())


def list_queryset():
    """QuerySet list + ``annotate`` jumlah WC & allocation rule (hindari N+1)."""
    return ProductionLine.objects.annotate(
        work_centers_count=Count("work_centers", distinct=True),
        allocation_rules_count=Count("allocation_rules", distinct=True),
    ).order_by("code")


def production_line_row(production_line: ProductionLine) -> dict:
    """Baris production line untuk API (list & detail) — JSON-safe.

    ``active`` = nama publik ``is_active`` (konsisten H1.1–H1.7).
    ``work_centers_count``/``allocation_rules_count`` memakai hasil ``annotate`` di
    list view dan fallback query saat dipanggil untuk satu objek. Daftar WC diekspor
    sebagai ``work_center_ids`` + ``work_center_names`` (M2M TANPA akhiran `_id`,
    bentuk daftar sesuai H1.1–H1.7).
    """
    refs = work_center_refs(production_line)

    return {
        "id": production_line.pk,
        "code": production_line.code,
        "name": production_line.name,
        "description": production_line.description,
        "capability_tags": list(production_line.capability_tags or []),
        "work_centers_count": _count_or_query(
            production_line, "work_centers_count", production_line.work_centers.count
        ),
        "work_center_ids": [ref["id"] for ref in refs],
        "work_center_names": [ref["code"] for ref in refs],
        "allocation_rules_count": _count_or_query(
            production_line, "allocation_rules_count", production_line.allocation_rules.count
        ),
        "active": bool(production_line.is_active),
        "created_at": _iso(production_line.created_at),
        "updated_at": _iso(production_line.updated_at),
    }


def production_line_detail_row(production_line: ProductionLine) -> dict:
    """Baris detail = ``production_line_row`` + ``work_centers[]`` + bundle aktif."""
    row = production_line_row(production_line)
    row["work_centers"] = work_center_refs(production_line)
    row["active_bundles_count"] = active_bundles_count(production_line)

    return row


# ---------------------------------------------------------------------------
# Validasi (PURE — dipakai view & test tanpa HTTP)
# ---------------------------------------------------------------------------
def resolve_work_centers(payload):
    """``work_center_ids`` → ``(list[WorkCenter] | None, error)``.

    ``None`` = field TIDAK dikirim (jangan sentuh M2M). List kosong **boleh**
    (lini tanpa anggota). Id harus angka > 0 & ADA di DB; kalau ada yang tidak
    dikenal → ``(None, error)`` supaya pemanggil membatalkan tanpa menyentuh M2M
    (dipakai bersama ``transaction.atomic`` → tidak ada state separuh).
    """
    if "work_center_ids" not in payload:
        return None, None

    raw = payload.get("work_center_ids")
    if raw is None:
        return [], None
    if not isinstance(raw, list):
        return None, "Field 'work_center_ids' harus array id work center."

    ids: list[int] = []
    for item in raw:
        if isinstance(item, bool):
            return None, f"Id work center {item!r} tidak valid (harus angka)."
        try:
            value = int(item)
        except (TypeError, ValueError):
            return None, f"Id work center {item!r} tidak valid (harus angka)."
        if value <= 0:
            return None, f"Id work center {item!r} tidak valid (harus > 0)."
        if value not in ids:
            ids.append(value)

    if not ids:
        return [], None

    found = {
        work_center.pk: work_center
        for work_center in WorkCenter.objects.filter(pk__in=ids).order_by("code")
    }
    missing = [value for value in ids if value not in found]
    if missing:
        daftar = ", ".join(str(value) for value in sorted(missing))
        return None, f"Work center tidak ditemukan: {daftar}."

    return [found[value] for value in ids], None


def validate_production_line_payload(data, instance: ProductionLine | None = None):
    """Validasi body POST/PUT Production Line → ``(values, error)``.

    Saat create (``instance=None``): ``code`` & ``name`` **wajib**; saat update hanya
    field yang dikirim yang divalidasi. ``code`` wajib & unik **case-insensitive**
    (identitas lini, bukan auto-generate — konsisten H1.7). ``capability_tags``
    memakai aturan Work Center (array string ≤ 20 × ≤ 32 karakter, trim + dedupe
    case-insensitive, huruf dipertahankan); ``work_center_ids`` divalidasi terpisah
    oleh ``resolve_work_centers``.
    """
    payload = data if isinstance(data, dict) else {}
    values: dict = {}

    if instance is None or "code" in payload:
        code = str(payload.get("code") or "").strip()
        if not code:
            return None, "Field 'code' wajib diisi."
        if len(code) > MAX_CODE_LENGTH:
            return None, f"Field 'code' maksimal {MAX_CODE_LENGTH} karakter."
        duplicates = ProductionLine.objects.filter(code__iexact=code)
        if instance is not None:
            duplicates = duplicates.exclude(pk=instance.pk)
        if duplicates.exists():
            return None, f"Kode production line '{code}' sudah dipakai line lain."
        values["code"] = code

    if instance is None or "name" in payload:
        name = str(payload.get("name") or "").strip()
        if not name:
            return None, "Field 'name' wajib diisi."
        if len(name) > MAX_NAME_LENGTH:
            return None, f"Field 'name' maksimal {MAX_NAME_LENGTH} karakter."
        values["name"] = name

    if "description" in payload:
        description = str(payload.get("description") or "").strip()
        if len(description) > MAX_DESCRIPTION_LENGTH:
            return None, f"Field 'description' maksimal {MAX_DESCRIPTION_LENGTH} karakter."
        values["description"] = description

    if "capability_tags" in payload:
        tags, error = normalize_tags(payload.get("capability_tags"))
        if error:
            return None, error
        values["capability_tags"] = tags

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
class ProductionLineWriteResult:
    """Hasil satu operasi tulis Production Line (dipakai view).

    **Tanpa** ``task_id``/``queued``: H1.8 MES-only → tidak ada task push yang
    di-enqueue; jejak sync cukup ditandai ``SyncStatus.SKIPPED``.
    """

    production_line: ProductionLine | None = None
    error: str | None = None
    sync_record_id: int | None = None

    @property
    def sync_status(self) -> str | None:
        """Status ledger yang ditulis (``SKIPPED``) — ``None`` kalau tak ada tulis."""
        return SyncStatus.SKIPPED.value if self.sync_record_id else None


def production_line_payload(production_line: ProductionLine) -> dict:
    """Payload yang disimpan di ``SyncRecord.payload`` (jejak audit master)."""
    row = production_line_row(production_line)

    return {
        "code": row["code"],
        "name": row["name"],
        "description": row["description"],
        "capability_tags": row["capability_tags"],
        "work_center_ids": row["work_center_ids"],
        "active": row["active"],
    }


def _record_mes_only(production_line: ProductionLine) -> int:
    """Tulis/segarkan ``SyncRecord`` lalu tandai ``SKIPPED``; kembalikan PK-nya.

    Satu baris per (resource, id, stage) seperti H1.1–H1.7; statusnya langsung
    ``SKIPPED`` + alasan baku di ``last_error`` supaya monitor sync bisa menjelaskan
    kenapa Production Line tidak dikirim ke Odoo.
    """
    payload = production_line_payload(production_line)
    sync = SyncIdempotency()
    record = sync.get_or_create_sync_record(
        PRODUCTION_LINE_RESOURCE, production_line.pk, STAGE, payload
    )

    if dict(record.payload or {}) != payload:
        record.payload = payload
        record.save(update_fields=("payload", "updated_at"))

    sync.mark_skipped(record, MES_ONLY_REASON)

    return record.pk


def _audit(
    action: str, production_line: ProductionLine, request, metadata: dict | None = None
) -> None:
    """Tulis ``AuditLog`` — best-effort (audit tidak boleh menggagalkan CRUD)."""
    try:
        AuditLogger().log(
            user=None,
            action=action,
            resource=PRODUCTION_LINE_RESOURCE,
            resource_id=production_line.pk,
            request=request,
            payload=production_line_payload(production_line),
            result=AuditLog.Result.OK,
            metadata={"mes_only": True, **(metadata or {})},
        )
    except Exception:  # noqa: BLE001 - audit tidak boleh menggagalkan CRUD master
        logger.exception(
            "master.production_line: gagal menulis audit (%s, line %s).",
            action,
            production_line.pk,
        )


def create_production_line(data, request=None) -> ProductionLineWriteResult:
    """Buat production line (+ M2M ``work_centers``) + ledger ``SKIPPED`` + audit."""
    values, error = validate_production_line_payload(data)
    if error:
        return ProductionLineWriteResult(error=error)

    payload = data if isinstance(data, dict) else {}
    work_centers, error = resolve_work_centers(payload)
    if error:
        return ProductionLineWriteResult(error=error)

    with transaction.atomic():
        production_line = ProductionLine.objects.create(**values)
        if work_centers:
            production_line.work_centers.set(work_centers)

    record_id = _record_mes_only(production_line)
    _audit(
        ACTION_CREATE,
        production_line,
        request,
        {"code": production_line.code, "work_centers": len(work_centers or [])},
    )

    logger.info(
        "master.production_line: line %s (%s) dibuat (ledger=%s, MES-only).",
        production_line.pk,
        production_line.code,
        record_id,
    )
    return ProductionLineWriteResult(production_line=production_line, sync_record_id=record_id)


def update_production_line(
    production_line: ProductionLine, data, request=None
) -> ProductionLineWriteResult:
    """Ubah production line (+ replace M2M) + ledger ``SKIPPED`` + audit.

    Replace M2M bersifat **atomic**: id WC divalidasi lebih dulu; kalau ada id ngawur
    → 400 dan M2M lama **tidak** tersentuh (tidak ada state separuh).
    """
    values, error = validate_production_line_payload(data, instance=production_line)
    if error:
        return ProductionLineWriteResult(production_line=production_line, error=error)

    payload = data if isinstance(data, dict) else {}
    work_centers, error = resolve_work_centers(payload)
    if error:
        return ProductionLineWriteResult(production_line=production_line, error=error)

    current_ids = sorted(production_line.work_centers.values_list("pk", flat=True))
    next_ids = (
        None
        if work_centers is None
        else sorted(work_center.pk for work_center in work_centers)
    )
    m2m_changed = next_ids is not None and next_ids != current_ids

    if not values and not m2m_changed:
        # Tidak ada perubahan -> tidak ada ledger/audit.
        return ProductionLineWriteResult(production_line=production_line)

    with transaction.atomic():
        if values:
            for field, value in values.items():
                setattr(production_line, field, value)
            production_line.save()
        if m2m_changed and work_centers is not None:
            production_line.work_centers.set(work_centers)

    record_id = _record_mes_only(production_line)
    _audit(
        ACTION_UPDATE,
        production_line,
        request,
        {"fields": sorted(values), "work_centers_replaced": bool(m2m_changed)},
    )

    logger.info(
        "master.production_line: line %s (%s) diubah (ledger=%s, MES-only).",
        production_line.pk,
        production_line.code,
        record_id,
    )
    return ProductionLineWriteResult(production_line=production_line, sync_record_id=record_id)


def deactivate_production_line(
    production_line: ProductionLine, request=None
) -> ProductionLineWriteResult:
    """Soft delete (``is_active=False``) + ledger ``SKIPPED`` + audit.

    **Guard dependensi**: 400 kalau line masih menampung **bundle aktif** (state di
    luar ``WCQueue.EXCLUDED_STATES``). ``WorkOrder`` tidak punya FK ke line, dan
    ``LineAllocationRule`` (CASCADE) tidak memblokir — soft delete tidak pernah
    menghapus baris, jumlah rule hanya dilaporkan lewat ``allocation_rules_count``.
    """
    active = active_bundles_count(production_line)
    if active > 0:
        return ProductionLineWriteResult(
            production_line=production_line,
            error=(
                f"Production line '{production_line.code}' masih dipakai {active} bundle "
                "aktif; pindahkan/selesaikan bundle itu dulu (state bukan DONE/CANCELLED)."
            ),
        )

    if production_line.is_active:
        production_line.is_active = False
        production_line.save(update_fields=("is_active",))

    record_id = _record_mes_only(production_line)
    _audit(ACTION_DELETE, production_line, request, {"soft_delete": True})

    logger.info(
        "master.production_line: line %s (%s) dinonaktifkan (ledger=%s, MES-only).",
        production_line.pk,
        production_line.code,
        record_id,
    )
    return ProductionLineWriteResult(production_line=production_line, sync_record_id=record_id)
