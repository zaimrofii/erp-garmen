"""Task Celery **rekonsiliasi stok** MES vs Odoo (fase I7).

Mendelegasikan ke
:class:`~integrations.erp_sync.services.reconciliation.ReconciliationService`
(``compare``) — yang membandingkan stok MES (WIP + FG) dengan on-hand Odoo di
semua lokasi ``usage='internal'`` dan menyimpan satu baris
``StockReconciliation`` per produk.

* Dijadwalkan **mingguan, Senin 03:00 WIB**: entry ``CELERY_BEAT_SCHEDULE``
  ``reconcile-stock`` → ``crontab(day_of_week=1, hour=3, minute=0)`` (setelah
  master sync 02:00 & sebelum jam kerja) — rekonsiliasi tidak perlu harian.
* Kalau ada selisih (``alert_count > 0``) → kirim **ringkasan WA** ke nomor di
  ``settings.RECONCILIATION_ALERT_WA_TO`` (gateway dari
  ``integrations.wa_bot.services.get_wa_gateway`` — tidak ada HTTP langsung di
  sini). Nomor kosong → alert dilewati (cukup log info).
* **WA gagal TIDAK menggagalkan task**: pengiriman dibungkus ``try/except`` dan
  respons ``ok=False`` hanya di-log; hasil rekonsiliasi tetap dikembalikan.
* ``RETRY_EXCEPTIONS`` **di-import** dari ``tasks_master`` (satu sumber
  kebenaran) — retry hanya untuk error transport/jaringan (``httpx.HTTPError`` /
  ``ConnectionError``), dan retry terjadi pada ``compare`` (sisi Odoo), bukan
  pada pengiriman WA.
* Odoo **tidak** dipanggil langsung dari task: service → transport.
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.conf import settings

from integrations.wa_bot.services import get_wa_gateway

from .services import ReconciliationService
from .tasks_master import RETRY_EXCEPTIONS

logger = logging.getLogger(__name__)

__all__ = ("reconcile_stock",)

#: Ambang default kalau setting tidak tersedia (produksi = settings).
DEFAULT_ALERT_WA_TO: tuple = ()


@shared_task(
    bind=True,
    name="erp_sync.reconcile_stock",
    autoretry_for=RETRY_EXCEPTIONS,
    retry_backoff=True,
    max_retries=3,
)
def reconcile_stock(self):  # noqa: ARG001 - `self` wajib (bind=True)
    """Rekonsiliasi stok MES vs Odoo; kirim alert WA kalau ada selisih.

    Return ringkasan ``ReconciliationService.compare()``:
    ``{"total_products", "alert_count", "alerts"}``.
    """
    logger.info("erp_sync.reconcile_stock: mulai rekonsiliasi stok MES vs Odoo.")
    result = ReconciliationService().compare()
    logger.info("erp_sync.reconcile_stock: selesai -> %s", result)

    if result.get("alert_count", 0) > 0:
        _send_reconciliation_alert(result)

    return result


def _send_reconciliation_alert(result: dict) -> None:
    """Kirim ringkasan alert rekonsiliasi ke WA (best-effort).

    * nomor tujuan dari ``settings.RECONCILIATION_ALERT_WA_TO`` — kosong → skip
      (log info), **tidak** error;
    * gateway dipilih factory existing (``get_wa_gateway``) — implementasi
      nyata/mock tidak memengaruhi task ini;
    * **semua** kegagalan (exception ATAU ``ok=False``) hanya di-log: task
      rekonsiliasi tidak boleh gagal karena notifikasi.
    """
    recipients = [
        str(number).strip()
        for number in (getattr(settings, "RECONCILIATION_ALERT_WA_TO", None) or DEFAULT_ALERT_WA_TO)
        if str(number).strip()
    ]
    if not recipients:
        logger.info(
            "erp_sync.reconcile_stock: RECONCILIATION_ALERT_WA_TO kosong "
            "-> alert WA dilewati."
        )
        return

    body = format_reconciliation_alert(result)
    try:
        gateway = get_wa_gateway()
        for number in recipients:
            response = gateway.send_message(number, body)
            if getattr(response, "ok", False):
                logger.info(
                    "erp_sync.reconcile_stock: alert WA terkirim ke %s (id=%s).",
                    number,
                    getattr(response, "message_id", None),
                )
            else:
                logger.error(
                    "erp_sync.reconcile_stock: alert WA ke %s gagal: %s",
                    number,
                    getattr(response, "error", None),
                )
    except Exception:  # noqa: BLE001 - notifikasi tidak boleh menggagalkan task
        logger.exception("erp_sync.reconcile_stock: gagal mengirim alert WA.")


def format_reconciliation_alert(result: dict) -> str:
    """Susun pesan ringkas: ``Rekonsiliasi stok: N produk selisih.`` + Top 5."""
    data = dict(result or {})
    alert_count = int(data.get("alert_count") or 0)
    lines = [f"Rekonsiliasi stok: {alert_count} produk selisih."]

    alerts = list(data.get("alerts") or [])
    if alerts:
        lines.append("Top 5:")
        for alert in alerts:
            lines.append(
                "- {code}: MES={mes}, Odoo={odoo}, diff={diff}".format(
                    code=alert.get("product_code") or f"#{alert.get('product_odoo_id')}",
                    mes=_format_qty(alert.get("mes_qty")),
                    odoo=_format_qty(alert.get("odoo_qty")),
                    diff=_format_qty(alert.get("diff")),
                )
            )
    return "\n".join(lines)


def _format_qty(value) -> str:
    """Qty untuk pesan WA: ``10.0`` → ``10``, ``248.5`` → ``248.5`` (tanpa error)."""
    try:
        return f"{float(value or 0):g}"
    except (TypeError, ValueError):
        return str(value)
