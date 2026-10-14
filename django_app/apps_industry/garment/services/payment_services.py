"""Service Payment + pembayarannya (H3.3) — transaksi satu arah MES → Odoo.

Pola **persis** `vendor_bill_services.py` (H3.2) / `customer_invoice_services.py` (H3.1):
dokumen transaksi MES yang di-push ke Odoo **saat state kritis** (`CONFIRMED`), dengan
ledger `SyncRecord` + `AuditLog` setiap operasi.

Perbedaan yang berasal dari STEP 0 H3.3:

  * **Greenfield**: `Payment` BARU. **Satu model dua arah** lewat `payment_type`
    (`INBOUND` = customer bayar kita → sumber `CustomerInvoice`; `OUTBOUND` = kita bayar
    vendor → sumber `VendorBill`) — padanan `account.payment` Odoo yang juga satu model
    dengan `payment_type` `inbound`/`outbound`;
  * **Resource BARU `payment` + STAGE BARU `PAYMENT`** (tidak menimpa ledger invoice/bill);
  * **Tepat satu sumber**: `customer_invoice` XOR `vendor_bill` (CheckConstraint DB +
    validasi service yang memastikan tipe cocok dengan sumbernya);
  * **Guard anti-overpay** (keputusan STEP 0): Σ payment **aktif** (bukan `CANCELLED`)
    untuk invoice/bill + `amount` baru **tidak boleh** melebihi `amount_total` dokumen
    (dihitung murni di MES, deterministik tanpa Odoo). Divalidasi saat create/update
    **dan** diulang saat `CONFIRMED` (defensive);
  * payload push memakai `payment_type`/`partner_type`/`partner_odoo_id`/`amount`/`date`
    + `payment_reference` (kode MES) + `ref` (no. referensi bank MES). `journal_id`
    **opsional** dari setting `ODOO_PAYMENT_JOURNAL_ID`; `currency_id`,
    `payment_method_line_id`, dan `reconciled_*` **tidak** dikirim (dihitung Odoo —
    probe STEP 0; `memo`/`communication` bahkan **tidak ada** di Odoo 17);
  * **Rekonsiliasi BUKAN tanggung jawab MES**: payment dibuat **draft** & akuntan Odoo
    yang mem-posting + merekonsiliasi.

Guard sebelum `CONFIRMED`: `partner.odoo_id` ada; `amount > 0`; `payment_date` ada;
tipe ↔ sumber cocok; guard overpay lolos. Kegagalan push **bukan** state model —
tercatat di `SyncRecord.status=FAILED` (payment tetap `CONFIRMED`, bisa di-retry).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
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
from master.models import Partner
from master.sequence_services import SequenceError, next_number

from ..models import CustomerInvoice, Payment, VendorBill

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
    "PAYMENT_INBOUND",
    "PAYMENT_METHODS",
    "PAYMENT_OUTBOUND",
    "PAYMENT_RESOURCE",
    "PAYMENT_STAGE",
    "PAYMENT_STATES",
    "PaymentError",
    "PaymentWriteResult",
    "active_payments_total",
    "cancel_payment",
    "confirm_payment",
    "create_payment",
    "delete_payment",
    "done_payment",
    "payment_detail_row",
    "payment_payload",
    "payment_push_payload",
    "payment_row",
    "remaining_amount",
    "sync_complete",
    "sync_failed",
    "update_payment",
    "validate_amount_vs_source",
    "validate_payment_payload",
)

#: Resource & stage ledger H3.3 (KEDUANYA baru).
PAYMENT_RESOURCE = SyncResource.PAYMENT.value
PAYMENT_STAGE = SyncStage.PAYMENT.value

#: Arah pembayaran (padanan `payment_type` Odoo di adapter).
PAYMENT_INBOUND = Payment.PaymentType.INBOUND.value
PAYMENT_OUTBOUND = Payment.PaymentType.OUTBOUND.value

#: Cara bayar MES-only (tidak dikirim ke Odoo).
PAYMENT_METHODS: tuple[str, ...] = tuple(Payment.Method.values)

#: State bisnis payment (§14 + keputusan H3.3, sama pola H3.1/H3.2).
PAYMENT_STATES: tuple[str, ...] = ("DRAFT", "CONFIRMED", "SENT", "DONE", "CANCELLED")
ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "DRAFT": ("CONFIRMED", "CANCELLED"),
    "CONFIRMED": ("DONE", "CANCELLED"),
    "SENT": ("DONE", "CANCELLED"),
    "DONE": (),
    "CANCELLED": (),
}

MAX_REF_LENGTH = 64
MAX_CURRENCY_LENGTH = 8
MAX_MEMO_LENGTH = 2000
MAX_NOTES_LENGTH = 2000

#: Action ``AuditLog`` (namespace transaksi, analog `vendor_bill.*` H3.2).
ACTION_CREATE = "payment.create"
ACTION_UPDATE = "payment.update"
ACTION_DELETE = "payment.delete"
ACTION_CONFIRM = "payment.confirm"
ACTION_DONE = "payment.done"
ACTION_CANCEL = "payment.cancel"
#: Jejak kegagalan push (state model tetap CONFIRMED) — ditulis task.
ACTION_SYNC_FAILED = "payment.sync_failed"
#: Jejak push sukses (CONFIRMED → SENT + `odoo_id`) — ditulis task.
ACTION_SYNC_COMPLETE = "payment.sync_complete"


class PaymentError(ValidationError):
    """Error validasi/transisi payment → dipetakan view menjadi **400**."""


@dataclass
class PaymentWriteResult:
    """Hasil satu operasi tulis/transisi payment (dipakai view)."""

    payment: Payment | None = None
    error: str | None = None
    sync_record_id: int | None = None
    task_id: str | None = None
    deleted: bool = False

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
# Validasi payload + guard anti-overpay
# ---------------------------------------------------------------------------
def _resolve_payment_type(raw):
    """``(payment_type, error)`` — wajib INBOUND/OUTBOUND (case-insensitive)."""
    value = str(raw or "").strip().upper()
    if value == "":
        return None, "Field 'payment_type' wajib diisi (INBOUND atau OUTBOUND)."
    if value not in (PAYMENT_INBOUND, PAYMENT_OUTBOUND):
        return None, "Field 'payment_type' harus 'INBOUND' atau 'OUTBOUND'."

    return value, None


def _resolve_source(payment_type: str, invoice_id, bill_id):
    """``(source, error)`` — tepat SATU sumber & tipe harus cocok.

    INBOUND ⇒ ``customer_invoice`` (``vendor_bill`` harus kosong);
    OUTBOUND ⇒ ``vendor_bill`` (``customer_invoice`` harus kosong).
    """
    has_invoice = invoice_id not in (None, "")
    has_bill = bill_id not in (None, "")

    if has_invoice and has_bill:
        return None, (
            "Isi salah satu saja: 'customer_invoice_id' (INBOUND) atau "
            "'vendor_bill_id' (OUTBOUND)."
        )
    if not has_invoice and not has_bill:
        return None, (
            "Payment harus terikat satu dokumen: 'customer_invoice_id' (INBOUND) atau "
            "'vendor_bill_id' (OUTBOUND)."
        )

    if payment_type == PAYMENT_INBOUND:
        if not has_invoice:
            return None, "Payment INBOUND harus memakai 'customer_invoice_id' (bukan vendor_bill)."
        try:
            invoice_pk = int(invoice_id)
        except (TypeError, ValueError):
            return None, "Field 'customer_invoice_id' harus berupa angka."
        invoice = CustomerInvoice.objects.filter(pk=invoice_pk).select_related("customer").first()
        if invoice is None:
            return None, f"Customer Invoice {invoice_pk} tidak ditemukan."

        return invoice, None

    if not has_bill:
        return None, "Payment OUTBOUND harus memakai 'vendor_bill_id' (bukan customer_invoice)."
    try:
        bill_pk = int(bill_id)
    except (TypeError, ValueError):
        return None, "Field 'vendor_bill_id' harus berupa angka."
    bill = VendorBill.objects.filter(pk=bill_pk).select_related("vendor").first()
    if bill is None:
        return None, f"Vendor Bill {bill_pk} tidak ditemukan."

    return bill, None


def source_partner(source):
    """Partner pemilik dokumen sumber (customer invoice → customer, bill → vendor)."""
    if isinstance(source, CustomerInvoice):
        return source.customer

    return getattr(source, "vendor", None)


def source_label(source) -> str:
    """Label dokumen sumber untuk pesan error/AuditLog."""
    if isinstance(source, CustomerInvoice):
        return f"Customer Invoice {source.code}"

    return f"Vendor Bill {getattr(source, 'code', '?')}"


def source_total(source) -> Decimal:
    """``amount_total`` dokumen sumber (field tersimpan, diisi service H3.1/H3.2)."""
    return _money(_decimal(getattr(source, "amount_total", 0)))


def active_payments_total(source, *, exclude_pk: int | None = None) -> Decimal:
    """Σ ``amount`` payment **aktif** (bukan CANCELLED) untuk satu dokumen sumber."""
    kind = "customer_invoice" if isinstance(source, CustomerInvoice) else "vendor_bill"
    queryset = Payment.objects.filter(**{kind: source}).exclude(state="CANCELLED")
    if exclude_pk is not None:
        queryset = queryset.exclude(pk=exclude_pk)

    total = queryset.aggregate(total=Sum("amount"))["total"]

    return _money(_decimal(total))


def remaining_amount(source, *, exclude_pk: int | None = None) -> Decimal:
    """Sisa yang belum dibayar (``amount_total`` − Σ payment aktif) — bisa 0/negatif."""
    return _money(source_total(source) - active_payments_total(source, exclude_pk=exclude_pk))


def validate_amount_vs_source(source, amount: Decimal, *, exclude_pk: int | None = None):
    """``(remaining_after, error)`` — **guard anti-overpay** (keputusan STEP 0 H3.3).

    Menolak bila Σ payment aktif dokumen + ``amount`` melebihi ``amount_total`` dokumen
    (dihitung murni di MES memakai field tersimpan `amount_total` H3.1/H3.2).
    """
    total = source_total(source)
    already = active_payments_total(source, exclude_pk=exclude_pk)
    remaining = _money(total - already)
    if amount > remaining:
        return remaining, (
            f"Jumlah bayar {_money(amount)} melebihi sisa {source_label(source)} "
            f"(total {total}, sudah dibayar {already}, sisa {remaining}). "
            "Kurangi jumlahnya atau batalkan payment lain lebih dulu."
        )

    return _money(remaining - amount), None


def _resolve_partner(raw, source):
    """``(partner, error)`` — eksplisit atau diturunkan dari dokumen sumber."""
    if raw in (None, ""):
        partner = source_partner(source)
        if partner is None:
            return None, "Field 'partner_id' wajib diisi (dokumen sumber belum punya partner)."

        return partner, None

    try:
        partner_id = int(raw)
    except (TypeError, ValueError):
        return None, "Field 'partner_id' harus berupa angka."

    partner = Partner.objects.filter(pk=partner_id).first()
    if partner is None:
        return None, f"Partner {partner_id} tidak ditemukan."

    return partner, None


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


def validate_payment_payload(data, *, exclude_pk: int | None = None):
    """Validasi header payment -> ``(values, error)`` (kolom model siap ``create``).

    Termasuk **guard anti-overpay**: `validate_amount_vs_source` (keputusan STEP 0).
    ``exclude_pk`` dipakai saat update agar payment yang sedang diubah tidak dihitung dua
    kali dalam Σ payment aktif.
    """
    payload = data if isinstance(data, dict) else {}
    values: dict = {}

    payment_type, error = _resolve_payment_type(payload.get("payment_type"))
    if error:
        return None, error
    values["payment_type"] = payment_type

    source, error = _resolve_source(
        payment_type, payload.get("customer_invoice_id"), payload.get("vendor_bill_id")
    )
    if error:
        return None, error
    values["customer_invoice"] = source if isinstance(source, CustomerInvoice) else None
    values["vendor_bill"] = source if isinstance(source, VendorBill) else None

    partner, error = _resolve_partner(payload.get("partner_id"), source)
    if error:
        return None, error
    values["partner"] = partner

    raw_amount = payload.get("amount")
    amount = _money(_decimal(raw_amount))
    if raw_amount in (None, ""):
        return None, "Field 'amount' wajib diisi (harus > 0)."
    if amount <= 0:
        return None, "Field 'amount' harus angka > 0."

    remaining, error = validate_amount_vs_source(source, amount, exclude_pk=exclude_pk)
    if error:
        return None, error
    values["amount"] = amount

    currency = str(payload.get("currency") or "IDR").strip().upper() or "IDR"
    if len(currency) > MAX_CURRENCY_LENGTH:
        return None, f"Field 'currency' maksimal {MAX_CURRENCY_LENGTH} karakter."
    values["currency"] = currency

    payment_date, error = _resolve_date(
        payload.get("payment_date"), "payment_date", required=True
    )
    if error:
        return None, error
    values["payment_date"] = payment_date

    method = str(payload.get("payment_method") or Payment.Method.MANUAL.value).strip().lower()
    if method not in PAYMENT_METHODS:
        return None, (
            "Field 'payment_method' harus salah satu: " f"{', '.join(PAYMENT_METHODS)}."
        )
    values["payment_method"] = method

    reference = str(payload.get("reference") or "").strip()
    if len(reference) > MAX_REF_LENGTH:
        return None, f"Field 'reference' maksimal {MAX_REF_LENGTH} karakter."
    values["reference"] = reference

    memo = str(payload.get("memo") or "")
    if len(memo) > MAX_MEMO_LENGTH:
        return None, f"Field 'memo' maksimal {MAX_MEMO_LENGTH} karakter."
    values["memo"] = memo

    notes = str(payload.get("notes") or "")
    if len(notes) > MAX_NOTES_LENGTH:
        return None, f"Field 'notes' maksimal {MAX_NOTES_LENGTH} karakter."
    values["notes"] = notes

    return values, None


# ---------------------------------------------------------------------------
# Serialisasi + payload push
# ---------------------------------------------------------------------------
def payment_row(payment: Payment) -> dict:
    """Baris list payment (kontrak API H3.3)."""
    invoice = payment.customer_invoice
    bill = payment.vendor_bill
    if invoice is not None:
        source_type, source_label_value = "CUSTOMER_INVOICE", f"Customer Invoice {invoice.code}"
    elif bill is not None:
        source_type, source_label_value = "VENDOR_BILL", f"Vendor Bill {bill.code}"
    else:
        source_type, source_label_value = "UNKNOWN", "-"

    return {
        "id": payment.pk,
        "code": payment.code,
        "payment_type": payment.payment_type,
        "partner_id": payment.partner_id,
        "partner_name": getattr(payment.partner, "name", None),
        "partner_code": getattr(payment.partner, "code", None),
        "customer_invoice_id": payment.customer_invoice_id,
        "customer_invoice_code": getattr(invoice, "code", None),
        "vendor_bill_id": payment.vendor_bill_id,
        "vendor_bill_code": getattr(bill, "code", None),
        "source_type": source_type,
        "source_label": source_label_value,
        "amount": str(_decimal(payment.amount)),
        "currency": payment.currency,
        "payment_date": _iso(payment.payment_date),
        "payment_method": payment.payment_method,
        "reference": payment.reference,
        "memo": payment.memo,
        "state": payment.state,
        "odoo_id": payment.odoo_id,
        "created_at": _iso(payment.created_at),
        "updated_at": _iso(payment.updated_at),
    }


def payment_detail_row(payment: Payment) -> dict:
    """Detail payment = baris list + info sync Odoo + sisa dokumen + aksi yang boleh."""
    record = SyncRecord.objects.filter(
        resource=PAYMENT_RESOURCE, resource_id=str(payment.pk), stage=PAYMENT_STAGE
    ).first()
    row = payment_row(payment)

    source = payment.customer_invoice or payment.vendor_bill
    row.update(
        {
            "odoo_sync_status": None if record is None else record.status,
            "odoo_sync_error": None if record is None else (record.last_error or None),
            "allowed_actions": list(ALLOWED_TRANSITIONS.get(payment.state, ())),
            "source_amount_total": (
                None if source is None else str(source_total(source))
            ),
            "source_remaining_amount": (
                None if source is None else str(remaining_amount(source))
            ),
        }
    )

    return row


def payment_payload(payment: Payment) -> dict:
    """Payload ledger/jejak sync (memakai pk MES) — ditulis ke `SyncRecord`/`AuditLog`."""
    return {
        "code": payment.code,
        "payment_type": payment.payment_type,
        "partner_id": payment.partner_id,
        "partner_odoo_id": getattr(payment.partner, "odoo_id", None),
        "customer_invoice_id": payment.customer_invoice_id,
        "vendor_bill_id": payment.vendor_bill_id,
        "amount": str(_decimal(payment.amount)),
        "currency": payment.currency,
        "payment_date": _iso(payment.payment_date),
        "payment_method": payment.payment_method,
        "reference": payment.reference,
        "state": payment.state,
        "odoo_id": payment.odoo_id,
    }


def payment_journal_odoo_id():
    """Journal pembayaran dari setting ``ODOO_PAYMENT_JOURNAL_ID`` (opsional).

    Kosong/`None` ⇒ adapter **tidak** mengirim `journal_id` dan Odoo memilih sendiri
    (`_search_default_journal()`). MES tidak pernah menulis konfigurasi ke Odoo.
    """
    value = getattr(settings, "ODOO_PAYMENT_JOURNAL_ID", None)

    return int(value) if value else None


def payment_push_payload(payment: Payment) -> dict:
    """Payload push **ke adapter** (`push_payment`, H3.3).

    Memakai id **Odoo** (`partner_odoo_id`) karena langsung dikirim. Pemetaan keputusan
    STEP 0: `payment_type` → `inbound`/`outbound`; `partner_type` →
    `customer`/`supplier`; `payment_reference` = kode MES `PAY-…` (field itu ADA di
    Odoo 17, sedangkan `memo`/`communication` **tidak ada**); `ref` = nomor referensi
    bank MES (kosong → jatuh ke kode MES supaya Odoo selalu punya penanda).
    `journal_odoo_id` hanya diisi kalau setting `ODOO_PAYMENT_JOURNAL_ID` diset;
    `currency_id`/`payment_method_line_id`/`reconciled_*` **tidak** dikirim (dihitung Odoo).
    """
    inbound = payment.payment_type == PAYMENT_INBOUND

    return {
        "payment_type": "inbound" if inbound else "outbound",
        "partner_type": "customer" if inbound else "supplier",
        "partner_odoo_id": getattr(payment.partner, "odoo_id", None),
        "amount": str(_decimal(payment.amount)),
        "date": _iso(payment.payment_date),
        "payment_reference": payment.code,
        "ref": payment.reference or payment.code,
        "journal_odoo_id": payment_journal_odoo_id(),
        "source": "customer_invoice" if inbound else "vendor_bill",
        "source_id": payment.customer_invoice_id or payment.vendor_bill_id,
    }


# ---------------------------------------------------------------------------
# Ledger (SyncRecord) + audit + enqueue task push
# ---------------------------------------------------------------------------
def _arm_push(payment: Payment, action: str = "push") -> SyncRecord:
    """Siapkan ``SyncRecord`` payment ini (PENDING, payload terbaru).

    ``unique(resource, resource_id, stage)`` hanya mengizinkan satu baris per payment ⇒
    perubahan berikutnya meng-*update* baris yang sama (idempoten). Payload yang disimpan
    = **payload push** + kunci ``action`` (``push``/``cancel``).
    """
    payload = payment_push_payload(payment) | {"action": action}
    sync = SyncIdempotency()
    record = sync.get_or_create_sync_record(PAYMENT_RESOURCE, payment.pk, PAYMENT_STAGE, payload)

    if (
        dict(record.payload or {}) != payload
        or record.status != SyncStatus.PENDING
        or record.last_error
    ):
        record.payload = payload
        record.status = SyncStatus.PENDING
        record.last_error = ""
        record.save(update_fields=("payload", "status", "last_error", "updated_at"))
        logger.info("payment: SyncRecord %s di-arm ulang (%s).", record.pk, action)

    return record


def _audit(action: str, payment: Payment, request, metadata: dict | None = None) -> None:
    """Tulis ``AuditLog`` — best-effort (tidak boleh menggagalkan transaksi)."""
    try:
        AuditLogger().log(
            user=None,
            action=action,
            resource=PAYMENT_RESOURCE,
            resource_id=payment.pk,
            request=request,
            payload=payment_payload(payment),
            result=AuditLog.Result.OK,
            metadata=metadata or {},
        )
    except Exception:  # noqa: BLE001 - audit tidak boleh menggagalkan transaksi payment
        logger.exception("payment: gagal menulis audit (%s, %s).", action, payment.pk)


def _enqueue_push(payment: Payment, record: SyncRecord, action: str) -> str | None:
    """Enqueue push/cancel payment ke Odoo; broker mati → ``None`` (record PENDING)."""
    try:
        # Import lazy: `tasks_payment_push` mengimpor modul ini (payload).
        from integrations.erp_sync.tasks_payment_push import push_payment

        async_result = push_payment.apply_async(
            args=[payment.pk, record.pk, action],
            headers={"x-request-id": get_request_id() or ""},
        )
        return str(async_result.id)
    except Exception:  # noqa: BLE001 - CRUD payment tidak boleh gagal karena broker
        logger.exception(
            "payment: gagal enqueue %s payment %s (SyncRecord %s tetap PENDING).",
            action,
            payment.pk,
            record.pk,
        )
        return None


# ---------------------------------------------------------------------------
# Helper transisi
# ---------------------------------------------------------------------------
def _assert_transition(payment: Payment, target: str) -> str | None:
    """``None`` kalau transisi ``payment.state → target`` diizinkan, else pesan error."""
    if target not in PAYMENT_STATES:
        return f"State '{target}' tidak dikenal."

    allowed = ALLOWED_TRANSITIONS.get(payment.state, ())
    if target not in allowed:
        return (
            f"Payment {payment.code} berstatus {payment.state}; transisi ke {target} "
            f"tidak diizinkan (yang boleh: {', '.join(allowed) or 'tidak ada'})."
        )

    return None


def _assert_draft(payment: Payment, verb: str) -> str | None:
    """Guard: hanya DRAFT yang boleh diubah/dihapus (pola H1/H2.1/H2.2/H3.1/H3.2)."""
    if payment.state != "DRAFT":
        return f"Payment {payment.code} berstatus {payment.state}; {verb} hanya boleh saat DRAFT."
    return None


def _current_header(payment: Payment) -> dict:
    """Header payment dalam bentuk payload (dipakai update parsial)."""
    return {
        "payment_type": payment.payment_type,
        "customer_invoice_id": payment.customer_invoice_id,
        "vendor_bill_id": payment.vendor_bill_id,
        "partner_id": payment.partner_id,
        "amount": str(_decimal(payment.amount)),
        "currency": payment.currency,
        "payment_date": _iso(payment.payment_date),
        "payment_method": payment.payment_method,
        "reference": payment.reference,
        "memo": payment.memo,
        "notes": payment.notes,
    }


# ---------------------------------------------------------------------------
# CRUD (DRAFT-only untuk perubahan) — menulis SyncRecord + AuditLog
# ---------------------------------------------------------------------------
def create_payment(data, request=None) -> PaymentWriteResult:
    """Buat payment (nomor ``PAY-<TAHUN>-<SEQ>``, Sprint C) — **DRAFT** (MES-only).

    Validasi lengkap termasuk **guard anti-overpay** terhadap dokumen sumber
    (`CustomerInvoice` untuk INBOUND / `VendorBill` untuk OUTBOUND). Payment lahir
    `DRAFT`; push ke Odoo terjadi saat `CONFIRMED`.
    """
    payload = data if isinstance(data, dict) else {}
    values, error = validate_payment_payload(payload)
    if error:
        return PaymentWriteResult(error=error)

    with transaction.atomic():
        try:
            code = next_number("PAY")
        except SequenceError as exc:
            return PaymentWriteResult(error=f"Penomoran payment gagal: {exc}")

        payment = Payment.objects.create(code=code, state="DRAFT", **values)

    record = _arm_push(payment)
    row = payment_row(payment)
    _audit(
        ACTION_CREATE,
        payment,
        request,
        {
            "code": payment.code,
            "payment_type": payment.payment_type,
            "source": row["source_label"],
            "amount": row["amount"],
            "remaining_after": str(remaining_amount(payment.customer_invoice or payment.vendor_bill)),
        },
    )

    logger.info(
        "payment: payment %s (%s, %s) dibuat: %s untuk %s (ledger=%s, DRAFT MES-only).",
        payment.pk,
        payment.code,
        payment.payment_type,
        row["amount"],
        row["source_label"],
        record.pk,
    )

    return PaymentWriteResult(payment=payment, sync_record_id=record.pk)


def update_payment(payment: Payment, data, request=None) -> PaymentWriteResult:
    """Ubah payment **DRAFT-only** (eksklusi self pada guard overpay)."""
    error = _assert_draft(payment, "perubahan")
    if error:
        return PaymentWriteResult(payment=payment, error=error)

    payload = data if isinstance(data, dict) else {}
    values, error = validate_payment_payload(
        {**_current_header(payment), **payload}, exclude_pk=payment.pk
    )
    if error:
        return PaymentWriteResult(payment=payment, error=error)

    with transaction.atomic():
        for field, value in values.items():
            setattr(payment, field, value)
        payment.save()

    record = _arm_push(payment)
    row = payment_row(payment)
    _audit(
        ACTION_UPDATE,
        payment,
        request,
        {"code": payment.code, "source": row["source_label"], "amount": row["amount"]},
    )

    logger.info("payment: payment %s (%s) diubah (ledger=%s).", payment.pk, payment.code, record.pk)

    return PaymentWriteResult(payment=payment, sync_record_id=record.pk)


def delete_payment(payment: Payment, request=None) -> PaymentWriteResult:
    """Hapus payment **DRAFT-only** (hard delete; belum pernah dikirim ke Odoo)."""
    error = _assert_draft(payment, "hapus")
    if error:
        return PaymentWriteResult(payment=payment, error=error)

    pk = payment.pk
    code = payment.code
    _audit(ACTION_DELETE, payment, request, {"code": code, "hard_delete": True})
    payment.delete()
    logger.info("payment: payment %s (%s) dihapus (DRAFT).", pk, code)

    return PaymentWriteResult(payment=None, deleted=True)


# ---------------------------------------------------------------------------
# Transisi (confirm → SENT → DONE, cancel) — guard STEP 0 H3.3
# ---------------------------------------------------------------------------
def confirm_payment(payment: Payment, request=None) -> PaymentWriteResult:
    """``DRAFT → CONFIRMED`` + enqueue push Odoo (draft `account.payment`).

    Guard (semua → **400**, bukan push cacat):

      * dokumen sumber masih ada (``customer_invoice`` XOR ``vendor_bill``);
      * **guard anti-overpay diulang** (defensive — keputusan STEP 0): Σ payment aktif
        dokumen (tanpa dirinya) + `amount` tidak melebihi `amount_total` dokumen;
      * `amount > 0` dan `payment_date` terisi;
      * `partner.odoo_id` ada (dibutuhkan `account.payment.partner_id`).
    """
    error = _assert_transition(payment, "CONFIRMED")
    if error:
        return PaymentWriteResult(payment=payment, error=error)

    source = payment.customer_invoice or payment.vendor_bill
    if source is None:
        return PaymentWriteResult(
            payment=payment,
            error=(
                "Payment tidak terikat dokumen sumber (customer_invoice/vendor_bill) — "
                "perbaiki dulu sebelum CONFIRMED."
            ),
        )

    amount = _money(_decimal(payment.amount))
    if amount <= 0:
        return PaymentWriteResult(
            payment=payment, error="Jumlah bayar harus > 0 sebelum CONFIRMED."
        )
    if payment.payment_date is None:
        return PaymentWriteResult(
            payment=payment, error="Tanggal bayar wajib diisi sebelum CONFIRMED."
        )

    _remaining, error = validate_amount_vs_source(source, amount, exclude_pk=payment.pk)
    if error:
        return PaymentWriteResult(payment=payment, error=error)

    if not getattr(payment.partner, "odoo_id", None):
        return PaymentWriteResult(
            payment=payment,
            error=(
                f"Partner {getattr(payment.partner, 'name', payment.partner_id)} belum punya "
                "odoo_id (sync master partner dulu)."
            ),
        )

    payment.state = "CONFIRMED"
    payment.save(update_fields=("state", "updated_at"))

    record = _arm_push(payment, action="push")
    task_id = _enqueue_push(payment, record, "push")
    _audit(
        ACTION_CONFIRM,
        payment,
        request,
        {
            "code": payment.code,
            "amount": str(amount),
            "source": source_label(source),
            "queued": task_id is not None,
        },
    )

    logger.info(
        "payment: payment %s (%s) CONFIRMED (ledger=%s, queued=%s).",
        payment.pk,
        payment.code,
        record.pk,
        task_id is not None,
    )

    return PaymentWriteResult(payment=payment, sync_record_id=record.pk, task_id=task_id)


def sync_complete(payment: Payment, erp_id) -> PaymentWriteResult:
    """``CONFIRMED → SENT``: simpan ``odoo_id`` + tandai ``SyncRecord`` = SENT.

    Dipanggil **task** setelah adapter sukses (``erp_id`` = id ``account.payment``).
    """
    if payment.state == "CONFIRMED" and erp_id:
        payment.state = "SENT"
        update_fields = ["state", "updated_at"]
        if str(erp_id).isdigit():
            payment.odoo_id = int(erp_id)
            update_fields.append("odoo_id")
        payment.save(update_fields=tuple(update_fields))

    record = SyncRecord.objects.filter(
        resource=PAYMENT_RESOURCE, resource_id=str(payment.pk), stage=PAYMENT_STAGE
    ).first()
    if record is not None and erp_id:
        SyncIdempotency().mark_sent(record, erp_id)

    _audit(
        ACTION_SYNC_COMPLETE,
        payment,
        None,
        {"code": payment.code, "erp_id": str(erp_id), "state": payment.state},
    )

    return PaymentWriteResult(
        payment=payment, sync_record_id=None if record is None else record.pk
    )


def sync_failed(payment: Payment, error, request=None) -> PaymentWriteResult:
    """Push gagal: ``SyncRecord`` = FAILED + audit; **state model tetap CONFIRMED**.

    Payment sengaja **tidak** dipindah ke state gagal (keputusan H3.3 = H3.1/H3.2: state
    model = state bisnis; kegagalan push = state sync) supaya bisa di-retry.
    """
    record = SyncRecord.objects.filter(
        resource=PAYMENT_RESOURCE, resource_id=str(payment.pk), stage=PAYMENT_STAGE
    ).first()
    if record is not None:
        SyncIdempotency().mark_failed(record, error)

    _audit(
        ACTION_SYNC_FAILED,
        payment,
        request,
        {"code": payment.code, "error": str(error), "state": payment.state},
    )

    return PaymentWriteResult(
        payment=payment,
        error=str(error),
        sync_record_id=None if record is None else record.pk,
    )


def done_payment(payment: Payment, request=None) -> PaymentWriteResult:
    """``CONFIRMED|SENT → DONE`` (murni MES — akuntan sudah selesai di Odoo)."""
    error = _assert_transition(payment, "DONE")
    if error:
        return PaymentWriteResult(payment=payment, error=error)

    payment.state = "DONE"
    payment.save(update_fields=("state", "updated_at"))
    _audit(ACTION_DONE, payment, request, {"code": payment.code})

    logger.info("payment: payment %s (%s) DONE.", payment.pk, payment.code)

    return PaymentWriteResult(payment=payment)


def cancel_payment(payment: Payment, request=None) -> PaymentWriteResult:
    """``DRAFT|CONFIRMED|SENT → CANCELLED``; kalau sudah punya ``odoo_id`` → push cancel.

    Odoo: `account.payment.action_cancel` — kegagalan cancel **tidak** membatalkan
    pembatalan di MES, hanya tercatat di `SyncRecord` (pola `cancel_vendor_bill`).
    """
    error = _assert_transition(payment, "CANCELLED")
    if error:
        return PaymentWriteResult(payment=payment, error=error)

    odoo_id = payment.odoo_id
    payment.state = "CANCELLED"
    payment.save(update_fields=("state", "updated_at"))

    record = None
    task_id = None
    if odoo_id:
        record = _arm_push(payment, action="cancel")
        task_id = _enqueue_push(payment, record, "cancel")

    _audit(
        ACTION_CANCEL,
        payment,
        request,
        {"code": payment.code, "odoo_id": odoo_id, "queued": task_id is not None},
    )

    logger.info(
        "payment: payment %s (%s) CANCELLED (odoo_id=%s, queued=%s).",
        payment.pk,
        payment.code,
        odoo_id,
        task_id is not None,
    )

    return PaymentWriteResult(
        payment=payment, sync_record_id=None if record is None else record.pk, task_id=task_id
    )








