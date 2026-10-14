"""Service **Inventory Adjustment** (H2.5) — log adjustment MES → Odoo.

Patuh `docs/CHANGES-DETAIL-H1H5.md` §4 (**MES TIDAK menyimpan stok**): service ini
**tidak** memelihara saldo stok. Ia hanya:

 1. mencatat niat adjustment sebagai **log** (`InventoryAdjustment`, state `DRAFT`);
 2. membaca on-hand Odoo **on-demand** (`stock.quant.quantity`) untuk pratinjau;
 3. saat `COMMITTED`, menyerahkan pengiriman ke task Celery
    (`erp_sync.push_inventory_adjustment`) yang memakai jalur **resmi** Odoo 17:
    `stock.quant` (context `inventory_mode=True`) → tulis `inventory_quantity`
    (absolut = on-hand terkini + `qty_delta`) → `action_apply_inventory()` yang
    membuat `stock.move` + `_action_done()` **di dalam Odoo** (jadi MES tidak perlu
    menyentuh `stock.move` yang method publiknya memang tidak ada);
 4. menutup siklus dengan `SYNCED` (+ `odoo_move_id`/`qty_after`) atau `FAILED`
    (+ `last_error`).

**Prerequisite Odoo (probe STEP 0, WAJIB)**: user API Odoo harus punya
`stock.group_stock_manager` — `_apply_inventory()` melempar `UserError` tanpa grup itu.
Pesan error diteruskan apa adanya supaya terlihat di `last_error` & UI.
Lihat `docs/integrations/CONTRACT.md` §TX-INVENTORY-ADJUST.

Batasan sadar (dicatat, bukan bug): produk `tracking in ('lot','serial')` **ditolak**
di MES karena MES belum mengelola `lot_id` (jalur quant akan memicu wizard
`stock.track.confirmation` di Odoo).
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
    STAGE_INVENTORY_ADJUST,
    SyncRecord,
    SyncResource,
)
from integrations.erp_sync.transport import get_transport
from master.models import Location, Product
from master.sequence_services import SequenceError, next_number

from ..models import InventoryAdjustment

logger = logging.getLogger(__name__)

__all__ = (
    "ACTION_COMMIT",
    "ACTION_CREATE",
    "ACTION_FAILED",
    "ACTION_SYNCED",
    "ADJ_RESOURCE",
    "ADJ_STAGE",
    "ADJ_STATES",
    "TRACKING_UNSUPPORTED_MESSAGE",
    "UNSUPPORTED_TRACKING",
    "AdjustmentWriteResult",
    "commit_adjustment",
    "create_adjustment",
    "fetch_product_tracking",
    "fetch_stock_qty",
    "mark_failed",
    "mark_synced",
    "adjustment_detail_row",
    "adjustment_payload",
    "adjustment_push_payload",
    "adjustment_row",
)

#: Resource & stage ledger (jangan ganti literal di view/task/test).
ADJ_RESOURCE = SyncResource.INVENTORY_ADJUSTMENT.value
ADJ_STAGE = STAGE_INVENTORY_ADJUST

#: State MES (bukan seed Odoo): DRAFT → COMMITTED → SYNCED/FAILED.
ADJ_STATES: tuple[str, ...] = ("DRAFT", "COMMITTED", "SYNCED", "FAILED")
COMMITTABLE_STATES: tuple[str, ...] = ("DRAFT",)

#: Hanya lokasi internal yang boleh disesuaikan (view/production/scrap/vendor dst TIDAK).
ALLOWED_LOCATION_USAGE = "internal"
#: Produk tracking lot/serial belum didukung MES (butuh `lot_id` di Odoo).
UNSUPPORTED_TRACKING: tuple[str, ...] = ("lot", "serial")

MAX_DELTA = Decimal("1000000")
MAX_REASON_LENGTH = 500
#: Referensi yang dikirim ke Odoo (`inventory_name`) — dipakai mencari `stock.move`.
ODOO_REFERENCE_LENGTH = 100

ACTION_CREATE = "inventory_adjustment.create"
ACTION_COMMIT = "inventory_adjustment.commit"
ACTION_SYNCED = "inventory_adjustment.synced"
ACTION_FAILED = "inventory_adjustment.failed"


class AdjustmentError(ValidationError):
    """Error validasi adjustment → dipetakan view menjadi **400**."""


@dataclass
class AdjustmentWriteResult:
    """Hasil operasi tulis adjustment (dipakai view)."""

    adjustment: InventoryAdjustment | None = None
    error: str | None = None
    #: True kalau resource tidak ada (view → 404).
    not_found: bool = False
    #: True kalau state/relasi melarang operasi (view → 409).
    conflict: bool = False
    #: Id ledger & hasil enqueue task push.
    ledger_id: int | None = None
    task_id: str | None = None
    queued: bool = False


def _decimal(value) -> Decimal | None:
    """Konversi aman ke ``Decimal`` (gagal → ``None``)."""
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _text(value) -> str:
    """Teks bersih (``None`` → ``''``)."""
    return "" if value is None else str(value).strip()


def _first_id(value) -> int | None:
    """Ambil id dari nilai Odoo `(id, name)` / `[id, name]` / int."""
    if isinstance(value, (list, tuple)) and value:
        value = value[0]
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Validasi
# ---------------------------------------------------------------------------
def _resolve_product(raw):
    """``(product, error, not_found)`` — produk master wajib ada."""
    if raw in (None, ""):
        return None, "Field 'product_id' wajib diisi.", False

    product_id = _first_id(raw)
    if product_id is None:
        return None, "Field 'product_id' harus berupa angka.", False

    product = Product.objects.filter(pk=product_id).first()
    if product is None:
        return None, f"Product {product_id} tidak ditemukan.", True

    return product, None, False


def _resolve_location(raw):
    """``(location, error, not_found)`` — lokasi wajib ada & ``usage='internal'``."""
    if raw in (None, ""):
        return None, "Field 'location_id' wajib diisi.", False

    location_id = _first_id(raw)
    if location_id is None:
        return None, "Field 'location_id' harus berupa angka.", False

    location = Location.objects.filter(pk=location_id).first()
    if location is None:
        return None, f"Location {location_id} tidak ditemukan.", True
    if location.usage != ALLOWED_LOCATION_USAGE:
        return (
            None,
            (
                f"Location {location.code or location.name} usage='{location.usage}'; "
                f"adjustment hanya untuk lokasi usage='{ALLOWED_LOCATION_USAGE}'."
            ),
            False,
        )

    return location, None, False


def validate_adjustment_payload(data):
    """Validasi payload adjustment → ``(values, error, not_found)``.

    Wajib: ``product_id``, ``location_id`` (`usage='internal'`), ``qty_delta`` ≠ 0,
    dan ``reason`` tidak kosong. **Tidak** menyentuh produk tracking lot/serial —
    penolakan tracking terjadi saat **commit** (butuh `odoo_id` juga).
    """
    payload = data if isinstance(data, dict) else {}
    values: dict = {}

    product, error, not_found = _resolve_product(payload.get("product_id"))
    if error:
        return None, error, not_found
    values["product"] = product

    location, error, not_found = _resolve_location(payload.get("location_id"))
    if error:
        return None, error, not_found
    values["location"] = location

    delta = _decimal(payload.get("qty_delta"))
    if delta is None:
        return None, "Field 'qty_delta' harus berupa angka (boleh negatif).", False
    # Normalisasi ke 2 desimal supaya serialisasi & DB konsisten ("5" → "5.00").
    delta = delta.quantize(Decimal("0.01"))
    if delta == 0:
        return None, "Field 'qty_delta' tidak boleh 0 (tidak ada yang disesuaikan).", False
    if abs(delta) > MAX_DELTA:
        return None, f"Field 'qty_delta' maksimal ±{MAX_DELTA}.", False
    values["qty_delta"] = delta

    reason = _text(payload.get("reason"))
    if not reason:
        return None, "Field 'reason' wajib diisi (alasan adjustment).", False
    if len(reason) > MAX_REASON_LENGTH:
        return None, f"Field 'reason' maksimal {MAX_REASON_LENGTH} karakter.", False
    values["reason"] = reason

    return values, None, False


#: Pesan guard untuk produk tracking lot/serial (dipakai commit + `_tracking_block`).
TRACKING_UNSUPPORTED_MESSAGE = (
    "Adjustment untuk produk tracking lot/serial belum didukung — gunakan Odoo UI "
    "atau tunggu sprint terpisah."
)


def _tracking_block(product: Product, location: Location) -> str | None:
    """Guard commit: produk lot/serial belum didukung + `odoo_id` wajib lengkap."""
    tracking = _text(getattr(product, "tracking", ""))
    if tracking in UNSUPPORTED_TRACKING:
        return TRACKING_UNSUPPORTED_MESSAGE
    if not product.odoo_id:
        return (
            f"Product {product.code} belum punya `odoo_id` — sinkronkan master Product dulu "
            "sebelum commit adjustment."
        )
    if not location.odoo_id:
        return (
            f"Location {location.code or location.name} belum punya `odoo_id` — sinkronkan "
            "master Location dulu sebelum commit adjustment."
        )

    return None


# ---------------------------------------------------------------------------
# Pembacaan on-demand dari Odoo (read-only; MES tidak menyimpan stok)
# ---------------------------------------------------------------------------
def fetch_stock_qty(product: Product, location: Location, transport=None) -> Decimal | None:
    """On-hand Odoo (`stock.quant.quantity`) untuk produk+lokasi → ``Decimal``/``None``.

    ``None`` = **tidak bisa dibaca** (odoo_id belum ada / transport gagal) — pemanggil
    memperlakukannya sebagai "tidak tahu", bukan 0. Kalau pembacaan berhasil tetapi
    quant-nya tidak ada, hasilnya ``Decimal('0.00')`` (memang tidak ada stok di situ).
    """
    product_odoo_id = _first_id(getattr(product, "odoo_id", None))
    location_odoo_id = _first_id(getattr(location, "odoo_id", None))
    if product_odoo_id is None or location_odoo_id is None:
        return None

    own = transport is None
    reader = transport if transport is not None else get_transport()
    try:
        rows = reader.fetch_stock_quants([location_odoo_id]) or []
    except Exception:  # noqa: BLE001 - pembacaan opsional; jangan gagalkan create
        logger.warning(
            "inventory_adjustment: gagal membaca stock.quant product=%s location=%s.",
            product_odoo_id,
            location_odoo_id,
            exc_info=True,
        )
        return None
    finally:
        if own:
            reader.close()

    total = Decimal("0.00")
    for row in rows:
        if not isinstance(row, dict):
            continue
        if _first_id(row.get("product_id")) != product_odoo_id:
            continue
        total += _decimal(row.get("quantity")) or Decimal("0.00")

    return total


def fetch_product_tracking(product: Product, transport=None) -> str | None:
    """Nilai ``product.product.tracking`` di Odoo (``none``/``lot``/``serial``)."""
    product_odoo_id = _first_id(getattr(product, "odoo_id", None))
    if product_odoo_id is None:
        return None

    own = transport is None
    reader = transport if transport is not None else get_transport()
    try:
        rows = (
            reader.search_read(
                "product.product", [["id", "=", product_odoo_id]], ["tracking"], limit=1
            )
            or []
        )
    except Exception:  # noqa: BLE001 - guard opsional (kalau tidak terbaca → tidak memblokir)
        logger.warning(
            "inventory_adjustment: gagal membaca tracking product=%s.",
            product_odoo_id,
            exc_info=True,
        )
        return None
    finally:
        if own:
            reader.close()

    if not rows or not isinstance(rows[0], dict):
        return None

    return _text(rows[0].get("tracking")) or None


# ---------------------------------------------------------------------------
# Serialisasi baris + payload
# ---------------------------------------------------------------------------
def adjustment_row(adj: InventoryAdjustment) -> dict:
    """Satu baris daftar adjustment (audit log)."""
    return {
        "id": adj.pk,
        "code": adj.code,
        "product_id": adj.product_id,
        "product_code": getattr(adj.product, "code", None),
        "product_name": getattr(adj.product, "name", None),
        "location_id": adj.location_id,
        "location_code": getattr(adj.location, "code", None),
        "location_name": getattr(adj.location, "name", None),
        "location_usage": getattr(adj.location, "usage", None),
        "qty_delta": str(adj.qty_delta),
        "qty_before": None if adj.qty_before is None else str(adj.qty_before),
        "qty_after": None if adj.qty_after is None else str(adj.qty_after),
        "reason": adj.reason,
        "state": adj.state,
        "odoo_move_id": adj.odoo_move_id,
        "odoo_reference": adj.odoo_reference,
        "last_error": adj.last_error,
        "created_by": getattr(adj.created_by, "username", None),
        "created_at": adj.created_at.isoformat() if adj.created_at else None,
        "updated_at": adj.updated_at.isoformat() if adj.updated_at else None,
    }


def adjustment_detail_row(adj: InventoryAdjustment) -> dict:
    """Detail adjustment = baris daftar + info sync (ledger terakhir)."""
    row = adjustment_row(adj)
    record = (
        SyncRecord.objects.filter(
            resource=ADJ_RESOURCE, resource_id=str(adj.pk), stage=ADJ_STAGE
        )
        .order_by("-id")
        .first()
    )
    row["sync"] = {
        "record_id": None if record is None else record.pk,
        "status": None if record is None else record.status,
        "erp_id": None if record is None else record.erp_id,
        "attempts": 0 if record is None else record.attempts,
    }

    return row


def adjustment_payload(adj: InventoryAdjustment) -> dict:
    """Payload MES **audit** (bentuk kaya) — dipakai `AuditLog`."""
    product = adj.product
    location = adj.location

    return {
        "code": adj.code,
        "product_id": adj.product_id,
        "product_code": getattr(product, "code", None),
        "product_odoo_id": getattr(product, "odoo_id", None),
        "location_id": adj.location_id,
        "location_odoo_id": getattr(location, "odoo_id", None),
        "location_code": getattr(location, "code", None),
        "qty_delta": str(adj.qty_delta),
        "reason": adj.reason,
        "state": adj.state,
        "odoo_reference": adj.odoo_reference,
    }


def adjustment_push_payload(adj: InventoryAdjustment) -> dict:
    """Payload **kanonik** untuk ledger + adapter (satu-satunya sumber bentuknya).

    Dipakai `commit_adjustment` (arm ledger) **dan** task
    `erp_sync.push_inventory_adjustment` — bentuknya harus identik supaya proteksi
    "enqueue/push ganda payload sama" di `SyncIdempotency` bekerja.
    """
    return {
        "ref": adj.code,
        "product_odoo_id": adj.product.odoo_id,
        "location_odoo_id": adj.location.odoo_id,
        "qty_delta": str(adj.qty_delta),
        "inventory_name": f"{adj.code} {adj.reason}".strip(),
    }


def _audit(action: str, adj: InventoryAdjustment, request, metadata: dict | None = None) -> None:
    """Tulis ``AuditLog`` — best-effort (audit tidak boleh menggagalkan transaksi)."""
    try:
        AuditLogger().log(
            user=None,
            action=action,
            resource=ADJ_RESOURCE,
            resource_id=adj.pk,
            request=request,
            payload=adjustment_payload(adj),
            result=AuditLog.Result.OK,
            metadata={"stock_owner": "odoo", **(metadata or {})},
        )
    except Exception:  # noqa: BLE001 - audit tidak boleh menggagalkan transaksi adjustment
        logger.exception(
            "inventory_adjustment: gagal menulis audit (%s, adj %s).", action, adj.pk
        )


# ---------------------------------------------------------------------------
# CREATE (DRAFT — MES-only, belum dikirim)
# ---------------------------------------------------------------------------
def _next_code() -> str | None:
    """``next_number('ADJ')`` → ``ADJ-<TAHUN>-<SEQ>``; ``None`` kalau sequence gagal."""
    try:
        return next_number("ADJ")
    except SequenceError:
        logger.warning(
            "inventory_adjustment: penomoran ADJ gagal (sequence belum di-seed?) — "
            "memakai fallback ADJ-<id>."
        )
        return None


def create_adjustment(data, request=None) -> AdjustmentWriteResult:
    """Buat log adjustment (**DRAFT** = MES-only) + snapshot on-hand Odoo (best-effort)."""
    values, error, not_found = validate_adjustment_payload(data)
    if error:
        return AdjustmentWriteResult(error=error, not_found=not_found)

    product = values["product"]
    location = values["location"]
    user = getattr(request, "user", None)
    created_by = user if getattr(user, "is_authenticated", False) else None

    qty_before = fetch_stock_qty(product, location)
    code = _next_code()

    with transaction.atomic():
        adj = InventoryAdjustment.objects.create(
            code=code or "",
            product=product,
            location=location,
            qty_delta=values["qty_delta"],
            qty_before=qty_before,
            reason=values["reason"],
            state=InventoryAdjustment.State.DRAFT,
            created_by=created_by,
        )
        if not code:
            adj.code = f"ADJ-{adj.pk:06d}"
            adj.save(update_fields=("code", "updated_at"))

    _audit(ACTION_CREATE, adj, request, {"qty_before": str(qty_before)})
    logger.info(
        "inventory_adjustment: %s dibuat (product=%s location=%s delta=%s, DRAFT).",
        adj.code,
        product.code,
        location.code or location.name,
        adj.qty_delta,
    )

    return AdjustmentWriteResult(adjustment=adj)


# ---------------------------------------------------------------------------
# COMMIT (DRAFT → COMMITTED + enqueue push)
# ---------------------------------------------------------------------------
def _enqueue_push(adj: InventoryAdjustment, record: SyncRecord) -> str | None:
    """Enqueue push ke Odoo; broker mati → ``None`` (record tetap PENDING)."""
    try:
        # Import lazy: `tasks_inventory_adjustment_push` mengimpor modul ini (payload).
        from integrations.erp_sync.tasks_inventory_adjustment_push import (
            push_inventory_adjustment,
        )

        async_result = push_inventory_adjustment.apply_async(
            args=[adj.pk, record.pk],
            headers={"x-request-id": get_request_id() or ""},
        )
        return str(async_result.id)
    except Exception:  # noqa: BLE001 - commit tidak boleh gagal karena broker
        logger.exception(
            "inventory_adjustment: gagal enqueue push %s (SyncRecord %s tetap PENDING).",
            adj.code,
            record.pk,
        )
        return None


def commit_adjustment(adj: InventoryAdjustment, request=None) -> AdjustmentWriteResult:
    """Kirim adjustment ke Odoo: **DRAFT → COMMITTED** + enqueue task push.

    Guard (→ 400/409, tidak ada push setengah jalan): state harus `DRAFT`, produk
    **bukan** tracking lot/serial (dibaca dari Odoo), `product.odoo_id` &
    `location.odoo_id` wajib ada.
    """
    if adj.state not in COMMITTABLE_STATES:
        return AdjustmentWriteResult(
            adjustment=adj,
            conflict=True,
            error=(
                f"Adjustment {adj.code} berstatus {adj.state}; commit hanya untuk "
                f"{'/'.join(COMMITTABLE_STATES)}."
            ),
        )

    block = _tracking_block(adj.product, adj.location)
    if block:
        return AdjustmentWriteResult(adjustment=adj, error=block)

    tracking = fetch_product_tracking(adj.product)
    if tracking in UNSUPPORTED_TRACKING:
        return AdjustmentWriteResult(adjustment=adj, error=TRACKING_UNSUPPORTED_MESSAGE)

    record = SyncIdempotency().get_or_create_sync_record(
        ADJ_RESOURCE, adj.pk, ADJ_STAGE, adjustment_push_payload(adj)
    )

    adj.state = InventoryAdjustment.State.COMMITTED
    if adj.qty_before is None:
        adj.qty_before = fetch_stock_qty(adj.product, adj.location)
    adj.save(update_fields=("state", "qty_before", "updated_at"))

    task_id = _enqueue_push(adj, record)
    _audit(ACTION_COMMIT, adj, request, {"ledger_id": record.pk, "task_id": task_id})
    logger.info(
        "inventory_adjustment: %s COMMITTED (ledger=%s, task=%s).",
        adj.code,
        record.pk,
        task_id or "-",
    )

    return AdjustmentWriteResult(
        adjustment=adj,
        ledger_id=record.pk,
        task_id=task_id,
        queued=task_id is not None,
    )


# ---------------------------------------------------------------------------
# HASIL PUSH (SYNCED / FAILED)
# ---------------------------------------------------------------------------
def _latest_record(adj: InventoryAdjustment) -> SyncRecord | None:
    """Record ledger terakhir untuk adjustment ini."""
    return (
        SyncRecord.objects.filter(
            resource=ADJ_RESOURCE, resource_id=str(adj.pk), stage=ADJ_STAGE
        )
        .order_by("-id")
        .first()
    )


def mark_synced(
    adj: InventoryAdjustment,
    *,
    erp_id: str | None = None,
    odoo_move_id: int | None = None,
    qty_after: Decimal | None = None,
) -> AdjustmentWriteResult:
    """COMMITTED → **SYNCED** + simpan jejak Odoo (`odoo_move_id`/`qty_after`)."""
    adj.state = InventoryAdjustment.State.SYNCED
    adj.last_error = ""
    if odoo_move_id is not None:
        adj.odoo_move_id = int(odoo_move_id)
    if qty_after is not None:
        adj.qty_after = qty_after
    adj.save(update_fields=("state", "last_error", "odoo_move_id", "qty_after", "updated_at"))

    record = _latest_record(adj)
    if record is not None:
        SyncIdempotency().mark_sent(record, erp_id or adj.odoo_move_id)

    _audit(ACTION_SYNCED, adj, None, {"erp_id": erp_id, "odoo_move_id": adj.odoo_move_id})

    return AdjustmentWriteResult(adjustment=adj, ledger_id=None if record is None else record.pk)


def mark_failed(adj: InventoryAdjustment, error, request=None) -> AdjustmentWriteResult:
    """COMMITTED → **FAILED** + simpan pesan error (mis. prerequisite grup Odoo)."""
    message = _text(error)
    adj.state = InventoryAdjustment.State.FAILED
    adj.last_error = message
    adj.save(update_fields=("state", "last_error", "updated_at"))

    record = _latest_record(adj)
    if record is not None:
        SyncIdempotency().mark_failed(record, Exception(message))

    _audit(ACTION_FAILED, adj, request, {"error": message})

    return AdjustmentWriteResult(adjustment=adj, ledger_id=None if record is None else record.pk)
