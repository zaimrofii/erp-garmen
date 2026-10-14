"""Task Celery push **customer invoice** MES → Odoo (H3.1).

Mengirim **satu** `CustomerInvoice` (model MES) ke Odoo sebagai `account.move`
**draft** — jalur **manual** (akuntan memilih order & melengkapi harga).

Beda dari I5 (`erp_sync.sync_invoice`, batch beat 15 menit untuk resource `order`
dengan `price_unit=0`): task ini **single-record**, dipicu saat `CONFIRMED`
(enqueue dari service), dan mengirim **harga & pajak nyata**
(`customer_invoice_push_payload` → adapter `push_customer_invoice`).

Alur sukses: `CONFIRMED → SENT` + `odoo_id` tersimpan + `SyncRecord` = SENT
(lewat `customer_invoice_services.sync_complete`). Alur gagal: `SyncRecord` =
FAILED + `AuditLog`, **state invoice tetap CONFIRMED** (bisa di-retry, idempoten).

Adapter diambil dari `get_adapter()`: dengan `ERP_ADAPTER=null` (dev/test) push
disimulasikan (`NULL-<uuid>`) — tidak ada panggilan jaringan.
"""

from __future__ import annotations

import logging

from celery import shared_task

from apps_industry.garment.models import CustomerInvoice
from apps_industry.garment.services.customer_invoice_services import (
    customer_invoice_push_payload,
    sync_complete,
    sync_failed,
)

from .adapters.factory import get_adapter
from .audit import log_push
from .idempotency import SyncIdempotency
from .models import SyncRecord, SyncResource, SyncStage
from .tasks import _bind_request_id
from .tasks_master import RETRY_EXCEPTIONS

logger = logging.getLogger(__name__)

__all__ = ("ACTION_CUSTOMER_INVOICE_PUSH", "push_customer_invoice")

#: Action audit percobaan push (pola ``erp_sync.push_*``).
ACTION_CUSTOMER_INVOICE_PUSH = "erp_sync.push_customer_invoice"

#: Resource & stage ledger (sama dengan service).
RESOURCE = SyncResource.CUSTOMER_INVOICE.value
STAGE = SyncStage.INVOICE.value



@shared_task(
    bind=True,
    name="erp_sync.push_customer_invoice",
    autoretry_for=RETRY_EXCEPTIONS,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=3,
)
def push_customer_invoice(
    self, invoice_id: int, sync_record_id: int | None = None, action: str = "push"
):
    """Kirim satu invoice MES ke Odoo (``action``: ``push`` | ``cancel``).

    ``action="cancel"`` memanggil `account.move.button_cancel` untuk invoice yang
    sudah punya `odoo_id` (pembatalan di MES tetap sah walau Odoo menolak).
    """
    _bind_request_id(self)
    sync = SyncIdempotency()

    invoice = CustomerInvoice.objects.filter(pk=invoice_id).select_related("customer").first()
    if invoice is None:
        logger.warning("erp_sync.push_customer_invoice: invoice %s tidak ada.", invoice_id)
        return {"status": "not-found", "invoice_id": invoice_id}

    record = (
        SyncRecord.objects.filter(pk=sync_record_id).first() if sync_record_id is not None else None
    )
    if record is None:
        record = sync.get_or_create_sync_record(
            RESOURCE, invoice.pk, STAGE, customer_invoice_push_payload(invoice)
        )

    adapter = get_adapter()
    try:
        if action == "cancel":
            return _cancel(self, adapter, invoice, record)

        payload = customer_invoice_push_payload(invoice)
        if sync.is_already_sent(record) and dict(record.payload or {}) == (
            payload | {"action": "push"}
        ):
            logger.info(
                "erp_sync.push_customer_invoice: invoice %s sudah terkirim & payload sama "
                "-> enqueue diabaikan.",
                invoice.pk,
            )
            return {
                "status": "duplicate-ignored",
                "erp_id": record.erp_id,
                "sync_record_id": record.pk,
                "resource": RESOURCE,
                "resource_id": str(invoice.pk),
            }

        try:
            response = adapter.push_customer_invoice(payload)
        except Exception as exc:  # noqa: BLE001 - dicatat dulu (retry diputuskan Celery)
            sync_failed(invoice, exc)
            log_push(
                ACTION_CUSTOMER_INVOICE_PUSH,
                RESOURCE,
                invoice.pk,
                status="failed",
                error=exc,
                task_id=self.request.id,
                payload=payload,
            )
            raise

        if not response.ok:
            sync_failed(invoice, response.error or "push invoice gagal.")
            log_push(
                ACTION_CUSTOMER_INVOICE_PUSH,
                RESOURCE,
                invoice.pk,
                status="failed",
                error=response.error or "push invoice gagal.",
                task_id=self.request.id,
                payload=payload,
            )
            return {
                "status": "failed",
                "error": response.error or "push invoice gagal.",
                "sync_record_id": record.pk,
                "resource": RESOURCE,
                "resource_id": str(invoice.pk),
            }

        result = sync_complete(invoice, response.erp_id)
        log_push(
            ACTION_CUSTOMER_INVOICE_PUSH,
            RESOURCE,
            invoice.pk,
            status="sent",
            erp_id=response.erp_id,
            task_id=self.request.id,
            payload=payload,
        )

        return {
            "status": "sent",
            "erp_id": response.erp_id,
            "sync_record_id": result.sync_record_id,
            "resource": RESOURCE,
            "resource_id": str(invoice.pk),
            "odoo_id": invoice.odoo_id,
            "state": invoice.state,
        }
    finally:
        adapter.close()


def _cancel(self, adapter, invoice: CustomerInvoice, record) -> dict:
    """Cabang pembatalan: panggil ``button_cancel`` Odoo (kalau ada ``odoo_id``)."""
    if not invoice.odoo_id:
        logger.info(
            "erp_sync.push_customer_invoice: invoice %s CANCELLED tanpa odoo_id (MES-only).",
            invoice.pk,
        )
        return {"status": "skipped", "reason": "tanpa-odoo-id", "resource_id": str(invoice.pk)}

    try:
        response = adapter.cancel_customer_invoice(str(invoice.odoo_id))
    except Exception as exc:  # noqa: BLE001 - jejak dulu, retry oleh Celery
        sync_failed(invoice, exc)
        log_push(
            ACTION_CUSTOMER_INVOICE_PUSH,
            RESOURCE,
            invoice.pk,
            status="failed",
            error=exc,
            task_id=self.request.id,
            payload={"action": "cancel", "odoo_id": invoice.odoo_id},
        )
        raise

    status = "sent" if response.ok else "failed"
    if response.ok:
        SyncIdempotency().mark_sent(record, response.erp_id or str(invoice.odoo_id))
    else:
        sync_failed(invoice, response.error or "cancel invoice gagal.")

    log_push(
        ACTION_CUSTOMER_INVOICE_PUSH,
        RESOURCE,
        invoice.pk,
        status=status,
        erp_id=response.erp_id,
        error=response.error,
        task_id=self.request.id,
        payload={"action": "cancel", "odoo_id": invoice.odoo_id},
    )

    return {
        "status": status,
        "erp_id": response.erp_id,
        "error": response.error,
        "resource": RESOURCE,
        "resource_id": str(invoice.pk),
        "state": invoice.state,
    }
