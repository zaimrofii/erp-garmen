"""Task Celery push **journal entry** MES → Odoo (H3.4).

Mengirim **satu** `JournalEntry` (double-entry manual MES) ke Odoo sebagai
``account.move`` ``move_type='entry'`` **draft**.

Beda dari jalur lain: task ini **membuat** jurnal draft (MES → Odoo) dan **tidak**
mem-posting apa pun — akuntan Odoo yang mem-posting (`action_post` tidak pernah
dipanggil; keputusan STEP 0 H3.4, konsisten H3.1–H3.3).

Alur sukses: `CONFIRMED → SENT` + `odoo_id` tersimpan + `SyncRecord` = SENT (lewat
`journal_entry_services.sync_complete`). Alur gagal: `SyncRecord` = FAILED +
`AuditLog`, **state entry tetap CONFIRMED** (bisa di-retry, idempoten).

Adapter diambil dari `get_adapter()`: dengan `ERP_ADAPTER=null` (dev/test) push
disimulasikan (`NULL-<uuid>`) — tidak ada panggilan jaringan.
"""

from __future__ import annotations

import logging

from celery import shared_task

from apps_industry.garment.models import JournalEntry
from apps_industry.garment.services.journal_entry_services import (
    journal_entry_push_payload,
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

__all__ = ("ACTION_JOURNAL_ENTRY_PUSH", "push_journal_entry")

#: Action audit percobaan push (pola ``erp_sync.push_*``).
ACTION_JOURNAL_ENTRY_PUSH = "erp_sync.push_journal_entry"

#: Resource & stage ledger (sama dengan service).
RESOURCE = SyncResource.JOURNAL_ENTRY.value
STAGE = SyncStage.JOURNAL_ENTRY.value


@shared_task(
    bind=True,
    name="erp_sync.push_journal_entry",
    autoretry_for=RETRY_EXCEPTIONS,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=3,
)
def push_journal_entry(
    self, entry_id: int, sync_record_id: int | None = None, action: str = "push"
):
    """Kirim satu journal entry MES ke Odoo (``action``: ``push`` | ``cancel``).

    ``action="cancel"`` memanggil `account.move.button_cancel` untuk entry yang sudah
    punya `odoo_id` (pembatalan di MES tetap sah walau Odoo menolak).
    """
    _bind_request_id(self)
    sync = SyncIdempotency()

    entry = (
        JournalEntry.objects.filter(pk=entry_id)
        .select_related("journal")
        .prefetch_related("lines__account", "lines__partner")
        .first()
    )
    if entry is None:
        logger.warning("erp_sync.push_journal_entry: entry %s tidak ada.", entry_id)
        return {"status": "not-found", "entry_id": entry_id}

    record = (
        SyncRecord.objects.filter(pk=sync_record_id).first() if sync_record_id is not None else None
    )
    if record is None:
        record = sync.get_or_create_sync_record(
            RESOURCE, entry.pk, STAGE, journal_entry_push_payload(entry)
        )

    adapter = get_adapter()
    try:
        if action == "cancel":
            return _cancel(self, adapter, entry, record)

        payload = journal_entry_push_payload(entry)
        if sync.is_already_sent(record) and dict(record.payload or {}) == (
            payload | {"action": "push"}
        ):
            logger.info(
                "erp_sync.push_journal_entry: entry %s sudah terkirim & payload sama "
                "-> enqueue diabaikan.",
                entry.pk,
            )
            return {
                "status": "duplicate-ignored",
                "resource": RESOURCE,
                "resource_id": str(entry.pk),
                "erp_id": record.erp_id,
            }

        try:
            response = adapter.push_journal_entry(payload)
        except Exception as exc:  # noqa: BLE001 - dicatat dulu (retry diputuskan Celery)
            sync_failed(entry, exc)
            log_push(
                ACTION_JOURNAL_ENTRY_PUSH,
                RESOURCE,
                entry.pk,
                status="failed",
                error=exc,
                task_id=self.request.id,
                payload=payload,
            )
            raise

        if not response.ok:
            sync_failed(entry, response.error or "push journal entry gagal.")
            log_push(
                ACTION_JOURNAL_ENTRY_PUSH,
                RESOURCE,
                entry.pk,
                status="failed",
                error=response.error or "push journal entry gagal.",
                task_id=self.request.id,
                payload=payload,
            )
            return {
                "status": "failed",
                "error": response.error or "push journal entry gagal.",
                "sync_record_id": record.pk,
                "resource": RESOURCE,
                "resource_id": str(entry.pk),
            }

        result = sync_complete(entry, response.erp_id)
        log_push(
            ACTION_JOURNAL_ENTRY_PUSH,
            RESOURCE,
            entry.pk,
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
            "resource_id": str(entry.pk),
            "odoo_id": entry.odoo_id,
            "state": entry.state,
        }
    finally:
        adapter.close()


def _cancel(self, adapter, entry: JournalEntry, record) -> dict:
    """Cabang pembatalan: panggil ``button_cancel`` Odoo (kalau ada ``odoo_id``)."""
    if not entry.odoo_id:
        logger.info(
            "erp_sync.push_journal_entry: entry %s CANCELLED tanpa odoo_id (MES-only).",
            entry.pk,
        )
        return {"status": "skipped", "reason": "tanpa-odoo-id", "resource_id": str(entry.pk)}

    try:
        response = adapter.cancel_journal_entry(str(entry.odoo_id))
    except Exception as exc:  # noqa: BLE001 - jejak dulu, retry oleh Celery
        sync_failed(entry, exc)
        log_push(
            ACTION_JOURNAL_ENTRY_PUSH,
            RESOURCE,
            entry.pk,
            status="failed",
            error=exc,
            task_id=self.request.id,
            payload={"action": "cancel", "odoo_id": entry.odoo_id},
        )
        raise

    status = "sent" if response.ok else "failed"
    if response.ok:
        SyncIdempotency().mark_sent(record, response.erp_id or str(entry.odoo_id))
    else:
        sync_failed(entry, response.error or "cancel journal entry gagal.")

    log_push(
        ACTION_JOURNAL_ENTRY_PUSH,
        RESOURCE,
        entry.pk,
        status=status,
        erp_id=response.erp_id,
        error=response.error,
        task_id=self.request.id,
        payload={"action": "cancel", "odoo_id": entry.odoo_id},
    )

    return {
        "status": status,
        "erp_id": response.erp_id,
        "error": response.error,
        "resource": RESOURCE,
        "resource_id": str(entry.pk),
        "state": entry.state,
    }
