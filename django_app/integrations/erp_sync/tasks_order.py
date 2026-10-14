"""Task Celery sync **Sales Order** Odoo → MES (fase I2).

Berbeda dari ``tasks_master`` (yang upsert per-baris via ``_sync``), task di sini
**mendelegasikan** ke
:class:`~integrations.erp_sync.services.sale_order_sync.SaleOrderSyncService` —
service yang memegang pemetaan ``sale.order`` → ``Order``/``OrderLine`` (termasuk
idempotensi ``odoo_id``). Task hanya membungkusnya supaya bisa dijadwalkan &
di-retry Celery.

* ``RETRY_EXCEPTIONS`` **di-import** dari ``tasks_master`` (satu sumber kebenaran —
  duplikasi konstanta berisiko drift); lihat laporan.
* Retry hanya untuk error **transport/jaringan** (``httpx.HTTPError`` /
  ``ConnectionError``) — error data tidak di-retry.
"""

from __future__ import annotations

import logging

from celery import shared_task

from .services import SaleOrderSyncService
from .tasks_master import RETRY_EXCEPTIONS

logger = logging.getLogger(__name__)

__all__ = ("sync_sale_orders",)


@shared_task(
    bind=True,
    name="erp_sync.sync_sale_orders",
    autoretry_for=RETRY_EXCEPTIONS,
    retry_backoff=True,
    max_retries=3,
)
def sync_sale_orders(self, since=None):  # noqa: ARG001 - `self` wajib (bind=True)
    """Tarik SO Odoo (``state='sale'``) → ``Order``/``OrderLine`` MES.

    Return ``{"created": N, "updated": N, "skipped": N}`` dari service.
    """
    logger.info("erp_sync.sync_sale_orders: mulai (since=%s).", since)
    result = SaleOrderSyncService().sync(since=since)
    logger.info("erp_sync.sync_sale_orders: selesai -> %s", result)
    return result
