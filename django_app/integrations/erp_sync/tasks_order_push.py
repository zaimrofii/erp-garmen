"""Task Celery **push Sales Order** MES → Odoo (H2.1) — transaksi satu arah.

Bedanya dengan ``tasks_master_push`` (master H1): ini **transaksi** — order
``DRAFT`` murni MES, dan hanya saat ``CONFIRMED`` order dikirim ke Odoo
(``docs/CHANGES-DETAIL-H1H5.md`` §1). Arah sebaliknya (pull SO Odoo → MES)
tetap di ``tasks_order.sync_sale_orders`` (fase I2) dan **tidak** diubah.

Payload ke ``sale.order`` (probe STEP 0 di Odoo 17):
  * **wajib tanpa default**: ``partner_id`` (+ ``partner_invoice_id``/
    ``partner_shipping_id`` dikirim eksplisit = partner) — ``company_id``/
    ``warehouse_id``/``picking_policy``/``date_order``/``name`` punya default Odoo
    dan **tidak** dikirim (Odoo menomori sendiri: ``S00033``);
  * nomor MES dikirim sebagai ``client_order_ref`` (bukan ``name``);
  * baris: ``order_line = [(0, 0, {...})]`` dengan ``name`` (wajib),
    ``product_id``, ``product_uom_qty`` (wajib), ``price_unit`` (wajib),
    ``tax_id = [(6, 0, [id...])]`` (opsional);
  * **create saja** (state Odoo ``draft``) — ``action_confirm`` TIDAK dipanggil
    supaya picking/stock move Odoo tidak bergerak; ``CANCELLED`` memakai
    ``action_cancel`` pada ``odoo_id`` yang sudah tersimpan.

Guard (dicatat jujur, tidak mengarang id): ``customer.odoo_id`` **wajib** dan setiap
``product.odoo_id`` **wajib** — kalau tidak, ``MasterPushError`` dengan pesan jelas
(sinkronkan master dulu).
"""

from __future__ import annotations

import logging
from uuid import uuid4

from celery import shared_task
from django.conf import settings

from apps_industry.garment.models import Order
from config.middleware import clear_request_id

from .audit import log_push
from .client import get_odoo_rpc_client
from .idempotency import SyncIdempotency
from .models import SyncRecord, SyncResource, SyncStage
from .tasks import _bind_request_id
from .tasks_master import RETRY_EXCEPTIONS

logger = logging.getLogger(__name__)

__all__ = (
    "ACTION_SALE_ORDER_PUSH",
    "ODOO_MODEL",
    "MasterPushError",
    "push_sale_order",
    "sale_order_values",
)

#: Model Odoo tujuan push (jangan ganti literal di tempat lain).
ODOO_MODEL = "sale.order"

#: Action audit untuk push transaksi.
ACTION_SALE_ORDER_PUSH = "order.push"

#: Resource/stage ledger (reuse resource `order` + stage baru H2.1).
ORDER_RESOURCE = SyncResource.ORDER.value
ORDER_STAGE = SyncStage.SALE_ORDER_PUSH.value


class MasterPushError(Exception):
    """Error data/master yang membuat push **tidak mungkin** (bukan error jaringan)."""


def is_noop_mode() -> bool:
    """True kalau ``ERP_ADAPTER`` bukan ``"odoo"`` (dev/test tanpa Odoo)."""
    return (getattr(settings, "ERP_ADAPTER", "") or "").strip().lower() != "odoo"


def sale_order_values(payload: dict) -> dict:
    """Petakan payload MES → nilai ``sale.order`` Odoo (field terverifikasi probe).

    Raises:
        MasterPushError: kalau customer/produk belum punya ``odoo_id``.
    """
    customer_odoo_id = payload.get("customer_odoo_id")
    if not customer_odoo_id:
        raise MasterPushError(
            "Customer order belum punya `odoo_id` — sinkronkan master Partner dulu "
            "sebelum mengirim Sales Order ke Odoo."
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
            "product_uom_qty": int(line.get("qty") or 0),
            "price_unit": float(line.get("price_unit") or 0),
        }
        tax_ids = [int(tax_id) for tax_id in (line.get("tax_odoo_ids") or [])]
        if tax_ids:
            values["tax_id"] = [(6, 0, tax_ids)]
        lines.append((0, 0, values))

    return {
        "partner_id": int(customer_odoo_id),
        # partner_invoice/shipping WAJIB di Odoo (tanpa default) — samakan dengan partner.
        "partner_invoice_id": int(customer_odoo_id),
        "partner_shipping_id": int(customer_odoo_id),
        "client_order_ref": payload.get("client_order_ref") or payload.get("code"),
        "order_line": lines,
    }


