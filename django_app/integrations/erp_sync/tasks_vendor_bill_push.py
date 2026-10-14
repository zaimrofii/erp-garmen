"""Task Celery push **vendor bill** MES → Odoo (H3.2).

Mengirim **satu** `VendorBill` (model MES) ke Odoo sebagai `account.move`
**draft** bertipe `in_invoice` — jalur **manual** (operator membuat bill dari PO
H2.2 atau manual, lalu `CONFIRMED`).

Beda dari I6 (`erp_sync.recompute_readiness` di `tasks_vendor_bill.py`): task itu
**menarik** vendor bill Odoo (`fetch_vendor_bills`) untuk `MaterialReadiness` dan
**tidak** menulis apa pun ke Odoo. H3.2 ini **mendorong** satu bill MES dan
mencatat jejaknya di `SyncRecord(resource="vendor_bill", stage="VENDOR_BILL")`.

Alur sukses: `CONFIRMED → SENT` + `odoo_id` tersimpan + `SyncRecord` = SENT (lewat
`vendor_bill_services.sync_complete`). Alur gagal: `SyncRecord` = FAILED + `AuditLog`,
**state bill tetap CONFIRMED** (bisa di-retry, idempoten).

Adapter diambil dari `get_adapter()`: dengan `ERP_ADAPTER=null` (dev/test) push
disimulasikan (`NULL-<uuid>`) — tidak ada panggilan jaringan.
"""

from __future__ import annotations

import logging

from celery import shared_task

from apps_industry.garment.models import VendorBill
from apps_industry.garment.services.vendor_bill_services import (
    sync_complete,
    sync_failed,
    vendor_bill_push_payload,
)

from .adapters.factory import get_adapter
from .audit import log_push
from .idempotency import SyncIdempotency
from .models import SyncRecord, SyncResource, SyncStage
from .tasks import _bind_request_id
from .tasks_master import RETRY_EXCEPTIONS

logger = logging.getLogger(__name__)

__all__ = ("ACTION_VENDOR_BILL_PUSH", "push_vendor_bill")

#: Action audit percobaan push (pola ``erp_sync.push_*``).
ACTION_VENDOR_BILL_PUSH = "erp_sync.push_vendor_bill"

#: Resource & stage ledger (sama dengan service).
RESOURCE = SyncResource.VENDOR_BILL.value
STAGE = SyncStage.VENDOR_BILL.value


@shared_task(
    bind=True,
    name="erp_sync.push_vendor_bill",
    autoretry_for=RETRY_EXCEPTIONS,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=3,
)
def push_vendor_bill(self, bill_id: int, sync_record_id: int | None = None, action: str = "push"):
    """Kirim satu vendor bill MES ke Odoo (``action``: ``push`` | ``cancel``).

    ``action="cancel"`` memanggil `account.move.button_cancel` untuk bill yang sudah
    punya `odoo_id` (pembatalan di MES tetap sah walau Odoo menolak).
    """
    _bind_request_id(self)
    sync = SyncIdempotency()

    bill = VendorBill.objects.filter(pk=bill_id).select_related("vendor").first()
    if bill is None:
        logger.warning("erp_sync.push_vendor_bill: bill %s tidak ada.", bill_id)
        return {"status": "not-found", "bill_id": bill_id}

    record = (
        SyncRecord.objects.filter(pk=sync_record_id).first() if sync_record_id is not None else None
    )
    if record is None:
        record = sync.get_or_create_sync_record(
            RESOURCE, bill.pk, STAGE, vendor_bill_push_payload(bill)
        )

    adapter = get_adapter()
    try:
        if action == "cancel":
            return _cancel(self, adapter, bill, record)

        payload = vendor_bill_push_payload(bill)
        if sync.is_already_sent(record) and dict(record.payload or {}) == (
            payload | {"action": "push"}
        ):
            logger.info(
                "erp_sync.push_vendor_bill: bill %s sudah terkirim & payload sama "
                "-> enqueue diabaikan.",
                bill.pk,
            )
            return {
                "status": "duplicate-ignored",
                "erp_id": record.erp_id,
                "sync_record_id": record.pk,
                "resource": RESOURCE,
                "resource_id": str(bill.pk),
            }

        try:
            response = adapter.push_vendor_bill(payload)
        except Exception as exc:  # noqa: BLE001 - dicatat dulu (retry diputuskan Celery)
            sync_failed(bill, exc)
            log_push(
                ACTION_VENDOR_BILL_PUSH,
                RESOURCE,
                bill.pk,
                status="failed",
                error=exc,
                task_id=self.request.id,
                payload=payload,
            )
            raise

        if not response.ok:
            sync_failed(bill, response.error or "push vendor bill gagal.")
            log_push(
                ACTION_VENDOR_BILL_PUSH,
                RESOURCE,
                bill.pk,
                status="failed",
                error=response.error or "push vendor bill gagal.",
                task_id=self.request.id,
                payload=payload,
            )
            return {
                "status": "failed",
                "error": response.error or "push vendor bill gagal.",
                "sync_record_id": record.pk,
                "resource": RESOURCE,
                "resource_id": str(bill.pk),
            }

        result = sync_complete(bill, response.erp_id)
        log_push(
            ACTION_VENDOR_BILL_PUSH,
            RESOURCE,
            bill.pk,
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
            "resource_id": str(bill.pk),
            "odoo_id": bill.odoo_id,
            "state": bill.state,
        }
    finally:
        adapter.close()


def _cancel(self, adapter, bill: VendorBill, record) -> dict:
    """Cabang pembatalan: panggil ``button_cancel`` Odoo (kalau ada ``odoo_id``)."""
    if not bill.odoo_id:
        logger.info(
            "erp_sync.push_vendor_bill: bill %s CANCELLED tanpa odoo_id (MES-only).",
            bill.pk,
        )
        return {"status": "skipped", "reason": "tanpa-odoo-id", "resource_id": str(bill.pk)}

    try:
        response = adapter.cancel_vendor_bill(str(bill.odoo_id))
    except Exception as exc:  # noqa: BLE001 - jejak dulu, retry oleh Celery
        sync_failed(bill, exc)
        log_push(
            ACTION_VENDOR_BILL_PUSH,
            RESOURCE,
            bill.pk,
            status="failed",
            error=exc,
            task_id=self.request.id,
            payload={"action": "cancel", "odoo_id": bill.odoo_id},
        )
        raise

    status = "sent" if response.ok else "failed"
    if response.ok:
        SyncIdempotency().mark_sent(record, response.erp_id or str(bill.odoo_id))
    else:
        sync_failed(bill, response.error or "cancel vendor bill gagal.")

    log_push(
        ACTION_VENDOR_BILL_PUSH,
        RESOURCE,
        bill.pk,
        status=status,
        erp_id=response.erp_id,
        error=response.error,
        task_id=self.request.id,
        payload={"action": "cancel", "odoo_id": bill.odoo_id},
    )

    return {
        "status": status,
        "erp_id": response.erp_id,
        "error": response.error,
        "resource": RESOURCE,
        "resource_id": str(bill.pk),
        "state": bill.state,
    }

