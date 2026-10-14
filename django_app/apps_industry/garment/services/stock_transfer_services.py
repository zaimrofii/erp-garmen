"""Service **Stock Transfer** (H2.6) — log transfer stok antar lokasi MES → Odoo.

Patuh `docs/CHANGES-DETAIL-H1H5.md` §4 (**MES TIDAK menyimpan stok**): service ini
**tidak** memelihara saldo. Ia hanya:

 1. mencatat niat transfer sebagai **log** (`StockTransfer`, state `DRAFT`);
 2. menyimpan **snapshot** on-hand lokasi asal (opsional/informatif, TIDAK memblokir —
    stok bisa berubah antara snapshot & push; Odoo yang memutuskan);
 3. saat `COMMITTED`, menyerahkan pengiriman ke task Celery
    (`erp_sync.push_stock_transfer`) yang memakai jalur **resmi** Odoo 17:
    `stock.picking` (internal transfer) + **`button_validate()`** — method PUBLIK yang
    di dalamnya `action_confirm()` → auto-isi `quantity` → auto-`picked` → `_action_done()`.
    (`stock.move` + `_action_done()` langsung TIDAK bisa: `_action_done` private.)
 4. menutup siklus dengan `SYNCED` (+ `odoo_picking_id`/`odoo_picking_name`) atau
    `FAILED` (+ `last_error`, mis. stok asal kurang → UserError Odoo).

Batasan sadar (konsisten H2.5): produk `tracking in ('lot','serial')` **DITOLAK** —
MES belum mengelola `lot_id`/`move_line`. Lihat `docs/integrations/CONTRACT.md`
§TX-STOCK-TRANSFER.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction

from config.middleware import get_request_id
from core.audit.models import AuditLog
from core.audit.services import AuditLogger
from integrations.erp_sync.idempotency import SyncIdempotency
from integrations.erp_sync.models import STAGE_STOCK_TRANSFER, SyncRecord, SyncResource
from integrations.erp_sync.transport import get_transport
from master.models import Location, Product
from master.sequence_services import SequenceError, next_number

from ..models import StockTransfer

logger = logging.getLogger(__name__)

__all__ = (
    "ACTION_COMMIT",
    "ACTION_CREATE",
    "ACTION_FAILED",
    "ACTION_SYNCED",
    "ALLOWED_LOCATION_USAGE",
    "TRACKING_UNSUPPORTED_MESSAGE",
    "TRF_RESOURCE",
    "TRF_STAGE",
    "TRF_STATES",
    "TransferWriteResult",
    "commit_transfer",
    "create_transfer",
    "fetch_stock_qty",
    "fetch_product_tracking",
    "mark_failed",
    "mark_synced",
    "transfer_detail_row",
    "transfer_payload",
    "transfer_push_payload",
    "transfer_row",
)

#: Resource & stage ledger (jangan ganti literal di view/task/test).
TRF_RESOURCE = SyncResource.STOCK_TRANSFER.value
TRF_STAGE = STAGE_STOCK_TRANSFER

#: State MES (bukan seed Odoo): DRAFT → COMMITTED → SYNCED/FAILED.
TRF_STATES: tuple[str, ...] = ("DRAFT", "COMMITTED", "SYNCED", "FAILED")
COMMITTABLE_STATES: tuple[str, ...] = ("DRAFT",)

#: Kedua sisi transfer WAJIB lokasi internal (view/production/scrap/vendor dst TIDAK).
ALLOWED_LOCATION_USAGE = "internal"
#: Produk tracking lot/serial belum didukung MES (butuh `lot_id`).
UNSUPPORTED_TRACKING: tuple[str, ...] = ("lot", "serial")

MAX_QTY = Decimal("1000000")
MAX_REASON_LENGTH = 500

ACTION_CREATE = "stock_transfer.create"
ACTION_COMMIT = "stock_transfer.commit"
ACTION_SYNCED = "stock_transfer.synced"
ACTION_FAILED = "stock_transfer.failed"

#: Pesan guard untuk produk tracking lot/serial (dipakai commit + `_tracking_block`).
TRACKING_UNSUPPORTED_MESSAGE = (
    "Transfer untuk produk tracking lot/serial belum didukung — gunakan Odoo UI "
    "atau tunggu sprint terpisah."
)


class TransferError(ValidationError):
    """Error validasi transfer → dipetakan view menjadi **400**."""


@dataclass
class TransferWriteResult:
    """Hasil operasi tulis transfer (dipakai view)."""

    transfer: StockTransfer | None = None
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


def _resolve_location(raw, *, label: str):
    """``(location, error, not_found)`` — lokasi wajib ada & ``usage='internal'``."""
    if raw in (None, ""):
        return None, f"Field '{label}' wajib diisi.", False

    location_id = _first_id(raw)
    if location_id is None:
        return None, f"Field '{label}' harus berupa angka.", False

    location = Location.objects.filter(pk=location_id).first()
    if location is None:
        return None, f"Location {location_id} tidak ditemukan.", True
    if location.usage != ALLOWED_LOCATION_USAGE:
        return (
            None,
            (
                f"Location {location.code or location.name} usage='{location.usage}'; transfer "
                f"hanya antar lokasi usage='{ALLOWED_LOCATION_USAGE}'."
            ),
            False,
        )

    return location, None, False


def validate_transfer_payload(data):
    """Validasi payload transfer → ``(values, error, not_found)``.

    Wajib: ``product_id``, ``from_location_id`` & ``to_location_id`` (keduanya
    `usage='internal'`), **``from_location_id != to_location_id``**, ``qty > 0``.
    ``reason`` opsional (maks 500 karakter). Penolakan tracking lot/serial terjadi
    saat **commit** (butuh `odoo_id` juga).
    """
    payload = data if isinstance(data, dict) else {}
    values: dict = {}

    product, error, not_found = _resolve_product(payload.get("product_id"))
    if error:
        return None, error, not_found
    values["product"] = product

    from_location, error, not_found = _resolve_location(
        payload.get("from_location_id"), label="from_location_id"
    )
    if error:
        return None, error, not_found
    values["from_location"] = from_location

    to_location, error, not_found = _resolve_location(
        payload.get("to_location_id"), label="to_location_id"
    )
    if error:
        return None, error, not_found
    values["to_location"] = to_location

    if from_location.pk == to_location.pk:
        return (
            None,
            "Lokasi asal dan tujuan TIDAK boleh sama (tidak ada yang dipindahkan).",
            False,
        )

    qty = _decimal(payload.get("qty"))
    if qty is None:
        return None, "Field 'qty' harus berupa angka.", False
    qty = qty.quantize(Decimal("0.01"))
    if qty <= 0:
        return None, "Field 'qty' harus lebih besar dari 0.", False
    if qty > MAX_QTY:
        return None, f"Field 'qty' maksimal {MAX_QTY}.", False
    values["qty"] = qty

    reason = _text(payload.get("reason"))
    if len(reason) > MAX_REASON_LENGTH:
        return None, f"Field 'reason' maksimal {MAX_REASON_LENGTH} karakter.", False
    values["reason"] = reason

    return values, None, False


def _transfer_block(transfer: StockTransfer) -> str | None:
    """Guard commit: produk lot/serial ditolak + `odoo_id` wajib lengkap (3 sisi)."""
    tracking = _text(getattr(transfer.product, "tracking", ""))
    if tracking in UNSUPPORTED_TRACKING:
        return TRACKING_UNSUPPORTED_MESSAGE
    if not transfer.product.odoo_id:
        return (
            f"Product {transfer.product.code} belum punya `odoo_id` — sinkronkan master Product "
            "dulu sebelum commit transfer."
        )
    if not transfer.from_location.odoo_id:
        return (
            f"Lokasi asal {transfer.from_location.code or transfer.from_location.name} belum punya "
            "`odoo_id` — sinkronkan master Location dulu sebelum commit transfer."
        )
    if not transfer.to_location.odoo_id:
        return (
            f"Lokasi tujuan {transfer.to_location.code or transfer.to_location.name} belum punya "
            "`odoo_id` — sinkronkan master Location dulu sebelum commit transfer."
        )

    return None


# ---------------------------------------------------------------------------
# Pembacaan on-demand dari Odoo (read-only; MES tidak menyimpan stok)
# ---------------------------------------------------------------------------
def fetch_stock_qty(product: Product, location: Location, transport=None) -> Decimal | None:
    """On-hand Odoo (`stock.quant.quantity`) produk di satu lokasi → ``Decimal``/``None``.

    ``None`` = **tidak bisa dibaca** (odoo_id belum ada / transport gagal) — bukan 0.
    Dipakai HANYA sebagai snapshot informatif (`qty_before`) di lokasi asal; commit
    **tidak** diblokir oleh nilai ini (stok bisa berubah sebelum push — Odoo yang
    memutuskan, dan bila gagal muncul `FAILED` + `last_error`).
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
            "stock_transfer: gagal membaca stock.quant product=%s location=%s.",
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
            "stock_transfer: gagal membaca tracking product=%s.", product_odoo_id, exc_info=True
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
def transfer_row(transfer: StockTransfer) -> dict:
    """Satu baris daftar transfer (audit log)."""
    return {
        "id": transfer.pk,
        "code": transfer.code,
        "product_id": transfer.product_id,
        "product_code": getattr(transfer.product, "code", None),
        "product_name": getattr(transfer.product, "name", None),
        "from_location_id": transfer.from_location_id,
        "from_location_code": getattr(transfer.from_location, "code", None),
        "from_location_name": getattr(transfer.from_location, "name", None),
        "to_location_id": transfer.to_location_id,
        "to_location_code": getattr(transfer.to_location, "code", None),
        "to_location_name": getattr(transfer.to_location, "name", None),
        "qty": str(transfer.qty),
        "qty_before": None if transfer.qty_before is None else str(transfer.qty_before),
        "reason": transfer.reason,
        "state": transfer.state,
        "odoo_picking_id": transfer.odoo_picking_id,
        "odoo_picking_name": transfer.odoo_picking_name,
        "last_error": transfer.last_error,
        "created_by": getattr(transfer.created_by, "username", None),
        "created_at": transfer.created_at.isoformat() if transfer.created_at else None,
        "updated_at": transfer.updated_at.isoformat() if transfer.updated_at else None,
    }


