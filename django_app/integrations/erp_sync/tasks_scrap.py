"""Task Celery **sync scrap** MES → Odoo (TX-SCRAP) — fase I4.

Mendelegasikan ke
:class:`~integrations.erp_sync.services.scrap_sync.ScrapSyncService` (``sync_batch``
— idempotensi lewat ``SyncRecord(resource="scrap_accumulator", stage="SCRAP")``),
jadi task ini hanya membungkusnya supaya bisa dijadwalkan & di-retry Celery.

* Dijadwalkan **per shift** (pagi/siang/malam): entry ``CELERY_BEAT_SCHEDULE``
  ``sync-scrap-accumulator`` → ``crontab(hour="6,14,22", minute=0)``
  (jam 06:00 / 14:00 / 22:00 WIB). Sengaja **bukan** tiap beberapa menit —
  scrap diakumulasi per shift.
* ``RETRY_EXCEPTIONS`` **di-import** dari ``tasks_master`` (satu sumber kebenaran).
* Retry hanya untuk error transport/jaringan (``httpx.HTTPError`` /
  ``ConnectionError``) — error data tidak di-retry.
* Odoo **tidak** dipanggil langsung dari task: service → adapter
  (``get_adapter()``).
"""

from __future__ import annotations

import logging

from celery import shared_task

from .services import ScrapSyncService
from .tasks_master import RETRY_EXCEPTIONS

logger = logging.getLogger(__name__)

__all__ = ("sync_scrap_accumulator",)


@shared_task(
    bind=True,
    name="erp_sync.sync_scrap_accumulator",
    autoretry_for=RETRY_EXCEPTIONS,
    retry_backoff=True,
    max_retries=3,
)
def sync_scrap_accumulator(self):  # noqa: ARG001 - `self` wajib (bind=True)
    """Kirim semua ``ScrapAccumulator`` yang pending ke Odoo (batch).

    Return counter dari service: ``{"sent", "failed", "skipped"}``.
    """
    logger.info("erp_sync.sync_scrap_accumulator: mulai.")
    result = ScrapSyncService().sync_batch()
    logger.info("erp_sync.sync_scrap_accumulator: selesai -> %s", result)
    return result
