"""Task Celery push **payment** MES → Odoo (H3.3).

Mengirim **satu** `Payment` (model MES) ke Odoo sebagai `account.payment`
**draft** — satu task untuk dua arah (`payment_type` `INBOUND`/`OUTBOUND`; arahnya
ada di payload, bukan di nama task).

Beda dari jalur lain: task ini **membuat** payment (MES → Odoo) dan **tidak**
merekonsiliasi apa pun — `account.payment` `_inherits account.move` sehingga create
langsung membuat satu jurnal **draft**; posting & rekonsiliasi dilakukan akuntan
Odoo (keputusan STEP 0 H3.3).

Alur sukses: `CONFIRMED → SENT` + `odoo_id` tersimpan + `SyncRecord` = SENT (lewat
`payment_services.sync_complete`). Alur gagal: `SyncRecord` = FAILED + `AuditLog`,
**state payment tetap CONFIRMED** (bisa di-retry, idempoten).

Adapter diambil dari `get_adapter()`: dengan `ERP_ADAPTER=null` (dev/test) push
disimulasikan (`NULL-<uuid>`) — tidak ada panggilan jaringan.
"""

from __future__ import annotations

import logging

from celery import shared_task

from apps_industry.garment.models import Payment
from apps_industry.garment.services.payment_services import (
    payment_push_payload,
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

__all__ = ("ACTION_PAYMENT_PUSH", "push_payment")

#: Action audit percobaan push (pola ``erp_sync.push_*``).
ACTION_PAYMENT_PUSH = "erp_sync.push_payment"

#: Resource & stage ledger (sama dengan service).
RESOURCE = SyncResource.PAYMENT.value
STAGE = SyncStage.PAYMENT.value


@shared_task(
    bind=True,
    name="erp_sync.push_payment",
    autoretry_for=RETRY_EXCEPTIONS,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=3,
)
def push_payment(self, payment_id: int, sync_record_id: int | None = None, action: str = "push"):
    """Kirim satu payment MES ke Odoo (``action``: ``push`` | ``cancel``).

    ``action="cancel"`` memanggil `account.payment.action_cancel` untuk payment yang
    sudah punya `odoo_id` (pembatalan di MES tetap sah walau Odoo menolak).
    """
    _bind_request_id(self)
    sync = SyncIdempotency()

    payment = Payment.objects.filter(pk=payment_id).select_related("partner").first()
    if payment is None:
        logger.warning("erp_sync.push_payment: payment %s tidak ada.", payment_id)
        return {"status": "not-found", "payment_id": payment_id}

    record = (
        SyncRecord.objects.filter(pk=sync_record_id).first() if sync_record_id is not None else None
    )
    if record is None:
        record = sync.get_or_create_sync_record(
            RESOURCE, payment.pk, STAGE, payment_push_payload(payment)
        )

    adapter = get_adapter()
    try:
        if action == "cancel":
            return _cancel(self, adapter, payment, record)

        payload = payment_push_payload(payment)
        if sync.is_already_sent(record) and dict(record.payload or {}) == (
            payload | {"action": "push"}
        ):
            logger.info(
                "erp_sync.push_payment: payment %s sudah terkirim & payload sama "
                "-> enqueue diabaikan.",
                payment.pk,
            )
            return {
                "status": "duplicate-ignored",
                "erp_id": record.erp_id,
                "sync_record_id": record.pk,
                "resource": RESOURCE,
                "resource_id": str(payment.pk),
            }

        try:
            response = adapter.push_payment(payload)
        except Exception as exc:  # noqa: BLE001 - dicatat dulu (retry diputuskan Celery)
            sync_failed(payment, exc)
            log_push(
                ACTION_PAYMENT_PUSH,
                RESOURCE,
                payment.pk,
                status="failed",
                error=exc,
                task_id=self.request.id,
                payload=payload,
            )
            raise

        if not response.ok:
            sync_failed(payment, response.error or "push payment gagal.")
            log_push(
                ACTION_PAYMENT_PUSH,
                RESOURCE,
                payment.pk,
                status="failed",
                error=response.error or "push payment gagal.",
                task_id=self.request.id,
                payload=payload,
            )
            return {
                "status": "failed",
                "error": response.error or "push payment gagal.",
                "sync_record_id": record.pk,
                "resource": RESOURCE,
                "resource_id": str(payment.pk),
            }

        result = sync_complete(payment, response.erp_id)
        log_push(
            ACTION_PAYMENT_PUSH,
            RESOURCE,
            payment.pk,
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
            "resource_id": str(payment.pk),
            "odoo_id": payment.odoo_id,
            "state": payment.state,
        }
    finally:
        adapter.close()


def _cancel(self, adapter, payment: Payment, record) -> dict:
    """Cabang pembatalan: panggil ``action_cancel`` Odoo (kalau ada ``odoo_id``)."""
    if not payment.odoo_id:
        logger.info(
            "erp_sync.push_payment: payment %s CANCELLED tanpa odoo_id (MES-only).",
            payment.pk,
        )
        return {"status": "skipped", "reason": "tanpa-odoo-id", "resource_id": str(payment.pk)}

    try:
        response = adapter.cancel_payment(str(payment.odoo_id))
    except Exception as exc:  # noqa: BLE001 - jejak dulu, retry oleh Celery
        sync_failed(payment, exc)
        log_push(
            ACTION_PAYMENT_PUSH,
            RESOURCE,
            payment.pk,
            status="failed",
            error=exc,
            task_id=self.request.id,
            payload={"action": "cancel", "odoo_id": payment.odoo_id},
        )
        raise

    status = "sent" if response.ok else "failed"
    if response.ok:
        SyncIdempotency().mark_sent(record, response.erp_id or str(payment.odoo_id))
    else:
        sync_failed(payment, response.error or "cancel payment gagal.")

    log_push(
        ACTION_PAYMENT_PUSH,
        RESOURCE,
        payment.pk,
        status=status,
        erp_id=response.erp_id,
        error=response.error,
        task_id=self.request.id,
        payload={"action": "cancel", "odoo_id": payment.odoo_id},
    )

    return {
        "status": status,
        "erp_id": response.erp_id,
        "error": response.error,
        "resource": RESOURCE,
        "resource_id": str(payment.pk),
        "state": payment.state,
    }
