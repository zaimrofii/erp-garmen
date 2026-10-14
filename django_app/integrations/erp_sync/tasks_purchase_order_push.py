"""Task Celery **push Purchase Order** MES → Odoo (H2.2) — transaksi satu arah.

Padanan pembelian dari ``tasks_order_push`` (H2.1). PO ``DRAFT`` murni MES; hanya
saat ``CONFIRMED`` PO dikirim ke Odoo (``docs/CHANGES-DETAIL-H1H5.md`` §1).

Payload ke ``purchase.order`` (probe STEP 0, Odoo 17 — READ-ONLY):

  * **wajib tanpa default**: hanya ``partner_id`` — ``company_id``/
    ``currency_id``/``date_order``/``name``/**``picking_type_id``** punya default
    Odoo ⇒ **tidak** dikirim (Odoo menomori sendiri: ``P00013``);
  * nomor MES dikirim sebagai **``partner_ref``** (field char, writable);
  * baris: ``order_line = [(0, 0, {...})]`` dengan ``name`` (wajib),
    ``product_id``, ``product_qty`` (wajib), ``price_unit`` (wajib),
    ``date_planned`` (opsional) dan **``taxes_id``** = m2m (⚠️ BUKAN ``tax_id`` —
    field itu TIDAK ADA di `purchase.order.line`; berbeda dari `sale.order.line`);
  * **create saja** (state Odoo ``draft``) — ``action_confirm`` TIDAK dipanggil
    supaya receipt/picking Odoo tidak bergerak; ``CANCELLED`` memakai
    ``action_cancel`` pada ``odoo_id`` yang sudah tersimpan.

Guard (dicatat jujur, tidak mengarang id): ``vendor.odoo_id`` **wajib** dan setiap
``product.odoo_id`` **wajib** — kalau tidak, ``MasterPushError`` dengan pesan jelas.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from celery import shared_task
from django.conf import settings

from apps_industry.garment.models import PurchaseOrder
from config.middleware import clear_request_id

from .audit import log_push
from .client import get_odoo_rpc_client
from .idempotency import SyncIdempotency
from .models import SyncRecord, SyncResource, SyncStage
from .tasks import _bind_request_id
from .tasks_master import RETRY_EXCEPTIONS

logger = logging.getLogger(__name__)

__all__ = (
    "ACTION_PURCHASE_ORDER_PUSH",
    "ODOO_MODEL",
    "MasterPushError",
    "is_noop_mode",
    "purchase_order_values",
    "push_purchase_order",
)

#: Model Odoo tujuan push (jangan ganti literal di tempat lain).
ODOO_MODEL = "purchase.order"

#: Action audit untuk push transaksi PO.
ACTION_PURCHASE_ORDER_PUSH = "purchase_order.push"

#: Resource/stage ledger (resource baru H2.2 + stage baru H2.2).
PO_RESOURCE = SyncResource.PURCHASE_ORDER.value
PO_STAGE = SyncStage.PURCHASE_ORDER_PUSH.value


class MasterPushError(Exception):
    """Error data/master yang membuat push **tidak mungkin** (bukan error jaringan)."""


def is_noop_mode() -> bool:
    """True kalau ``ERP_ADAPTER`` bukan ``"odoo"`` (dev/test tanpa Odoo)."""
    return (getattr(settings, "ERP_ADAPTER", "") or "").strip().lower() != "odoo"


def _planned(value) -> str | None:
    """Tanggal MES (``YYYY-MM-DD``) → datetime Odoo (``YYYY-MM-DD 00:00:00``)."""
    text = str(value or "").strip()
    if len(text) == 0:
        return None

    return text if " " in text else f"{text} 00:00:00"


def purchase_order_values(payload: dict) -> dict:
    """Petakan payload MES → nilai ``purchase.order`` Odoo (field terverifikasi probe).

    Raises:
        MasterPushError: kalau vendor/produk belum punya ``odoo_id``.
    """
    vendor_odoo_id = payload.get("vendor_odoo_id")
    if not vendor_odoo_id:
        raise MasterPushError(
            "Vendor PO belum punya `odoo_id` — sinkronkan master Partner dulu "
            "sebelum mengirim Purchase Order ke Odoo."
        )

    lines = []
    for index, line in enumerate(payload.get("lines") or []):
        product_odoo_id = line.get("product_odoo_id")
        if not product_odoo_id:
            raise MasterPushError(
                f"Produk baris #{index + 1} ({line.get('product_code') or line.get('product_id')}) "
                "belum punya `odoo_id` — sinkronkan master Product dulu."
            )

        values = {
            "name": line.get("product_code") or f"Line {index + 1}",
            "product_id": int(product_odoo_id),
            "product_qty": float(line.get("qty") or 0),
            "price_unit": float(line.get("price_unit") or 0),
        }
        planned = _planned(line.get("date_planned"))
        if planned is not None:
            values["date_planned"] = planned

        # ⚠️ `taxes_id` (m2m) — `tax_id` TIDAK ADA di purchase.order.line (probe).
        tax_ids = [int(tax_id) for tax_id in (line.get("tax_odoo_ids") or [])]
        if tax_ids:
            values["taxes_id"] = [(6, 0, tax_ids)]
        lines.append((0, 0, values))

    return {
        "partner_id": int(vendor_odoo_id),
        "partner_ref": payload.get("partner_ref") or payload.get("code"),
        "order_line": lines,
    }


def _push_create(po: PurchaseOrder, payload: dict) -> str:
    """``purchase.order.create()`` → id Odoo (str)."""
    client = get_odoo_rpc_client()
    try:
        return str(client.transport.create(ODOO_MODEL, purchase_order_values(payload)))
    finally:
        client.close()


def _push_cancel(po: PurchaseOrder) -> str:
    """``purchase.order.action_cancel`` untuk PO yang sudah punya ``odoo_id``."""
    if not po.odoo_id:
        raise MasterPushError(f"PO {po.code} belum punya `odoo_id` — tidak ada yang dibatalkan.")
    client = get_odoo_rpc_client()
    try:
        client.transport.call(ODOO_MODEL, "action_cancel", [[int(po.odoo_id)]])
        return str(po.odoo_id)
    finally:
        client.close()


@shared_task(
    bind=True,
    name="erp_sync.push_purchase_order",
    autoretry_for=RETRY_EXCEPTIONS,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=3,
)
def push_purchase_order(
    self, po_id: int, sync_record_id: int | None = None, action: str = "create"
) -> dict:
    """Kirim satu ``PurchaseOrder`` MES ke Odoo (``action="create"``/``"cancel"``).

    Alur: ambil PO → siapkan/ambil ``SyncRecord`` stage ``PURCHASE_ORDER_PUSH`` →
    kalau sudah ``SENT`` **dengan payload sama** → lewati (enqueue ganda) → push
    (create/action_cancel) → simpan ``odoo_id`` (create) → ``mark_sent`` + audit.
    Gagal → ``mark_failed`` lalu **raise** (retry hanya untuk error transport).
    """
    _bind_request_id(self)
    resource = PO_RESOURCE

    try:
        po = (
            PurchaseOrder.objects.select_related("vendor")
            .prefetch_related("lines__product", "lines__tax_ids")
            .filter(pk=po_id)
            .first()
        )
        if po is None:
            logger.warning("erp_sync.push_purchase_order: PO %s tidak ada.", po_id)
            return {"status": "not-found", "po_id": po_id}

        # Payload = `purchase_order_payload` apa adanya (bentuk yang SAMA dengan yang
        # di-arm service) supaya proteksi "enqueue ganda payload identik" bekerja;
        # `action` tidak masuk payload (create vs cancel dibedakan oleh `state`).
        from apps_industry.garment.services.purchase_order_services import purchase_order_payload

        payload = purchase_order_payload(po)
        sync = SyncIdempotency()
        record = (
            SyncRecord.objects.filter(pk=sync_record_id).first()
            if sync_record_id is not None
            else None
        )
        if record is None:
            record = sync.get_or_create_sync_record(resource, po.pk, PO_STAGE, payload)

        if sync.is_already_sent(record) and dict(record.payload or {}) == payload:
            logger.info(
                "erp_sync.push_purchase_order: PO %s sudah terkirim & payload sama -> diabaikan.",
                po.pk,
            )
            return {
                "status": "duplicate-ignored",
                "erp_id": record.erp_id,
                "sync_record_id": record.pk,
                "resource": resource,
                "resource_id": str(po.pk),
            }

        try:
            if is_noop_mode():
                erp_id = f"NULL-{uuid4()}"
                logger.info(
                    "erp_sync.push_purchase_order: ERP_ADAPTER=%s -> no-op %s PO %s (%s).",
                    getattr(settings, "ERP_ADAPTER", "") or "-",
                    action,
                    po.pk,
                    erp_id,
                )
            elif action == "cancel":
                erp_id = _push_cancel(po)
            else:
                erp_id = _push_create(po, payload)
        except Exception as exc:  # noqa: BLE001 - dicatat dulu, lalu di-raise untuk retry
            sync.mark_failed(record, exc)
            log_push(
                ACTION_PURCHASE_ORDER_PUSH,
                resource,
                po.pk,
                status="failed",
                error=exc,
                task_id=self.request.id,
                payload=payload,
            )
            raise

        if action == "create" and not po.odoo_id and str(erp_id).isdigit():
            po.odoo_id = int(erp_id)
            po.save(update_fields=("odoo_id", "updated_at"))

        sync.mark_sent(record, erp_id)
        log_push(
            ACTION_PURCHASE_ORDER_PUSH,
            resource,
            po.pk,
            status="sent",
            erp_id=erp_id,
            task_id=self.request.id,
            payload={**payload, "action": action},
        )

        return {
            "status": "sent",
            "erp_id": erp_id,
            "sync_record_id": record.pk,
            "resource": resource,
            "resource_id": str(po.pk),
            "odoo_id": po.odoo_id,
            "action": action,
        }
    finally:
        clear_request_id()

