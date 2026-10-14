"""Service Customer Invoice + barisnya (H3.1) — transaksi satu arah MES → Odoo.

Pola **persis** `purchase_order_services.py` (H2.2)/`order_services.py` (H2.1):
dokumen transaksi MES yang di-push ke Odoo **saat state kritis** (di sini
`CONFIRMED`), dengan ledger `SyncRecord` + `AuditLog` setiap operasi.

Perbedaan yang berasal dari STEP 0 H3.1:

  * **Greenfield**: `CustomerInvoice`/`CustomerInvoiceLine` BARU. Jalur I5
    (otomatis saat semua WorkOrder selesai) **tidak** disentuh: ia memakai
    `SyncRecord(resource="order", stage="INVOICE")` dan mengirim `price_unit=0`;
    H3.1 memakai **resource baru** `customer_invoice` dengan **stage yang sama**
    (`INVOICE`, di-reuse) sehingga dua jalur coexist tanpa saling menimpa;
  * **State bisnis 5 nilai**: `DRAFT → CONFIRMED → SENT → DONE`, plus `CANCELLED`.
    Kegagalan push **bukan** state model — tercatat di `SyncRecord.status=FAILED`
    dan invoice tetap `CONFIRMED` (bisa di-retry, idempoten lewat `SyncRecord`);
  * **Satu order boleh >1 invoice** (termin/DP) — tidak ada unique per order;
  * payload push memuat **harga & pajak nyata** (`price_unit`, `tax_odoo_ids`),
    berbeda dari I5 yang mengirim 0/tanpa pajak (usulan perbaikan I5 = backlog).

Guard sebelum `CONFIRMED` (§5 + probe STEP 0):
`customer.odoo_id`, tiap `line.product.odoo_id`, tiap `tax.odoo_id`, dan
**semua `price_unit > 0`** — kalau tidak → error jelas (view → 400) alih-alih
mengirim invoice cacat ke Odoo.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date

from config.middleware import get_request_id
from core.audit.models import AuditLog
from core.audit.services import AuditLogger
from integrations.erp_sync.idempotency import SyncIdempotency
from integrations.erp_sync.models import (
    SyncRecord,
    SyncResource,
    SyncStage,
    SyncStatus,
)
from master.models import Partner, Product, Tax
from master.sequence_services import SequenceError, next_number

from ..models import CustomerInvoice, CustomerInvoiceLine, Order, OrderLine

logger = logging.getLogger(__name__)

__all__ = (
    "ACTION_CANCEL",
    "ACTION_CONFIRM",
    "ACTION_CREATE",
    "ACTION_DELETE",
    "ACTION_DONE",
    "ACTION_SYNC_COMPLETE",
    "ACTION_SYNC_FAILED",
    "ACTION_UPDATE",
    "ALLOWED_TRANSITIONS",
    "INVOICE_RESOURCE",
    "INVOICE_STAGE",
    "INVOICE_STATES",
    "CustomerInvoiceError",
    "CustomerInvoiceWriteResult",
    "cancel_invoice",
    "confirm_invoice",
    "create_invoice",
    "customer_invoice_push_payload",
    "delete_invoice",
    "done_invoice",
    "invoice_detail_row",
    "invoice_line_row",
    "invoice_payload",
    "invoice_row",
    "sync_complete",
    "sync_failed",
    "update_invoice",
    "validate_invoice_payload",
    "validate_line_payload",
)

#: Resource & stage ledger (resource BARU, stage di-REUSE dari I5).
INVOICE_RESOURCE = SyncResource.CUSTOMER_INVOICE.value
INVOICE_STAGE = SyncStage.INVOICE.value

#: State bisnis invoice (§14 + keputusan H3.1).
INVOICE_STATES: tuple[str, ...] = ("DRAFT", "CONFIRMED", "SENT", "DONE", "CANCELLED")
ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "DRAFT": ("CONFIRMED", "CANCELLED"),
    "CONFIRMED": ("SENT", "DONE", "CANCELLED"),  # SENT lewat push; DONE bila diposting manual
    "SENT": ("DONE", "CANCELLED"),
    "DONE": (),
    "CANCELLED": (),
}

MAX_CODE_LENGTH = 64
MAX_LINES = 200
MAX_NOTES_LENGTH = 2000

#: Action ``AuditLog`` (namespace transaksi, analog `purchase_order.*` H2.2).
ACTION_CREATE = "customer_invoice.create"
ACTION_UPDATE = "customer_invoice.update"
ACTION_DELETE = "customer_invoice.delete"
ACTION_CONFIRM = "customer_invoice.confirm"
ACTION_DONE = "customer_invoice.done"
ACTION_CANCEL = "customer_invoice.cancel"
#: Jejak kegagalan push (state model tetap CONFIRMED) — ditulis task.
ACTION_SYNC_FAILED = "customer_invoice.sync_failed"
#: Jejak push sukses (CONFIRMED → SENT + `odoo_id`) — ditulis task.
ACTION_SYNC_COMPLETE = "customer_invoice.sync_complete"


class CustomerInvoiceError(ValidationError):
    """Error validasi/transisi invoice → dipetakan view menjadi **400**."""


@dataclass
class CustomerInvoiceWriteResult:
    """Hasil satu operasi tulis/transisi invoice (dipakai view)."""

    invoice: CustomerInvoice | None = None
    error: str | None = None
    sync_record_id: int | None = None
    task_id: str | None = None
    deleted: bool = False
    #: Peringatan (bukan error): order sudah punya invoice aktif → termin/DP?
    duplicate_warning: str | None = None

    @property
    def queued(self) -> bool:
        """True kalau task push/cancel berhasil di-enqueue (broker hidup)."""
        return self.task_id is not None


def _iso(value) -> str | None:
    """ISO-8601 atau ``None`` (date/datetime kosong)."""
    return value.isoformat() if value else None


def _decimal(value) -> Decimal:
    """Konversi aman ke ``Decimal`` (gagal → 0)."""
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


#: Kuantum uang 2 desimal (bentuk API & kolom model konsisten).
_MONEY = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    """Bulatkan nilai uang ke 2 desimal (``ROUND_HALF_UP``)."""
    return value.quantize(_MONEY, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Validasi payload
# ---------------------------------------------------------------------------
def _resolve_order(raw):
    """``(order, error)`` — order sumber WAJIB ada."""
    if raw in (None, ""):
        return None, "Field 'order_id' wajib diisi."

    try:
        order_id = int(raw)
    except (TypeError, ValueError):
        return None, "Field 'order_id' harus berupa angka."

    order = Order.objects.filter(pk=order_id).select_related("customer").first()
    if order is None:
        return None, f"Order {order_id} tidak ditemukan."

    return order, None


def _resolve_customer(raw, order):
    """``(customer, error)`` — customer eksplisit atau diturunkan dari order."""
    if raw in (None, ""):
        if order is None or order.customer is None:
            return None, "Field 'customer_id' wajib diisi (order sumber belum punya customer)."
        return order.customer, None

    try:
        customer_id = int(raw)
    except (TypeError, ValueError):
        return None, "Field 'customer_id' harus berupa angka."

    customer = Partner.objects.filter(pk=customer_id).first()
    if customer is None:
        return None, f"Customer {customer_id} tidak ditemukan."

    return customer, None


def _resolve_date(raw, field: str, *, required: bool = False):
    """``(date, error)`` — tanggal opsional/wajib (ISO ``YYYY-MM-DD``)."""
    if raw in (None, ""):
        if required:
            return None, f"Field '{field}' wajib diisi."
        return None, None

    if isinstance(raw, str):
        parsed = parse_date(raw)
        if parsed is None:
            return None, f"Field '{field}' harus format tanggal ISO (YYYY-MM-DD)."
        return parsed, None

    return raw, None


def validate_invoice_payload(data):
    """Validasi header invoice -> ``(values, error)`` (kolom model siap ``create``)."""
    payload = data if isinstance(data, dict) else {}
    values: dict = {}

    order, error = _resolve_order(payload.get("order_id"))
    if error:
        return None, error
    values["order"] = order

    customer, error = _resolve_customer(payload.get("customer_id"), order)
    if error:
        return None, error
    values["customer"] = customer

    invoice_date, error = _resolve_date(payload.get("invoice_date"), "invoice_date", required=True)
    if error:
        return None, error
    values["invoice_date"] = invoice_date

    due_date, error = _resolve_date(payload.get("due_date"), "due_date")
    if error:
        return None, error
    values["due_date"] = due_date

    notes = str(payload.get("notes") or "")
    if len(notes) > MAX_NOTES_LENGTH:
        return None, f"Field 'notes' maksimal {MAX_NOTES_LENGTH} karakter."
    values["notes"] = notes

    return values, None


def validate_line_payload(data, index: int = 0):
    """Validasi satu baris invoice -> ``(values, error)``; ``taxes`` = objek Tax."""
    payload = data if isinstance(data, dict) else {}
    label = f"lines[{index}]"
    values: dict = {}

    raw_product = payload.get("product_id")
    if raw_product in (None, ""):
        return None, f"{label}: field 'product_id' wajib diisi."
    try:
        product_id = int(raw_product)
    except (TypeError, ValueError):
        return None, f"{label}: 'product_id' harus berupa angka."

    product = Product.objects.filter(pk=product_id).first()
    if product is None:
        return None, f"{label}: produk {product_id} tidak ditemukan."
    values["product"] = product

    raw_qty = payload.get("qty")
    qty = _decimal(raw_qty)
    if raw_qty in (None, "") or qty <= 0:
        return None, f"{label}: 'qty' wajib angka > 0."
    values["qty"] = qty

    raw_price = payload.get("price_unit")
    if raw_price in (None, ""):
        return None, f"{label}: field 'price_unit' wajib diisi (0 diizinkan, dipush hanya saat CONFIRMED)."
    if _decimal(raw_price) < 0:
        return None, f"{label}: 'price_unit' tidak boleh negatif."
    values["price_unit"] = _decimal(raw_price)

    raw_taxes = payload.get("tax_ids")
    if raw_taxes in (None, ""):
        raw_taxes = []
    if not isinstance(raw_taxes, list):
        return None, f"{label}: field 'tax_ids' harus array id pajak."

    taxes = []
    for raw_tax in raw_taxes:
        try:
            tax_id = int(raw_tax)
        except (TypeError, ValueError):
            return None, f"{label}: id pajak {raw_tax!r} tidak valid."
        tax = Tax.objects.filter(pk=tax_id).first()
        if tax is None:
            return None, f"{label}: pajak {tax_id} tidak ditemukan."
        taxes.append(tax)
    values["taxes"] = taxes

    order_line = None
    raw_order_line = payload.get("order_line_id")
    if raw_order_line not in (None, ""):
        try:
            order_line_id = int(raw_order_line)
        except (TypeError, ValueError):
            return None, f"{label}: 'order_line_id' harus berupa angka."
        order_line = OrderLine.objects.filter(pk=order_line_id).first()
        if order_line is None:
            return None, f"{label}: baris order {order_line_id} tidak ditemukan."
    values["order_line"] = order_line

    return values, None



# ---------------------------------------------------------------------------
# Auto-fill dari OrderLine (H2.1) + serialisasi
# ---------------------------------------------------------------------------
def lines_from_order(order) -> list[dict]:
    """Baris awal invoice dari `OrderLine` order (qty × harga + pajak) — editable.

    Dipakai ``create_invoice`` bila payload tidak mengirim ``lines``; operator
    boleh mengubah/menambah/menghapus baris di UI sebelum ``CONFIRMED``.
    """
    lines: list[dict] = []
    for order_line in order.lines.select_related("product").order_by("id"):
        lines.append(
            {
                "order_line": order_line,
                "product": order_line.product,
                "qty": _decimal(order_line.qty),
                "price_unit": _decimal(order_line.price_unit),
                "taxes": list(order_line.tax_ids.all()) if order_line.pk else [],
            }
        )

    return lines


def _write_lines(invoice: CustomerInvoice, lines: list[dict]) -> None:
    """Tulis baris invoice (dipakai create & update/replace) + sinkronkan `amount_total`."""
    total = Decimal("0")
    for values in lines:
        write_values = dict(values)
        taxes = write_values.pop("taxes", [])
        qty = _decimal(write_values.get("qty"))
        price = _decimal(write_values.get("price_unit"))
        write_values["qty"] = qty
        write_values["price_unit"] = price
        write_values["line_total"] = _money(qty * price)
        total += _money(qty * price)

        line = CustomerInvoiceLine.objects.create(invoice=invoice, **write_values)
        if taxes:
            line.tax_ids.set(taxes)

    #: H3.3 — `amount_total` disimpan di header (dipakai guard anti-overpay `Payment`).
    invoice.amount_total = _money(total)
    invoice.save(update_fields=("amount_total", "updated_at"))


def invoice_line_row(line: CustomerInvoiceLine) -> dict:
    """Satu baris invoice (kontrak API) — termasuk ``subtotal`` & pajak."""
    qty = _decimal(line.qty)
    price = _decimal(line.price_unit)
    taxes = list(line.tax_ids.all())

    return {
        "id": line.pk,
        "order_line_id": line.order_line_id,
        "product_id": line.product_id,
        "product_code": getattr(line.product, "code", None),
        "product_name": getattr(line.product, "name", None),
        "qty": str(qty),
        "price_unit": str(price),
        "subtotal": str(_money(qty * price)),
        "tax_ids": sorted(tax.pk for tax in taxes),
        "tax_odoo_ids": sorted(tax.odoo_id for tax in taxes if tax.odoo_id),
        "line_total": str(_decimal(line.line_total)),
        "created_at": _iso(line.created_at),
        "updated_at": _iso(line.updated_at),
    }


def invoice_row(invoice: CustomerInvoice) -> dict:
    """Baris list invoice (`lines_count` + `amount_total` dari field tersimpan)."""
    lines = list(invoice.lines.all())
    total = _money(_decimal(invoice.amount_total))

    return {
        "id": invoice.pk,
        "code": invoice.code,
        "order_id": invoice.order_id,
        "order_no": getattr(invoice.order, "code", None),
        "customer_id": invoice.customer_id,
        "customer_name": getattr(invoice.customer, "name", None),
        "customer_code": getattr(invoice.customer, "code", None),
        "invoice_date": _iso(invoice.invoice_date),
        "due_date": _iso(invoice.due_date),
        "state": invoice.state,
        "notes": invoice.notes,
        "lines_count": len(lines),
        "amount_total": str(total),
        "odoo_id": invoice.odoo_id,
        "created_at": _iso(invoice.created_at),
        "updated_at": _iso(invoice.updated_at),
    }


def invoice_detail_row(invoice: CustomerInvoice) -> dict:
    """Detail invoice = baris list + ``lines[]`` + info sync Odoo + aksi yang boleh."""
    record = SyncRecord.objects.filter(
        resource=INVOICE_RESOURCE, resource_id=str(invoice.pk), stage=INVOICE_STAGE
    ).first()
    row = invoice_row(invoice)
    row.update(
        {
            "lines": [invoice_line_row(line) for line in invoice.lines.all()],
            "odoo_sync_status": None if record is None else record.status,
            "odoo_sync_error": None if record is None else (record.last_error or None),
            "allowed_actions": list(ALLOWED_TRANSITIONS.get(invoice.state, ())),
        }
    )

    return row


def invoice_payload(invoice: CustomerInvoice) -> dict:
    """Payload ledger/jejak sync (dasar payload push ke Odoo)."""
    return {
        "code": invoice.code,
        "order_id": invoice.order_id,
        "order_no": getattr(invoice.order, "code", None),
        "customer_id": invoice.customer_id,
        "customer_odoo_id": getattr(invoice.customer, "odoo_id", None),
        "state": invoice.state,
        "invoice_date": _iso(invoice.invoice_date),
        "due_date": _iso(invoice.due_date),
        "odoo_id": invoice.odoo_id,
        "lines": [
            {
                "product_id": line.product_id,
                "product_odoo_id": getattr(line.product, "odoo_id", None),
                "product_code": getattr(line.product, "code", None),
                "qty": str(_decimal(line.qty)),
                "price_unit": str(_decimal(line.price_unit)),
                "tax_odoo_ids": sorted(
                    tax.odoo_id for tax in line.tax_ids.all() if tax.odoo_id
                ),
            }
            for line in invoice.lines.all()
        ],
    }


def customer_invoice_push_payload(invoice: CustomerInvoice) -> dict:
    """Payload push **ke adapter** (`push_customer_invoice`, H3.1).

    Berbeda dari `invoice_payload` (jejak ledger yang memakai pk MES), payload ini
    memakai id **Odoo** karena langsung dikirim: ``partner_odoo_id`` +
    ``lines[].product_odoo_id`` + ``lines[].tax_odoo_ids``. Baris tanpa
    ``product.odoo_id`` sengaja dilewati (guard CONFIRMED sudah menahan sebelumnya).
    """
    lines = []
    for line in invoice.lines.select_related("product").all():
        product_odoo_id = getattr(line.product, "odoo_id", None)
        if not product_odoo_id:
            continue

        lines.append(
            {
                "product_odoo_id": product_odoo_id,
                "quantity": str(_decimal(line.qty)),
                "price_unit": str(_decimal(line.price_unit)),
                "name": getattr(line.product, "code", None) or invoice.code,
                "tax_odoo_ids": sorted(
                    tax.odoo_id for tax in line.tax_ids.all() if tax.odoo_id
                ),
            }
        )

    return {
        "ref": invoice.code,
        "partner_odoo_id": getattr(invoice.customer, "odoo_id", None),
        "invoice_date": _iso(invoice.invoice_date),
        "due_date": _iso(invoice.due_date),
        "lines": lines,
    }


# ---------------------------------------------------------------------------
# Ledger (SyncRecord) + audit + enqueue task push
# ---------------------------------------------------------------------------
def _arm_push(invoice: CustomerInvoice, action: str = "push") -> SyncRecord:
    """Siapkan ``SyncRecord`` invoice ini (PENDING, payload terbaru).

    ``unique(resource, resource_id, stage)`` hanya mengizinkan satu baris per
    invoice ⇒ perubahan berikutnya meng-*update* baris yang sama (idempoten).

    Payload yang disimpan = **payload push** (`customer_invoice_push_payload`, dipakai
    task untuk cek idempoten "sudah terkirim & payload sama") + kunci ``action``
    (``push``/``cancel``) supaya jejak di `/settings/sync` menjelaskan aksinya.
    """
    payload = customer_invoice_push_payload(invoice) | {"action": action}
    sync = SyncIdempotency()
    record = sync.get_or_create_sync_record(INVOICE_RESOURCE, invoice.pk, INVOICE_STAGE, payload)

    if (
        dict(record.payload or {}) != payload
        or record.status != SyncStatus.PENDING
        or record.last_error
    ):
        record.payload = payload
        record.status = SyncStatus.PENDING
        record.last_error = ""
        record.save(update_fields=("payload", "status", "last_error", "updated_at"))
        logger.info("customer_invoice: SyncRecord %s di-arm ulang (%s).", record.pk, action)

    return record


def _audit(action: str, invoice: CustomerInvoice, request, metadata: dict | None = None) -> None:
    """Tulis ``AuditLog`` — best-effort (tidak boleh menggagalkan transaksi)."""
    try:
        AuditLogger().log(
            user=None,
            action=action,
            resource=INVOICE_RESOURCE,
            resource_id=invoice.pk,
            request=request,
            payload=invoice_payload(invoice),
            result=AuditLog.Result.OK,
            metadata=metadata or {},
        )
    except Exception:  # noqa: BLE001 - audit tidak boleh menggagalkan transaksi invoice
        logger.exception("customer_invoice: gagal menulis audit (%s, %s).", action, invoice.pk)


def _enqueue_push(invoice: CustomerInvoice, record: SyncRecord, action: str) -> str | None:
    """Enqueue push/cancel invoice ke Odoo; broker mati → ``None`` (record PENDING)."""
    try:
        # Import lazy: `tasks_customer_invoice_push` mengimpor modul ini (payload).
        from integrations.erp_sync.tasks_customer_invoice_push import push_customer_invoice

        async_result = push_customer_invoice.apply_async(
            args=[invoice.pk, record.pk, action],
            headers={"x-request-id": get_request_id() or ""},
        )
        return str(async_result.id)
    except Exception:  # noqa: BLE001 - CRUD invoice tidak boleh gagal karena broker
        logger.exception(
            "customer_invoice: gagal enqueue %s invoice %s (SyncRecord %s tetap PENDING).",
            action,
            invoice.pk,
            record.pk,
        )
        return None


# ---------------------------------------------------------------------------
# Helper transisi
# ---------------------------------------------------------------------------
def _assert_transition(invoice: CustomerInvoice, target: str) -> str | None:
    """``None`` kalau transisi ``invoice.state → target`` diizinkan, else pesan error."""
    if target not in INVOICE_STATES:
        return f"State '{target}' tidak dikenal."

    allowed = ALLOWED_TRANSITIONS.get(invoice.state, ())
    if target not in allowed:
        return (
            f"Invoice {invoice.code} berstatus {invoice.state}; transisi ke {target} "
            f"tidak diizinkan (yang boleh: {', '.join(allowed) or 'tidak ada'})."
        )

    return None


def _assert_draft(invoice: CustomerInvoice, verb: str) -> str | None:
    """Guard: hanya DRAFT yang boleh diubah/dihapus (pola H1/H2.1/H2.2)."""
    if invoice.state != "DRAFT":
        return f"Invoice {invoice.code} berstatus {invoice.state}; {verb} hanya boleh saat DRAFT."
    return None


def active_invoices_for_order(order) -> int:
    """Jumlah invoice AKTIF (bukan CANCELLED) satu order (peringatan UI, bukan blokir)."""
    return CustomerInvoice.objects.filter(order=order).exclude(state="CANCELLED").count()


def _current_header(invoice: CustomerInvoice) -> dict:
    """Header invoice dalam bentuk payload (dipakai update parsial)."""
    return {
        "order_id": invoice.order_id,
        "customer_id": invoice.customer_id,
        "invoice_date": _iso(invoice.invoice_date),
        "due_date": _iso(invoice.due_date),
        "notes": invoice.notes,
    }


def _resolve_lines(payload, order):
    """``(lines, error)`` — baris dari payload, atau auto-fill dari `OrderLine`."""
    raw_lines = payload.get("lines")
    if raw_lines in (None, ""):
        lines = lines_from_order(order)
        if not lines:
            return None, (
                f"Order {order.code} tidak punya baris (OrderLine) untuk dibuat invoice; "
                "kirim 'lines' secara eksplisit."
            )
        return lines, None

    if not isinstance(raw_lines, list) or not raw_lines:
        return None, "Field 'lines' harus array baris (minimal satu)."
    if len(raw_lines) > MAX_LINES:
        return None, f"Field 'lines' maksimal {MAX_LINES} baris."

    lines: list[dict] = []
    for index, raw_line in enumerate(raw_lines):
        values, error = validate_line_payload(raw_line, index=index)
        if error:
            return None, error
        lines.append(values)

    return lines, None





# ---------------------------------------------------------------------------
# CRUD (DRAFT-only untuk perubahan) — menulis SyncRecord + AuditLog
# ---------------------------------------------------------------------------
def create_invoice(data, request=None) -> CustomerInvoiceWriteResult:
    """Buat invoice (nomor ``INV-<TAHUN>-<SEQ>``, Sprint C) + baris nested **atomik**.

    Baris: dari ``lines`` payload bila dikirim, kalau tidak **auto-fill** dari
    `OrderLine` order (qty × harga + pajak; lihat `lines_from_order`) — semuanya
    masih editable selama `DRAFT`. Invoice lahir `DRAFT` = MES-only.

    **Tidak** ada blokir duplikat per order (termin/DP): bila order yang sama sudah
    punya invoice aktif, hasilnya memuat ``duplicate_warning`` + jejak `AuditLog`.
    """
    payload = data if isinstance(data, dict) else {}
    values, error = validate_invoice_payload(payload)
    if error:
        return CustomerInvoiceWriteResult(error=error)

    lines, error = _resolve_lines(payload, values["order"])
    if error:
        return CustomerInvoiceWriteResult(error=error)

    duplicate_active = active_invoices_for_order(values["order"])

    with transaction.atomic():
        try:
            code = next_number("INV")
        except SequenceError as exc:
            return CustomerInvoiceWriteResult(error=f"Penomoran invoice gagal: {exc}")

        invoice = CustomerInvoice.objects.create(code=code, state="DRAFT", **values)
        _write_lines(invoice, lines)

    record = _arm_push(invoice)
    _audit(
        ACTION_CREATE,
        invoice,
        request,
        {
            "code": invoice.code,
            "lines": invoice.lines.count(),
            "duplicate_order_invoice": duplicate_active > 0,
            "active_invoices_for_order": duplicate_active,
        },
    )

    logger.info(
        "customer_invoice: invoice %s (%s) dibuat dengan %s baris (ledger=%s, DRAFT MES-only%s).",
        invoice.pk,
        invoice.code,
        invoice.lines.count(),
        record.pk,
        ", duplikat order (termin/DP)" if duplicate_active else "",
    )

    return CustomerInvoiceWriteResult(
        invoice=invoice,
        sync_record_id=record.pk,
        duplicate_warning=(
            f"Order {getattr(values['order'], 'code', '')} sudah punya {duplicate_active} "
            "invoice aktif — pastikan ini termin/DP yang benar."
            if duplicate_active
            else None
        ),
    )


def update_invoice(invoice: CustomerInvoice, data, request=None) -> CustomerInvoiceWriteResult:
    """Ubah invoice **DRAFT-only**; ``lines`` (bila dikirim) **mengganti** seluruh baris."""
    error = _assert_draft(invoice, "perubahan")
    if error:
        return CustomerInvoiceWriteResult(invoice=invoice, error=error)

    payload = data if isinstance(data, dict) else {}
    values, error = validate_invoice_payload({**_current_header(invoice), **payload})
    if error:
        return CustomerInvoiceWriteResult(invoice=invoice, error=error)

    if payload.get("lines") is not None:
        lines, error = _resolve_lines(payload, values["order"])
        if error:
            return CustomerInvoiceWriteResult(invoice=invoice, error=error)
    else:
        lines = None

    with transaction.atomic():
        for field, value in values.items():
            setattr(invoice, field, value)
        invoice.save()

        if lines is not None:
            invoice.lines.all().delete()
            _write_lines(invoice, lines)

    record = _arm_push(invoice)
    _audit(ACTION_UPDATE, invoice, request, {"code": invoice.code, "lines": invoice.lines.count()})

    logger.info(
        "customer_invoice: invoice %s (%s) diubah (ledger=%s).", invoice.pk, invoice.code, record.pk
    )

    return CustomerInvoiceWriteResult(invoice=invoice, sync_record_id=record.pk)


def delete_invoice(invoice: CustomerInvoice, request=None) -> CustomerInvoiceWriteResult:
    """Hapus invoice **DRAFT-only** (hard delete; baris ikut terhapus lewat CASCADE)."""
    error = _assert_draft(invoice, "hapus")
    if error:
        return CustomerInvoiceWriteResult(invoice=invoice, error=error)

    pk = invoice.pk
    code = invoice.code
    _audit(ACTION_DELETE, invoice, request, {"code": code, "hard_delete": True})
    invoice.delete()
    logger.info("customer_invoice: invoice %s (%s) dihapus (DRAFT).", pk, code)

    return CustomerInvoiceWriteResult(invoice=None, deleted=True)


# ---------------------------------------------------------------------------
# Transisi (confirm → SENT → DONE, cancel) — guard §5 + probe STEP 0
# ---------------------------------------------------------------------------
def confirm_invoice(invoice: CustomerInvoice, request=None) -> CustomerInvoiceWriteResult:
    """``DRAFT → CONFIRMED`` + enqueue push Odoo (draft) — guard lengkap.

    Guard (semua → **400**, bukan push cacat):

      * invoice punya minimal satu baris;
      * **semua** `price_unit > 0` (§5 CHANGES-DETAIL);
      * `customer.odoo_id` ada;
      * tiap baris `product.odoo_id` ada;
      * tiap pajak baris punya `tax.odoo_id` (pajak tanpa id Odoo tidak bisa dikirim).
    """
    error = _assert_transition(invoice, "CONFIRMED")
    if error:
        return CustomerInvoiceWriteResult(invoice=invoice, error=error)

    lines = list(invoice.lines.select_related("product").all())
    if not lines:
        return CustomerInvoiceWriteResult(
            invoice=invoice, error="Invoice belum punya baris; tambahkan minimal satu baris."
        )

    zero_prices = [line.pk for line in lines if _decimal(line.price_unit) <= 0]
    if zero_prices:
        return CustomerInvoiceWriteResult(
            invoice=invoice,
            error=(
                f"Harga baris {', '.join(str(pk) for pk in zero_prices)} harus > 0 sebelum "
                "CONFIRMED (invoice harga 0 ditolak; §5)."
            ),
        )

    if not getattr(invoice.customer, "odoo_id", None):
        return CustomerInvoiceWriteResult(
            invoice=invoice,
            error=(
                f"Customer {getattr(invoice.customer, 'name', invoice.customer_id)} belum punya "
                "odoo_id (sync master partner dulu)."
            ),
        )

    missing_products = [
        getattr(line.product, "code", None) or line.product_id
        for line in lines
        if not getattr(line.product, "odoo_id", None)
    ]
    if missing_products:
        return CustomerInvoiceWriteResult(
            invoice=invoice,
            error=(
                "Produk baris belum punya odoo_id: "
                f"{', '.join(str(code) for code in missing_products)} (sync master produk dulu)."
            ),
        )

    missing_taxes = sorted(
        tax.pk for line in lines for tax in line.tax_ids.all() if not tax.odoo_id
    )
    if missing_taxes:
        return CustomerInvoiceWriteResult(
            invoice=invoice,
            error=(
                f"Pajak {', '.join(str(pk) for pk in missing_taxes)} belum punya odoo_id "
                "(sync master pajak dulu)."
            ),
        )

    invoice.state = "CONFIRMED"
    invoice.save(update_fields=("state", "updated_at"))

    record = _arm_push(invoice, action="push")
    task_id = _enqueue_push(invoice, record, "push")
    _audit(
        ACTION_CONFIRM,
        invoice,
        request,
        {"code": invoice.code, "lines": len(lines), "queued": task_id is not None},
    )

    logger.info(
        "customer_invoice: invoice %s (%s) CONFIRMED (ledger=%s, queued=%s).",
        invoice.pk,
        invoice.code,
        record.pk,
        task_id is not None,
    )

    return CustomerInvoiceWriteResult(invoice=invoice, sync_record_id=record.pk, task_id=task_id)




def sync_complete(invoice: CustomerInvoice, erp_id) -> CustomerInvoiceWriteResult:
    """``CONFIRMED → SENT``: simpan ``odoo_id`` + tandai ``SyncRecord`` = SENT.

    Dipanggil **task** setelah adapter sukses (``erp_id`` = id ``account.move``).
    """
    if invoice.state == "CONFIRMED" and erp_id:
        invoice.state = "SENT"
        update_fields = ["state", "updated_at"]
        if str(erp_id).isdigit():
            invoice.odoo_id = int(erp_id)
            update_fields.append("odoo_id")
        invoice.save(update_fields=tuple(update_fields))

    record = SyncRecord.objects.filter(
        resource=INVOICE_RESOURCE, resource_id=str(invoice.pk), stage=INVOICE_STAGE
    ).first()
    if record is not None and erp_id:
        SyncIdempotency().mark_sent(record, erp_id)

    _audit(
        ACTION_SYNC_COMPLETE,
        invoice,
        None,
        {"code": invoice.code, "erp_id": str(erp_id), "state": invoice.state},
    )

    return CustomerInvoiceWriteResult(
        invoice=invoice, sync_record_id=None if record is None else record.pk
    )


def sync_failed(invoice: CustomerInvoice, error, request=None) -> CustomerInvoiceWriteResult:
    """Push gagal: ``SyncRecord`` = FAILED + audit; **state model tetap CONFIRMED**.

    Invoice sengaja **tidak** dipindah ke state gagal (keputusan H3.1: state model =
    state bisnis; kegagalan push = state sync) supaya bisa di-retry — lewat task
    Celery berikutnya maupun tombol Confirm ulang (idempoten via `SyncRecord`).
    """
    record = SyncRecord.objects.filter(
        resource=INVOICE_RESOURCE, resource_id=str(invoice.pk), stage=INVOICE_STAGE
    ).first()
    if record is not None:
        SyncIdempotency().mark_failed(record, error)

    _audit(
        ACTION_SYNC_FAILED,
        invoice,
        request,
        {"code": invoice.code, "error": str(error), "state": invoice.state},
    )

    return CustomerInvoiceWriteResult(
        invoice=invoice,
        error=str(error),
        sync_record_id=None if record is None else record.pk,
    )


def done_invoice(invoice: CustomerInvoice, request=None) -> CustomerInvoiceWriteResult:
    """``CONFIRMED|SENT → DONE`` (murni MES — akuntan sudah selesai di Odoo)."""
    error = _assert_transition(invoice, "DONE")
    if error:
        return CustomerInvoiceWriteResult(invoice=invoice, error=error)

    invoice.state = "DONE"
    invoice.save(update_fields=("state", "updated_at"))
    _audit(ACTION_DONE, invoice, request, {"code": invoice.code})

    logger.info("customer_invoice: invoice %s (%s) DONE.", invoice.pk, invoice.code)

    return CustomerInvoiceWriteResult(invoice=invoice)


def cancel_invoice(invoice: CustomerInvoice, request=None) -> CustomerInvoiceWriteResult:
    """``DRAFT|CONFIRMED|SENT → CANCELLED``; kalau sudah punya ``odoo_id`` → push cancel.

    Odoo: `account.move.button_cancel` — kegagalan cancel **tidak** membatalkan
    pembatalan di MES, hanya tercatat di `SyncRecord` (pola `cancel_purchase_order`).
    """
    error = _assert_transition(invoice, "CANCELLED")
    if error:
        return CustomerInvoiceWriteResult(invoice=invoice, error=error)

    odoo_id = invoice.odoo_id
    invoice.state = "CANCELLED"
    invoice.save(update_fields=("state", "updated_at"))

    record = None
    task_id = None
    if odoo_id:
        record = _arm_push(invoice, action="cancel")
        task_id = _enqueue_push(invoice, record, "cancel")

    _audit(
        ACTION_CANCEL,
        invoice,
        request,
        {"code": invoice.code, "odoo_id": odoo_id, "queued": task_id is not None},
    )

    logger.info(
        "customer_invoice: invoice %s (%s) CANCELLED (odoo_id=%s, queued=%s).",
        invoice.pk,
        invoice.code,
        odoo_id,
        task_id is not None,
    )

    return CustomerInvoiceWriteResult(
        invoice=invoice, sync_record_id=None if record is None else record.pk, task_id=task_id
    )