def _push_create(order: Order, payload: dict) -> str:
    """``sale.order.create()`` → id Odoo (str)."""
    client = get_odoo_rpc_client()
    try:
        return str(client.transport.create(ODOO_MODEL, sale_order_values(payload)))
    finally:
        client.close()


def _push_cancel(order: Order) -> str:
    """``sale.order.action_cancel`` untuk order yang sudah punya ``odoo_id``."""
    if not order.odoo_id:
        raise MasterPushError(f"Order {order.code} belum punya `odoo_id` — tidak ada yang dibatalkan.")
    client = get_odoo_rpc_client()
    try:
        client.transport.call(ODOO_MODEL, "action_cancel", [[int(order.odoo_id)]])
        return str(order.odoo_id)
    finally:
        client.close()


@shared_task(
    bind=True,
    name="erp_sync.push_sale_order",
    autoretry_for=RETRY_EXCEPTIONS,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=3,
)
def push_sale_order(
    self, order_id: int, sync_record_id: int | None = None, action: str = "create"
) -> dict:
    """Kirim satu ``Order`` MES ke Odoo (``action="create"``/``"cancel"``).

    Alur: ambil order → siapkan/ambil ``SyncRecord`` stage ``SALE_ORDER_PUSH`` →
    kalau sudah ``SENT`` **dengan payload sama** untuk aksi yang sama → lewati
    (enqueue ganda) → push (create/action_cancel) → simpan ``odoo_id`` (create) →
    ``mark_sent`` + audit. Gagal → ``mark_failed`` lalu **raise** (retry transport).
    """
    _bind_request_id(self)
    resource = ORDER_RESOURCE

    try:
        order = (
            Order.objects.select_related("customer")
            .prefetch_related("lines__product", "lines__tax_ids")
            .filter(pk=order_id)
            .first()
        )
        if order is None:
            logger.warning("erp_sync.push_sale_order: order %s tidak ada.", order_id)
            return {"status": "not-found", "order_id": order_id}

        from apps_industry.garment.services.order_services import order_payload

        # Payload = `order_payload` apa adanya (bentuk yang SAMA dengan yang di-arm
        # service) supaya proteksi "enqueue ganda dengan payload identik" bekerja.
        # `action` tidak masuk payload: create vs cancel dibedakan oleh `state`.
        payload = order_payload(order)
        sync = SyncIdempotency()
        record = (
            SyncRecord.objects.filter(pk=sync_record_id).first()
            if sync_record_id is not None
            else None
        )
        if record is None:
            record = sync.get_or_create_sync_record(resource, order.pk, ORDER_STAGE, payload)

        if sync.is_already_sent(record) and dict(record.payload or {}) == payload:
            logger.info(
                "erp_sync.push_sale_order: order %s sudah terkirim & payload sama -> diabaikan.",
                order.pk,
            )
            return {
                "status": "duplicate-ignored",
                "erp_id": record.erp_id,
                "sync_record_id": record.pk,
                "resource": resource,
                "resource_id": str(order.pk),
            }

        try:
            if is_noop_mode():
                erp_id = f"NULL-{uuid4()}"
                logger.info(
                    "erp_sync.push_sale_order: ERP_ADAPTER=%s -> no-op %s order %s (%s).",
                    getattr(settings, "ERP_ADAPTER", "") or "-",
                    action,
                    order.pk,
                    erp_id,
                )
            elif action == "cancel":
                erp_id = _push_cancel(order)
            else:
                erp_id = _push_create(order, payload)
        except Exception as exc:  # noqa: BLE001 - dicatat dulu, lalu di-raise untuk retry
            sync.mark_failed(record, exc)
            log_push(
                ACTION_SALE_ORDER_PUSH,
                resource,
                order.pk,
                status="failed",
                error=exc,
                task_id=self.request.id,
                payload=payload,
            )
            raise

        if action == "create" and not order.odoo_id and str(erp_id).isdigit():
            order.odoo_id = int(erp_id)
            order.save(update_fields=("odoo_id", "updated_at"))

        sync.mark_sent(record, erp_id)
        log_push(
            ACTION_SALE_ORDER_PUSH,
            resource,
            order.pk,
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
            "resource_id": str(order.pk),
            "odoo_id": order.odoo_id,
            "action": action,
        }
    finally:
        clear_request_id()

