"""Task Celery **recompute material readiness** (konsolidasi I3.4 + I6.3 → I7).

Mendelegasikan ke
:class:`~integrations.erp_sync.services.material_readiness.MaterialReadinessService`
(``compute_batch`` — PO **dan** vendor bill Odoo di-fetch **sekali** per batch),
jadi task ini hanya membungkusnya supaya bisa dijadwalkan & di-retry Celery.

Konsolidasi (keputusan I7): dulu ada **dua** task yang memanggil ``compute_batch``
untuk pekerjaan yang sama — ``erp_sync.compute_readiness`` (``tasks_purchase.py``,
**tanpa** jadwal beat) dan ``erp_sync.sync_vendor_bills`` (harian 04:00). Keduanya
digabung menjadi satu task ``erp_sync.recompute_readiness`` supaya:

* tidak ada pekerjaan dobel (fetch PO + vendor bill dua kali sehari);
* cakupannya dipersempit — **hanya** OrderLine yang belum ``READY``
  (``exclude(readiness__status="READY")``), bukan semua baris seperti dulu.

Dijadwalkan **harian jam 04:00 WIB**: entry ``CELERY_BEAT_SCHEDULE``
``recompute-readiness`` → ``crontab(hour=4, minute=0)`` (setelah master sync
jam 02:00, sebelum jam kerja).

Catatan pola:
* ``RETRY_EXCEPTIONS`` **di-import** dari ``tasks_master`` (satu sumber kebenaran).
* Retry hanya untuk error transport/jaringan (``httpx.HTTPError`` /
  ``ConnectionError``) — error data tidak di-retry.
* Odoo **tidak** dipanggil langsung dari task: service → transport.
"""

from __future__ import annotations

import logging

from celery import shared_task

from apps_industry.garment.models import MaterialReadiness, OrderLine

from .services import MaterialReadinessService
from .tasks_master import RETRY_EXCEPTIONS

logger = logging.getLogger(__name__)

__all__ = ("recompute_readiness",)


def _order_lines_to_recompute():
    """OrderLine yang **belum** ``READY`` (queryset, bukan list).

    ``OrderLine`` tidak punya kolom ``state``, jadi patokan "masih perlu
    dihitung" = status ``MaterialReadiness``-nya belum ``READY``. Baris yang
    **belum punya** readiness ikut terambil karena ``exclude()`` membangkitkan
    subquery ``NOT IN`` (bukan LEFT JOIN yang membuang baris tanpa relasi).
    Queryset dijaga *lazy* supaya ``compute_batch`` meng-iterasi hemat memori.
    """
    return OrderLine.objects.exclude(readiness__status=MaterialReadiness.Status.READY)


@shared_task(
    bind=True,
    name="erp_sync.recompute_readiness",
    autoretry_for=RETRY_EXCEPTIONS,
    retry_backoff=True,
    max_retries=3,
)
def recompute_readiness(self):  # noqa: ARG001 - `self` wajib (bind=True)
    """Recompute ``MaterialReadiness`` untuk OrderLine yang **belum** ``READY``.

    Termasuk OrderLine tanpa readiness sama sekali (belum pernah dihitung).
    Satu batch memakai transport yang sama untuk PO **dan** vendor bill.

    Return counter dari service:
    ``{"processed", "waiting", "partial", "ready", "errors"}``.
    """
    order_lines = _order_lines_to_recompute()
    logger.info(
        "erp_sync.recompute_readiness: mulai (%s OrderLine belum READY).",
        order_lines.count(),
    )
    result = MaterialReadinessService().compute_batch(order_lines)
    logger.info("erp_sync.recompute_readiness: selesai -> %s", result)
    return result
