"""Service Sales Order + OrderLine (H2.1) — **transaksi**, sync satu arah MES → Odoo.

Berbeda dari master H1 (sync dua arah), H2.1 = **transaksi satu arah**
(`docs/CHANGES-DETAIL-H1H5.md` §1): MES = ERP produksi, Odoo = back-office pasif.

  * ``Order``/``OrderLine`` adalah model **existing** (fase I2 memakainya untuk
    *pull* SO Odoo → MES). H2.1 menambah arah sebaliknya: ``DRAFT`` (MES-only) →
    ``CONFIRMED`` → enqueue push ``sale.order`` ke Odoo (create **draft** di Odoo;
    **tidak** memanggil ``action_confirm`` supaya stok/picking Odoo tidak bergerak).
  * Nomor order MES dari **Sprint C**: ``next_number("SO")`` → ``SO-2026-0001``.
    Nomor itu juga dikirim ke Odoo sebagai ``client_order_ref`` (Odoo tetap memakai
    nomornya sendiri, mis. ``S00033``) dan disimpan di ``Order.client_order_ref``.
  * **State machine** (CHANGES-DETAIL §14): ``DRAFT → CONFIRMED → DONE`` dan
    ``DRAFT|CONFIRMED → CANCELLED``. Transisi ditulis **eksplisit** di service
    (bukan `core.state_machine`) karena state order sudah CharField dan workflow
    engine belum punya definisi "order" (engine tetap tersedia untuk H5).
    ``DONE`` = semua ``WorkOrder`` order itu sudah ``DONE``/``CANCELLED`` (pola I8.2);
    Odoo 17 **tidak punya** state `done` ⇒ DONE murni MES. ``CANCELLED`` meng-enqueue
    ``action_cancel`` bila order sudah punya ``odoo_id``.
  * **Guard harga** (§5): setiap line wajib ``price_unit > 0`` sebelum CONFIRMED
    (auto-isi dari ``Product.sale_price`` saat create bila tidak dikirim).
  * **Guard sync** (§2): ``customer.odoo_id`` & setiap ``product.odoo_id`` wajib ada —
    kalau tidak, push **gagal** dengan pesan jelas (``MasterPushError``), tidak
    mengirim ``False``.
  * Ledger: satu ``SyncRecord`` per order, stage ``SALE_ORDER_PUSH`` (resource
    ``order`` existing), di-arm ulang (``PENDING``) setiap perubahan yang perlu dikirim.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from config.middleware import get_request_id
from core.audit.models import AuditLog
from core.audit.services import AuditLogger
from integrations.erp_sync.idempotency import SyncIdempotency
from integrations.erp_sync.models import (
    STAGE_SALE_ORDER_PUSH,
    SyncRecord,
    SyncResource,
    SyncStatus,
)
from master.models import Partner, Product, Tax
from master.sequence_services import SequenceError, next_number

from ..models import Order, OrderLine, WorkOrder

logger = logging.getLogger(__name__)

__all__ = (
    "ACTION_CANCEL",
    "ACTION_CONFIRM",
    "ACTION_CREATE",
    "ACTION_DELETE",
    "ACTION_DONE",
    "ACTION_UPDATE",
    "ALLOWED_TRANSITIONS",
    "CLOSED_WORK_ORDER_STATES",
    "ORDER_RESOURCE",
    "ORDER_STAGE",
    "ORDER_STATES",
    "OrderError",
    "OrderWriteResult",
    "cancel_order",
    "confirm_order",
    "create_order",
    "delete_order",
    "done_order",
    "line_row",
    "order_detail_row",
    "order_payload",
    "order_row",
    "update_order",
    "validate_line_payload",
    "validate_order_payload",
)

#: Resource & stage ledger (jangan ganti literal di view/task).
ORDER_RESOURCE = SyncResource.ORDER.value
ORDER_STAGE = STAGE_SALE_ORDER_PUSH

#: State order MES (§14) + transisi yang diizinkan.
ORDER_STATES: tuple[str, ...] = ("DRAFT", "CONFIRMED", "DONE", "CANCELLED")
ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "DRAFT": ("CONFIRMED", "CANCELLED"),
    "CONFIRMED": ("DONE", "CANCELLED"),
    "DONE": (),
    "CANCELLED": (),
}

#: State WorkOrder yang dianggap "sudah selesai" untuk syarat DONE.
CLOSED_WORK_ORDER_STATES: tuple[str, ...] = ("DONE", "CANCELLED")

ORDER_TYPES: tuple[str, ...] = ("EXPORT", "CUSTOM", "BRAND")
MAX_CODE_LENGTH = 64
MAX_TAG_LENGTH = 64
MAX_LINES = 200
MAX_REASON_LENGTH = 255


class OrderError(ValidationError):
    """Error validasi/transisi order → dipetakan view menjadi **400**."""


#: Action ``AuditLog`` (namespace transaksi, analog `master.create|update|delete`).
ACTION_CREATE = "order.create"
ACTION_UPDATE = "order.update"
ACTION_DELETE = "order.delete"
ACTION_CONFIRM = "order.confirm"
ACTION_DONE = "order.done"
ACTION_CANCEL = "order.cancel"


@dataclass
class OrderWriteResult:
    """Hasil satu operasi tulis/transisi order (dipakai view)."""

    order: Order | None = None
    error: str | None = None
    sync_record_id: int | None = None
    task_id: str | None = None
    deleted: bool = False

    @property
    def queued(self) -> bool:
        """True kalau task push/cancel berhasil di-enqueue (broker hidup)."""
        return self.task_id is not None


def _iso(value) -> str | None:
    """ISO-8601 atau ``None`` (datetime kosong)."""
    return value.isoformat() if value else None


def _decimal(value) -> Decimal:
    """Konversi aman ke ``Decimal`` (gagal → 0)."""
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


# ---------------------------------------------------------------------------
# Validasi payload
# ---------------------------------------------------------------------------
def _resolve_customer(raw):
    """``(customer, error)`` — customer WAJIB ada (order tanpa customer ditolak)."""
    if raw in (None, ""):
        return None, "Field 'customer_id' wajib diisi."

    try:
        customer_id = int(raw)
    except (TypeError, ValueError):
        return None, "Field 'customer_id' harus berupa angka."

    customer = Partner.objects.filter(pk=customer_id).first()
    if customer is None:
        return None, f"Customer {customer_id} tidak ditemukan."

    return customer, None


def _resolve_deadline(raw):
    """``(datetime, error)`` — deadline opsional (ISO date atau datetime, aware)."""
    if raw in (None, ""):
        return None, None

    if isinstance(raw, str):
        parsed = parse_datetime(raw)
        if parsed is None:
            day = parse_date(raw)
            if day is not None:
                parsed = timezone.datetime.combine(day, timezone.datetime.min.time())
        if parsed is None:
            return None, "Field 'deadline' harus ISO datetime/date."
        if timezone.is_naive(parsed):
            # `parse_datetime("2026-11-30")` mengembalikan tengah malam NAIVE di
            # Django 5 → jadikan aware supaya tidak ada warning naive-datetime.
            parsed = timezone.make_aware(parsed)
        return parsed, None

    return raw, None


def _resolve_taxes(raw):
    """``(tax list, error)`` — daftar id ``master.Tax`` (boleh kosong)."""
    if raw in (None, ""):
        return [], None
    if not isinstance(raw, list):
        return None, "Field 'tax_ids' harus array id pajak."

    taxes = []
    for item in raw:
        try:
            tax = Tax.objects.filter(pk=int(item)).first()
        except (TypeError, ValueError):
            return None, f"Id pajak {item!r} tidak valid."
        if tax is None:
            return None, f"Pajak {item} tidak ditemukan."
        if tax not in taxes:
            taxes.append(tax)

    return taxes, None


def validate_order_payload(data, instance: Order | None = None):
    """Validasi header order → ``(values, error)``.

    Create: ``customer_id`` wajib; ``code`` opsional (kosong = ``next_number("SO")``,
    kalau diisi harus unik). Update: hanya field yang dikirim; ``state`` TIDAK boleh
    diubah lewat sini (pakai endpoint transisi /confirm/, /done/, /cancel/).
    """
    payload = data if isinstance(data, dict) else {}
    values: dict = {}

    if "state" in payload:
        return None, (
            "Field 'state' tidak dapat diubah langsung; gunakan endpoint "
            "/confirm/, /done/, atau /cancel/."
        )

    if instance is None or "customer_id" in payload or "customer" in payload:
        customer, error = _resolve_customer(
            payload.get("customer_id", payload.get("customer"))
        )
        if error:
            return None, error
        values["customer"] = customer

    if "code" in payload:
        code = str(payload.get("code") or "").strip()
        if code:
            if len(code) > MAX_CODE_LENGTH:
                return None, f"Field 'code' maksimal {MAX_CODE_LENGTH} karakter."
            duplicates = Order.objects.filter(code=code)
            if instance is not None:
                duplicates = duplicates.exclude(pk=instance.pk)
            if duplicates.exists():
                return None, f"Kode order '{code}' sudah dipakai."
            values["code"] = code

    if "order_type" in payload:
        order_type = str(payload.get("order_type") or "").strip().upper()
        if order_type not in ORDER_TYPES:
            return None, f"Field 'order_type' harus salah satu: {', '.join(ORDER_TYPES)}."
        values["order_type"] = order_type

    if "priority" in payload:
        raw_priority = payload.get("priority")
        if isinstance(raw_priority, bool) or not isinstance(raw_priority, int):
            return None, "Field 'priority' harus integer."
        values["priority"] = raw_priority

    if "deadline" in payload:
        deadline, error = _resolve_deadline(payload.get("deadline"))
        if error:
            return None, error
        values["deadline"] = deadline

    return values, None


# ---------------------------------------------------------------------------
# Serialisasi baris & detail
# ---------------------------------------------------------------------------
def validate_line_payload(data):
    """Validasi satu baris → ``(values, error)`` (product/qty/price_unit/tag)."""
    payload = data if isinstance(data, dict) else {}
    values: dict = {}

    raw_product = payload.get("product_id", payload.get("product"))
    if raw_product in (None, ""):
        return None, "Field 'product_id' wajib diisi di setiap baris."
    try:
        product = Product.objects.filter(pk=int(raw_product)).first()
    except (TypeError, ValueError):
        return None, f"Field 'product_id' {raw_product!r} bukan angka."
    if product is None:
        return None, f"Produk {raw_product} tidak ditemukan."
    values["product"] = product

    raw_qty = payload.get("qty")
    if isinstance(raw_qty, bool) or not isinstance(raw_qty, int) or raw_qty <= 0:
        return None, "Field 'qty' harus integer > 0."
    values["qty"] = raw_qty

    raw_price = payload.get("price_unit")
    if raw_price in (None, ""):
        raw_price = getattr(product, "sale_price", 0) or 0
    price = _decimal(raw_price)
    if price < 0:
        return None, "Field 'price_unit' tidak boleh negatif."
    values["price_unit"] = price

    tag = str(payload.get("tag") or "").strip()
    if len(tag) > MAX_TAG_LENGTH:
        return None, f"Field 'tag' maksimal {MAX_TAG_LENGTH} karakter."
    values["tag"] = tag

    return values, None


def _resolve_lines(raw_lines, *, require_price: bool = False):
    """``(parsed list, error)`` — validasi SEMUA baris (nested, pola BOMLine H1.5)."""
    if not isinstance(raw_lines, list) or not raw_lines:
        return None, "Field 'lines' wajib array tidak kosong."
    if len(raw_lines) > MAX_LINES:
        return None, f"Jumlah baris maksimal {MAX_LINES}."

    parsed: list[dict] = []
    for index, raw_line in enumerate(raw_lines):
        if not isinstance(raw_line, dict):
            return None, f"lines[{index}] harus berupa objek."

        values, error = validate_line_payload(raw_line)
        if error:
            return None, f"lines[{index}]: {error}"

        taxes, error = _resolve_taxes(raw_line.get("tax_ids"))
        if error:
            return None, f"lines[{index}]: {error}"
        if require_price and _decimal(values["price_unit"]) <= 0:
            return None, (
                f"lines[{index}]: harga satuan harus > 0 sebelum order dikonfirmasi."
            )

        values["taxes"] = taxes
        parsed.append(values)

    return parsed, None


def _write_lines(order: Order, lines: list[dict]) -> None:
    """Tulis baris-baris order (dipakai create & update/replace)."""
    for values in lines:
        write_values = dict(values)
        taxes = write_values.pop("taxes", [])
        line = OrderLine.objects.create(order=order, **write_values)
        if taxes:
            line.tax_ids.set(taxes)


# ---------------------------------------------------------------------------
# Ledger (SyncRecord) + audit
# ---------------------------------------------------------------------------
def _arm_push(order: Order) -> SyncRecord:
    """Siapkan ``SyncRecord`` SALE_ORDER_PUSH order ini (PENDING + payload terbaru)."""
    payload = order_payload(order)
    sync = SyncIdempotency()
    record = sync.get_or_create_sync_record(ORDER_RESOURCE, order.pk, ORDER_STAGE, payload)

    if (
        dict(record.payload or {}) != payload
        or record.status != SyncStatus.PENDING
        or record.last_error
    ):
        record.payload = payload
        record.status = SyncStatus.PENDING
        record.last_error = ""
        record.save(update_fields=("payload", "status", "last_error", "updated_at"))
        logger.info("order: SyncRecord %s di-arm ulang (PENDING).", record.pk)

    return record


def _audit(action: str, order: Order, request, metadata: dict | None = None) -> None:
    """Tulis ``AuditLog`` — best-effort (audit tidak boleh menggagalkan transaksi)."""
    try:
        AuditLogger().log(
            user=None,
            action=action,
            resource=ORDER_RESOURCE,
            resource_id=order.pk,
            request=request,
            payload=order_payload(order),
            result=AuditLog.Result.OK,
            metadata={"direction": "mes_to_odoo", **(metadata or {})},
        )
    except Exception:  # noqa: BLE001 - audit tidak boleh menggagalkan transaksi order
        logger.exception("order: gagal menulis audit (%s, order %s).", action, order.pk)


def _enqueue_push(order: Order, record: SyncRecord, action: str) -> str | None:
    """Enqueue push/cancel SO ke Odoo; broker mati → ``None`` (record tetap PENDING)."""
    try:
        # Import lazy: `tasks_order_push` mengimpor modul ini (payload) — hindari siklus.
        from integrations.erp_sync.tasks_order_push import push_sale_order

        async_result = push_sale_order.apply_async(
            args=[order.pk, record.pk, action],
            headers={"x-request-id": get_request_id() or ""},
        )
        return str(async_result.id)
    except Exception:  # noqa: BLE001 - CRUD order tidak boleh gagal karena broker
        logger.exception(
            "order: gagal enqueue push SO %s (SyncRecord %s tetap PENDING).", order.pk, record.pk
        )
        return None


def _assert_transition(order: Order, target: str) -> str | None:
    """``None`` kalau transisi ``order.state → target`` diizinkan, else pesan error."""
    if target not in ORDER_STATES:
        return f"State '{target}' tidak dikenal."

    allowed = ALLOWED_TRANSITIONS.get(order.state, ())
    if target not in allowed:
        return (
            f"Order {order.code} berstatus {order.state}; transisi ke {target} tidak "
            f"diizinkan (yang boleh: {', '.join(allowed) or 'tidak ada'})."
        )

    return None


def _assert_draft(order: Order, verb: str) -> str | None:
    """Guard: hanya DRAFT yang boleh diubah/dihapus (pola H1 CRUD master)."""
    if order.state != "DRAFT":
        return f"Order {order.code} berstatus {order.state}; {verb} hanya boleh saat DRAFT."
    return None


# ---------------------------------------------------------------------------
# CRUD (DRAFT-only untuk perubahan) — menulis SyncRecord + AuditLog
# ---------------------------------------------------------------------------
def create_order(data, request=None) -> OrderWriteResult:
    """Buat order (nomor otomatis ``SO-<TAHUN>-<SEQ>``) + baris nested **atomik**.

    Nomor diambil dari Sprint C (`next_number("SO")`) dan **selalu** diisi ke
    ``client_order_ref`` (nomor yang dikirim ke Odoo, karena Odoo memakai nomornya
    sendiri). Order lahir ``DRAFT`` = MES-only (belum dikirim ke Odoo).
    """
    payload = data if isinstance(data, dict) else {}
    values, error = validate_order_payload(payload)
    if error:
        return OrderWriteResult(error=error)

    lines, error = _resolve_lines(payload.get("lines"))
    if error:
        return OrderWriteResult(error=error)

    strategy = transaction.atomic()
    with strategy:
        code = values.pop("code", "")
        if not code:
            try:
                code = next_number("SO")
            except SequenceError as exc:
                return OrderWriteResult(error=f"Penomoran order gagal: {exc}")

        order = Order.objects.create(code=code, client_order_ref=code, **values)
        _write_lines(order, lines)

    record = _arm_push(order)
    _audit(ACTION_CREATE, order, request, {"code": order.code, "lines": order.lines.count()})

    logger.info(
        "order: order %s (%s) dibuat dengan %s baris (ledger=%s, DRAFT MES-only).",
        order.pk,
        order.code,
        order.lines.count(),
        record.pk,
    )

    return OrderWriteResult(order=order, sync_record_id=record.pk)


def update_order(order: Order, data, request=None) -> OrderWriteResult:
    """Ubah order + replace ``lines`` (atomic) — **hanya DRAFT**.

    ``lines`` tidak dikirim = baris tidak disentuh; ``lines`` dikirim = **replace
    penuh** (pola BOMLine H1.5); validasi selesai sebelum penulisan supaya tidak ada
    state separuh.
    """
    error = _assert_draft(order, "perubahan")
    if error:
        return OrderWriteResult(order=order, error=error)

    payload = data if isinstance(data, dict) else {}
    values, error = validate_order_payload(payload, instance=order)
    if error:
        return OrderWriteResult(order=order, error=error)

    lines: list[dict] | None = None
    if "lines" in payload:
        lines, error = _resolve_lines(payload.get("lines"))
        if error:
            return OrderWriteResult(order=order, error=error)

    if not values and lines is None:
        return OrderWriteResult(order=order)

    with transaction.atomic():
        for field, value in values.items():
            setattr(order, field, value)
        if values:
            order.save()

        if lines is not None:
            order.lines.all().delete()
            _write_lines(order, lines)

    record = _arm_push(order)
    _audit(
        ACTION_UPDATE,
        order,
        request,
        {"fields": sorted(values), "lines_replaced": lines is not None},
    )

    logger.info("order: order %s (%s) diubah (ledger=%s).", order.pk, order.code, record.pk)

    return OrderWriteResult(order=order, sync_record_id=record.pk)


def delete_order(order: Order, request=None) -> OrderWriteResult:
    """Hapus order **hard delete** — hanya **DRAFT** (belum masuk produksi/sync).

    ``Order`` tidak punya kolom ``is_active`` (soft delete H1 tidak berlaku), jadi
    delete = hapus baris + line-nya (CASCADE). Setelah CONFIRMED, order tidak boleh
    dihapus lagi — pakai ``/cancel/`` supaya jejak Odoo ikut dibatalkan.
    """
    error = _assert_draft(order, "hapus")
    if error:
        return OrderWriteResult(order=order, error=error)

    code = order.code
    pk = order.pk
    _audit(ACTION_DELETE, order, request, {"hard_delete": True})
    SyncRecord.objects.filter(
        resource=ORDER_RESOURCE, resource_id=str(pk), stage=ORDER_STAGE
    ).delete()
    order.delete()

    logger.info("order: order %s (%s) dihapus (DRAFT, hard delete).", pk, code)

    return OrderWriteResult(deleted=True)


# ---------------------------------------------------------------------------
# Transisi state (§14) — DRAFT → CONFIRMED → DONE, dan → CANCELLED
# ---------------------------------------------------------------------------
def confirm_order(order: Order, request=None) -> OrderWriteResult:
    """``DRAFT → CONFIRMED`` + enqueue push ``sale.order`` (create **draft** di Odoo).

    Guard harga (§5): setiap baris wajib ``price_unit > 0`` — kalau ada yang 0,
    konfirmasi ditolak (400) supaya Odoo tidak menerima SO bernilai 0.
    Panggilan ``action_confirm`` Odoo **tidak** dilakukan (MES = source of truth;
    konfirmasi Odoo akan memicu picking/stock move yang belum dikelola).
    """
    error = _assert_transition(order, "CONFIRMED")
    if error:
        return OrderWriteResult(order=order, error=error)

    empty_price = [
        line.pk for line in order.lines.all() if _decimal(line.price_unit) <= 0
    ]
    if empty_price:
        return OrderWriteResult(
            order=order,
            error=(
                "Harga satuan harus > 0 di semua baris sebelum konfirmasi "
                f"(baris bermasalah: {empty_price})."
            ),
        )

    order.state = "CONFIRMED"
    order.save(update_fields=("state", "updated_at"))

    record = _arm_push(order)
    task_id = _enqueue_push(order, record, "create")
    _audit(ACTION_CONFIRM, order, request, {"queued": task_id is not None})

    logger.info(
        "order: order %s (%s) CONFIRMED (push %s).",
        order.pk,
        order.code,
        task_id or "tertunda (broker mati)",
    )

    return OrderWriteResult(order=order, sync_record_id=record.pk, task_id=task_id)


def done_order(order: Order, request=None) -> OrderWriteResult:
    """``CONFIRMED → DONE`` bila **semua** WorkOrder order itu sudah DONE/CANCELLED.

    ``DONE`` murni MES: Odoo 17 tidak punya state ``done`` untuk ``sale.order``
    (probe STEP 0: draft/sent/sale/cancel) ⇒ TIDAK ada push di transisi ini.
    """
    error = _assert_transition(order, "DONE")
    if error:
        return OrderWriteResult(order=order, error=error)

    work_orders = WorkOrder.objects.filter(order_line__order=order)
    pending = work_orders.exclude(state__in=CLOSED_WORK_ORDER_STATES)
    if pending.exists():
        codes = ", ".join(pending.values_list("code", flat=True)[:5])
        return OrderWriteResult(
            order=order,
            error=(
                f"Masih ada {pending.count()} WorkOrder belum selesai ({codes}); "
                "selesaikan/batalkan dulu sebelum menutup order."
            ),
        )

    order.state = "DONE"
    order.save(update_fields=("state", "updated_at"))

    record = _arm_push(order)
    _audit(ACTION_DONE, order, request, {"work_orders": work_orders.count()})

    logger.info("order: order %s (%s) DONE (MES-only, tanpa push).", order.pk, order.code)

    return OrderWriteResult(order=order, sync_record_id=record.pk)


def cancel_order(order: Order, request=None, reason: str = "") -> OrderWriteResult:
    """``DRAFT|CONFIRMED → CANCELLED`` + enqueue ``action_cancel`` Odoo bila sudah sync.

    ``reason`` opsional (disimpan di metadata audit). Order DRAFT belum pernah dikirim
    ke Odoo ⇒ tidak ada tugas cancel.
    """
    error = _assert_transition(order, "CANCELLED")
    if error:
        return OrderWriteResult(order=order, error=error)

    reason = str(reason or "").strip()[:MAX_REASON_LENGTH]
    had_odoo_id = order.odoo_id is not None

    order.state = "CANCELLED"
    order.save(update_fields=("state", "updated_at"))

    record = _arm_push(order)
    task_id = _enqueue_push(order, record, "cancel") if had_odoo_id else None
    _audit(
        ACTION_CANCEL,
        order,
        request,
        {"reason": reason, "odoo_id": order.odoo_id, "queued": task_id is not None},
    )

    logger.info(
        "order: order %s (%s) CANCELLED (push cancel=%s).",
        order.pk,
        order.code,
        "ya" if task_id else "tidak",
    )

    return OrderWriteResult(order=order, sync_record_id=record.pk, task_id=task_id)



# ---------------------------------------------------------------------------
# Serialisasi baris & detail
# ---------------------------------------------------------------------------
def line_row(line: OrderLine) -> dict:

    """Satu baris order (kontrak API) — termasuk ``subtotal`` (qty × price_unit)."""
    price = _decimal(line.price_unit)
    qty = int(line.qty or 0)

    return {
        "id": line.pk,
        "product_id": line.product_id,
        "product_code": getattr(line.product, "code", None),
        "product_name": getattr(line.product, "name", None),
        "qty": qty,
        "tag": line.tag,
        "ticket_code": line.ticket_code,
        "price_unit": str(price),
        "subtotal": str(price * qty),
        "tax_ids": sorted(tax.pk for tax in line.tax_ids.all()),
        "odoo_id": line.odoo_id,
        "created_at": _iso(line.created_at),
        "updated_at": _iso(line.updated_at),
    }


def order_row(order: Order) -> dict:
    """Baris list order (`lines_count` + `amount_total` dari line-nya)."""
    lines = list(order.lines.all())
    total = sum((_decimal(line.price_unit) * int(line.qty or 0) for line in lines), Decimal("0"))

    return {
        "id": order.pk,
        "code": order.code,
        "client_order_ref": order.client_order_ref,
        "customer_id": order.customer_id,
        "customer_name": getattr(order.customer, "name", None),
        "order_type": order.order_type,
        "state": order.state,
        "priority": order.priority,
        "deadline": _iso(order.deadline),
        "lines_count": len(lines),
        "amount_total": str(total),
        "odoo_id": order.odoo_id,
        "created_at": _iso(order.created_at),
        "updated_at": _iso(order.updated_at),
    }


def order_detail_row(order: Order) -> dict:
    """Detail order = baris list + ``lines[]`` + informasi sync Odoo."""
    record = SyncRecord.objects.filter(
        resource=ORDER_RESOURCE, resource_id=str(order.pk), stage=ORDER_STAGE
    ).first()
    row = order_row(order)
    row.update(
        {
            "lines": [line_row(line) for line in order.lines.all()],
            "work_orders_count": WorkOrder.objects.filter(order_line__order=order).count(),
            "odoo_sync_status": None if record is None else record.status,
            "allowed_actions": list(ALLOWED_TRANSITIONS.get(order.state, ())),
        }
    )

    return row


def order_payload(order: Order) -> dict:
    """Payload ledger/jejak sync (juga dasar payload push ke Odoo)."""
    lines = list(order.lines.all())

    return {
        "code": order.code,
        "client_order_ref": order.client_order_ref,
        "customer_id": order.customer_id,
        "customer_odoo_id": getattr(order.customer, "odoo_id", None),
        "state": order.state,
        "order_type": order.order_type,
        "deadline": _iso(order.deadline),
        "odoo_id": order.odoo_id,
        "lines": [
            {
                "product_id": line.product_id,
                "product_odoo_id": getattr(line.product, "odoo_id", None),
                "product_code": getattr(line.product, "code", None),
                "qty": int(line.qty or 0),
                "price_unit": str(_decimal(line.price_unit)),
                "tag": line.tag,
                "tax_ids": sorted(tax.pk for tax in line.tax_ids.all()),
                "tax_odoo_ids": sorted(
                    tax.odoo_id for tax in line.tax_ids.all() if tax.odoo_id
                ),
            }
            for line in lines
        ],
    }

