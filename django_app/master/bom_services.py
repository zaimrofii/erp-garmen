"""Service CRUD master BOM (H1.5) — MES = source of truth master.

Pola **sama** dengan ``master/services.py`` (H1.1) dan ``master/location_services.py``
(H1.4): satu operasi tulis = data + ``SyncRecord`` (``master.bom`` / ``MASTER_PUSH``,
kunci idempotensi ``odoo_id``) + ``AuditLog`` (``master.create|update|delete``) +
enqueue task Celery ``erp_sync.push_master_bom``. Odoo **tidak** dipanggil di sini.

Kekhususan H1.5 (header + baris):

  * **BOMLine INLINE** — create/update BOM menerima ``lines[]`` sekaligus dan
    menulisnya di dalam ``transaction.atomic()`` (1 baris invalid = seluruh BOM
    batal, tidak ada BOM setengah jadi);
  * **baris lama tidak di-hard-delete** — baris yang tidak lagi dikirim diubah
    ``is_active=False`` (soft), supaya ``odoo_id`` tiap baris tetap ada dan push
    berikutnya me-*update* baris Odoo yang sama (bukan membuat duplikat);
  * **self-reference** (komponen = produk BOM itu sendiri) → 400; **siklus**
    (produk jadi bahan dirinya sendiri lewat BOM lain) → 400, ditelusuri rekursif
    dengan batas ``MAX_BOM_DEPTH``;
  * ``output_qty`` & ``product_qty`` (qty baris) divalidasi **di service**
    (> 0) — bukan ``CheckConstraint`` DB, karena pull Odoo (``_bom_line_defaults``)
    boleh menulis 0 tanpa menggagalkan sync;
  * DELETE = soft delete **tanpa** guard dependensi: tidak ada FK lain yang
    menunjuk BOM (``garment.WorkOrder`` hanya menunjuk ``OrderLine``) dan semua
    konsumen (``material_readiness``) sudah memfilter ``is_active=True``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.db import transaction

from config.middleware import get_request_id
from core.audit.models import AuditLog
from core.audit.services import AuditLogger
from integrations.erp_sync.idempotency import SyncIdempotency
from integrations.erp_sync.models import SyncRecord, SyncResource, SyncStage, SyncStatus
from integrations.erp_sync.tasks_master_push import bom_payload, push_master_bom

from .models import BOM, BOMLine, Product, UoM
from .services import ACTION_CREATE, ACTION_DELETE, ACTION_UPDATE, parse_bool

logger = logging.getLogger(__name__)

__all__ = (
    "BomWriteResult",
    "bom_detail_row",
    "bom_row",
    "create_bom",
    "deactivate_bom",
    "line_row",
    "update_bom",
    "validate_bom_payload",
    "validate_line_payload",
)

#: Kunci sync BOM (jangan diganti string literal di view).
BOM_RESOURCE = SyncResource.MASTER_BOM.value
STAGE = SyncStage.MASTER_PUSH.value

#: Batas panjang teks (selaras kolom model — beda dari DB = 400, bukan 500).
MAX_CODE_LENGTH = 64
MAX_NAME_LENGTH = 255

#: Batas jumlah baris komponen per BOM (jaring pengaman payload raksasa).
MAX_LINES = 200

#: Kedalaman maksimum penelusuran siklus BOM (keputusan H1.5).
MAX_BOM_DEPTH = 10

#: Batas nilai qty (selaras `DecimalField(max_digits=16, decimal_places=3)`).
MAX_QTY = Decimal("9999999999999.999")


def _iso(value) -> str | None:
    """ISO-8601 atau ``None`` (datetime kosong)."""
    return value.isoformat() if value else None


def line_row(line: BOMLine) -> dict:
    """Baris komponen BOM untuk API — JSON-safe.

    Kuantitas diekspor sebagai ``qty`` (nama di dokumen H1.5) walau kolomnya
    ``product_qty`` (dipakai ``material_readiness`` & pull Odoo — tidak di-rename).
    """
    product = line.product if line.product_id else None
    uom = line.uom if line.uom_id else None

    return {
        "id": line.pk,
        "product_id": line.product_id,
        "product_code": product.code if product is not None else None,
        "product_name": product.name if product is not None else None,
        "qty": float(line.product_qty or 0),
        "uom_id": line.uom_id,
        "uom_code": uom.code if uom is not None else None,
        "sequence": line.sequence,
        "notes": line.notes,
        "active": bool(line.is_active),
        "odoo_id": line.odoo_id,
    }


def bom_row(bom: BOM, lines_count: int = 0) -> dict:
    """Baris BOM (header) untuk API — seluruhnya JSON-safe.

    ``product_id``/``uom_id`` = **pk** (atau ``null``; BOM hasil pull bisa belum
    punya produk) + nama produk supaya UI tidak perlu request tambahan.
    ``lines_count`` diisi pemanggil (list memakai ``annotate(Count)``, detail
    memakai jumlah baris aktif).
    """
    product = bom.product if bom.product_id else None
    uom = bom.uom if bom.uom_id else None

    return {
        "id": bom.pk,
        "code": bom.code,
        "name": bom.name,
        "product_id": bom.product_id,
        "product_code": product.code if product is not None else None,
        "product_name": product.name if product is not None else None,
        "output_qty": float(bom.output_qty or 0),
        "uom_id": bom.uom_id,
        "uom_code": uom.code if uom is not None else None,
        "notes": bom.notes,
        "active": bool(bom.is_active),
        "odoo_id": bom.odoo_id,
        "lines_count": lines_count,
        "created_at": _iso(bom.created_at),
        "updated_at": _iso(bom.updated_at),
    }


def bom_detail_row(bom: BOM) -> dict:
    """Baris BOM lengkap dengan ``lines[]`` (hanya baris **aktif**, urut ``sequence``)."""
    lines = list(bom.lines.filter(is_active=True).order_by("sequence", "id"))
    row = bom_row(bom, lines_count=len(lines))
    row["lines"] = [line_row(line) for line in lines]

    return row


# ---------------------------------------------------------------------------
# Validasi (PURE — dipakai view & test tanpa HTTP)
# ---------------------------------------------------------------------------
def _parse_qty(value, label: str, *, required: bool):
    """``(Decimal|None, error)`` — angka > 0 (dipakai ``output_qty`` & ``qty`` baris)."""
    if value in (None, ""):
        return (None, f"Field '{label}' wajib diisi.") if required else (None, None)

    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError):
        return None, f"Field '{label}' harus berupa angka."

    if not parsed.is_finite():
        return None, f"Field '{label}' harus berupa angka."
    if parsed <= 0:
        return None, f"Field '{label}' harus lebih besar dari 0."
    if parsed > MAX_QTY:
        return None, f"Field '{label}' terlalu besar (maks {MAX_QTY})."

    return parsed, None


def _fk_or_error(value, model, label: str):
    """``(instance|None, error)`` untuk FK opsional; kosong → ``None``."""
    if value in (None, ""):
        return None, None

    try:
        pk = int(value)
    except (TypeError, ValueError):
        return None, f"Field '{label}' harus berupa id (angka)."

    instance = model.objects.filter(pk=pk).first()
    if instance is None:
        return None, f"{label} {pk} tidak ditemukan."

    return instance, None


def _optional_pk(value, label: str):
    """``(int|None, error)`` untuk id opsional (dipakai ``id``/``odoo_id`` baris)."""
    if value in (None, ""):
        return None, None

    try:
        return int(value), None
    except (TypeError, ValueError):
        return None, f"Field '{label}' harus berupa id (angka)."


def _text(value, label: str, max_length: int):
    """``(str, error)`` untuk teks opsional dengan batas panjang."""
    text = "" if value is None else str(value).strip()
    if len(text) > max_length:
        return "", f"Field '{label}' maksimal {max_length} karakter."

    return text, None


def generate_bom_code(product: Product | None) -> str:
    """Kode BOM unik: ``BOM-<kode produk>`` + suffix ``-2``, ``-3``, … bila terpakai.

    ``BOM.code`` unik **dan** wajib, sedangkan operator tidak selalu tahu kode
    Odoo/``reference``; jadi kode dibangkitkan deterministik dari produk lalu
    dicari kandidat bebas berikutnya (aman dari ``IntegrityError``).
    """
    base = f"BOM-{(product.code if product is not None else '')}".rstrip("-") or "BOM"

    candidate = base[:MAX_CODE_LENGTH]
    suffix = 2
    while BOM.objects.filter(code__iexact=candidate).exists():
        tail = f"-{suffix}"
        candidate = f"{base[: MAX_CODE_LENGTH - len(tail)]}{tail}"
        suffix += 1

    return candidate


def validate_line_payload(payload, index: int):
    """Validasi **satu** baris ``lines[]`` → ``(values, error)``.

    ``values`` memakai nama atribut model: ``{id, odoo_id, product, quantity,
    uom, sequence, notes}`` (``quantity`` = nilai untuk kolom ``product_qty``).
    ``qty`` diterima juga sebagai ``product_qty`` supaya bentuk hasil GET detail
    (``qty``) bisa langsung dikirim balik saat PUT.
    """
    if not isinstance(payload, dict):
        return None, f"Baris #{index + 1} harus berupa objek."
    data = payload

    product, error = _fk_or_error(data.get("product_id"), Product, f"Produk baris #{index + 1}")
    if error:
        return None, error
    if product is None:
        return None, f"Field 'product_id' baris #{index + 1} wajib diisi."

    quantity, error = _parse_qty(
        data.get("qty", data.get("product_qty")), f"qty baris #{index + 1}", required=True
    )
    if error:
        return None, error

    uom, error = _fk_or_error(data.get("uom_id"), UoM, f"Satuan baris #{index + 1}")
    if error:
        return None, error

    sequence = data.get("sequence")
    if sequence in (None, ""):
        sequence = (index + 1) * 10
    else:
        try:
            sequence = int(sequence)
        except (TypeError, ValueError):
            return None, f"Field 'sequence' baris #{index + 1} harus berupa angka."
        if sequence < 0:
            return None, f"Field 'sequence' baris #{index + 1} tidak boleh negatif."

    notes, error = _text(data.get("notes"), f"notes baris #{index + 1}", 2000)
    if error:
        return None, error

    line_id, error = _optional_pk(data.get("id"), f"id baris #{index + 1}")
    if error:
        return None, error

    odoo_id, error = _optional_pk(data.get("odoo_id"), f"odoo_id baris #{index + 1}")
    if error:
        return None, error

    return (
        {
            "id": line_id,
            "odoo_id": odoo_id,
            "product": product,
            "quantity": float(quantity),
            "uom": uom,
            "sequence": sequence,
            "notes": notes,
        },
        None,
    )


def _cycle_error(product: Product | None, components, exclude_bom: BOM | None = None):
    """Pesan error kalau ``product`` muncul lagi sebagai komponen turunan (siklus).

    Penelusuran turun lewat BOM aktif milik tiap komponen; ``seen`` mencegah loop
    dan kedalaman dibatasi ``MAX_BOM_DEPTH`` (rantai lebih dalam tidak ditelusuri).
    """
    if product is None:
        return None

    target = product.pk
    stack = [(component, 1) for component in components if component is not None]
    seen: set[int] = set()

    while stack:
        node, depth = stack.pop()
        if node.pk is None or node.pk in seen:
            continue
        seen.add(node.pk)

        if node.pk == target:
            return (
                f"Siklus BOM terdeteksi: produk '{product.code}' juga muncul sebagai "
                "komponen turunannya. Perbaiki susunan komponen dulu."
            )

        if depth >= MAX_BOM_DEPTH:
            continue

        child_boms = BOM.objects.filter(is_active=True, product=node)
        if exclude_bom is not None and exclude_bom.pk is not None:
            child_boms = child_boms.exclude(pk=exclude_bom.pk)

        for child in child_boms:
            for child_line in child.lines.filter(is_active=True):
                if child_line.product_id:
                    stack.append((child_line.product, depth + 1))

    return None


def validate_bom_payload(payload, instance: BOM | None = None):
    """Validasi body POST/PUT BOM → ``(values, lines, error)``.

    Saat create (``instance=None``) ``product_id`` wajib & ``code`` dibangkitkan
    otomatis bila kosong; saat update keduanya opsional (hanya field yang dikirim
    yang diubah). ``lines`` opsional — **kalau ada**, isinya menggantikan seluruh
    baris aktif (baris lama yang hilang di-soft-delete, lihat ``_apply_lines``).

    Guard hierarki: komponen tidak boleh produk BOM itu sendiri (**400**) dan
    susunan hasil edit tidak boleh membentuk **siklus** (**400**).
    """
    data = payload if isinstance(payload, dict) else {}
    values: dict = {}
    lines: list = []

    product = instance.product if instance is not None else None
    if instance is None or "product_id" in data:
        product, error = _fk_or_error(data.get("product_id"), Product, "Produk (product_id)")
        if error:
            return None, None, error
        if product is None:
            return None, None, "Field 'product_id' wajib diisi."
        values["product"] = product

    if instance is None or "code" in data:
        code, error = _text(data.get("code"), "code", MAX_CODE_LENGTH)
        if error:
            return None, None, error
        if code:
            duplicates = BOM.objects.filter(code__iexact=code)
            if instance is not None:
                duplicates = duplicates.exclude(pk=instance.pk)
            if duplicates.exists():
                return None, None, f"Kode BOM '{code}' sudah dipakai BOM lain."
            values["code"] = code
        elif instance is None:
            values["code"] = generate_bom_code(product)

    if instance is None or "name" in data:
        name, error = _text(data.get("name"), "name", MAX_NAME_LENGTH)
        if error:
            return None, None, error
        values["name"] = name

    if instance is None or "output_qty" in data:
        output_qty, error = _parse_qty(
            data.get("output_qty"), "output_qty", required=instance is None
        )
        if error:
            return None, None, error
        values["output_qty"] = output_qty if output_qty is not None else Decimal("1")

    if "uom_id" in data:
        uom, error = _fk_or_error(data.get("uom_id"), UoM, "Satuan (uom_id)")
        if error:
            return None, None, error
        values["uom"] = uom

    if instance is None or "notes" in data:
        notes, error = _text(data.get("notes"), "notes", 2000)
        if error:
            return None, None, error
        values["notes"] = notes

    if "active" in data:
        active = parse_bool(data.get("active"))
        if active is None:
            return None, None, "Field 'active' harus true|false."
        values["is_active"] = active

    if "lines" in data:
        raw_lines = data.get("lines") or []
        if not isinstance(raw_lines, list):
            return None, None, "Field 'lines' harus berupa array."
        if len(raw_lines) > MAX_LINES:
            return None, None, f"Jumlah baris komponen melebihi batas {MAX_LINES}."

        for index, raw in enumerate(raw_lines):
            line_values, error = validate_line_payload(raw, index)
            if error:
                return None, None, error
            lines.append(line_values)

    bom_product = values.get("product", product)
    if bom_product is not None:
        for index, line in enumerate(lines):
            if line["product"].pk == bom_product.pk:
                return None, None, (
                    f"Baris #{index + 1}: produk '{bom_product.code}' tidak boleh menjadi "
                    "komponen BOM-nya sendiri."
                )

        cycle = _cycle_error(
            bom_product, [line["product"] for line in lines], exclude_bom=instance
        )
        if cycle:
            return None, None, cycle

    return values, lines, None


# ---------------------------------------------------------------------------
# Tulis (create / update / soft delete) — data + idempotensi + audit
# ---------------------------------------------------------------------------
@dataclass
class BomWriteResult:
    """Hasil satu operasi tulis master BOM (dipakai view)."""

    bom: BOM | None = None
    error: str | None = None
    sync_record_id: int | None = None
    task_id: str | None = None

    @property
    def queued(self) -> bool:
        """True kalau task push master berhasil di-enqueue (broker hidup)."""
        return self.task_id is not None


def _arm_push(bom: BOM, payload: dict) -> SyncRecord:
    """Siapkan ``SyncRecord`` MASTER_PUSH BOM ini (PENDING + payload terbaru).

    ``unique(resource, resource_id, stage)`` hanya mengizinkan satu baris per BOM,
    jadi perubahan berikutnya meng-*update* baris yang sama (pola H1.1–H1.4).
    """
    sync = SyncIdempotency()
    record = sync.get_or_create_sync_record(BOM_RESOURCE, bom.pk, STAGE, payload)

    if (
        dict(record.payload or {}) != payload
        or record.status != SyncStatus.PENDING
        or record.last_error
    ):
        record.payload = payload
        record.status = SyncStatus.PENDING
        record.last_error = ""
        record.save(update_fields=("payload", "status", "last_error", "updated_at"))
        logger.info("master.bom: SyncRecord %s di-arm ulang (PENDING).", record.pk)

    return record


def _audit(
    action: str, bom: BOM, payload: dict, request, metadata: dict | None = None
) -> None:
    """Tulis ``AuditLog`` — best-effort (pola ``integrations/erp_sync/audit.py``)."""
    try:
        AuditLogger().log(
            user=None,
            action=action,
            resource=BOM_RESOURCE,
            resource_id=bom.pk,
            request=request,
            payload=payload,
            result=AuditLog.Result.OK,
            metadata=metadata or {},
        )
    except Exception:  # noqa: BLE001 - audit tidak boleh menggagalkan CRUD master
        logger.exception("master.bom: gagal menulis audit (%s, BOM %s).", action, bom.pk)


def _enqueue(bom: BOM, record: SyncRecord) -> str | None:
    """Enqueue task push master; broker mati -> ``None`` (record tetap PENDING)."""
    try:
        async_result = push_master_bom.apply_async(
            args=[bom.pk, record.pk],
            headers={"x-request-id": get_request_id() or ""},
        )
        return str(async_result.id)
    except Exception:  # noqa: BLE001 - CRUD master tidak boleh gagal karena broker
        logger.exception(
            "master.bom: gagal enqueue push BOM %s (SyncRecord %s tetap PENDING).",
            bom.pk,
            record.pk,
        )
        return None


def _apply_lines(bom: BOM, lines: list) -> None:
    """Tulis baris komponen BOM (WAJIB dipanggil di dalam ``transaction.atomic``).

    Pencocokan baris lama→baru: ``id`` (pk MES) → ``odoo_id`` → baris baru.
    Baris lama yang **tidak** lagi dikirim di-*soft-delete* (``is_active=False``)
    bukan dihapus, supaya ``odoo_id`` tiap baris tetap tersimpan dan push
    berikutnya me-*update* baris Odoo yang sama (bukan membuat duplikat).
    """
    existing = list(bom.lines.all())
    by_pk = {line.pk: line for line in existing}
    by_odoo = {line.odoo_id: line for line in existing if line.odoo_id is not None}
    matched: set[int] = set()

    for values in lines:
        target = None
        if values["id"] is not None:
            target = by_pk.get(values["id"])
        if target is None and values["odoo_id"] is not None:
            target = by_odoo.get(values["odoo_id"])
        if target is None:
            target = BOMLine(bom=bom)

        target.product = values["product"]
        target.product_qty = values["quantity"]
        target.uom = values["uom"]
        target.sequence = values["sequence"]
        target.notes = values["notes"]
        target.is_active = True
        target.save()
        matched.add(target.pk)

    for line in existing:
        if line.pk not in matched and line.is_active:
            line.is_active = False
            line.save(update_fields=("is_active",))


def create_bom(data, request=None) -> BomWriteResult:
    """Buat BOM + ``lines[]`` **atomic** + ``SyncRecord`` + ``AuditLog`` + enqueue."""
    values, lines, error = validate_bom_payload(data)
    if error:
        return BomWriteResult(error=error)

    with transaction.atomic():
        bom = BOM.objects.create(**values)
        _apply_lines(bom, lines)

    payload = bom_payload(bom)
    record = _arm_push(bom, payload)
    _audit(
        ACTION_CREATE,
        bom,
        payload,
        request,
        {"odoo_id": bom.odoo_id, "lines": len(lines)},
    )
    task_id = _enqueue(bom, record)

    logger.info(
        "master.bom: BOM %s (%s) dibuat dengan %s baris (sync=%s).",
        bom.pk,
        bom.code,
        len(lines),
        record.pk,
    )
    return BomWriteResult(bom=bom, sync_record_id=record.pk, task_id=task_id)


def update_bom(bom: BOM, data, request=None) -> BomWriteResult:
    """Ubah BOM (hanya field yang dikirim) + ganti baris bila ``lines`` dikirim.

    Seluruh perubahan (header + baris) dijalankan dalam **satu** ``transaction.atomic``
    sehingga satu baris invalid tidak meninggalkan BOM setengah jadi.
    """
    payload_data = data if isinstance(data, dict) else {}
    values, lines, error = validate_bom_payload(payload_data, instance=bom)
    if error:
        return BomWriteResult(bom=bom, error=error)

    replace_lines = "lines" in payload_data
    if not values and not replace_lines:
        # Tidak ada perubahan -> tidak ada audit/push.
        return BomWriteResult(bom=bom)

    with transaction.atomic():
        for field, value in values.items():
            setattr(bom, field, value)
        if values:
            bom.save()
        if replace_lines:
            _apply_lines(bom, lines)

    payload = bom_payload(bom)
    record = _arm_push(bom, payload)
    _audit(
        ACTION_UPDATE,
        bom,
        payload,
        request,
        {
            "odoo_id": bom.odoo_id,
            "fields": sorted(values),
            "lines_replaced": replace_lines,
        },
    )
    task_id = _enqueue(bom, record)

    logger.info(
        "master.bom: BOM %s (%s) diubah (sync=%s).",
        bom.pk,
        bom.code,
        record.pk,
    )
    return BomWriteResult(bom=bom, sync_record_id=record.pk, task_id=task_id)


def deactivate_bom(bom: BOM, request=None) -> BomWriteResult:
    """Soft delete (``is_active=False``) + ``SyncRecord`` + ``AuditLog`` + enqueue.

    **Tanpa** guard dependensi (keputusan H1.5): tidak ada FK lain yang menunjuk
    ``master.BOM`` — ``garment.WorkOrder`` hanya menunjuk ``OrderLine`` — dan semua
    konsumen (``material_readiness``) sudah memfilter ``is_active=True``, sehingga
    menonaktifkan BOM tidak bisa merusak alur produksi. Baris **tidak** dihapus dari
    DB (tidak ada ``delete()``) supaya relasi & jejak audit tetap utuh.
    """
    if bom.is_active:
        bom.is_active = False
        bom.save(update_fields=("is_active",))

    payload = bom_payload(bom)
    record = _arm_push(bom, payload)
    _audit(
        ACTION_DELETE,
        bom,
        payload,
        request,
        {"soft_delete": True, "odoo_id": bom.odoo_id},
    )
    task_id = _enqueue(bom, record)

    logger.info(
        "master.bom: BOM %s (%s) dinonaktifkan (sync=%s).",
        bom.pk,
        bom.code,
        record.pk,
    )
    return BomWriteResult(bom=bom, sync_record_id=record.pk, task_id=task_id)
