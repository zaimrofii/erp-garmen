"""Task Celery untuk sinkronisasi ke/dari ERP (Odoo, Accurate, SAP, ...).

Task di modul ini memakai nama ``erp_sync.*`` sehingga otomatis di-route ke
queue ``erp_sync`` (lihat `CELERY_TASK_ROUTES` di settings dan
`config/celery.py`); worker dijalankan dengan
``celery -A config worker -Q default,erp_sync``.

Isi:

  * ``erp_sync.ping`` — task diagnosa infrastruktur (Fase 0, dipertahankan);
  * ``erp_sync.push_wip_issue`` / ``erp_sync.push_fg_receipt`` — two-stage sync
    (Fase 4.2): ambil ``SyncRecord``, push lewat adapter aktif, catat
    SENT/FAILED, dan **retry otomatis** (3x, exponential backoff + jitter)
    kalau ERP menolak/gagal supaya jaringan lantai produksi yang tidak stabil
    tidak membuat data hilang.
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.conf import settings

from config.middleware import clear_request_id, set_request_id

from .adapters.base import STAGE_FG, STAGE_WIP, ERPAdapterError
from .adapters.factory import get_adapter
from .audit import ACTION_FG, ACTION_WIP, log_push
from .client import get_odoo_client
from .idempotency import SyncIdempotency
from .models import SyncRecord

logger = logging.getLogger(__name__)


def _bind_request_id(task) -> str:
    """Kaitkan request id ke thread-local worker untuk korelasi log.

    View HTTP mengirim id-nya lewat header Celery ``x-request-id`` (lihat
    ``SyncOdooView`` -> ``apply_async(headers=...)``). Kalau header kosong
    (mis. task dipicu beat/listener), fallback ke ``task.request.id`` (task id)
    supaya log worker tetap punya satu id.
    """
    request_id = (task.request.headers or {}).get("x-request-id") or task.request.id
    set_request_id(request_id)
    return request_id


@shared_task(bind=True, name="erp_sync.ping")
def ping(self) -> dict:
    """Task diagnosa infrastruktur sinkronisasi.

    Membuat adapter lewat factory (tanpa login ke Odoo), jadi aman dijalankan
    walau kredensial Odoo belum valid. Dipakai untuk memastikan worker hidup
    dan routing queue ``erp_sync`` bekerja
    """
    client = get_odoo_client()
    result = {
        "status": "ok",
        "task_id": self.request.id,
        "queue": "erp_sync",
        "adapter": type(client).__name__,
        "odoo_url": settings.ODOO_URL,
    }
    logger.info("erp_sync.ping selesai: %s", result)
    return result


# ---------------------------------------------------------------------------
# Two-stage sync (Fase 4.2): WIP issue + FG receipt
# ---------------------------------------------------------------------------
#: Action audit per stage (I8.11) — lihat ``integrations/erp_sync/audit.py``.
_AUDIT_ACTIONS = {STAGE_WIP: ACTION_WIP, STAGE_FG: ACTION_FG}


def _push_stage(
    stage: str,
    resource: str,
    resource_id: str,
    payload: dict,
    sync_record_id: int,
    task_id: str | None = None,
) -> dict:
    """Kirim satu pergerakan stok ke ERP lewat adapter aktif (dipakai kedua task).

    Alur:

      1. ambil ``SyncRecord``; kalau sudah SENT/DUPLICATE -> berhenti
         (``duplicate-ignored``) supaya stok tidak dobel;
      2. ``get_adapter()`` -> ``push_wip_issue``/``push_fg_receipt``;
      3. sukses -> ``mark_sent`` (erp_id + sent_at);
      4. gagal -> ``mark_failed`` (attempts += 1 + last_error) lalu **raise**
         supaya ``autoretry_for`` Celery menjalankan retry;
      5. **baik sukses maupun gagal**, percobaan kirim dicatat ke ``AuditLog``
         (I8.11) dengan ``action=erp_sync.push_wip|push_fg``, ``resource_id``,
         ``status`` (sent/failed), ``erp_id``, ``error``, dan ``task_id``.
    """
    sync = SyncIdempotency()
    try:
        record = SyncRecord.objects.get(pk=sync_record_id)
    except SyncRecord.DoesNotExist as exc:
        raise ERPAdapterError(f"SyncRecord {sync_record_id} tidak ditemukan.") from exc

    if sync.is_already_sent(record):
        logger.info(
            "erp_sync: %s#%s:%s sudah terkirim (status=%s) -> enqueue diabaikan.",
            resource,
            resource_id,
            stage,
            record.status,
        )
        return {
            "status": "duplicate-ignored",
            "erp_id": record.erp_id,
            "sync_record_id": record.pk,
            "stage": stage,
        }

    data = dict(payload or {})
    adapter = get_adapter()
    try:
        logger.info(
            "erp_sync: push %s %s#%s lewat %s (record=%s).",
            stage,
            resource,
            resource_id,
            type(adapter).__name__,
            record.pk,
        )
        if stage == STAGE_WIP:
            response = adapter.push_wip_issue(data)
        else:
            response = adapter.push_fg_receipt(data)
    finally:
        adapter.close()

    if response.ok:
        sync.mark_sent(record, response.erp_id)
        log_push(  # I8.11 — jejak audit percobaan kirim yang berhasil
            _AUDIT_ACTIONS[stage],
            resource,
            resource_id,
            status="sent",
            erp_id=response.erp_id,
            task_id=task_id,
            payload=data,
        )
        return {
            "status": "sent",
            "erp_id": response.erp_id,
            "sync_record_id": record.pk,
            "stage": stage,
            "resource": resource,
            "resource_id": resource_id,
        }

    sync.mark_failed(record, response.error)
    log_push(  # I8.11 — jejak audit percobaan kirim yang gagal
        _AUDIT_ACTIONS[stage],
        resource,
        resource_id,
        status="failed",
        error=response.error,
        task_id=task_id,
        payload=data,
    )
    raise ERPAdapterError(
        f"Push {stage} gagal untuk {resource}#{resource_id}: {response.error}"
    )


@shared_task(
    bind=True,
    name="erp_sync.push_wip_issue",
    autoretry_for=(Exception,),
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
)
def push_wip_issue(
    self,
    resource: str,
    resource_id: str,
    payload: dict,
    sync_record_id: int,
) -> dict:
    """Task: kirim **WIP issue** (stok bahan turun) untuk satu ``SyncRecord``."""
    _bind_request_id(self)
    try:
        return _push_stage(
            STAGE_WIP,
            resource,
            resource_id,
            payload,
            sync_record_id,
            task_id=self.request.id,
        )
    finally:
        clear_request_id()


@shared_task(
    bind=True,
    name="erp_sync.push_fg_receipt",
    autoretry_for=(Exception,),
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
)
def push_fg_receipt(
    self,
    resource: str,
    resource_id: str,
    payload: dict,
    sync_record_id: int,
) -> dict:
    """Task: kirim **FG receipt** (stok barang jadi naik) untuk satu ``SyncRecord``."""
    _bind_request_id(self)
    try:
        return _push_stage(
            STAGE_FG,
            resource,
            resource_id,
            payload,
            sync_record_id,
            task_id=self.request.id,
        )
    finally:
        clear_request_id()

