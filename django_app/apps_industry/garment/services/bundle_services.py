"""Service Bundle (H2.4) — CRUD + split/merge, **perubahan OBJEK** bundle MES.

`Bundle` sudah ada sejak Sprint 2.1/2.2 (unit pelacakan terkecil: kode
`{order_line_id}-{SIZE}-{seq:03d}`, `size`, `qty`, `qty_done`, `state`,
`current_work_center`, `production_line`, dan `version` SHA-256 state kritis yang
dihitung di `Bundle.save()` — **JANGAN diubah**). Service ini melengkapi jalur yang
sudah ada (F2 `POST /garmen/bundles/` lewat `BundleEngine`, aksi state machine
seeded, chatter `BundleEvent`) dengan create/update/delete hibrida + split/merge.

**MES-only sebagai OBJEK.** Probe STEP 0 (read-only): Odoo tidak punya model bundle
(`garment.bundle`/`wo.bundle`/`mrp.bundle`/`stock.bundle`/`bundle.bundle` ⇒ "Objek
tidak ada") dan tidak ada field `bundle` di `stock.move`/`stock.move.line`/
`stock.picking`/`stock.lot`/`mrp.workorder`; 0 dari 192 `stock.move` memuat kode bundle
MES. Jadi CUD bundle hanya meninggalkan jejak ledger
`SyncRecord(resource="bundle", stage="BUNDLE_PUSH")` status **SKIPPED** + `AuditLog`.
**PERGERAKAN** stok bundle (WIP/FG per `SyncResource.BUNDLE` stage `WIP`/`FG` dan
scrap) tetap lewat jalur lama — TIDAK disentuh di sini.

Delete = **hibrida** (keputusan pemilik proyek): hanya `DRAFT` yang **belum** punya
`BundleEvent`, **belum** punya record pergerakan (`WIP`/`FG`), dan belum punya
`ScrapAccumulator` yang boleh dihapus permanen; selain itu **409**. State machine
bundle (`garment.bundle`) TIDAK punya `CANCELLED` ⇒ tidak ada soft delete & seed
machine TIDAK diubah.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction

from core.audit.models import AuditLog
from core.audit.services import AuditLogger
from integrations.erp_sync.idempotency import SyncIdempotency
from integrations.erp_sync.models import (
    STAGE_BUNDLE_PUSH,
    STAGE_FG,
    STAGE_WIP,
    SyncRecord,
    SyncResource,
    SyncStatus,
)

from ..models import (
    Bundle,
    BundleEvent,
    OrderLine,
    ProductionLine,
    ScrapAccumulator,
    WorkCenter,
    WorkOrder,
)
from .bundle_engine import BundleEngine
from .exceptions import BundleEngineError

logger = logging.getLogger(__name__)

__all__ = (
    "ACTION_CREATE",
    "ACTION_DELETE",
    "ACTION_MERGE",
    "ACTION_SPLIT",
    "ACTION_UPDATE",
    "BUNDLE_RESOURCE",
    "BUNDLE_STAGE",
    "BUNDLE_STATES",
    "BundleServiceError",
    "BundleWriteResult",
    "bundle_detail_row",
    "bundle_payload",
    "bundle_row",
    "create_bundles",
    "delete_bundle",
    "merge_bundles",
    "preview_bundles",
    "split_bundle",
    "update_bundle",
)

#: Resource & stage ledger (jangan ganti literal di view/test).
BUNDLE_RESOURCE = SyncResource.BUNDLE.value
BUNDLE_STAGE = STAGE_BUNDLE_PUSH
#: Stage pergerakan stok yang menandakan bundle sudah bergerak (guard delete).
MOVEMENT_STAGES = (STAGE_WIP, STAGE_FG)

#: State WO yang boleh melahirkan bundle (selaras F2/`create_view`).
BUNDLE_SOURCE_STATES: tuple[str, ...] = ("DRAFT",)
#: State bundle MES = state machine yang di-SEED (`garment.bundle`).
BUNDLE_STATES: tuple[str, ...] = ("DRAFT", "CUTTING", "SEWING", "QC", "DONE")

SKIPPED_REASON = (
    "MES-only: Odoo tidak punya model Bundle (probe H2.4: `garment.bundle`/"
    "`mrp.bundle`/`stock.bundle` tidak ada; tidak ada field `bundle` di stock.move/"
    "stock.picking). Pergerakan stok bundle tetap lewat stage WIP/FG."
)

MAX_CODE_LENGTH = 64
MAX_SIZE_LENGTH = 32
MAX_SKU_LENGTH = 64
MAX_QTY = 1_000_000
MAX_SPLIT_PARTS = 20
MAX_MERGE_SOURCES = 20
MAX_MATRIX_SIZE_KEYS = 30

ACTION_CREATE = "bundle.create"
ACTION_UPDATE = "bundle.update"
ACTION_DELETE = "bundle.delete"
ACTION_SPLIT = "bundle.split"
ACTION_MERGE = "bundle.merge"


class BundleServiceError(ValidationError):
    """Error validasi bundle → dipetakan view menjadi **400**."""


@dataclass
class BundleWriteResult:
    """Hasil operasi tulis bundle (dipakai view)."""

    bundle: Bundle | None = None
    bundles: list = field(default_factory=list)
    error: str | None = None
    #: True kalau resource tidak ada (view → 404).
    not_found: bool = False
    #: True kalau ditolak karena state/jejak (view → 409).
    conflict: bool = False
    deleted: bool = False
    #: Id ledger bundle utama.
    ledger_id: int | None = None
    #: Ringkasan (mis. {"created": 3}) / rencana preview.
    summary: dict = field(default_factory=dict)
    plan: list = field(default_factory=list)


def _iso(value) -> str | None:
    """ISO-8601 atau ``None``."""
    return value.isoformat() if value else None


def _int(value) -> int | None:
    """Konversi aman ke ``int`` (gagal → ``None``)."""
    try:
        return int(value)
    except (TypeError, ValueError, InvalidOperation):
        return None


def _text(value) -> str:
    """Teks bersih (``None`` → ``''``)."""
    return "" if value is None else str(value).strip()


def _decimal(value) -> Decimal:
    """Konversi aman ke ``Decimal`` (pembanding angka)."""
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


# ---------------------------------------------------------------------------
# Validasi
# ---------------------------------------------------------------------------
def _resolve_work_order(raw):
    """``(work_order, error, not_found)`` — WO sumber bundle (DRAFT, belum punya bundle)."""
    if raw in (None, ""):
        return None, "Field 'work_order_id' wajib diisi.", False

    work_order_id = _int(raw)
    if work_order_id is None:
        return None, "Field 'work_order_id' harus berupa angka.", False

    work_order = (
        WorkOrder.objects.select_related(
            "order_line", "order_line__product", "order_line__order"
        )
        .filter(pk=work_order_id)
        .first()
    )
    if work_order is None:
        return None, f"WorkOrder {work_order_id} tidak ditemukan.", True
    if work_order.state not in BUNDLE_SOURCE_STATES:
        return (
            None,
            (
                f"WorkOrder {work_order.code} state={work_order.state}; bundle hanya bisa "
                f"dibuat dari {', '.join(BUNDLE_SOURCE_STATES)}."
            ),
            False,
        )
    if Bundle.objects.filter(work_order=work_order).exists():
        return None, f"WorkOrder {work_order.code} sudah punya bundle (idempoten).", False

    return work_order, None, False


def _resolve_order_line(raw):
    """``(order_line, error, not_found)`` — jalur kompatibilitas F2 (`order_line_id`)."""
    if raw in (None, ""):
        return None, "Field 'order_line_id' wajib diisi.", False

    order_line_id = _int(raw)
    if order_line_id is None:
        return None, "Field 'order_line_id' harus berupa angka.", False

    order_line = (
        OrderLine.objects.select_related("order", "product").filter(pk=order_line_id).first()
    )
    if order_line is None:
        return None, f"OrderLine {order_line_id} tidak ditemukan.", True

    return order_line, None, False


def _validate_size_matrix(raw):
    """``(matrix, error)`` — dict ``{size: qty}`` (qty int ≥ 0, total > 0)."""
    if not isinstance(raw, dict) or not raw:
        return None, "Field 'size_matrix' wajib objek {size: qty} tidak kosong."
    if len(raw) > MAX_MATRIX_SIZE_KEYS:
        return None, f"Field 'size_matrix' maksimal {MAX_MATRIX_SIZE_KEYS} ukuran."

    matrix: dict[str, int] = {}
    for size, qty in raw.items():
        size_code = _text(size).upper()
        if not size_code:
            return None, "Kode size tidak boleh kosong."
        if len(size_code) > MAX_SIZE_LENGTH:
            return None, f"Kode size maksimal {MAX_SIZE_LENGTH} karakter."
        qty_int = _int(qty)
        if qty_int is None or qty_int < 0 or qty_int > MAX_QTY:
            return None, f"qty untuk size '{size_code}' harus integer 0..{MAX_QTY}."
        matrix[size_code] = matrix.get(size_code, 0) + qty_int

    if sum(matrix.values()) <= 0:
        return None, "Total qty (sum size_matrix) harus > 0."

    return matrix, None


def _validate_bundle_size(raw):
    """``(bundle_size, error)`` — integer > 0 (default 1 bila kosong)."""
    if raw in (None, ""):
        return 1, None

    size = _int(raw)
    if size is None or size <= 0 or size > MAX_QTY:
        return None, f"Field 'bundle_size' harus integer 1..{MAX_QTY}."

    return size, None


def validate_bundle_payload(data, instance: Bundle | None = None):
    """Validasi payload bundle → ``(values, error, not_found)``.

    Create: ``size_matrix`` + ``bundle_size`` + (``work_order_id`` **atau**
    ``order_line_id`` demi kompatibilitas F2). Update: hanya ``size``, ``sku_variant``,
    ``qty``, ``current_work_center_id``, ``production_line_id`` (``code``/``state``
    TIDAK bisa diubah di sini).
    """
    payload = data if isinstance(data, dict) else {}
    values: dict = {}

    if instance is None:
        if "work_order_id" in payload:
            work_order, error, not_found = _resolve_work_order(payload.get("work_order_id"))
            if error:
                return None, error, not_found
            values["work_order"] = work_order
            values["order_line"] = work_order.order_line
        else:
            order_line, error, not_found = _resolve_order_line(payload.get("order_line_id"))
            if error:
                return None, error, not_found
            first = order_line.work_orders.order_by("id").first()
            if first is None:
                return (
                    None,
                    (
                        f"order line {order_line.pk} belum punya WorkOrder; buat work order "
                        "dulu sebelum membentuk bundle."
                    ),
                    False,
                )
            if first.state not in BUNDLE_SOURCE_STATES:
                return (
                    None,
                    (
                        f"WorkOrder {first.code} state={first.state}; bundle hanya bisa "
                        f"dibuat dari {', '.join(BUNDLE_SOURCE_STATES)}."
                    ),
                    False,
                )
            if Bundle.objects.filter(work_order=first).exists():
                return None, f"WorkOrder {first.code} sudah punya bundle (idempoten).", False
            values["work_order"] = first
            values["order_line"] = order_line

        matrix, error = _validate_size_matrix(payload.get("size_matrix"))
        if error:
            return None, error, False
        bundle_size, error = _validate_bundle_size(payload.get("bundle_size"))
        if error:
            return None, error, False

        sku_variant = _text(payload.get("sku_variant"))
        if len(sku_variant) > MAX_SKU_LENGTH:
            return None, f"Field 'sku_variant' maksimal {MAX_SKU_LENGTH} karakter.", False

        values["size_matrix"] = matrix
        values["bundle_size"] = bundle_size
        values["sku_variant"] = sku_variant

        return values, None, False

    # --- update -------------------------------------------------------------
    if "code" in payload:
        return (
            None,
            (
                "Field 'code' tidak dapat diubah (dipakai jejak WIP/FG & chatter); buat "
                "bundle baru bila kode harus berbeda."
            ),
            False,
        )
    if "state" in payload:
        return (
            None,
            (
                "Field 'state' tidak dapat diubah langsung; gunakan endpoint aksi "
                "(BUNDLE_START/BUNDLE_ADVANCE/BUNDLE_QC/BUNDLE_FINISH/BUNDLE_SCRAP)."
            ),
            False,
        )

    if "size" in payload:
        size = _text(payload.get("size")).upper()
        if len(size) > MAX_SIZE_LENGTH:
            return None, f"Field 'size' maksimal {MAX_SIZE_LENGTH} karakter.", False
        values["size"] = size

    if "sku_variant" in payload:
        sku_variant = _text(payload.get("sku_variant"))
        if len(sku_variant) > MAX_SKU_LENGTH:
            return None, f"Field 'sku_variant' maksimal {MAX_SKU_LENGTH} karakter.", False
        values["sku_variant"] = sku_variant

    if "qty" in payload:
        qty = _int(payload.get("qty"))
        if qty is None or qty <= 0 or qty > MAX_QTY:
            return None, f"Field 'qty' harus integer 1..{MAX_QTY}.", False
        if qty < int(instance.qty_done or 0):
            return (
                None,
                f"qty ({qty}) tidak boleh lebih kecil dari qty_done ({instance.qty_done}).",
                False,
            )
        values["qty"] = qty

    if "current_work_center_id" in payload:
        raw_wc = payload.get("current_work_center_id")
        if raw_wc in (None, ""):
            values["current_work_center"] = None
        else:
            wc_id = _int(raw_wc)
            wc = WorkCenter.objects.filter(pk=wc_id).first() if wc_id is not None else None
            if wc is None:
                return None, f"WorkCenter {raw_wc} tidak ditemukan.", True
            values["current_work_center"] = wc

    if "production_line_id" in payload:
        raw_line = payload.get("production_line_id")
        if raw_line in (None, ""):
            values["production_line"] = None
        else:
            line_id = _int(raw_line)
            line = (
                ProductionLine.objects.filter(pk=line_id).first()
                if line_id is not None
                else None
            )
            if line is None:
                return None, f"ProductionLine {raw_line} tidak ditemukan.", True
            values["production_line"] = line

    return values, None, False


# ---------------------------------------------------------------------------
# Serialisasi baris (H2.4 — superset; list/detail F3 TIDAK diubah)
# ---------------------------------------------------------------------------
def bundle_row(bundle: Bundle) -> dict:
    """Satu baris bundle versi H2.4 (superset: + WO/order line + jejak sync)."""
    work_order = bundle.work_order
    order_line = work_order.order_line if work_order is not None else None

    return {
        "id": bundle.pk,
        "code": bundle.code,
        "state": bundle.state,
        "size": bundle.size,
        "sku_variant": bundle.sku_variant,
        "qty": bundle.qty,
        "qty_done": bundle.qty_done,
        "version": bundle.version,
        "work_order_id": bundle.work_order_id,
        "work_order_code": getattr(work_order, "code", None),
        "order_line_id": getattr(order_line, "pk", None),
        "order_code": getattr(getattr(order_line, "order", None), "code", None),
        "product_code": getattr(getattr(order_line, "product", None), "code", None),
        "current_work_center_id": bundle.current_work_center_id,
        "current_work_center_code": getattr(bundle.current_work_center, "code", None),
        "production_line_id": bundle.production_line_id,
        "production_line_code": getattr(bundle.production_line, "code", None),
        "events_count": BundleEvent.objects.filter(bundle=bundle).count(),
        "ledger_status": SyncStatus.SKIPPED.value,
        "created_at": _iso(bundle.created_at),
        "updated_at": _iso(bundle.updated_at),
    }


def bundle_detail_row(bundle: Bundle) -> dict:
    """Detail bundle versi H2.4 = ``bundle_row`` + aksi state machine yang diizinkan."""
    from apps_industry.garment.api.resources.bundle import BundleSchemaBuilder

    builder = BundleSchemaBuilder(instance=bundle, request=None)
    row = bundle_row(bundle)
    row["allowed_actions"] = builder.get_state_machine()["allowed_actions"]

    return row


def bundle_payload(bundle: Bundle) -> dict:
    """Payload jejak ledger/audit bundle (MES-only — tidak dikirim ke Odoo)."""
    return {
        "code": bundle.code,
        "state": bundle.state,
        "size": bundle.size,
        "sku_variant": bundle.sku_variant,
        "qty": bundle.qty,
        "qty_done": bundle.qty_done,
        "work_order_id": bundle.work_order_id,
        "work_order_code": getattr(bundle.work_order, "code", None),
        "current_work_center_code": getattr(bundle.current_work_center, "code", None),
        "production_line_code": getattr(bundle.production_line, "code", None),
        "mes_only": True,
    }


# ---------------------------------------------------------------------------
# Ledger (SKIPPED) + audit + guard
# ---------------------------------------------------------------------------
def _write_ledger(bundle: Bundle, action: str) -> SyncRecord:
    """Tulis/perbarui ``SyncRecord`` bundle (stage ``BUNDLE_PUSH``) → **SKIPPED**."""
    payload = {**bundle_payload(bundle), "action": action}
    sync = SyncIdempotency()
    record = sync.get_or_create_sync_record(BUNDLE_RESOURCE, bundle.pk, BUNDLE_STAGE, payload)

    if dict(record.payload or {}) != payload or record.last_error != SKIPPED_REASON:
        record.payload = payload
        record.save(update_fields=("payload", "updated_at"))

    return sync.mark_skipped(record, SKIPPED_REASON)


def _audit(action: str, bundle: Bundle, request, metadata: dict | None = None) -> None:
    """Tulis ``AuditLog`` — best-effort (audit tidak boleh menggagalkan CRUD)."""
    try:
        AuditLogger().log(
            user=None,
            action=action,
            resource=BUNDLE_RESOURCE,
            resource_id=bundle.pk,
            request=request,
            payload=bundle_payload(bundle),
            result=AuditLog.Result.OK,
            metadata={"mes_only": True, **(metadata or {})},
        )
    except Exception:  # noqa: BLE001 - audit tidak boleh menggagalkan transaksi bundle
        logger.exception("bundle: gagal menulis audit (%s, bundle %s).", action, bundle.pk)


def _movement_records(bundle: Bundle):
    """QuerySet ``SyncRecord`` pergerakan stok (WIP/FG) bundle ini."""
    return SyncRecord.objects.filter(
        resource=BUNDLE_RESOURCE, resource_id=str(bundle.pk), stage__in=MOVEMENT_STAGES
    )


def _assert_draft(bundle: Bundle, verb: str) -> str | None:
    """Guard: hanya DRAFT yang boleh diubah/dipecah (state lain sudah di lantai)."""
    if bundle.state != "DRAFT":
        return f"Bundle {bundle.code} berstatus {bundle.state}; {verb} hanya boleh saat DRAFT."
    return None


def _movement_block(bundle: Bundle) -> str | None:
    """Guard: bundle yang sudah bergerak (event/WIP/FG/scrap) tidak boleh diubah strukturnya."""
    if BundleEvent.objects.filter(bundle=bundle).exists():
        return f"Bundle {bundle.code} sudah punya event produksi (chatter); operasi ditolak."
    if _movement_records(bundle).exists():
        return (
            f"Bundle {bundle.code} sudah punya jejak pergerakan stok (WIP/FG); operasi ditolak."
        )
    if ScrapAccumulator.objects.filter(bundle=bundle).exists():
        return f"Bundle {bundle.code} sudah punya catatan scrap; operasi ditolak."
    return None


# ---------------------------------------------------------------------------
# CREATE / PREVIEW
# ---------------------------------------------------------------------------
def _unique_code(order_line_id: int, size: str, seq: int, work_order_id: int) -> str:
    """Kode bundle unik & deterministik (``{order_line}-{SIZE}-{seq:03d}`` gaya engine).

    Kalau kode gaya engine sudah terpakai (mis. order line yang sama sudah dipecah ke
    beberapa WorkOrder H2.3), fallback ke ``{work_order}-{SIZE}-{seq:03d}`` lalu naikkan
    ``seq`` sampai bebas — anti tabrakan, tetap deterministik.
    """
    candidates = (
        f"{order_line_id}-{size}-{seq:03d}",
        f"{work_order_id}-{size}-{seq:03d}",
    )
    for code in candidates:
        if not Bundle.objects.filter(code=code).exists():
            return code

    bumped = seq
    while True:
        bumped += 1
        code = f"{order_line_id}-{size}-{bumped:03d}"
        if not Bundle.objects.filter(code=code).exists():
            return code


def _code_for_item(item: dict, order_line_id: int, work_order_id: int) -> str:
    """Kode final satu item rencana engine (seq diambil dari kode engine ⇒ konsisten)."""
    try:
        seq = int(str(item.get("code", "")).rsplit("-", 1)[-1])
    except (TypeError, ValueError):
        seq = 1

    return _unique_code(order_line_id, str(item["size"]), seq, work_order_id)


def preview_bundles(data):
    """Rencana bundle **tanpa menyimpan** (dipakai form create H2.4) → ``BundleWriteResult``.

    Memakai ``BundleEngine.preview_bundles`` (service lama, tidak diubah) supaya kode &
    pemecahan qty identik dengan hasil create.
    """
    values, error, not_found = validate_bundle_payload(data)
    if error:
        return BundleWriteResult(error=error, not_found=not_found)

    work_order = values["work_order"]
    order_line = values["order_line"]

    try:
        plan = BundleEngine.preview_bundles(
            order_line, values["size_matrix"], values["bundle_size"]
        )
    except BundleEngineError as exc:
        return BundleWriteResult(error=str(exc))

    rows = [
        {
            "code": _code_for_item(item, order_line.pk, work_order.pk),
            "size": item["size"],
            "sku_variant": values["sku_variant"],
            "qty": item["qty"],
            "work_order_id": work_order.pk,
        }
        for item in plan
    ]

    return BundleWriteResult(
        bundles=[],
        plan=rows,
        summary={"created": 0, "planned": len(rows), "total_qty": sum(r["qty"] for r in rows)},
    )


def create_bundles(data, request=None) -> BundleWriteResult:
    """Buat bundle dari ``size_matrix`` + ``bundle_size`` untuk satu **WorkOrder**.

    Kompatibel jalur F2 (``order_line_id`` ⇒ memakai WO pertama order line, guard DRAFT &
    idempoten) **dan** mendukung ``work_order_id`` eksplisit (H2.3 memungkinkan >1 WO per
    order line ⇒ bundle harus menempel ke WO yang dipilih, bukan selalu WO pertama).
    """
    values, error, not_found = validate_bundle_payload(data)
    if error:
        return BundleWriteResult(error=error, not_found=not_found)

    work_order = values["work_order"]
    order_line = values["order_line"]
    matrix = values["size_matrix"]
    bundle_size = values["bundle_size"]
    sku_variant = values["sku_variant"]

    try:
        plan = BundleEngine.preview_bundles(order_line, matrix, bundle_size)
    except BundleEngineError as exc:
        return BundleWriteResult(error=str(exc))

    if not plan:
        return BundleWriteResult(error="Rencana bundle kosong (cek size_matrix/bundle_size).")

    created: list[Bundle] = []
    with transaction.atomic():
        for item in plan:
            created.append(
                Bundle.objects.create(
                    code=_code_for_item(item, order_line.pk, work_order.pk),
                    work_order=work_order,
                    size=item["size"],
                    sku_variant=sku_variant,
                    qty=item["qty"],
                )
            )

    records = [_write_ledger(bundle, "create") for bundle in created]
    _audit(
        ACTION_CREATE,
        created[0],
        request,
        {
            "work_order_id": work_order.pk,
            "created": len(created),
            "bundle_size": bundle_size,
            "sizes": sorted(matrix),
        },
    )

    logger.info(
        "bundle: %s bundle dibuat untuk WO %s (order line %s) — MES-only, ledger SKIPPED.",
        len(created),
        work_order.pk,
        order_line.pk,
    )

    return BundleWriteResult(
        bundle=created[0],
        bundles=created,
        ledger_id=records[0].pk,
        summary={"created": len(created), "total_qty": sum(b.qty for b in created)},
    )


# ---------------------------------------------------------------------------
# UPDATE / DELETE
# ---------------------------------------------------------------------------
def update_bundle(bundle: Bundle, data, request=None) -> BundleWriteResult:
    """Ubah bundle (``size``/``sku_variant``/``qty``/WC/line) — **hanya DRAFT**.

    ``code``/``state`` tidak bisa diubah di sini. ``version`` TIDAK dihitung ulang di
    service: `Bundle.save()` yang melakukannya (state kritis berubah ⇒ version baru),
    jadi optimistic lock frontend (`X-Base-Version`) tetap sah.
    """
    error = _assert_draft(bundle, "perubahan")
    if error:
        return BundleWriteResult(bundle=bundle, error=error)

    values, error, not_found = validate_bundle_payload(data, instance=bundle)
    if error:
        return BundleWriteResult(bundle=bundle, error=error, not_found=not_found)
    if not values:
        return BundleWriteResult(bundle=bundle)

    for field, value in values.items():
        setattr(bundle, field, value)
    bundle.save()

    record = _write_ledger(bundle, "update")
    _audit(ACTION_UPDATE, bundle, request, {"fields": sorted(values)})

    logger.info("bundle: %s diubah (ledger=%s).", bundle.code, record.pk)

    return BundleWriteResult(bundle=bundle, ledger_id=record.pk)


def delete_bundle(bundle: Bundle, request=None) -> BundleWriteResult:
    """Hapus bundle — **hibrida** (keputusan pemilik proyek H2.4).

    Hanya boleh dihapus permanen bila: `DRAFT` **dan** belum punya `BundleEvent`
    **dan** belum punya record pergerakan stok (WIP/FG) **dan** belum punya catatan
    scrap. Selain itu **409** (`conflict=True`) — state machine bundle TIDAK punya
    `CANCELLED`, jadi tidak ada soft delete & seed machine tidak diubah.
    """
    block = _movement_block(bundle) or _assert_draft(bundle, "penghapusan")
    if block:
        return BundleWriteResult(bundle=bundle, conflict=True, error=block)

    code = bundle.code
    pk = bundle.pk
    _audit(ACTION_DELETE, bundle, request, {"hard_delete": True})
    SyncRecord.objects.filter(
        resource=BUNDLE_RESOURCE, resource_id=str(pk), stage=BUNDLE_STAGE
    ).delete()
    bundle.delete()

    logger.info("bundle: %s (%s) dihapus permanen (DRAFT tanpa jejak produksi).", pk, code)

    return BundleWriteResult(deleted=True)


# ---------------------------------------------------------------------------
# SPLIT / MERGE (perubahan struktur; hanya DRAFT tanpa jejak produksi)
# ---------------------------------------------------------------------------
def _resolve_parts(raw):
    """``(parts, error)`` — daftar qty hasil split (integer > 0, minimal 2 bagian)."""
    if not isinstance(raw, list):
        return None, "Field 'parts' wajib array qty (integer > 0)."
    if len(raw) < 2:
        return None, "Split minimal 2 bagian."
    if len(raw) > MAX_SPLIT_PARTS:
        return None, f"Split maksimal {MAX_SPLIT_PARTS} bagian."

    parts: list[int] = []
    for index, item in enumerate(raw):
        qty = _int(item)
        if qty is None or qty <= 0 or qty > MAX_QTY:
            return None, f"parts[{index}] harus integer 1..{MAX_QTY}."
        parts.append(qty)

    return parts, None


def split_bundle(bundle: Bundle, data, request=None) -> BundleWriteResult:
    """Pecah satu bundle menjadi ``len(parts)`` bagian — DRAFT & belum bergerak.

    Semantik (konsisten `split_work_order` H2.3): **bundle asli menjadi bagian PERTAMA**
    (kode & relasinya dipertahankan) dan sisanya bundle baru pada WorkOrder yang sama;
    ``sum(parts)`` WAJIB = ``qty`` sumber supaya total tidak berubah (atomic).
    """
    error = _assert_draft(bundle, "split")
    if error:
        return BundleWriteResult(bundle=bundle, error=error)

    block = _movement_block(bundle)
    if block:
        return BundleWriteResult(bundle=bundle, conflict=True, error=block)

    payload = data if isinstance(data, dict) else {}
    parts, error = _resolve_parts(payload.get("parts"))
    if error:
        return BundleWriteResult(bundle=bundle, error=error)

    total = sum(parts)
    if total != int(bundle.qty or 0):
        return BundleWriteResult(
            bundle=bundle,
            error=f"Total split ({total}) harus sama dengan qty bundle sumber ({bundle.qty}).",
        )

    work_order = bundle.work_order
    order_line_id = work_order.order_line_id

    created: list[Bundle] = []
    with transaction.atomic():
        bundle.qty = parts[0]
        bundle.save(update_fields=("qty",))

        for index, qty in enumerate(parts[1:]):
            created.append(
                Bundle.objects.create(
                    code=_unique_code(order_line_id, bundle.size, 900 + index, work_order.pk),
                    work_order=work_order,
                    size=bundle.size,
                    sku_variant=bundle.sku_variant,
                    qty=qty,
                )
            )

    records = [_write_ledger(bundle, "split")]
    records.extend(_write_ledger(child, "create") for child in created)
    _audit(
        ACTION_SPLIT,
        bundle,
        request,
        {"parts": parts, "created_ids": [child.pk for child in created]},
    )

    logger.info(
        "bundle: %s di-split menjadi %s bagian %s (ledger=%s).",
        bundle.code,
        len(parts),
        parts,
        records[0].pk,
    )

    return BundleWriteResult(
        bundle=bundle,
        bundles=created,
        ledger_id=records[0].pk,
        summary={"parts": parts, "created": len(created)},
    )


def merge_bundles(target: Bundle, data, request=None) -> BundleWriteResult:
    """Gabungkan 2+ bundle DRAFT menjadi ``target`` — WO, size, dan SKU harus sama.

    ``qty`` target menjadi jumlah qty semua sumber; bundle sumber DIHAPUS permanen
    (guard: semuanya DRAFT & belum bergerak). Atomic: gagal ⇒ tidak ada yang berubah.
    """
    error = _assert_draft(target, "merge")
    if error:
        return BundleWriteResult(bundle=target, error=error)

    block = _movement_block(target)
    if block:
        return BundleWriteResult(bundle=target, conflict=True, error=block)

    payload = data if isinstance(data, dict) else {}
    raw_ids = payload.get("bundle_ids")
    if not isinstance(raw_ids, list) or not raw_ids:
        return BundleWriteResult(bundle=target, error="Field 'bundle_ids' wajib array id bundle.")
    if len(raw_ids) + 1 > MAX_MERGE_SOURCES:
        return BundleWriteResult(bundle=target, error=f"Merge maksimal {MAX_MERGE_SOURCES} bundle.")

    source_ids: list[int] = []
    for index, raw in enumerate(raw_ids):
        source_id = _int(raw)
        if source_id is None:
            return BundleWriteResult(bundle=target, error=f"bundle_ids[{index}] harus berupa angka.")
        if source_id == target.pk:
            return BundleWriteResult(
                bundle=target, error="Target merge tidak boleh ikut di daftar bundle_ids."
            )
        source_ids.append(source_id)

    found = list(
        Bundle.objects.select_related("work_order").filter(pk__in=source_ids).order_by("id")
    )
    if len(found) != len(set(source_ids)):
        return BundleWriteResult(
            bundle=target, error="Ada bundle sumber yang tidak ditemukan.", not_found=True
        )

    for source in found:
        if source.work_order_id != target.work_order_id:
            return BundleWriteResult(
                bundle=target,
                conflict=True,
                error=f"Bundle {source.code} bukan milik WorkOrder yang sama.",
            )
        if source.size != target.size or source.sku_variant != target.sku_variant:
            return BundleWriteResult(
                bundle=target,
                conflict=True,
                error=(
                    f"Bundle {source.code} berbeda size/SKU "
                    f"({source.size}/{source.sku_variant or '-'}); merge hanya untuk yang sama."
                ),
            )
        block = _movement_block(source) or _assert_draft(source, "merge")
        if block:
            return BundleWriteResult(bundle=target, conflict=True, error=block)

    total = int(target.qty or 0) + sum(int(source.qty or 0) for source in found)
    if total > MAX_QTY:
        return BundleWriteResult(bundle=target, error=f"Total qty hasil merge melebihi {MAX_QTY}.")

    merged_ids = [source.pk for source in found]
    with transaction.atomic():
        target.qty = total
        target.save(update_fields=("qty",))

        SyncRecord.objects.filter(
            resource=BUNDLE_RESOURCE,
            resource_id__in=[str(pk) for pk in merged_ids],
            stage=BUNDLE_STAGE,
        ).delete()
        Bundle.objects.filter(pk__in=merged_ids).delete()

    record = _write_ledger(target, "merge")
    _audit(ACTION_MERGE, target, request, {"merged_ids": merged_ids, "qty": total})

    logger.info(
        "bundle: merge %s bundle ke %s (qty=%s, ledger=%s).",
        len(merged_ids),
        target.code,
        total,
        record.pk,
    )

    return BundleWriteResult(
        bundle=target,
        ledger_id=record.pk,
        summary={"merged": len(merged_ids), "qty": total, "merged_ids": merged_ids},
    )
