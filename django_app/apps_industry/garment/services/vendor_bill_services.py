"""Service Vendor Bill + barisnya (H3.2) — transaksi satu arah MES → Odoo.

Pola **persis** `customer_invoice_services.py` (H3.1) / `purchase_order_services.py`
(H2.2): dokumen transaksi MES yang di-push ke Odoo **saat state kritis** (di sini
`CONFIRMED`), dengan ledger `SyncRecord` + `AuditLog` setiap operasi.

Perbedaan yang berasal dari STEP 0 H3.2:

  * **Greenfield**: `VendorBill`/`VendorBillLine` BARU. Jalur **I6** (tarik
    `fetch_vendor_bills` dari Odoo + `MaterialReadiness.vendor_bill_*`)
    **tidak** disentuh: ia read-only dan menyimpan hasil observasi Odoo, bukan
    ledger MES. H3.2 memakai **resource baru** `vendor_bill` dengan **stage baru**
    `VENDOR_BILL` (bukan reuse `INVOICE` milik I5/H3.1 — konsepnya `in_invoice`,
    bukan `out_invoice`);
  * **State bisnis 5 nilai**: `DRAFT → CONFIRMED → SENT → DONE`, plus `CANCELLED`.
    Kegagalan push **bukan** state model — tercatat di `SyncRecord.status=FAILED`
    dan bill tetap `CONFIRMED` (bisa di-retry, idempoten lewat `SyncRecord`);
  * **`purchase_order` opsional** (bill tanpa PO, mis. biaya jasa) **dan tidak
    unique** (satu PO boleh >1 bill: termin/partial);
  * `ref` = nomor bill dari vendor, **best-effort**: tidak wajib & boleh duplikat
    (Odoo `account.move.ref` tidak required — probe STEP 0);
  * payload push memakai `move_type="in_invoice"` + `tax_ids` **m2m**
    (`account.move.line.tax_ids`), dan **tidak** mengirim
    `account_id`/`product_uom_id`/`journal_id`/`currency_id`/`date`/`invoice_origin`
    (Odoo menghitungnya — probe STEP 0).

Guard sebelum `CONFIRMED` (brief H3.2 + probe STEP 0): `vendor.odoo_id`, tiap
`line.product.odoo_id`, tiap `tax.odoo_id`, `qty > 0`, dan `price_unit >= 0`
(bill boleh 0 — mis. nota kredit/biaya ditagih menyusul) → kalau tidak, error jelas
(view → 400) alih-alih mengirim bill cacat ke Odoo.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import transaction
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

from ..models import PurchaseOrder, PurchaseOrderLine, VendorBill, VendorBillLine

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
    "BILL_RESOURCE",
    "BILL_STAGE",
    "BILL_STATES",
    "VendorBillError",
    "VendorBillWriteResult",
    "active_bills_for_purchase_order",
    "bill_detail_row",
    "bill_line_row",
    "bill_payload",
    "bill_row",
    "cancel_bill",
    "confirm_bill",
    "create_bill",
    "delete_bill",
    "done_bill",
    "lines_from_purchase_order",
    "sync_complete",
    "sync_failed",
    "update_bill",
    "validate_bill_payload",
    "validate_line_payload",
    "vendor_bill_push_payload",
)

#: Resource & stage ledger H3.2 (KEDUANYA baru; I6 tidak memakai ledger).
BILL_RESOURCE = SyncResource.VENDOR_BILL.value
BILL_STAGE = SyncStage.VENDOR_BILL.value

#: State bisnis bill (§14 + keputusan H3.2, sama pola H3.1).
BILL_STATES: tuple[str, ...] = ("DRAFT", "CONFIRMED", "SENT", "DONE", "CANCELLED")
ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "DRAFT": ("CONFIRMED", "CANCELLED"),
    "CONFIRMED": ("DONE", "CANCELLED"),
    "SENT": ("DONE", "CANCELLED"),
    "DONE": (),
    "CANCELLED": (),
}

MAX_CODE_LENGTH = 64
MAX_REF_LENGTH = 64
MAX_LINES = 200
MAX_NOTES_LENGTH = 2000

#: Action ``AuditLog`` (namespace transaksi, analog `customer_invoice.*` H3.1).
ACTION_CREATE = "vendor_bill.create"
ACTION_UPDATE = "vendor_bill.update"
ACTION_DELETE = "vendor_bill.delete"
ACTION_CONFIRM = "vendor_bill.confirm"
ACTION_DONE = "vendor_bill.done"
ACTION_CANCEL = "vendor_bill.cancel"
#: Jejak kegagalan push (state model tetap CONFIRMED) — ditulis task.
ACTION_SYNC_FAILED = "vendor_bill.sync_failed"
#: Jejak push sukses (CONFIRMED → SENT + `odoo_id`) — ditulis task.
ACTION_SYNC_COMPLETE = "vendor_bill.sync_complete"


class VendorBillError(ValidationError):
    """Error validasi/transisi bill → dipetakan view menjadi **400**."""


@dataclass
class VendorBillWriteResult:
    """Hasil satu operasi tulis/transisi bill (dipakai view)."""

    bill: VendorBill | None = None
    error: str | None = None
    sync_record_id: int | None = None
    task_id: str | None = None
    deleted: bool = False
    #: Peringatan (bukan error): PO sudah punya bill aktif → termin/partial?
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
def _resolve_vendor(raw):
    """``(vendor, error)`` — vendor (supplier) WAJIB ada."""
    if raw in (None, ""):
        return None, "Field 'vendor_id' wajib diisi."

    try:
        vendor_id = int(raw)
    except (TypeError, ValueError):
        return None, "Field 'vendor_id' harus berupa angka."

    vendor = Partner.objects.filter(pk=vendor_id).first()
    if vendor is None:
        return None, f"Vendor {vendor_id} tidak ditemukan."

    return vendor, None


def _resolve_purchase_order(raw):
    """``(po, error)`` — PO sumber **opsional** (bill tanpa PO diizinkan)."""
    if raw in (None, ""):
        return None, None

    try:
        po_id = int(raw)
    except (TypeError, ValueError):
        return None, "Field 'purchase_order_id' harus berupa angka."

    po = PurchaseOrder.objects.filter(pk=po_id).first()
    if po is None:
        return None, f"Purchase Order {po_id} tidak ditemukan."

    return po, None


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


def validate_bill_payload(data):
    """Validasi header bill -> ``(values, error)`` (kolom model siap ``create``)."""
    payload = data if isinstance(data, dict) else {}
    values: dict = {}

    vendor, error = _resolve_vendor(payload.get("vendor_id"))
    if error:
        return None, error
    values["vendor"] = vendor

    po, error = _resolve_purchase_order(payload.get("purchase_order_id"))
    if error:
        return None, error
    values["purchase_order"] = po

    # `ref` = nomor bill dari vendor: **best-effort** — boleh kosong/duplikat,
    # hanya dibatasi panjangnya (Odoo `account.move.ref` char tanpa batas view).
    ref = str(payload.get("ref") or "").strip()
    if len(ref) > MAX_REF_LENGTH:
        return None, f"Field 'ref' maksimal {MAX_REF_LENGTH} karakter."
    values["ref"] = ref

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
    """Validasi satu baris bill -> ``(values, error)``; ``taxes`` = objek Tax."""
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
        return None, f"{label}: field 'price_unit' wajib diisi (0 diizinkan)."
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

    po_line = None
    raw_po_line = payload.get("po_line_id")
    if raw_po_line not in (None, ""):
        try:
            po_line_id = int(raw_po_line)
        except (TypeError, ValueError):
            return None, f"{label}: 'po_line_id' harus berupa angka."
        po_line = PurchaseOrderLine.objects.filter(pk=po_line_id).first()
        if po_line is None:
            return None, f"{label}: baris PO {po_line_id} tidak ditemukan."
    values["po_line"] = po_line

    return values, None


# ---------------------------------------------------------------------------
# Auto-fill dari PurchaseOrderLine (H2.2) + serialisasi
# ---------------------------------------------------------------------------
def lines_from_purchase_order(po) -> list[dict]:
    """Baris awal bill dari `PurchaseOrderLine` PO (qty × harga + pajak) — editable.

    Dipakai ``create_bill`` bila payload tidak mengirim ``lines``; operator boleh
    mengubah/menambah/menghapus baris di UI sebelum ``CONFIRMED`` (mis. bill
    termin: qty diturunkan, atau harga disesuaikan ke tagihan vendor).
    """
    lines: list[dict] = []
    if po is None:
        return lines

    for po_line in po.lines.select_related("product").order_by("id"):
        lines.append(
            {
                "po_line": po_line,
                "product": po_line.product,
                "qty": _decimal(po_line.qty),
                "price_unit": _decimal(po_line.price_unit),
                "taxes": list(po_line.tax_ids.all()) if po_line.pk else [],
            }
        )

    return lines


def _write_lines(bill: VendorBill, lines: list[dict]) -> None:
    """Tulis baris bill (dipakai create & update/replace) + sinkronkan `amount_total`."""
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

        line = VendorBillLine.objects.create(bill=bill, **write_values)
        if taxes:
            line.tax_ids.set(taxes)

    #: H3.3 — `amount_total` disimpan di header (dipakai guard anti-overpay `Payment`).
    bill.amount_total = _money(total)
    bill.save(update_fields=("amount_total", "updated_at"))


def bill_line_row(line: VendorBillLine) -> dict:
    """Satu baris bill (kontrak API) — termasuk ``subtotal`` & pajak."""
    qty = _decimal(line.qty)
    price = _decimal(line.price_unit)
    taxes = list(line.tax_ids.all())

    return {
        "id": line.pk,
        "po_line_id": line.po_line_id,
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


def bill_row(bill: VendorBill) -> dict:
    """Baris list bill (`lines_count` + `amount_total` dari field tersimpan)."""
    lines = list(bill.lines.all())
    total = _money(_decimal(bill.amount_total))

    return {
        "id": bill.pk,
        "code": bill.code,
        "purchase_order_id": bill.purchase_order_id,
        "purchase_order_no": getattr(bill.purchase_order, "code", None),
        "vendor_id": bill.vendor_id,
        "vendor_name": getattr(bill.vendor, "name", None),
        "vendor_code": getattr(bill.vendor, "code", None),
        "ref": bill.ref,
        "invoice_date": _iso(bill.invoice_date),
        "due_date": _iso(bill.due_date),
        "state": bill.state,
        "notes": bill.notes,
        "lines_count": len(lines),
        "amount_total": str(total),
        "odoo_id": bill.odoo_id,
        "created_at": _iso(bill.created_at),
        "updated_at": _iso(bill.updated_at),
    }


def bill_detail_row(bill: VendorBill) -> dict:
    """Detail bill = baris list + ``lines[]`` + info sync Odoo + aksi yang boleh."""
    record = SyncRecord.objects.filter(
        resource=BILL_RESOURCE, resource_id=str(bill.pk), stage=BILL_STAGE
    ).first()
    row = bill_row(bill)
    row.update(
        {
            "lines": [bill_line_row(line) for line in bill.lines.all()],
            "odoo_sync_status": None if record is None else record.status,
            "odoo_sync_error": None if record is None else (record.last_error or None),
            "allowed_actions": list(ALLOWED_TRANSITIONS.get(bill.state, ())),
        }
    )

    return row


def bill_payload(bill: VendorBill) -> dict:
    """Payload ledger/jejak sync (dasar payload push ke Odoo)."""
    return {
        "code": bill.code,
        "purchase_order_id": bill.purchase_order_id,
        "purchase_order_no": getattr(bill.purchase_order, "code", None),
        "vendor_id": bill.vendor_id,
        "vendor_odoo_id": getattr(bill.vendor, "odoo_id", None),
        "ref": bill.ref,
        "state": bill.state,
        "invoice_date": _iso(bill.invoice_date),
        "due_date": _iso(bill.due_date),
        "odoo_id": bill.odoo_id,
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
            for line in bill.lines.all()
        ],
    }


def vendor_bill_push_payload(bill: VendorBill) -> dict:
    """Payload push **ke adapter** (`push_vendor_bill`, H3.2).

    Berbeda dari `bill_payload` (jejak ledger yang memakai pk MES), payload ini
    memakai id **Odoo** karena langsung dikirim: ``partner_odoo_id`` +
    ``lines[].product_odoo_id`` + ``lines[].tax_odoo_ids``. ``ref`` = nomor bill
    vendor, **fallback** ke kode MES `VB-…` supaya Odoo selalu punya penanda
    (best-effort — `ref` tidak wajib di Odoo, probe STEP 0). Baris tanpa
    ``product.odoo_id`` sengaja dilewati (guard CONFIRMED sudah menahan sebelumnya).
    """
    lines = []
    for line in bill.lines.select_related("product").all():
        product_odoo_id = getattr(line.product, "odoo_id", None)
        if not product_odoo_id:
            continue

        lines.append(
            {
                "product_odoo_id": product_odoo_id,
                "quantity": str(_decimal(line.qty)),
                "price_unit": str(_decimal(line.price_unit)),
                "tax_odoo_ids": sorted(
                    tax.odoo_id for tax in line.tax_ids.all() if tax.odoo_id
                ),
            }
        )

    return {
        "ref": bill.ref or bill.code,
        "partner_odoo_id": getattr(bill.vendor, "odoo_id", None),
        "invoice_date": _iso(bill.invoice_date),
        "due_date": _iso(bill.due_date),
        "lines": lines,
    }


# ---------------------------------------------------------------------------
# Ledger (SyncRecord) + audit + enqueue task push
# ---------------------------------------------------------------------------
def _arm_push(bill: VendorBill, action: str = "push") -> SyncRecord:
    """Siapkan ``SyncRecord`` bill ini (PENDING, payload terbaru).

    ``unique(resource, resource_id, stage)`` hanya mengizinkan satu baris per bill
    ⇒ perubahan berikutnya meng-*update* baris yang sama (idempoten). Payload yang
    disimpan = **payload push** + kunci ``action`` (``push``/``cancel``).
    """
    payload = vendor_bill_push_payload(bill) | {"action": action}
    sync = SyncIdempotency()
    record = sync.get_or_create_sync_record(BILL_RESOURCE, bill.pk, BILL_STAGE, payload)

    if (
        dict(record.payload or {}) != payload
        or record.status != SyncStatus.PENDING
        or record.last_error
    ):
        record.payload = payload
        record.status = SyncStatus.PENDING
        record.last_error = ""
        record.save(update_fields=("payload", "status", "last_error", "updated_at"))
        logger.info("vendor_bill: SyncRecord %s di-arm ulang (%s).", record.pk, action)

    return record


def _audit(action: str, bill: VendorBill, request, metadata: dict | None = None) -> None:
    """Tulis ``AuditLog`` — best-effort (tidak boleh menggagalkan transaksi)."""
    try:
        AuditLogger().log(
            user=None,
            action=action,
            resource=BILL_RESOURCE,
            resource_id=bill.pk,
            request=request,
            payload=bill_payload(bill),
            result=AuditLog.Result.OK,
            metadata=metadata or {},
        )
    except Exception:  # noqa: BLE001 - audit tidak boleh menggagalkan transaksi bill
        logger.exception("vendor_bill: gagal menulis audit (%s, %s).", action, bill.pk)


def _enqueue_push(bill: VendorBill, record: SyncRecord, action: str) -> str | None:
    """Enqueue push/cancel bill ke Odoo; broker mati → ``None`` (record PENDING)."""
    try:
        # Import lazy: `tasks_vendor_bill_push` mengimpor modul ini (payload).
        from integrations.erp_sync.tasks_vendor_bill_push import push_vendor_bill

        async_result = push_vendor_bill.apply_async(
            args=[bill.pk, record.pk, action],
            headers={"x-request-id": get_request_id() or ""},
        )
        return str(async_result.id)
    except Exception:  # noqa: BLE001 - CRUD bill tidak boleh gagal karena broker
        logger.exception(
            "vendor_bill: gagal enqueue %s bill %s (SyncRecord %s tetap PENDING).",
            action,
            bill.pk,
            record.pk,
        )
        return None


# ---------------------------------------------------------------------------
# Helper transisi
# ---------------------------------------------------------------------------
def _assert_transition(bill: VendorBill, target: str) -> str | None:
    """``None`` kalau transisi ``bill.state → target`` diizinkan, else pesan error."""
    if target not in BILL_STATES:
        return f"State '{target}' tidak dikenal."

    allowed = ALLOWED_TRANSITIONS.get(bill.state, ())
    if target not in allowed:
        return (
            f"Vendor Bill {bill.code} berstatus {bill.state}; transisi ke {target} "
            f"tidak diizinkan (yang boleh: {', '.join(allowed) or 'tidak ada'})."
        )

    return None


def _assert_draft(bill: VendorBill, verb: str) -> str | None:
    """Guard: hanya DRAFT yang boleh diubah/dihapus (pola H1/H2.1/H2.2/H3.1)."""
    if bill.state != "DRAFT":
        return f"Vendor Bill {bill.code} berstatus {bill.state}; {verb} hanya boleh saat DRAFT."
    return None


def active_bills_for_purchase_order(po) -> int:
    """Jumlah bill AKTIF (bukan CANCELLED) satu PO (peringatan UI, bukan blokir)."""
    if po is None:
        return 0
    return VendorBill.objects.filter(purchase_order=po).exclude(state="CANCELLED").count()


def _current_header(bill: VendorBill) -> dict:
    """Header bill dalam bentuk payload (dipakai update parsial)."""
    return {
        "purchase_order_id": bill.purchase_order_id,
        "vendor_id": bill.vendor_id,
        "ref": bill.ref,
        "invoice_date": _iso(bill.invoice_date),
        "due_date": _iso(bill.due_date),
        "notes": bill.notes,
    }


def _resolve_lines(payload, po):
    """``(lines, error)`` — baris dari payload, atau auto-fill dari PO (H2.2)."""
    raw_lines = payload.get("lines")
    if raw_lines in (None, ""):
        if po is None:
            return None, (
                "Bill tanpa Purchase Order harus mengirim 'lines' secara eksplisit "
                "(tidak ada PO sumber untuk auto-fill)."
            )
        lines = lines_from_purchase_order(po)
        if not lines:
            return None, (
                f"Purchase Order {po.code} tidak punya baris (PO Line) untuk dibuat bill; "
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
def create_bill(data, request=None) -> VendorBillWriteResult:
    """Buat bill (nomor ``VB-<TAHUN>-<SEQ>``, Sprint C) + baris nested **atomik**.

    Baris: dari ``lines`` payload bila dikirim, kalau tidak **auto-fill** dari
    `PurchaseOrderLine` PO (bila ``purchase_order_id`` ada; lihat
    `lines_from_purchase_order`) — semuanya masih editable selama `DRAFT`. Bill
    lahir `DRAFT` = MES-only.

    **Tidak** ada blokir duplikat per PO (termin/partial) **maupun** blokir `ref`
    duplikat (best-effort, probe STEP 0): bila PO yang sama sudah punya bill aktif,
    hasilnya memuat ``duplicate_warning`` + jejak `AuditLog`.
    """
    payload = data if isinstance(data, dict) else {}
    values, error = validate_bill_payload(payload)
    if error:
        return VendorBillWriteResult(error=error)

    lines, error = _resolve_lines(payload, values["purchase_order"])
    if error:
        return VendorBillWriteResult(error=error)

    duplicate_active = active_bills_for_purchase_order(values["purchase_order"])

    with transaction.atomic():
        try:
            code = next_number("VB")
        except SequenceError as exc:
            return VendorBillWriteResult(error=f"Penomoran vendor bill gagal: {exc}")

        bill = VendorBill.objects.create(code=code, state="DRAFT", **values)
        _write_lines(bill, lines)

    record = _arm_push(bill)
    _audit(
        ACTION_CREATE,
        bill,
        request,
        {
            "code": bill.code,
            "lines": bill.lines.count(),
            "duplicate_po_bill": duplicate_active > 0,
            "active_bills_for_po": duplicate_active,
        },
    )

    logger.info(
        "vendor_bill: bill %s (%s) dibuat dengan %s baris (ledger=%s, DRAFT MES-only%s).",
        bill.pk,
        bill.code,
        bill.lines.count(),
        record.pk,
        ", duplikat PO (termin/partial)" if duplicate_active else "",
    )

    return VendorBillWriteResult(
        bill=bill,
        sync_record_id=record.pk,
        duplicate_warning=(
            f"Purchase Order {getattr(values['purchase_order'], 'code', '')} sudah punya "
            f"{duplicate_active} bill aktif — pastikan ini termin/partial yang benar."
            if duplicate_active
            else None
        ),
    )


def update_bill(bill: VendorBill, data, request=None) -> VendorBillWriteResult:
    """Ubah bill **DRAFT-only**; ``lines`` (bila dikirim) **mengganti** seluruh baris."""
    error = _assert_draft(bill, "perubahan")
    if error:
        return VendorBillWriteResult(bill=bill, error=error)

    payload = data if isinstance(data, dict) else {}
    values, error = validate_bill_payload({**_current_header(bill), **payload})
    if error:
        return VendorBillWriteResult(bill=bill, error=error)

    if payload.get("lines") is not None:
        lines, error = _resolve_lines(payload, values["purchase_order"])
        if error:
            return VendorBillWriteResult(bill=bill, error=error)
    else:
        lines = None

    with transaction.atomic():
        for field, value in values.items():
            setattr(bill, field, value)
        bill.save()

        if lines is not None:
            bill.lines.all().delete()
            _write_lines(bill, lines)

    record = _arm_push(bill)
    _audit(ACTION_UPDATE, bill, request, {"code": bill.code, "lines": bill.lines.count()})

    logger.info("vendor_bill: bill %s (%s) diubah (ledger=%s).", bill.pk, bill.code, record.pk)

    return VendorBillWriteResult(bill=bill, sync_record_id=record.pk)


def delete_bill(bill: VendorBill, request=None) -> VendorBillWriteResult:
    """Hapus bill **DRAFT-only** (hard delete; baris ikut terhapus lewat CASCADE)."""
    error = _assert_draft(bill, "hapus")
    if error:
        return VendorBillWriteResult(bill=bill, error=error)

    pk = bill.pk
    code = bill.code
    _audit(ACTION_DELETE, bill, request, {"code": code, "hard_delete": True})
    bill.delete()
    logger.info("vendor_bill: bill %s (%s) dihapus (DRAFT).", pk, code)

    return VendorBillWriteResult(bill=None, deleted=True)


# ---------------------------------------------------------------------------
# Transisi (confirm → SENT → DONE, cancel) — guard brief H3.2 + probe STEP 0
# ---------------------------------------------------------------------------
def confirm_bill(bill: VendorBill, request=None) -> VendorBillWriteResult:
    """``DRAFT → CONFIRMED`` + enqueue push Odoo (draft `in_invoice`) — guard lengkap.

    Guard (semua → **400**, bukan push cacat):

      * bill punya minimal satu baris;
      * **semua** `qty > 0` dan `price_unit >= 0` (harga 0 diizinkan, mis. tagihan
        menyusul/nota — beda dari customer invoice H3.1 yang menolak 0);
      * `vendor.odoo_id` ada;
      * tiap baris `product.odoo_id` ada;
      * tiap pajak baris punya `tax.odoo_id` (pajak tanpa id Odoo tidak bisa dikirim).
    """
    error = _assert_transition(bill, "CONFIRMED")
    if error:
        return VendorBillWriteResult(bill=bill, error=error)

    lines = list(bill.lines.select_related("product").all())
    if not lines:
        return VendorBillWriteResult(
            bill=bill, error="Vendor Bill belum punya baris; tambahkan minimal satu baris."
        )

    bad_qty = [line.pk for line in lines if _decimal(line.qty) <= 0]
    if bad_qty:
        return VendorBillWriteResult(
            bill=bill,
            error=(
                f"Qty baris {', '.join(str(pk) for pk in bad_qty)} harus > 0 sebelum "
                "CONFIRMED (Odoo menolak quantity 0)."
            ),
        )

    negative_prices = [line.pk for line in lines if _decimal(line.price_unit) < 0]
    if negative_prices:
        return VendorBillWriteResult(
            bill=bill,
            error=(
                f"Harga baris {', '.join(str(pk) for pk in negative_prices)} tidak boleh "
                "negatif sebelum CONFIRMED."
            ),
        )

    if not getattr(bill.vendor, "odoo_id", None):
        return VendorBillWriteResult(
            bill=bill,
            error=(
                f"Vendor {getattr(bill.vendor, 'name', bill.vendor_id)} belum punya "
                "odoo_id (sync master partner dulu)."
            ),
        )

    missing_products = [
        getattr(line.product, "code", None) or line.product_id
        for line in lines
        if not getattr(line.product, "odoo_id", None)
    ]
    if missing_products:
        return VendorBillWriteResult(
            bill=bill,
            error=(
                "Produk baris belum punya odoo_id: "
                f"{', '.join(str(code) for code in missing_products)} (sync master produk dulu)."
            ),
        )

    missing_taxes = sorted(
        tax.pk for line in lines for tax in line.tax_ids.all() if not tax.odoo_id
    )
    if missing_taxes:
        return VendorBillWriteResult(
            bill=bill,
            error=(
                f"Pajak {', '.join(str(pk) for pk in missing_taxes)} belum punya odoo_id "
                "(sync master pajak dulu)."
            ),
        )

    bill.state = "CONFIRMED"
    bill.save(update_fields=("state", "updated_at"))

    record = _arm_push(bill, action="push")
    task_id = _enqueue_push(bill, record, "push")
    _audit(
        ACTION_CONFIRM,
        bill,
        request,
        {"code": bill.code, "lines": len(lines), "queued": task_id is not None},
    )

    logger.info(
        "vendor_bill: bill %s (%s) CONFIRMED (ledger=%s, queued=%s).",
        bill.pk,
        bill.code,
        record.pk,
        task_id is not None,
    )

    return VendorBillWriteResult(bill=bill, sync_record_id=record.pk, task_id=task_id)


def sync_complete(bill: VendorBill, erp_id) -> VendorBillWriteResult:
    """``CONFIRMED → SENT``: simpan ``odoo_id`` + tandai ``SyncRecord`` = SENT.

    Dipanggil **task** setelah adapter sukses (``erp_id`` = id ``account.move``).
    """
    if bill.state == "CONFIRMED" and erp_id:
        bill.state = "SENT"
        update_fields = ["state", "updated_at"]
        if str(erp_id).isdigit():
            bill.odoo_id = int(erp_id)
            update_fields.append("odoo_id")
        bill.save(update_fields=tuple(update_fields))

    record = SyncRecord.objects.filter(
        resource=BILL_RESOURCE, resource_id=str(bill.pk), stage=BILL_STAGE
    ).first()
    if record is not None and erp_id:
        SyncIdempotency().mark_sent(record, erp_id)

    _audit(
        ACTION_SYNC_COMPLETE,
        bill,
        None,
        {"code": bill.code, "erp_id": str(erp_id), "state": bill.state},
    )

    return VendorBillWriteResult(
        bill=bill, sync_record_id=None if record is None else record.pk
    )


def sync_failed(bill: VendorBill, error, request=None) -> VendorBillWriteResult:
    """Push gagal: ``SyncRecord`` = FAILED + audit; **state model tetap CONFIRMED**.

    Bill sengaja **tidak** dipindah ke state gagal (keputusan H3.2 = H3.1: state
    model = state bisnis; kegagalan push = state sync) supaya bisa di-retry — lewat
    task Celery berikutnya maupun tombol Confirm ulang (idempoten via `SyncRecord`).
    """
    record = SyncRecord.objects.filter(
        resource=BILL_RESOURCE, resource_id=str(bill.pk), stage=BILL_STAGE
    ).first()
    if record is not None:
        SyncIdempotency().mark_failed(record, error)

    _audit(
        ACTION_SYNC_FAILED,
        bill,
        request,
        {"code": bill.code, "error": str(error), "state": bill.state},
    )

    return VendorBillWriteResult(
        bill=bill,
        error=str(error),
        sync_record_id=None if record is None else record.pk,
    )


def done_bill(bill: VendorBill, request=None) -> VendorBillWriteResult:
    """``CONFIRMED|SENT → DONE`` (murni MES — akuntan sudah selesai di Odoo)."""
    error = _assert_transition(bill, "DONE")
    if error:
        return VendorBillWriteResult(bill=bill, error=error)

    bill.state = "DONE"
    bill.save(update_fields=("state", "updated_at"))
    _audit(ACTION_DONE, bill, request, {"code": bill.code})

    logger.info("vendor_bill: bill %s (%s) DONE.", bill.pk, bill.code)

    return VendorBillWriteResult(bill=bill)


def cancel_bill(bill: VendorBill, request=None) -> VendorBillWriteResult:
    """``DRAFT|CONFIRMED|SENT → CANCELLED``; kalau sudah punya ``odoo_id`` → push cancel.

    Odoo: `account.move.button_cancel` — kegagalan cancel **tidak** membatalkan
    pembatalan di MES, hanya tercatat di `SyncRecord` (pola `cancel_purchase_order`).
    """
    error = _assert_transition(bill, "CANCELLED")
    if error:
        return VendorBillWriteResult(bill=bill, error=error)

    odoo_id = bill.odoo_id
    bill.state = "CANCELLED"
    bill.save(update_fields=("state", "updated_at"))

    record = None
    task_id = None
    if odoo_id:
        record = _arm_push(bill, action="cancel")
        task_id = _enqueue_push(bill, record, "cancel")

    _audit(
        ACTION_CANCEL,
        bill,
        request,
        {"code": bill.code, "odoo_id": odoo_id, "queued": task_id is not None},
    )

    logger.info(
        "vendor_bill: bill %s (%s) CANCELLED (odoo_id=%s, queued=%s).",
        bill.pk,
        bill.code,
        odoo_id,
        task_id is not None,
    )

    return VendorBillWriteResult(
        bill=bill, sync_record_id=None if record is None else record.pk, task_id=task_id
    )