def transfer_detail_row(transfer: StockTransfer) -> dict:
    """Detail transfer = baris daftar + info sync (ledger terakhir)."""
    row = transfer_row(transfer)
    record = (
        SyncRecord.objects.filter(
            resource=TRF_RESOURCE, resource_id=str(transfer.pk), stage=TRF_STAGE
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


def transfer_payload(transfer: StockTransfer) -> dict:
    """Payload MES **audit** (bentuk kaya) — dipakai `AuditLog`."""
    return {
        "code": transfer.code,
        "product_id": transfer.product_id,
        "product_code": getattr(transfer.product, "code", None),
        "product_odoo_id": getattr(transfer.product, "odoo_id", None),
        "from_location_id": transfer.from_location_id,
        "from_location_odoo_id": getattr(transfer.from_location, "odoo_id", None),
        "to_location_id": transfer.to_location_id,
        "to_location_odoo_id": getattr(transfer.to_location, "odoo_id", None),
        "qty": str(transfer.qty),
        "reason": transfer.reason,
        "state": transfer.state,
    }


def transfer_push_payload(transfer: StockTransfer) -> dict:
    """Payload **kanonik** untuk ledger + adapter (satu-satunya sumber bentuknya).

    Dipakai `commit_transfer` (arm ledger) **dan** task
    `erp_sync.push_stock_transfer` — bentuknya harus identik supaya proteksi
    "enqueue/push ganda payload sama" di `SyncIdempotency` bekerja.
    """
    product = transfer.product
    from_location = transfer.from_location
    to_location = transfer.to_location

    return {
        "ref": transfer.code,
        "product_odoo_id": product.odoo_id,
        "from_location_odoo_id": from_location.odoo_id,
        "to_location_odoo_id": to_location.odoo_id,
        "qty": str(transfer.qty),
        "product_code": product.code,
        "move_name": f"{transfer.code} {transfer.reason}".strip(),
        "origin": transfer.code,
    }


def _audit(action: str, transfer: StockTransfer, request, metadata: dict | None = None) -> None:
    """Tulis ``AuditLog`` — best-effort (audit tidak boleh menggagalkan transaksi)."""
    try:
        AuditLogger().log(
            user=None,
            action=action,
            resource=TRF_RESOURCE,
            resource_id=transfer.pk,
            request=request,
            payload=transfer_payload(transfer),
            result=AuditLog.Result.OK,
            metadata={"stock_owner": "odoo", **(metadata or {})},
        )
    except Exception:  # noqa: BLE001 - audit tidak boleh menggagalkan transaksi transfer
        logger.exception("stock_transfer: gagal menulis audit (%s, trf %s).", action, transfer.pk)


# ---------------------------------------------------------------------------
# CREATE (DRAFT — MES-only, belum dikirim)
# ---------------------------------------------------------------------------
def _next_code() -> str | None:
    """``next_number('TRF')`` → ``TRF-<TAHUN>-<SEQ>``; ``None`` kalau sequence gagal."""
    try:
        return next_number("TRF")
    except SequenceError:
        logger.warning(
            "stock_transfer: penomoran TRF gagal (sequence belum di-seed?) — memakai fallback "
            "TRF-<id>."
        )
        return None


def create_transfer(data, request=None) -> TransferWriteResult:
    """Buat log transfer (**DRAFT** = MES-only) + snapshot on-hand asal (best-effort)."""
    values, error, not_found = validate_transfer_payload(data)
    if error:
        return TransferWriteResult(error=error, not_found=not_found)

    product = values["product"]
    from_location = values["from_location"]
    user = getattr(request, "user", None)
    created_by = user if getattr(user, "is_authenticated", False) else None

    qty_before = fetch_stock_qty(product, from_location)
    code = _next_code()

    with transaction.atomic():
        transfer = StockTransfer.objects.create(
            code=code or "",
            product=product,
            from_location=from_location,
            to_location=values["to_location"],
            qty=values["qty"],
            qty_before=qty_before,
            reason=values["reason"],
            state=StockTransfer.State.DRAFT,
            created_by=created_by,
        )
        if not code:
            transfer.code = f"TRF-{transfer.pk:06d}"
            transfer.save(update_fields=("code", "updated_at"))

    _audit(ACTION_CREATE, transfer, request, {"qty_before": str(qty_before)})
    logger.info(
        "stock_transfer: %s dibuat (product=%s %s→%s qty=%s, DRAFT).",
        transfer.code,
        product.code,
        from_location.code or from_location.name,
        transfer.to_location.code or transfer.to_location.name,
        transfer.qty,
    )

    return TransferWriteResult(transfer=transfer)


# ---------------------------------------------------------------------------
# COMMIT (DRAFT → COMMITTED + enqueue push)
# ---------------------------------------------------------------------------
def _enqueue_push(transfer: StockTransfer, record: SyncRecord) -> str | None:
    """Enqueue push ke Odoo; broker mati → ``None`` (record tetap PENDING)."""
    try:
        # Import lazy: `tasks_stock_transfer_push` mengimpor modul ini (payload).
        from integrations.erp_sync.tasks_stock_transfer_push import push_stock_transfer

        async_result = push_stock_transfer.apply_async(
            args=[transfer.pk, record.pk],
            headers={"x-request-id": get_request_id() or ""},
        )
        return str(async_result.id)
    except Exception:  # noqa: BLE001 - commit tidak boleh gagal karena broker
        logger.exception(
            "stock_transfer: gagal enqueue push %s (SyncRecord %s tetap PENDING).",
            transfer.code,
            record.pk,
        )
        return None


def commit_transfer(transfer: StockTransfer, request=None) -> TransferWriteResult:
    """Kirim transfer ke Odoo: **DRAFT → COMMITTED** + enqueue task push.

    Guard (→ 400/409, tidak ada push setengah jalan): state harus `DRAFT`, produk
    **bukan** tracking lot/serial (dibaca dari Odoo), `product.odoo_id`,
    `from_location.odoo_id`, dan `to_location.odoo_id` wajib ada.
    """
    if transfer.state not in COMMITTABLE_STATES:
        return TransferWriteResult(
            transfer=transfer,
            conflict=True,
            error=(
                f"Transfer {transfer.code} berstatus {transfer.state}; commit hanya untuk "
                f"{'/'.join(COMMITTABLE_STATES)}."
            ),
        )

    block = _transfer_block(transfer)
    if block:
        return TransferWriteResult(transfer=transfer, error=block)

    tracking = fetch_product_tracking(transfer.product)
    if tracking in UNSUPPORTED_TRACKING:
        return TransferWriteResult(transfer=transfer, error=TRACKING_UNSUPPORTED_MESSAGE)

    record = SyncIdempotency().get_or_create_sync_record(
        TRF_RESOURCE, transfer.pk, TRF_STAGE, transfer_push_payload(transfer)
    )

    transfer.state = StockTransfer.State.COMMITTED
    if transfer.qty_before is None:
        transfer.qty_before = fetch_stock_qty(transfer.product, transfer.from_location)
    transfer.save(update_fields=("state", "qty_before", "updated_at"))

    task_id = _enqueue_push(transfer, record)
    _audit(ACTION_COMMIT, transfer, request, {"ledger_id": record.pk, "task_id": task_id})
    logger.info(
        "stock_transfer: %s COMMITTED (ledger=%s, task=%s).",
        transfer.code,
        record.pk,
        task_id or "-",
    )

    return TransferWriteResult(
        transfer=transfer,
        ledger_id=record.pk,
        task_id=task_id,
        queued=task_id is not None,
    )


# ---------------------------------------------------------------------------
# HASIL PUSH (SYNCED / FAILED)
# ---------------------------------------------------------------------------
def _latest_record(transfer: StockTransfer) -> SyncRecord | None:
    """Record ledger terakhir untuk transfer ini."""
    return (
        SyncRecord.objects.filter(
            resource=TRF_RESOURCE, resource_id=str(transfer.pk), stage=TRF_STAGE
        )
        .order_by("-id")
        .first()
    )


def mark_synced(
    transfer: StockTransfer,
    *,
    erp_id: str | None = None,
    odoo_picking_id: int | None = None,
    odoo_picking_name: str = "",
) -> TransferWriteResult:
    """COMMITTED → **SYNCED** + simpan jejak Odoo (`odoo_picking_id`/name)."""
    transfer.state = StockTransfer.State.SYNCED
    transfer.last_error = ""
    if odoo_picking_id is not None:
        transfer.odoo_picking_id = int(odoo_picking_id)
    if odoo_picking_name:
        transfer.odoo_picking_name = odoo_picking_name[:64]
    transfer.save(
        update_fields=(
            "state",
            "last_error",
            "odoo_picking_id",
            "odoo_picking_name",
            "updated_at",
        )
    )

    record = _latest_record(transfer)
    if record is not None:
        SyncIdempotency().mark_sent(record, erp_id or transfer.odoo_picking_id)

    _audit(
        ACTION_SYNCED,
        transfer,
        None,
        {"erp_id": erp_id, "odoo_picking_id": transfer.odoo_picking_id},
    )

    return TransferWriteResult(transfer=transfer, ledger_id=None if record is None else record.pk)


def mark_failed(transfer: StockTransfer, error, request=None) -> TransferWriteResult:
    """COMMITTED → **FAILED** + simpan pesan error (mis. stok asal kurang)."""
    message = _text(error)
    transfer.state = StockTransfer.State.FAILED
    transfer.last_error = message
    transfer.save(update_fields=("state", "last_error", "updated_at"))

    record = _latest_record(transfer)
    if record is not None:
        SyncIdempotency().mark_failed(record, Exception(message))

    _audit(ACTION_FAILED, transfer, request, {"error": message})

    return TransferWriteResult(transfer=transfer, ledger_id=None if record is None else record.pk)


