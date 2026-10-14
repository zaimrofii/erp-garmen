"""Task Celery **sync invoice** MES → Odoo (TX-INVOICE) — fase I5.

Mendelegasikan ke
:class:`~integrations.erp_sync.services.invoice_sync.InvoiceSyncService`
(``sync_pending`` — idempotensi lewat ``SyncRecord(resource="order",
stage="INVOICE")``), jadi task ini hanya membungkusnya supaya bisa dijadwalkan &
di-retry Celery.

* Dijadwalkan **tiap 15 menit**: entry ``CELERY_BEAT_SCHEDULE`` ``sync-invoice``
  → ``crontab(minute="*/15")`` (menit 0/15/30/45). Invoice tidak perlu real-time
  (draft dulu; harga dilengkapi supervisor di UI Odoo), tapi juga tidak menunggu
  berhari-hari.
* ``RETRY_EXCEPTIONS`` **di-import** dari ``tasks_master`` (satu sumber kebenaran).
* Retry hanya untuk error transport/jaringan (``httpx.HTTPError`` /
  ``ConnectionError``) — error data tidak di-retry di level task; ``sync_one``
  sudah menandai record ``FAILED`` supaya dicoba lagi pada jadwal berikutnya.
* Odoo **tidak** dipanggil langsung dari task: service → adapter
  (``get_adapter()``).
"""

from __future__ import annotations

import logging

from celery import shared_task

from .services import InvoiceSyncService
from .tasks_master import RETRY_EXCEPTIONS

logger = logging.getLogger(__name__)

__all__ = ("sync_invoice",)


@shared_task(
    bind=True,
    name="erp_sync.sync_invoice",
    autoretry_for=RETRY_EXCEPTIONS,
    retry_backoff=True,
    max_retries=3,
)
def sync_invoice(self):  # noqa: ARG001 - `self` wajib (bind=True)
    """Kirim semua record invoice yang pending ke Odoo (batch).

    Return counter dari service: ``{"sent", "failed", "skipped"}``.
    """
    logger.info("erp_sync.sync_invoice: mulai.")
    result = InvoiceSyncService().sync_pending()
    logger.info("erp_sync.sync_invoice: selesai -> %s", result)
    return result
