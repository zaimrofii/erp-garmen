"""Service Work Order (H2.3) — transaksi produksi **MES-only**.

`WorkOrder` sudah ada sejak Sprint 2.1 (bukan greenfield): model
`apps_industry/garment/models/work_order.py` (`code`, `order_line`, `state`,
`qty_planned`, `qty_done`) dan jalur HTTP **create** sudah ada di F2
(`api/resources/create_view.py`, dipakai simulator). Service ini **melengkapi**
(CRUD penuh, split, generate batch) tanpa mengubah kontrak yang sudah di-pin.

Kenapa MES-only (probe STEP 0, read-only): Odoo `mrp.workorder` = **operasi per
`mrp.production`** (`production_id` required & readonly, `workcenter_id` required,
`product_id`/`state`/`qty_*` readonly) dan `sale.order.line` **tidak punya** field
`workorder` ⇒ tidak ada padanan "WO per OrderLine". Jadi setiap CUD hanya menulis
jejak ledger `SyncRecord(resource="work_order", stage="WORK_ORDER_PUSH")` dengan
status **`SKIPPED`** (pola H1.7/H1.8/H1.9 + Sprint C), tanpa push & tanpa `odoo_id`.

**State machine = data** (`core.state_machine`, seed
`garment/migrations/0002_seed_state_machines.py`): `DRAFT → IN_PROGRESS → DONE`,
`DRAFT|IN_PROGRESS → CANCELLED` (aksi `WO_START`/`WO_CLOSE`/`WO_CANCEL` di endpoint
aksi existing). H2.3 **memakai state itu apa adanya** — tidak ada state baru — dan
**tidak** menyediakan endpoint transisi sendiri (klien memakai
`POST /api/v1/garmen/work-orders/<id>/<action>/` yang sudah ada).

Delete = **hibrida**: WO `DRAFT` yang belum punya Bundle ⇒ hard delete (bersihkan
salah input); selain itu (ada Bundle / bukan DRAFT) ⇒ **soft delete** lewat transisi
ke `CANCELLED`; WO yang sudah `CANCELLED` (terminal) ⇒ **409** (tidak boleh
menghapus dua kali).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction

from config.middleware import get_request_id
from core.audit.models import AuditLog
from core.audit.services import AuditLogger
from integrations.erp_sync.idempotency import SyncIdempotency
from integrations.erp_sync.models import (
    STAGE_WORK_ORDER_PUSH,
    SyncRecord,
    SyncResource,
    SyncStatus,
)
from master.sequence_services import SequenceError, next_number

from ..models import Bundle, Order, OrderLine, WorkOrder

logger = logging.getLogger(__name__)

__all__ = (
    "ACTION_CANCEL",
    "ACTION_CREATE",
    "ACTION_DELETE",
    "ACTION_GENERATE",
    "ACTION_SPLIT",
    "ACTION_UPDATE",
    "ALLOWED_TRANSITIONS",
    "WO_RESOURCE",
    "WO_STAGE",
    "WO_STATES",
    "WorkOrderError",
    "WorkOrderWriteResult",
    "create_work_order",
    "delete_work_order",
    "generate_work_orders_for_order",
    "split_work_order",
    "update_work_order",
    "wo_detail_row",
    "wo_payload",
    "wo_row",
)

#: Resource & stage ledger (jangan ganti literal di view/test).
WO_RESOURCE = SyncResource.WORK_ORDER.value
WO_STAGE = STAGE_WORK_ORDER_PUSH

#: State WO MES = state machine yang di-SEED (bukan dikarang di sini).
WO_STATES: tuple[str, ...] = ("DRAFT", "IN_PROGRESS", "DONE", "CANCELLED")
ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "DRAFT": ("IN_PROGRESS", "CANCELLED"),
    "IN_PROGRESS": ("DONE", "CANCELLED"),
    "DONE": (),
    "CANCELLED": (),
}

#: Alasan ledger SKIPPED (dipakai di monitor sync).
SKIPPED_REASON = (
    "MES-only: Odoo `mrp.workorder` = operasi per `mrp.production` "
    "(production_id required & readonly) & `sale.order.line` tanpa field workorder "
    "⇒ tidak ada padanan WorkOrder per OrderLine."
)

MAX_CODE_LENGTH = 64
MAX_QTY = 1_000_000
MIN_SPLIT_PARTS = 2
MAX_SPLIT_PARTS = 20
MAX_SPLIT_QTY = 200_000

#: Action ``AuditLog`` (namespace transaksi, analog `order.*`/`purchase_order.*`).
ACTION_CREATE = "work_order.create"
ACTION_UPDATE = "work_order.update"
ACTION_DELETE = "work_order.delete"
ACTION_SPLIT = "work_order.split"
ACTION_GENERATE = "work_order.generate"
ACTION_CANCEL = "work_order.cancel"


class WorkOrderError(ValidationError):
    """Error validasi/transisi WO → dipetakan view menjadi **400**."""


@dataclass
class WorkOrderWriteResult:
    """Hasil satu operasi tulis WO (dipakai view)."""

    work_order: WorkOrder | None = None
    error: str | None = None
    #: True kalau penyebabnya resource tidak ada (view → **404**, kontrak F2).
    not_found: bool = False
    #: True kalau operasi tidak boleh dilakukan karena state/relasi (view → **409**).
    conflict: bool = False
    #: True kalau WO dihapus permanen (hard delete) — bukan soft delete.
    deleted: bool = False
    #: True kalau "penghapusan" dilakukan dengan soft delete (transisi CANCELLED).
    cancelled: bool = False
    #: WO hasil split/generate (baris tambahan).
    work_orders: list = field(default_factory=list)
    #: Ringkasan generate: ``{"created": n, "skipped": n}``.
    summary: dict = field(default_factory=dict)
    #: Id ``SyncRecord`` (ledger SKIPPED) WO utama.
    ledger_id: int | None = None

    @property
    def sync_record_id(self) -> int | None:
        """Id ledger WO utama (kalau ada)."""
        return self.ledger_id


def _iso(value) -> str | None:
    """ISO-8601 atau ``None`` (timestamp kosong)."""
    return value.isoformat() if value else None


def _int(value) -> int | None:
    """Konversi aman ke ``int`` (gagal → ``None``)."""
    try:
        return int(value)
    except (TypeError, ValueError, InvalidOperation):
        return None


def _decimal(value) -> Decimal:
    """Konversi aman ke ``Decimal`` (dipakai hanya untuk pembanding angka)."""
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


# ---------------------------------------------------------------------------
# Validasi payload
# ---------------------------------------------------------------------------
def _resolve_order_line(raw):
    """``(order_line, error, not_found)`` — order line WAJIB ada (WO tanpa baris ditolak).

    ``not_found`` dipakai view untuk membedakan **404** (baris tidak ada — kontrak F2)
    dari **400** (payload salah).
    """
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


def _resolve_code(raw, instance: WorkOrder | None = None):
    """``(code, error)`` — kode opsional & unik (kosong ⇒ dibangkitkan pemanggil)."""
    if raw in (None, ""):
        return "", None

    code = str(raw).strip()
    if len(code) > MAX_CODE_LENGTH:
        return None, f"Field 'code' maksimal {MAX_CODE_LENGTH} karakter."

    duplicates = WorkOrder.objects.filter(code=code)
    if instance is not None:
        duplicates = duplicates.exclude(pk=instance.pk)
    if duplicates.exists():
        return None, f"Kode Work Order '{code}' sudah dipakai."

    return code, None


def validate_wo_payload(data, instance: WorkOrder | None = None):
    """Validasi payload WO → ``(values, error, not_found)``.

    Create: ``order_line_id`` wajib; ``code`` opsional (kosong ⇒ ``next_number("WO")``);
    ``qty_planned`` opsional (kosong ⇒ ``order_line.qty``). Update: hanya
    ``qty_planned``/``code`` yang diterima (``state`` lewat endpoint aksi existing).
    """
    payload = data if isinstance(data, dict) else {}
    values: dict = {}

    if "state" in payload:
        return None, (
            "Field 'state' tidak dapat diubah langsung; gunakan endpoint aksi "
            "(WO_START/WO_CLOSE/WO_CANCEL) pada /work-orders/<id>/<action>/."
        ), False

    if instance is None or "order_line_id" in payload:
        order_line, error, not_found = _resolve_order_line(payload.get("order_line_id"))
        if error:
            return None, error, not_found
        values["order_line"] = order_line

    if "code" in payload:
        code, error = _resolve_code(payload.get("code"), instance=instance)
        if error:
            return None, error, False
        values["code"] = code

    if "qty_planned" in payload:
        qty = _int(payload.get("qty_planned"))
        if qty is None or qty <= 0 or qty > MAX_QTY:
            return None, f"Field 'qty_planned' harus integer 1..{MAX_QTY}.", False
        values["qty_planned"] = qty

    return values, None, False


def _resolve_splits(raw):
    """``(parts, error)`` — daftar qty hasil split (integer > 0, minimal 2 bagian)."""
    if not isinstance(raw, list):
        return None, "Field 'splits' wajib array qty (integer > 0)."
    if len(raw) < MIN_SPLIT_PARTS:
        return None, f"Split minimal {MIN_SPLIT_PARTS} bagian."
    if len(raw) > MAX_SPLIT_PARTS:
        return None, f"Split maksimal {MAX_SPLIT_PARTS} bagian."

    parts: list[int] = []
    for index, item in enumerate(raw):
        qty = _int(item)
        if qty is None or qty <= 0 or qty > MAX_SPLIT_QTY:
            return None, f"splits[{index}] harus integer 1..{MAX_SPLIT_QTY}."
        parts.append(qty)

    return parts, None


# ---------------------------------------------------------------------------
# Serialisasi baris (H2.3 — superset; list/detail F3 TIDAK diubah)
# ---------------------------------------------------------------------------
def wo_row(wo: WorkOrder) -> dict:
    """Satu baris WO versi H2.3 (superset: + info order line & jumlah bundle)."""
    order_line = wo.order_line

    return {
        "id": wo.pk,
        "code": wo.code,
        "state": wo.state,
        "qty_planned": wo.qty_planned,
        "qty_done": wo.qty_done,
        "order_line_id": wo.order_line_id,
        "order_id": order_line.order_id if order_line is not None else None,
        "order_code": getattr(getattr(order_line, "order", None), "code", None),
        "product_id": order_line.product_id if order_line is not None else None,
        "product_code": getattr(getattr(order_line, "product", None), "code", None),
        "bundles_count": Bundle.objects.filter(work_order=wo).count(),
        "allowed_actions": list(ALLOWED_TRANSITIONS.get(wo.state, ())),
        "created_at": _iso(wo.created_at),
        "updated_at": _iso(wo.updated_at),
    }


def wo_detail_row(wo: WorkOrder) -> dict:
    """Detail WO versi H2.3 = ``wo_row`` + daftar bundle (ringkas)."""
    row = wo_row(wo)
    row["bundles"] = [
        {
            "id": bundle.pk,
            "code": bundle.code,
            "state": bundle.state,
            "size": bundle.size,
            "qty": bundle.qty,
            "qty_done": bundle.qty_done,
        }
        for bundle in Bundle.objects.filter(work_order=wo).order_by("code")
    ]

    return row


def wo_payload(wo: WorkOrder) -> dict:
    """Payload jejak ledger/audit WO (MES-only — tidak dikirim ke Odoo)."""
    return {
        "code": wo.code,
        "state": wo.state,
        "order_line_id": wo.order_line_id,
        "order_code": getattr(getattr(wo.order_line, "order", None), "code", None),
        "product_code": getattr(getattr(wo.order_line, "product", None), "code", None),
        "qty_planned": wo.qty_planned,
        "qty_done": wo.qty_done,
        "bundles_count": Bundle.objects.filter(work_order=wo).count(),
        "mes_only": True,
    }


# ---------------------------------------------------------------------------
# Ledger (SKIPPED) + audit
# ---------------------------------------------------------------------------
def _write_ledger(wo: WorkOrder, action: str) -> SyncRecord:
    """Tulis/perbarui ``SyncRecord`` WO (stage ``WORK_ORDER_PUSH``) → **SKIPPED**."""
    payload = {**wo_payload(wo), "action": action}
    sync = SyncIdempotency()
    record = sync.get_or_create_sync_record(WO_RESOURCE, wo.pk, WO_STAGE, payload)

    if dict(record.payload or {}) != payload or record.last_error != SKIPPED_REASON:
        record.payload = payload
        record.save(update_fields=("payload", "updated_at"))

    return sync.mark_skipped(record, SKIPPED_REASON)


def _audit(action: str, wo: WorkOrder, request, metadata: dict | None = None) -> None:
    """Tulis ``AuditLog`` — best-effort (audit tidak boleh menggagalkan CRUD WO)."""
    try:
        AuditLogger().log(
            user=None,
            action=action,
            resource=WO_RESOURCE,
            resource_id=wo.pk,
            request=request,
            payload=wo_payload(wo),
            result=AuditLog.Result.OK,
            metadata={"mes_only": True, **(metadata or {})},
        )
    except Exception:  # noqa: BLE001 - audit tidak boleh menggagalkan transaksi WO
        logger.exception("work_order: gagal menulis audit (%s, WO %s).", action, wo.pk)


def _assert_draft(wo: WorkOrder, verb: str) -> str | None:
    """Guard: hanya DRAFT yang boleh diubah/displit (state lain sudah masuk lantai)."""
    if wo.state != "DRAFT":
        return f"WO {wo.code} berstatus {wo.state}; {verb} hanya boleh saat DRAFT."
    return None


def _has_bundle(wo: WorkOrder) -> bool:
    """True kalau WO sudah punya bundle (produksi sudah mulai)."""
    return Bundle.objects.filter(work_order=wo).exists()


def _next_code_for() -> str | None:
    """``next_number('WO')`` → ``WO-<TAHUN>-<SEQ>``; ``None`` kalau penomoran gagal."""
    try:
        return next_number("WO")
    except SequenceError:
        logger.warning("work_order: penomoran WO gagal (sequence nonaktif/hilang).")
        return None


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
def create_work_order(data, request=None) -> WorkOrderWriteResult:
    """Buat WO (kode otomatis ``WO-<TAHUN>-<SEQ>`` bila tidak diisi) — **DRAFT**.

    Kompatibel dengan jalur F2 (`POST /garmen/work-orders/`): ``order_line_id`` wajib,
    ``qty_planned`` default = ``order_line.qty``, ``state="DRAFT"``. Bedanya: kode
    default memakai Sprint C (`next_number("WO")`, mis. ``WO-2026-0001``) dan setiap
    CUD meninggalkan jejak ledger ``SKIPPED`` + audit.
    """
    payload = data if isinstance(data, dict) else {}
    values, error, not_found = validate_wo_payload(payload)
    if error:
        return WorkOrderWriteResult(error=error, not_found=not_found)

    order_line = values.get("order_line")
    code = values.pop("code", "")
    if not code:
        code = _next_code_for()
        if code is None:
            return WorkOrderWriteResult(
                error="Penomoran WO gagal: sequence 'WO' belum ada/nonaktif."
            )

    qty_planned = values.pop("qty_planned", None)
    if qty_planned is None:
        qty_planned = int(getattr(order_line, "qty", 0) or 0)
    if qty_planned <= 0:
        return WorkOrderWriteResult(
            error=(
                "Field 'qty_planned' kosong & OrderLine.qty = 0 ⇒ tidak ada yang "
                "direncanakan; isi 'qty_planned' eksplisit."
            )
        )

    with transaction.atomic():
        wo = WorkOrder.objects.create(
            code=code, order_line=order_line, qty_planned=qty_planned, state="DRAFT"
        )

    record = _write_ledger(wo, "create")
    _audit(ACTION_CREATE, wo, request, {"qty_planned": qty_planned})

    logger.info(
        "work_order: WO %s (%s) dibuat untuk order line %s qty=%s (ledger=%s, MES-only).",
        wo.pk,
        wo.code,
        wo.order_line_id,
        qty_planned,
        record.pk,
    )

    return WorkOrderWriteResult(work_order=wo, ledger_id=record.pk)


def update_work_order(wo: WorkOrder, data, request=None) -> WorkOrderWriteResult:
    """Ubah WO (``qty_planned``/``code``) — **hanya DRAFT**.

    ``state`` TIDAK bisa diubah di sini (pakai endpoint aksi existing). ``qty_planned``
    tidak boleh < ``qty_done`` (produksi yang sudah tercatat tidak boleh hilang).
    """
    error = _assert_draft(wo, "perubahan")
    if error:
        return WorkOrderWriteResult(work_order=wo, error=error)

    payload = data if isinstance(data, dict) else {}
    values, error, _not_found = validate_wo_payload(payload, instance=wo)
    if error:
        return WorkOrderWriteResult(work_order=wo, error=error)

    values.pop("order_line", None)  # WO tidak boleh pindah order line
    if not values:
        return WorkOrderWriteResult(work_order=wo)

    qty_planned = values.get("qty_planned")
    if qty_planned is not None and qty_planned < int(wo.qty_done or 0):
        return WorkOrderWriteResult(
            work_order=wo,
            error=(
                f"qty_planned ({qty_planned}) tidak boleh lebih kecil dari qty_done "
                f"({wo.qty_done})."
            ),
        )

    for field, value in values.items():
        setattr(wo, field, value)
    wo.save()

    record = _write_ledger(wo, "update")
    _audit(ACTION_UPDATE, wo, request, {"fields": sorted(values)})

    logger.info("work_order: WO %s (%s) diubah (ledger=%s).", wo.pk, wo.code, record.pk)

    return WorkOrderWriteResult(work_order=wo, ledger_id=record.pk)


def delete_work_order(wo: WorkOrder, request=None) -> WorkOrderWriteResult:
    """Hapus WO — **hibrida** (keputusan pemilik proyek H2.3).

    * `CANCELLED` (terminal) ⇒ **409** (``conflict=True``) — tidak boleh hapus dua kali;
    * `DRAFT` **tanpa** Bundle ⇒ **hard delete** (bersihkan salah input) + ledger ikut
      dihapus;
    * selain itu (bukan DRAFT atau sudah punya Bundle) ⇒ **soft delete** = transisi ke
      `CANCELLED` (Bundle memakai FK PROTECT & jejak produksi harus utuh).
    """
    if wo.state == "CANCELLED":
        return WorkOrderWriteResult(
            work_order=wo,
            conflict=True,
            error=f"WO {wo.code} sudah CANCELLED (terminal); tidak ada yang perlu dihapus.",
        )

    if wo.state == "DRAFT" and not _has_bundle(wo):
        code = wo.code
        pk = wo.pk
        _audit(ACTION_DELETE, wo, request, {"hard_delete": True})
        SyncRecord.objects.filter(resource=WO_RESOURCE, resource_id=str(pk), stage=WO_STAGE).delete()
        wo.delete()

        logger.info("work_order: WO %s (%s) dihapus permanen (DRAFT tanpa bundle).", pk, code)

        return WorkOrderWriteResult(deleted=True)

    wo.state = "CANCELLED"
    wo.save(update_fields=("state", "updated_at"))

    record = _write_ledger(wo, "cancel")
    _audit(
        ACTION_CANCEL,
        wo,
        request,
        {"soft_delete": True, "has_bundle": _has_bundle(wo), "previous_state": "non-DRAFT"},
    )

    logger.info("work_order: WO %s (%s) di-soft-delete (CANCELLED).", wo.pk, wo.code)

    return WorkOrderWriteResult(work_order=wo, cancelled=True, ledger_id=record.pk)


def split_work_order(wo: WorkOrder, data, request=None) -> WorkOrderWriteResult:
    """Pecah satu WO menjadi ``len(splits)`` bagian — **hanya DRAFT, tanpa Bundle**.

    Semantik: **WO asli menjadi bagian PERTAMA** (`splits[0]`, kode & relasinya
    dipertahankan) dan sisanya dibuat sebagai WO baru (`next_number('WO')`) pada
    `order_line` yang sama. ``sum(splits)`` **wajib =** ``wo.qty_planned`` supaya
    total rencana produksi tidak berubah (atomic: gagal ⇒ tidak ada WO separuh).
    """
    error = _assert_draft(wo, "split")
    if error:
        return WorkOrderWriteResult(work_order=wo, error=error)
    if _has_bundle(wo):
        return WorkOrderWriteResult(
            work_order=wo,
            conflict=True,
            error=(
                f"WO {wo.code} sudah punya bundle; split tidak diizinkan karena bundle "
                "sudah menempel ke WO ini."
            ),
        )

    payload = data if isinstance(data, dict) else {}
    parts, error = _resolve_splits(payload.get("splits"))
    if error:
        return WorkOrderWriteResult(work_order=wo, error=error)

    total = sum(parts)
    if total != int(wo.qty_planned or 0):
        return WorkOrderWriteResult(
            work_order=wo,
            error=(
                f"Total split ({total}) harus sama dengan qty_planned WO sumber "
                f"({wo.qty_planned})."
            ),
        )

    created: list[WorkOrder] = []
    with transaction.atomic():
        wo.qty_planned = parts[0]
        wo.save(update_fields=("qty_planned", "updated_at"))

        for qty in parts[1:]:
            code = _next_code_for()
            if code is None:
                raise WorkOrderError(
                    "Penomoran WO gagal saat split: sequence 'WO' belum ada/nonaktif."
                )
            created.append(
                WorkOrder.objects.create(
                    code=code, order_line=wo.order_line, qty_planned=qty, state="DRAFT"
                )
            )

    records = [_write_ledger(wo, "split")]
    for child in created:
        records.append(_write_ledger(child, "create"))

    _audit(
        ACTION_SPLIT,
        wo,
        request,
        {"splits": parts, "created_ids": [child.pk for child in created]},
    )

    logger.info(
        "work_order: WO %s (%s) di-split menjadi %s bagian (%s).",
        wo.pk,
        wo.code,
        len(parts),
        parts,
    )

    return WorkOrderWriteResult(
        work_order=wo,
        work_orders=created,
        ledger_id=records[0].pk,
        summary={"parts": parts, "created": len(created)},
    )


def generate_work_orders_for_order(order: Order, request=None) -> WorkOrderWriteResult:
    """Buat WO untuk **setiap OrderLine** milik ``order`` yang belum punya WO.

    Idempoten: baris yang sudah punya WO dilewati (``summary["skipped"]``), jadi
    menekan tombol "Generate WO" dua kali tidak menghasilkan duplikat. Satu OrderLine
    ⇒ satu WO dengan ``qty_planned = OrderLine.qty`` (pecah lebih lanjut lewat split).
    """
    created: list[WorkOrder] = []
    skipped = 0

    lines = (
        OrderLine.objects.filter(order=order)
        .select_related("product", "order")
        .order_by("id")
    )

    for order_line in lines:
        if WorkOrder.objects.filter(order_line=order_line).exists():
            skipped += 1
            continue

        result = create_work_order({"order_line_id": order_line.pk}, request=request)
        if result.error:
            return WorkOrderWriteResult(
                error=result.error, summary={"created": len(created), "skipped": skipped}
            )
        created.append(result.work_order)

    if created:
        _audit(
            ACTION_GENERATE,
            created[0],
            request,
            {"order_id": order.pk, "created": len(created), "skipped": skipped},
        )

    logger.info(
        "work_order: generate untuk order %s -> %s WO baru, %s baris dilewati (sudah punya WO).",
        order.pk,
        len(created),
        skipped,
    )

    return WorkOrderWriteResult(
        work_orders=created,
        summary={"created": len(created), "skipped": skipped},
    )


