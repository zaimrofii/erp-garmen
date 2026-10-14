"""Service Purchase Order + PurchaseOrderLine (H2.2) — transaksi satu arah MES → Odoo.

Pola **persis** `order_services.py` (H2.1) karena PO = dokumen transaksi sejenis,
dengan empat perbedaan yang berasal dari probe STEP 0:

  * **Greenfield**: `PurchaseOrder`/`PurchaseOrderLine` model BARU (tidak ada PO di
    MES sebelumnya — PO Odoo hanya dibaca transport di B10/B11 & `po_ids` I3);
  * Odoo `purchase.order` memakai **`partner_ref`** untuk nomor MES (bukan
    `client_order_ref` seperti `sale.order`);
  * baris Odoo memakai **`taxes_id`** (m2m), bukan `tax_id` seperti sale order;
  * `qty` baris = **Decimal** (Odoo `product_qty` float, mis. benang 0.3).

Aturan yang sama dengan H2.1:

  * `DRAFT` murni MES ⇒ `CONFIRMED` meng-enqueue push `purchase.order.create`
    (create **draft** di Odoo, `action_confirm` **tidak** dipanggil);
  * `DONE` murni MES (Odoo `done` = *Locked* yang dipicu receipt) dan
    `CANCELLED` meng-enqueue `action_cancel` bila `odoo_id` sudah ada;
  * guard §5: semua baris wajib `price_unit > 0` **dan** `vendor.odoo_id` ada
    sebelum CONFIRMED;
  * guard §2: `product.odoo_id` setiap baris wajib ada ⇒ kalau tidak, push gagal
    dengan pesan jelas (`MasterPushError`), bukan mengirim `False`;
  * ledger `SyncRecord` stage **`PURCHASE_ORDER_PUSH`**, resource
    **`purchase_order`**, di-arm ulang (PENDING) setiap perubahan yang perlu dikirim.

Catatan operasional I3 (`material_readiness`): PO yang kita push tetap **draft** di
Odoo, sedangkan I3 hanya menghitung `PO_STATES = ("purchase", "done")` ⇒ purchasing
harus men-*confirm* PO di UI Odoo agar readiness ikut menghitungnya (MES **tidak**
auto-confirm — lihat `decisions[]` di JSON).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date

from config.middleware import get_request_id
from core.audit.models import AuditLog
from core.audit.services import AuditLogger
from integrations.erp_sync.idempotency import SyncIdempotency
from integrations.erp_sync.models import (
    STAGE_PURCHASE_ORDER_PUSH,
    SyncRecord,
    SyncResource,
    SyncStatus,
)
from master.models import Partner, Product, Tax
from master.sequence_services import SequenceError, next_number

from ..models import PurchaseOrder, PurchaseOrderLine

logger = logging.getLogger(__name__)

__all__ = (
    "ACTION_CANCEL",
    "ACTION_CONFIRM",
    "ACTION_CREATE",
    "ACTION_DELETE",
    "ACTION_DONE",
    "ACTION_UPDATE",
    "ALLOWED_TRANSITIONS",
    "PO_RESOURCE",
    "PO_STAGE",
    "PO_STATES",
    "PurchaseOrderError",
    "PurchaseOrderWriteResult",
    "cancel_purchase_order",
    "confirm_purchase_order",
    "create_purchase_order",
    "delete_purchase_order",
    "done_purchase_order",
    "fetch_odoo_state",
    "purchase_order_detail_row",
    "purchase_order_line_row",
    "purchase_order_payload",
    "purchase_order_row",
    "update_purchase_order",
    "validate_line_payload",
    "validate_po_payload",
)

#: Resource & stage ledger (jangan ganti literal di view/task).
PO_RESOURCE = SyncResource.PURCHASE_ORDER.value
PO_STAGE = STAGE_PURCHASE_ORDER_PUSH

#: State PO MES (§14) + transisi yang diizinkan.
PO_STATES: tuple[str, ...] = ("DRAFT", "CONFIRMED", "DONE", "CANCELLED")
ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "DRAFT": ("CONFIRMED", "CANCELLED"),
    "CONFIRMED": ("DONE", "CANCELLED"),
    "DONE": (),
    "CANCELLED": (),
}

MAX_CODE_LENGTH = 64
MAX_LINES = 200
MAX_NOTES_LENGTH = 2000
MAX_REASON_LENGTH = 255

#: Action ``AuditLog`` (namespace transaksi, analog `order.*` H2.1).
ACTION_CREATE = "purchase_order.create"
ACTION_UPDATE = "purchase_order.update"
ACTION_DELETE = "purchase_order.delete"
ACTION_CONFIRM = "purchase_order.confirm"
ACTION_DONE = "purchase_order.done"
ACTION_CANCEL = "purchase_order.cancel"


class PurchaseOrderError(ValidationError):
    """Error validasi/transisi PO → dipetakan view menjadi **400**."""


@dataclass
class PurchaseOrderWriteResult:
    """Hasil satu operasi tulis/transisi PO (dipakai view)."""

    po: PurchaseOrder | None = None
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


#: Kuantum uang 2 desimal (mis. `Decimal("10.50") * Decimal("30000.00")` =
#: `315000.0000` ⇒ dibulatkan ke `315000.00` supaya bentuk API konsisten).
_MONEY = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    """Bulatkan nilai uang ke 2 desimal (``ROUND_HALF_UP`` bawaan Decimal)."""
    return value.quantize(_MONEY)



# ---------------------------------------------------------------------------
# Validasi payload
# ---------------------------------------------------------------------------
def _resolve_vendor(raw):
    """``(vendor, error)`` — vendor WAJIB ada (PO tanpa vendor ditolak)."""
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


def _resolve_date(raw, field: str):
    """``(date, error)`` — tanggal opsional (ISO ``YYYY-MM-DD``)."""
    if raw in (None, ""):
        return None, None

    if isinstance(raw, str):
        parsed = parse_date(raw)
        if parsed is None:
            return None, f"Field '{field}' harus format tanggal ISO (YYYY-MM-DD)."
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


def validate_po_payload(data, instance: PurchaseOrder | None = None):
    """Validasi header PO → ``(values, error)``.

    Create: ``vendor_id`` wajib; ``code`` opsional (kosong = ``next_number("PO")``,
    kalau diisi harus unik). Update: hanya field yang dikirim; ``state`` TIDAK boleh
    diubah lewat sini (pakai endpoint transisi).
    """
    payload = data if isinstance(data, dict) else {}
    values: dict = {}

    if "state" in payload:
        return None, (
            "Field 'state' tidak dapat diubah langsung; gunakan endpoint "
            "/confirm/, /done/, atau /cancel/."
        )

    if instance is None or "vendor_id" in payload or "vendor" in payload:
        vendor, error = _resolve_vendor(payload.get("vendor_id", payload.get("vendor")))
        if error:
            return None, error
        values["vendor"] = vendor

    if "code" in payload:
        code = str(payload.get("code") or "").strip()
        if code:
            if len(code) > MAX_CODE_LENGTH:
                return None, f"Field 'code' maksimal {MAX_CODE_LENGTH} karakter."
            duplicates = PurchaseOrder.objects.filter(code=code)
            if instance is not None:
                duplicates = duplicates.exclude(pk=instance.pk)
            if duplicates.exists():
                return None, f"Kode PO '{code}' sudah dipakai."
            values["code"] = code

    if "expected_date" in payload:
        expected, error = _resolve_date(payload.get("expected_date"), "expected_date")
        if error:
            return None, error
        values["expected_date"] = expected

    if "notes" in payload:
        notes = str(payload.get("notes") or "").strip()
        if len(notes) > MAX_NOTES_LENGTH:
            return None, f"Field 'notes' maksimal {MAX_NOTES_LENGTH} karakter."
        values["notes"] = notes

    return values, None


# ---------------------------------------------------------------------------
# Validasi & penulisan baris
# ---------------------------------------------------------------------------
def validate_line_payload(data):
    """Validasi satu baris → ``(values, error)`` (product/qty/price_unit/date)."""
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

    qty = _decimal(payload.get("qty"))
    if qty <= 0:
        return None, "Field 'qty' harus angka > 0."
    values["qty"] = qty

    raw_price = payload.get("price_unit")
    if raw_price in (None, ""):
        # Harga beli default dari master (analog `Product.sale_price` di H2.1).
        raw_price = getattr(product, "cost_price", 0) or 0
    price = _decimal(raw_price)
    if price < 0:
        return None, "Field 'price_unit' tidak boleh negatif."
    values["price_unit"] = price

    planned, error = _resolve_date(payload.get("date_planned"), "date_planned")
    if error:
        return None, error
    values["date_planned"] = planned

    return values, None


def _resolve_lines(raw_lines):
    """``(parsed list, error)`` — validasi SEMUA baris (nested, pola H1.5/H2.1)."""
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

        values["taxes"] = taxes
        parsed.append(values)

    return parsed, None


def _write_lines(po: PurchaseOrder, lines: list[dict]) -> None:
    """Tulis baris-baris PO (dipakai create & update/replace)."""
    for values in lines:
        write_values = dict(values)
        taxes = write_values.pop("taxes", [])
        line = PurchaseOrderLine.objects.create(po=po, **write_values)
        if taxes:
            line.tax_ids.set(taxes)


# ---------------------------------------------------------------------------
# Serialisasi baris & detail
# ---------------------------------------------------------------------------
def purchase_order_line_row(line: PurchaseOrderLine) -> dict:
    """Satu baris PO (kontrak API) — termasuk ``subtotal`` (qty × price_unit)."""
    qty = _decimal(line.qty)
    price = _decimal(line.price_unit)

    return {
        "id": line.pk,
        "product_id": line.product_id,
        "product_code": getattr(line.product, "code", None),
        "product_name": getattr(line.product, "name", None),
        "qty": str(qty),
        "price_unit": str(price),
        "subtotal": str(_money(qty * price)),
        "tax_ids": sorted(tax.pk for tax in line.tax_ids.all()),
        "date_planned": _iso(line.date_planned),
        "odoo_id": line.odoo_id,
        "created_at": _iso(line.created_at),
        "updated_at": _iso(line.updated_at),
    }


def purchase_order_row(po: PurchaseOrder) -> dict:
    """Baris list PO (`lines_count` + `amount_total` dari barisnya)."""
    lines = list(po.lines.all())
    total = _money(
        sum((_decimal(line.qty) * _decimal(line.price_unit) for line in lines), Decimal("0"))
    )

    return {
        "id": po.pk,
        "code": po.code,
        "partner_ref": po.partner_ref,
        "vendor_id": po.vendor_id,
        "vendor_name": getattr(po.vendor, "name", None),
        "vendor_code": getattr(po.vendor, "code", None),
        "state": po.state,
        "expected_date": _iso(po.expected_date),
        "notes": po.notes,
        "lines_count": len(lines),
        "amount_total": str(total),
        "odoo_id": po.odoo_id,
        "created_at": _iso(po.created_at),
        "updated_at": _iso(po.updated_at),
    }


def purchase_order_detail_row(po: PurchaseOrder) -> dict:
    """Detail PO = baris list + ``lines[]`` + informasi sync Odoo."""
    record = SyncRecord.objects.filter(
        resource=PO_RESOURCE, resource_id=str(po.pk), stage=PO_STAGE
    ).first()
    row = purchase_order_row(po)
    row.update(
        {
            "lines": [purchase_order_line_row(line) for line in po.lines.all()],
            "odoo_sync_status": None if record is None else record.status,
            "allowed_actions": list(ALLOWED_TRANSITIONS.get(po.state, ())),
        }
    )

    return row


def purchase_order_payload(po: PurchaseOrder) -> dict:
    """Payload ledger/jejak sync (juga dasar payload push ke Odoo)."""
    lines = list(po.lines.all())

    return {
        "code": po.code,
        "partner_ref": po.partner_ref,
        "vendor_id": po.vendor_id,
        "vendor_odoo_id": getattr(po.vendor, "odoo_id", None),
        "state": po.state,
        "expected_date": _iso(po.expected_date),
        "odoo_id": po.odoo_id,
        "lines": [
            {
                "product_id": line.product_id,
                "product_odoo_id": getattr(line.product, "odoo_id", None),
                "product_code": getattr(line.product, "code", None),
                "qty": str(_decimal(line.qty)),
                "price_unit": str(_decimal(line.price_unit)),
                "date_planned": _iso(line.date_planned),
                "tax_ids": sorted(tax.pk for tax in line.tax_ids.all()),
                "tax_odoo_ids": sorted(
                    tax.odoo_id for tax in line.tax_ids.all() if tax.odoo_id
                ),
            }
            for line in lines
        ],
    }


# ---------------------------------------------------------------------------
# Ledger (SyncRecord) + audit
# ---------------------------------------------------------------------------
def _arm_push(po: PurchaseOrder) -> SyncRecord:
    """Siapkan ``SyncRecord`` PURCHASE_ORDER_PUSH PO ini (PENDING + payload terbaru)."""
    payload = purchase_order_payload(po)
    sync = SyncIdempotency()
    record = sync.get_or_create_sync_record(PO_RESOURCE, po.pk, PO_STAGE, payload)

    if (
        dict(record.payload or {}) != payload
        or record.status != SyncStatus.PENDING
        or record.last_error
    ):
        record.payload = payload
        record.status = SyncStatus.PENDING
        record.last_error = ""
        record.save(update_fields=("payload", "status", "last_error", "updated_at"))
        logger.info("purchase_order: SyncRecord %s di-arm ulang (PENDING).", record.pk)

    return record


def _audit(action: str, po: PurchaseOrder, request, metadata: dict | None = None) -> None:
    """Tulis ``AuditLog`` — best-effort (audit tidak boleh menggagalkan transaksi)."""
    try:
        AuditLogger().log(
            user=None,
            action=action,
            resource=PO_RESOURCE,
            resource_id=po.pk,
            request=request,
            payload=purchase_order_payload(po),
            result=AuditLog.Result.OK,
            metadata={"direction": "mes_to_odoo", **(metadata or {})},
        )
    except Exception:  # noqa: BLE001 - audit tidak boleh menggagalkan transaksi PO
        logger.exception("purchase_order: gagal menulis audit (%s, PO %s).", action, po.pk)


def _enqueue_push(po: PurchaseOrder, record: SyncRecord, action: str) -> str | None:
    """Enqueue push/cancel PO ke Odoo; broker mati → ``None`` (record tetap PENDING)."""
    try:
        # Import lazy: `tasks_purchase_order_push` mengimpor modul ini (payload).
        from integrations.erp_sync.tasks_purchase_order_push import push_purchase_order

        async_result = push_purchase_order.apply_async(
            args=[po.pk, record.pk, action],
            headers={"x-request-id": get_request_id() or ""},
        )
        return str(async_result.id)
    except Exception:  # noqa: BLE001 - CRUD PO tidak boleh gagal karena broker
        logger.exception(
            "purchase_order: gagal enqueue push PO %s (SyncRecord %s tetap PENDING).",
            po.pk,
            record.pk,
        )
        return None


def _assert_transition(po: PurchaseOrder, target: str) -> str | None:
    """``None`` kalau transisi ``po.state → target`` diizinkan, else pesan error."""
    if target not in PO_STATES:
        return f"State '{target}' tidak dikenal."

    allowed = ALLOWED_TRANSITIONS.get(po.state, ())
    if target not in allowed:
        return (
            f"PO {po.code} berstatus {po.state}; transisi ke {target} tidak diizinkan "
            f"(yang boleh: {', '.join(allowed) or 'tidak ada'})."
        )

    return None


def _assert_draft(po: PurchaseOrder, verb: str) -> str | None:
    """Guard: hanya DRAFT yang boleh diubah/dihapus (pola H1/H2.1)."""
    if po.state != "DRAFT":
        return f"PO {po.code} berstatus {po.state}; {verb} hanya boleh saat DRAFT."
    return None


# ---------------------------------------------------------------------------
# CRUD (DRAFT-only untuk perubahan) — menulis SyncRecord + AuditLog
# ---------------------------------------------------------------------------
def create_purchase_order(data, request=None) -> PurchaseOrderWriteResult:
    """Buat PO (nomor otomatis ``PO-<TAHUN>-<SEQ>``) + baris nested **atomik**.

    Nomor diambil dari Sprint C (`next_number("PO")`) dan **selalu** disalin ke
    ``partner_ref`` (nomor yang dikirim ke Odoo, karena Odoo memakai nomornya sendiri
    `P00013`). PO lahir ``DRAFT`` = MES-only (belum dikirim ke Odoo).
    """
    payload = data if isinstance(data, dict) else {}
    values, error = validate_po_payload(payload)
    if error:
        return PurchaseOrderWriteResult(error=error)

    lines, error = _resolve_lines(payload.get("lines"))
    if error:
        return PurchaseOrderWriteResult(error=error)

    with transaction.atomic():
        code = values.pop("code", "")
        if not code:
            try:
                code = next_number("PO")
            except SequenceError as exc:
                return PurchaseOrderWriteResult(error=f"Penomoran PO gagal: {exc}")

        po = PurchaseOrder.objects.create(code=code, partner_ref=code, **values)
        _write_lines(po, lines)

    record = _arm_push(po)
    _audit(ACTION_CREATE, po, request, {"code": po.code, "lines": po.lines.count()})

    logger.info(
        "purchase_order: PO %s (%s) dibuat dengan %s baris (ledger=%s, DRAFT MES-only).",
        po.pk,
        po.code,
        po.lines.count(),
        record.pk,
    )

    return PurchaseOrderWriteResult(po=po, sync_record_id=record.pk)


def update_purchase_order(po: PurchaseOrder, data, request=None) -> PurchaseOrderWriteResult:
    """Ubah PO + replace ``lines`` (atomic) — **hanya DRAFT**.

    ``lines`` tidak dikirim = baris tidak disentuh; ``lines`` dikirim = **replace
    penuh** (pola BOMLine H1.5/H2.1); validasi selesai sebelum penulisan.
    """
    error = _assert_draft(po, "perubahan")
    if error:
        return PurchaseOrderWriteResult(po=po, error=error)

    payload = data if isinstance(data, dict) else {}
    values, error = validate_po_payload(payload, instance=po)
    if error:
        return PurchaseOrderWriteResult(po=po, error=error)

    lines: list[dict] | None = None
    if "lines" in payload:
        lines, error = _resolve_lines(payload.get("lines"))
        if error:
            return PurchaseOrderWriteResult(po=po, error=error)

    if not values and lines is None:
        return PurchaseOrderWriteResult(po=po)

    with transaction.atomic():
        for field, value in values.items():
            setattr(po, field, value)
        if values:
            po.save()

        if lines is not None:
            po.lines.all().delete()
            _write_lines(po, lines)

    record = _arm_push(po)
    _audit(
        ACTION_UPDATE,
        po,
        request,
        {"fields": sorted(values), "lines_replaced": lines is not None},
    )

    logger.info("purchase_order: PO %s (%s) diubah (ledger=%s).", po.pk, po.code, record.pk)

    return PurchaseOrderWriteResult(po=po, sync_record_id=record.pk)


def delete_purchase_order(po: PurchaseOrder, request=None) -> PurchaseOrderWriteResult:
    """Hapus PO **hard delete** — hanya **DRAFT** (belum masuk produksi/sync).

    ``PurchaseOrder`` tidak punya kolom ``is_active`` (soft delete H1 tidak berlaku),
    jadi delete = hapus baris + line-nya (CASCADE). Setelah CONFIRMED pakai
    ``/cancel/`` supaya jejak Odoo ikut dibatalkan.
    """
    error = _assert_draft(po, "hapus")
    if error:
        return PurchaseOrderWriteResult(po=po, error=error)

    code = po.code
    pk = po.pk
    _audit(ACTION_DELETE, po, request, {"hard_delete": True})
    SyncRecord.objects.filter(resource=PO_RESOURCE, resource_id=str(pk), stage=PO_STAGE).delete()
    po.delete()

    logger.info("purchase_order: PO %s (%s) dihapus (DRAFT, hard delete).", pk, code)

    return PurchaseOrderWriteResult(deleted=True)


# ---------------------------------------------------------------------------
# Transisi state (§14) — DRAFT → CONFIRMED → DONE, dan → CANCELLED
# ---------------------------------------------------------------------------
def confirm_purchase_order(po: PurchaseOrder, request=None) -> PurchaseOrderWriteResult:
    """``DRAFT → CONFIRMED`` + enqueue push ``purchase.order`` (create **draft**).

    Guard sebelum kirim (supaya Odoo tidak menerima PO cacat):

    * §5 — setiap baris wajib ``price_unit > 0``;
    * §2 — ``vendor.odoo_id`` wajib ada (kalau tidak: 400 + pesan "sinkronkan
      master Partner dulu").

    ``action_confirm`` Odoo **tidak** dipanggil: MES tidak auto-confirm (konfirmasi
    Odoo memicu receipt/picking). Purchasing men-confirm di UI Odoo bila ingin PO
    ikut dihitung `material_readiness` (I3 hanya membaca `purchase`/`done`).
    """
    error = _assert_transition(po, "CONFIRMED")
    if error:
        return PurchaseOrderWriteResult(po=po, error=error)

    empty_price = [
        line.pk for line in po.lines.all() if _decimal(line.price_unit) <= 0
    ]
    if empty_price:
        return PurchaseOrderWriteResult(
            po=po,
            error=(
                "Harga satuan harus > 0 di semua baris sebelum konfirmasi "
                f"(baris bermasalah: {empty_price})."
            ),
        )

    if not getattr(po.vendor, "odoo_id", None):
        return PurchaseOrderWriteResult(
            po=po,
            error=(
                f"Vendor {getattr(po.vendor, 'code', '')} belum punya `odoo_id` — "
                "sinkronkan master Partner dulu sebelum mengonfirmasi PO."
            ),
        )

    po.state = "CONFIRMED"
    po.save(update_fields=("state", "updated_at"))

    record = _arm_push(po)
    task_id = _enqueue_push(po, record, "create")
    _audit(ACTION_CONFIRM, po, request, {"queued": task_id is not None})

    logger.info(
        "purchase_order: PO %s (%s) CONFIRMED (push %s).",
        po.pk,
        po.code,
        task_id or "tertunda (broker mati)",
    )

    return PurchaseOrderWriteResult(po=po, sync_record_id=record.pk, task_id=task_id)


def done_purchase_order(po: PurchaseOrder, request=None) -> PurchaseOrderWriteResult:
    """``CONFIRMED → DONE`` — **manual** (MES-only).

    Odoo `purchase.order` punya state ``done`` (*Locked*), tetapi state itu dipicu
    receipt/lock di Odoo ⇒ **tidak** kita kirim (brief H2.2 poin 12). Penerimaan
    otomatis = sprint lain.
    """
    error = _assert_transition(po, "DONE")
    if error:
        return PurchaseOrderWriteResult(po=po, error=error)

    po.state = "DONE"
    po.save(update_fields=("state", "updated_at"))

    record = _arm_push(po)
    _audit(ACTION_DONE, po, request, {"lines": po.lines.count()})

    logger.info("purchase_order: PO %s (%s) DONE (MES-only, tanpa push).", po.pk, po.code)

    return PurchaseOrderWriteResult(po=po, sync_record_id=record.pk)


def cancel_purchase_order(
    po: PurchaseOrder, request=None, reason: str = ""
) -> PurchaseOrderWriteResult:
    """``DRAFT|CONFIRMED → CANCELLED`` + enqueue ``action_cancel`` Odoo bila sudah sync.

    ``reason`` opsional (disimpan di metadata audit). PO DRAFT belum pernah dikirim ke
    Odoo ⇒ tidak ada tugas cancel.
    """
    error = _assert_transition(po, "CANCELLED")
    if error:
        return PurchaseOrderWriteResult(po=po, error=error)

    reason = str(reason or "").strip()[:MAX_REASON_LENGTH]
    had_odoo_id = po.odoo_id is not None

    po.state = "CANCELLED"
    po.save(update_fields=("state", "updated_at"))

    record = _arm_push(po)
    task_id = _enqueue_push(po, record, "cancel") if had_odoo_id else None
    _audit(
        ACTION_CANCEL,
        po,
        request,
        {"reason": reason, "odoo_id": po.odoo_id, "queued": task_id is not None},
    )

    logger.info(
        "purchase_order: PO %s (%s) CANCELLED (push cancel=%s).",
        po.pk,
        po.code,
        "ya" if task_id else "tidak",
    )

    return PurchaseOrderWriteResult(po=po, sync_record_id=record.pk, task_id=task_id)


# ---------------------------------------------------------------------------
# Baca state Odoo ON-DEMAND (read-only; TIDAK menulis field MES)
# ---------------------------------------------------------------------------
def fetch_odoo_state(po: PurchaseOrder) -> dict:
    """Baca ``purchase.order`` Odoo untuk PO ini → ``{odoo_id, odoo_state, odoo_name}``.

    Dipakai endpoint ``POST /purchase-orders/<id>/sync-odoo-state/`` supaya purchasing
    bisa melihat apakah PO sudah di-confirm di Odoo (syarat I3) **tanpa** menyimpan
    state Odoo di MES (tidak ada field mati). Read-only: tidak memicu push/sync.

    Raises:
        PurchaseOrderError: PO belum punya ``odoo_id``, atau Odoo tidak menemukan
        record-nya (mis. PO dihapus manual di Odoo).
    """
    if not po.odoo_id:
        raise PurchaseOrderError(
            f"PO {po.code} belum punya `odoo_id` (belum pernah dikirim ke Odoo)."
        )

    # Import lazy: `get_odoo_rpc_client` membaca settings Odoo (bisa kosong di dev).
    from integrations.erp_sync.client import get_odoo_rpc_client

    client = get_odoo_rpc_client()
    try:
        rows = client.transport.search_read(
            "purchase.order",
            [["id", "=", int(po.odoo_id)]],
            ["name", "state"],
            limit=1,
        )
    finally:
        client.close()

    if not rows:
        raise PurchaseOrderError(
            f"PO {po.code} (odoo_id={po.odoo_id}) tidak ditemukan di Odoo."
        )

    row = rows[0]
    return {
        "odoo_id": po.odoo_id,
        "odoo_state": row.get("state"),
        "odoo_name": row.get("name"),
    }


