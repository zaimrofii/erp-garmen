"""Service CRUD master Product (H1.1) — MES = source of truth master.

Konsep (``docs/REPLACE-NOTICE.md``): klien hanya membuka MES; Odoo = back-office
pasif. Jadi CRUD master **selesai di MES dulu**, baru di-push asinkron ke Odoo.

Kenapa service terpisah dari view: tiga kewajiban menulis harus terjadi **bersama**
setiap POST/PUT/DELETE dan harus bisa diuji tanpa HTTP —

  1. **data** (``Product``) — create/update/soft-delete (``is_active=False``,
     tidak pernah ``delete()`` supaya jejak & relasi tetap utuh);
  2. **idempotensi** — ``SyncRecord(resource="master.product", stage="MASTER_PUSH")``
     di-*arm* ulang (``PENDING`` + payload terbaru) karena unique constraint
     ``(resource, resource_id, stage)`` hanya mengizinkan **satu** baris per produk;
     task ``erp_sync.push_master_product`` yang menandai ``SENT``/``FAILED``;
  3. **audit** — ``AuditLog`` action ``master.create`` / ``master.update`` /
     ``master.delete`` lewat :class:`core.audit.services.AuditLogger`.

Push ke Odoo **tidak** dilakukan di sini: ``push_master_product.apply_async``
(hasilnya ``task_id`` dikembalikan ke pemanggil). Kalau broker sedang mati,
CRUD tetap sukses dan ``SyncRecord`` tertinggal ``PENDING`` (terlihat di
``/api/v1/sync/records/``) — lantai produksi tidak boleh gagal hanya karena ERP.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.utils import timezone

from config.middleware import get_request_id
from core.audit.models import AuditLog
from core.audit.services import AuditLogger
from integrations.erp_sync.idempotency import SyncIdempotency
from integrations.erp_sync.models import SyncRecord, SyncResource, SyncStage, SyncStatus
from integrations.erp_sync.tasks_master_push import product_payload, push_master_product

from .models import Product, UoM

logger = logging.getLogger(__name__)

__all__ = (
    "ACTION_CREATE",
    "ACTION_DELETE",
    "ACTION_UPDATE",
    "ACTION_UPDATE_PRICE",
    "MASTER_WRITE_ROLE_CODES",
    "ProductWriteResult",
    "create_product",
    "deactivate_product",
    "parse_bool",
    "price_history",
    "product_row",
    "update_price",
    "update_product",
    "validate_product_payload",
)

#: Kunci sync (``SyncResource``/``SyncStage``) — jangan diganti string literal di view.
RESOURCE = SyncResource.MASTER_PRODUCT.value
STAGE = SyncStage.MASTER_PUSH.value

#: Action audit per operasi (kontrak H1.1) + H3.5 (khusus harga).
ACTION_CREATE = "master.create"
ACTION_UPDATE = "master.update"
ACTION_DELETE = "master.delete"
ACTION_UPDATE_PRICE = "master.update_price"

#: Kode role backend yang boleh menulis master (CHANGES-DETAIL §7: role purchasing).
#: Dicek **case-insensitive**; ``is_superuser`` selalu boleh (lihat view).
MASTER_WRITE_ROLE_CODES = ("ADMIN", "OWNER", "PURCHASING")

#: Batas panjang teks (selaras kolom model — beda dari DB = 500, bukan 400).
MAX_CODE_LENGTH = 64
MAX_NAME_LENGTH = 255
MAX_CATEGORY_LENGTH = 64

#: Batas nilai uang (selaras `DecimalField(max_digits=16, decimal_places=2)`).
MAX_PRICE = Decimal("99999999999999.99")
PRICE_QUANT = Decimal("0.01")

#: Nilai bool yang diterima di JSON (string dari form HTML ikut diterima).
BOOL_TRUE = ("true", "1", "yes", "y", "on")
BOOL_FALSE = ("false", "0", "no", "n", "off")



def _iso(value) -> str | None:
    """ISO-8601 atau ``None`` (datetime kosong)."""
    return value.isoformat() if value else None


def product_row(product: Product) -> dict:
    """Baris produk untuk API (list & detail) — seluruhnya JSON-safe.

    ``odoo_id`` **wajib** ada di response: frontend memakainya untuk debug sync
    (``null`` = belum pernah terkirim ke Odoo). ``active`` adalah nama publik
    dari ``Product.is_active`` (kontrak H1.1).
    """
    uom = product.uom if product.uom_id else None

    return {
        "id": product.pk,
        "code": product.code,
        "name": product.name,
        "category": product.category,
        "uom_id": product.uom_id,
        "uom_code": uom.code if uom is not None else None,
        "sale_price": float(product.sale_price or 0),
        "cost_price": float(product.cost_price or 0),
        "price_updated_at": _iso(product.price_updated_at),
        "weight": product.weight,
        "image_url": product.image_url,
        "active": bool(product.is_active),
        "odoo_id": product.odoo_id,
        "created_at": _iso(product.created_at),
        "updated_at": _iso(product.updated_at),
    }


def parse_bool(value) -> bool | None:
    """``True``/``False`` dari bool atau string ``true/false/1/0/yes/no``; lain ``None``."""
    if isinstance(value, bool):
        return value

    text = str(value or "").strip().lower()
    if text in BOOL_TRUE:
        return True
    if text in BOOL_FALSE:
        return False

    return None


def _parse_decimal(value, label: str):
    """``(Decimal, error)`` untuk nilai uang; kosong -> ``0``."""
    if value in (None, ""):
        return Decimal("0"), None

    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None, f"Field '{label}' harus berupa angka."

    if not amount.is_finite():
        return None, f"Field '{label}' harus berupa angka."
    if amount < 0:
        return None, f"Field '{label}' tidak boleh negatif."
    if amount > MAX_PRICE:
        return None, f"Field '{label}' maksimal {MAX_PRICE}."

    return amount.quantize(PRICE_QUANT), None


def _parse_weight(value):
    """``(float|None, error)`` untuk berat; kosong -> ``None``."""
    if value in (None, ""):
        return None, None
    if isinstance(value, bool):
        return None, "Field 'weight' harus berupa angka."

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None, "Field 'weight' harus berupa angka."

    if number != number or number in (float("inf"), float("-inf")):
        return None, "Field 'weight' harus berupa angka."
    if number < 0:
        return None, "Field 'weight' tidak boleh negatif."

    return number, None


def validate_product_payload(data, instance: Product | None = None):
    """Validasi body POST/PUT -> ``(values, error)``.

    Saat create (``instance=None``) ``code`` & ``name`` **wajib**; saat update
    keduanya opsional (hanya field yang dikirim yang diubah — pola
    ``SettingsUserDetailView.put``). Nilai yang dikembalikan sudah siap
    ``setattr``/``create`` (memakai nama kolom model, mis. ``is_active``).
    """
    payload = data if isinstance(data, dict) else {}
    values: dict = {}

    if instance is None or "code" in payload:
        code = str(payload.get("code") or "").strip()
        if not code:
            return None, "Field 'code' wajib diisi."
        if len(code) > MAX_CODE_LENGTH:
            return None, f"Field 'code' maksimal {MAX_CODE_LENGTH} karakter."

        duplicates = Product.objects.filter(code__iexact=code)
        if instance is not None:
            duplicates = duplicates.exclude(pk=instance.pk)
        if duplicates.exists():
            return None, f"Kode produk '{code}' sudah dipakai produk lain."
        values["code"] = code

    if instance is None or "name" in payload:
        name = str(payload.get("name") or "").strip()
        if not name:
            return None, "Field 'name' wajib diisi."
        if len(name) > MAX_NAME_LENGTH:
            return None, f"Field 'name' maksimal {MAX_NAME_LENGTH} karakter."
        values["name"] = name

    if "category" in payload:
        category = str(payload.get("category") or "").strip()
        if len(category) > MAX_CATEGORY_LENGTH:
            return None, f"Field 'category' maksimal {MAX_CATEGORY_LENGTH} karakter."
        values["category"] = category

    if "uom_id" in payload:
        raw_uom = payload.get("uom_id")
        if raw_uom in (None, ""):
            values["uom_id"] = None
        else:
            try:
                uom_id = int(raw_uom)
            except (TypeError, ValueError):
                return None, "Field 'uom_id' harus berupa id UoM (angka)."
            if not UoM.objects.filter(pk=uom_id).exists():
                return None, f"UoM {uom_id} tidak ditemukan."
            values["uom_id"] = uom_id

    for field in ("sale_price", "cost_price"):
        if field in payload:
            amount, error = _parse_decimal(payload.get(field), field)
            if error:
                return None, error
            values[field] = amount

    if "weight" in payload:
        number, error = _parse_weight(payload.get("weight"))
        if error:
            return None, error
        values["weight"] = number

    if "image_url" in payload:
        image_url = str(payload.get("image_url") or "").strip()
        if image_url and not image_url.startswith(("http://", "https://")):
            return None, "Field 'image_url' harus URL http(s) yang valid."
        values["image_url"] = image_url

    if "active" in payload:
        active = parse_bool(payload.get("active"))
        if active is None:
            return None, "Field 'active' harus true|false."
        values["is_active"] = active

    return values, None


# ---------------------------------------------------------------------------
# Tulis (create / update / soft delete) — data + idempotensi + audit
# ---------------------------------------------------------------------------
@dataclass
class ProductWriteResult:
    """Hasil satu operasi tulis master product (dipakai view)."""

    product: Product | None = None
    error: str | None = None
    sync_record_id: int | None = None
    task_id: str | None = None

    @property
    def queued(self) -> bool:
        """True kalau task push master berhasil di-enqueue (broker hidup)."""
        return self.task_id is not None


def _arm_push(product: Product, payload: dict) -> SyncRecord:
    """Siapkan ``SyncRecord`` MASTER_PUSH produk ini (PENDING + payload terbaru).

    ``unique(resource, resource_id, stage)`` hanya mengizinkan satu baris per
    produk, jadi perubahan berikutnya meng-*update* baris yang sama (bukan
    menumpuk baris baru) — riwayat pengiriman tetap satu tempat.
    """
    sync = SyncIdempotency()
    record = sync.get_or_create_sync_record(RESOURCE, product.pk, STAGE, payload)

    if (
        dict(record.payload or {}) != payload
        or record.status != SyncStatus.PENDING
        or record.last_error
    ):
        record.payload = payload
        record.status = SyncStatus.PENDING
        record.last_error = ""
        record.save(update_fields=("payload", "status", "last_error", "updated_at"))
        logger.info("master.product: SyncRecord %s di-arm ulang (PENDING).", record.pk)

    return record


def _audit(action: str, product: Product, payload: dict, request, metadata: dict | None = None) -> None:
    """Tulis ``AuditLog`` — best-effort (pola ``integrations/erp_sync/audit.py``)."""
    try:
        AuditLogger().log(
            user=None,
            action=action,
            resource=RESOURCE,
            resource_id=product.pk,
            request=request,
            payload=payload,
            result=AuditLog.Result.OK,
            metadata=metadata or {},
        )
    except Exception:  # noqa: BLE001 - audit tidak boleh menggagalkan CRUD master
        logger.exception(
            "master.product: gagal menulis audit (%s, produk %s).", action, product.pk
        )


def _enqueue(product: Product, record: SyncRecord) -> str | None:
    """Enqueue task push master; broker mati -> ``None`` (record tetap PENDING)."""
    try:
        async_result = push_master_product.apply_async(
            args=[product.pk, record.pk],
            headers={"x-request-id": get_request_id() or ""},
        )
        return str(async_result.id)
    except Exception:  # noqa: BLE001 - CRUD master tidak boleh gagal karena broker
        logger.exception(
            "master.product: gagal enqueue push produk %s (SyncRecord %s tetap PENDING).",
            product.pk,
            record.pk,
        )
        return None


def create_product(data, request=None) -> ProductWriteResult:
    """Buat produk baru + ``SyncRecord`` + ``AuditLog`` + enqueue push ke Odoo."""
    values, error = validate_product_payload(data)
    if error:
        return ProductWriteResult(error=error)

    product = Product.objects.create(**values)
    payload = product_payload(product)
    record = _arm_push(product, payload)
    _audit(ACTION_CREATE, product, payload, request, {"odoo_id": product.odoo_id})
    task_id = _enqueue(product, record)

    logger.info(
        "master.product: produk %s (%s) dibuat (sync=%s).", product.pk, product.code, record.pk
    )
    return ProductWriteResult(product=product, sync_record_id=record.pk, task_id=task_id)


def update_product(product: Product, data, request=None) -> ProductWriteResult:
    """Ubah produk (hanya field yang dikirim) + ``SyncRecord`` + ``AuditLog`` + enqueue."""
    values, error = validate_product_payload(data, instance=product)
    if error:
        return ProductWriteResult(product=product, error=error)

    if not values:
        # Tidak ada perubahan -> tidak ada audit/push: AuditLog mencatat perubahan nyata.
        return ProductWriteResult(product=product)

    # H3.5 — deteksi perubahan harga SEBELUM setattr supaya bisa dicatat
    # `price_updated_at` + audit khusus `master.update_price` (nilai lama vs baru).
    prices_before = _price_snapshot(product)
    price_changed = _price_changes(product, values)

    for field, value in values.items():
        setattr(product, field, value)
    if price_changed:
        product.price_updated_at = timezone.now()
    product.save()

    payload = product_payload(product)
    record = _arm_push(product, payload)
    _audit(
        ACTION_UPDATE,
        product,
        payload,
        request,
        {"odoo_id": product.odoo_id, "fields": sorted(values)},
    )
    if price_changed:
        _audit(
            ACTION_UPDATE_PRICE,
            product,
            payload,
            request,
            price_change_metadata(prices_before, product, price_changed, source="product_update"),
        )
    task_id = _enqueue(product, record)

    logger.info(
        "master.product: produk %s (%s) diubah (sync=%s).", product.pk, product.code, record.pk
    )
    return ProductWriteResult(product=product, sync_record_id=record.pk, task_id=task_id)


def deactivate_product(product: Product, request=None) -> ProductWriteResult:
    """Soft delete (``is_active=False``) + ``SyncRecord`` + ``AuditLog`` + enqueue push.

    Baris **tidak** dihapus dari DB (tidak ada ``delete()``) supaya relasi
    (order line, BOM) dan jejak audit tetap utuh; Odoo menerima ``active=False``
    lewat push yang sama (stage ``MASTER_PUSH``).
    """
    if product.is_active:
        product.is_active = False
        product.save(update_fields=("is_active", "updated_at"))

    payload = product_payload(product)
    record = _arm_push(product, payload)
    _audit(
        ACTION_DELETE,
        product,
        payload,
        request,
        {"soft_delete": True, "odoo_id": product.odoo_id},
    )
    task_id = _enqueue(product, record)

    logger.info(
        "master.product: produk %s (%s) dinonaktifkan (sync=%s).",
        product.pk,
        product.code,
        record.pk,
    )
    return ProductWriteResult(product=product, sync_record_id=record.pk, task_id=task_id)


# ---------------------------------------------------------------------------
# H3.5 — harga produk: update khusus + riwayat (audit trail)
# ---------------------------------------------------------------------------
#: Field harga yang dikelola (jangan ganti literal di view/test).
PRICE_FIELDS: tuple[str, ...] = ("sale_price", "cost_price")


def _price_snapshot(product: Product) -> dict:
    """Snapshot harga produk (string 2 desimal) untuk metadata audit."""
    return {field: str(getattr(product, field) or 0) for field in PRICE_FIELDS}


def _price_changes(product: Product, values: dict) -> dict:
    """``{field: nilai_baru}`` untuk harga yang BENAR-BENAR berubah saja."""
    return {
        field: values[field]
        for field in PRICE_FIELDS
        if field in values and values[field] != (getattr(product, field) or Decimal("0"))
    }


def price_change_metadata(before: dict, product: Product, changed: dict, *, source: str) -> dict:
    """Metadata audit perubahan harga: nilai lama → baru + sumber perubahan."""
    after = _price_snapshot(product)

    return {
        "source": source,
        "fields": sorted(changed),
        "before": {field: before[field] for field in changed},
        "after": {field: after[field] for field in changed},
    }


def validate_price_payload(data):
    """Validasi body update harga → ``(values, error)``.

    Minimal satu dari ``sale_price``/``cost_price`` harus dikirim. Nilai **0
    diizinkan** (produk gratis/diskon penuh) tetapi **negatif DITOLAK** (§5 hanya
    mensyaratkan ``price_unit > 0`` pada baris order saat CONFIRMED, bukan pada master).
    """
    payload = data if isinstance(data, dict) else {}
    values: dict = {}

    for field in PRICE_FIELDS:
        if field not in payload:
            continue
        amount, error = _parse_decimal(payload.get(field), field)
        if error:
            return None, error
        values[field] = amount

    if not values:
        return None, "Kirim minimal satu dari 'sale_price' atau 'cost_price'."

    return values, None


def update_price(product: Product, data, request=None) -> ProductWriteResult:
    """Ubah **harga saja** (``sale_price``/``cost_price``) + audit + push ke Odoo.

    Perbedaan dengan :func:`update_product`: payload hanya boleh berisi harga, jejaknya
    memakai action audit khusus **``master.update_price``** (metadata nilai lama vs baru),
    dan ``price_updated_at`` di-set. ``SyncRecord`` MASTER_PUSH + task push memakai jalur
    yang SAMA dengan H1.1 (payload produk utuh, termasuk ``list_price``/``standard_price``).
    """
    values, error = validate_price_payload(data)
    if error:
        return ProductWriteResult(product=product, error=error)

    before = _price_snapshot(product)
    changed = _price_changes(product, values)
    if not changed:
        # Nilai sama -> tidak ada perubahan nyata: tidak ada audit/push (pola H1.1).
        return ProductWriteResult(product=product)

    for field, amount in changed.items():
        setattr(product, field, amount)
    product.price_updated_at = timezone.now()
    product.save(update_fields=(*sorted(changed), "price_updated_at", "updated_at"))

    payload = product_payload(product)
    record = _arm_push(product, payload)
    _audit(
        ACTION_UPDATE_PRICE,
        product,
        payload,
        request,
        price_change_metadata(before, product, changed, source="price_endpoint"),
    )
    task_id = _enqueue(product, record)

    logger.info(
        "master.product: harga produk %s (%s) diubah %s (sync=%s).",
        product.pk,
        product.code,
        sorted(changed),
        record.pk,
    )
    return ProductWriteResult(product=product, sync_record_id=record.pk, task_id=task_id)


def price_history(product: Product, *, limit: int = 20, offset: int = 0) -> dict:
    """Riwayat perubahan harga produk dari ``AuditLog`` (action ``master.update_price``).

    TIDAK ada tabel baru: riwayat dibaca dari ``AuditLog`` yang sudah append-only
    (pola H1.1 ``master.update`` + H2.x). Baris memuat nilai **lama** vs **baru**
    (dari ``metadata``) supaya UI bisa menampilkan diff tanpa join ke mana pun.
    """
    queryset = AuditLog.objects.filter(
        resource=RESOURCE,
        resource_id=str(product.pk),
        action=ACTION_UPDATE_PRICE,
    ).select_related("user")
    total = queryset.count()
    rows = []

    for log in queryset.order_by("-timestamp", "-id")[offset : offset + limit]:
        metadata = log.metadata if isinstance(log.metadata, dict) else {}
        rows.append(
            {
                "id": log.pk,
                "action": log.action,
                "source": metadata.get("source") or "",
                "fields": list(metadata.get("fields") or []),
                "before": dict(metadata.get("before") or {}),
                "after": dict(metadata.get("after") or {}),
                "user": getattr(log.user, "username", None),
                "timestamp": log.timestamp.isoformat() if log.timestamp else None,
                "request_id": log.request_id or "",
            }
        )

    return {"rows": rows, "total_count": total}
