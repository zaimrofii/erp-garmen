"""Service **invoice** MES → Odoo (TX-INVOICE, Fase I5).

Berbeda dari :mod:`scrap_sync` (sumber ``ScrapAccumulator``), sumber di sini
adalah ``Order``: **satu order = satu invoice**.

Tiga langkah:

1. :meth:`InvoiceSyncService.enqueue` — daftarkan order ke antrean lewat
   ``SyncRecord(resource="order", resource_id=<order.pk>, stage="INVOICE",
   status=PENDING)``. Unique constraint ``(resource, resource_id, stage)``
   membuat enqueue **idempoten**: sesering apa pun WO order itu selesai, hanya
   ada **satu** baris invoice per order.
2. :meth:`InvoiceSyncService.sync_one` — kirim satu record lewat adapter
   (``push_customer_invoice_wo``); sukses → ``SENT`` (``erp_id`` = id
   ``account.move``), gagal → ``FAILED`` + ``last_error`` (record **tidak**
   dihapus, jadi bisa di-retry).
3. :meth:`InvoiceSyncService.sync_pending` — kirim semua record ``PENDING`` dan
   ``FAILED`` yang ``attempts < MAX_ATTEMPTS`` → counter
   ``{"sent", "failed", "skipped"}``.

Pemicu produksi: listener ``WORK_ORDER_STATE_CHANGED`` dengan ``state="DONE"``
yang didaftarkan di ``integrations/erp_sync/apps.py:ready()``.

Catatan desain:

* **Tidak ada model** ``InvoiceQueue``: antrean + idempotensi memakai
  ``SyncRecord`` (keputusan Fase I5).
* Odoo **tidak** dipanggil langsung — adapter dari :func:`get_adapter`.
* Repo belum menyimpan harga jual → adapter mengirim ``price_unit=0`` dan
  invoice dibiarkan **draft** supaya supervisor melengkapi harga di UI Odoo.
* ``enqueue`` terjadi saat WO **pertama** selesai ⇒ invoice mencerminkan kondisi
  order saat itu; order dengan banyak WO tetap **satu** invoice (lihat laporan).
"""

from __future__ import annotations

import logging

from django.db.models import Q

from apps_industry.garment.models import Order

from ..adapters.factory import get_adapter
from ..audit import ACTION_INVOICE, log_push
from ..idempotency import SyncIdempotency
from ..models import SyncRecord, SyncResource, SyncStage, SyncStatus

logger = logging.getLogger(__name__)

__all__ = ("InvoiceSyncService",)

#: Resource & stage TX-INVOICE (kunci idempotensi di ``SyncRecord``).
RESOURCE = SyncResource.ORDER
STAGE = SyncStage.INVOICE

#: Batas percobaan untuk record ``FAILED`` (sejalan ``max_retries=3`` Celery).
MAX_ATTEMPTS = 3


def _invoice_ref(order) -> str:
    """Ref deterministik invoice satu order: ``INV-<kode order>``."""
    return f"INV-{order.code}"


class InvoiceSyncService:
    """Antrean + pengiriman customer invoice per ``Order`` (idempotent)."""

    def __init__(self, adapter=None):
        """``adapter`` opsional (untuk test); ``None`` → :func:`get_adapter`."""
        self.adapter = adapter

    # ---------------------------------------------------------------- enqueue
    def enqueue(self, order) -> SyncRecord:
        """Daftarkan ``order`` ke antrean invoice (idempoten) → ``SyncRecord``.

        Record **lama** dipakai ulang kalau sudah ada (mis. WO kedua dari order
        yang sama selesai) — tidak akan ada invoice dobel per order.
        """
        if order is None or order.pk is None:
            raise ValueError("order wajib diisi dan sudah tersimpan.")

        record = SyncIdempotency().get_or_create_sync_record(
            RESOURCE,
            order.pk,
            STAGE,
            {"order_id": order.pk, "ref": _invoice_ref(order)},
        )
        logger.info(
            "invoice_sync: order %s di-enqueue (record=%s, status=%s).",
            order.code,
            record.pk,
            record.status,
        )
        return record

    def sync_one(self, sync_record) -> SyncRecord:
        """Kirim satu record invoice (idempotent) — **tidak** melempar.

        * sudah ``SENT``/``DUPLICATE`` → dilewati (adapter tidak dipanggil);
        * order tidak bisa di-resolve → ``FAILED``;
        * adapter mengembalikan gagal **atau** melempar → ``FAILED`` +
          ``last_error`` (record tetap ada, boleh di-retry).
        """
        sync = SyncIdempotency()

        if sync.is_already_sent(sync_record):
            logger.info(
                "invoice_sync: record %s sudah terkirim (status=%s) -> dilewati.",
                sync_record.pk,
                sync_record.status,
            )
            return sync_record

        order = self._resolve_order(sync_record)
        if order is None:
            error = f"Order {sync_record.resource_id} tidak ditemukan."
            record = sync.mark_failed(sync_record, error)
            log_push(  # I8.11 — gagal sebelum push (order tidak bisa di-resolve)
                ACTION_INVOICE,
                RESOURCE,
                sync_record.resource_id,
                status="failed",
                error=error,
            )
            return record

        wo = {"order_id": order.pk, "ref": _invoice_ref(order)}
        adapter = self.adapter if self.adapter is not None else get_adapter()
        try:
            logger.info(
                "invoice_sync: push %s lewat %s (record=%s).",
                wo["ref"],
                type(adapter).__name__,
                sync_record.pk,
            )
            response = adapter.push_customer_invoice_wo(wo)
        except Exception as exc:  # noqa: BLE001 - listener/task tidak boleh mati
            logger.exception("invoice_sync: adapter error untuk order %s.", order.code)
            error = f"Adapter error: {exc}"
            record = sync.mark_failed(sync_record, error)
            log_push(  # I8.11 — adapter melempar = percobaan kirim yang gagal
                ACTION_INVOICE,
                RESOURCE,
                sync_record.resource_id,
                status="failed",
                error=error,
                payload=wo,
            )
            return record
        finally:
            if self.adapter is None:  # tutup hanya kalau kita yang membangunnya
                adapter.close()

        if response.ok:
            record = sync.mark_sent(sync_record, response.erp_id)
            log_push(  # I8.11 — jejak audit percobaan kirim yang berhasil
                ACTION_INVOICE,
                RESOURCE,
                sync_record.resource_id,
                status="sent",
                erp_id=response.erp_id,
                payload=wo,
            )
            return record

        record = sync.mark_failed(sync_record, response.error)
        log_push(  # I8.11 — jejak audit percobaan kirim yang gagal
            ACTION_INVOICE,
            RESOURCE,
            sync_record.resource_id,
            status="failed",
            error=response.error,
            payload=wo,
        )
        return record

    def sync_pending(self) -> dict:
        """Kirim semua invoice yang belum beres (``PENDING`` + ``FAILED``).

        ``FAILED`` ikut dikirim ulang selama ``attempts < MAX_ATTEMPTS``. Satu
        record gagal **tidak** menghentikan sisanya.

        Return ``{"sent", "failed", "skipped"}``; ``skipped`` = record yang tidak
        masuk antrean (sudah ``SENT``/``DUPLICATE`` atau ``FAILED`` mentok).
        """
        pending = self._collect_pending()
        result = {"sent": 0, "failed": 0, "skipped": 0}

        for sync_record in pending:
            try:
                record = self.sync_one(sync_record)
            except Exception:  # noqa: BLE001 - satu record gagal != batch gagal
                logger.exception(
                    "invoice_sync: gagal memproses record %s.", sync_record.pk
                )
                result["failed"] += 1
                continue

            if record.status == SyncStatus.SENT:
                result["sent"] += 1
            else:
                result["failed"] += 1

        total = SyncRecord.objects.filter(resource=RESOURCE, stage=STAGE).count()
        result["skipped"] = max(total - pending.count(), 0)
        return result

    # ---------------------------------------------------------------- internal
    @staticmethod
    def _collect_pending():
        """Queryset record invoice yang perlu dikirim (urut ``id``, lazy)."""
        return (
            SyncRecord.objects.filter(resource=RESOURCE, stage=STAGE)
            .filter(
                Q(status=SyncStatus.PENDING)
                | Q(status=SyncStatus.FAILED, attempts__lt=MAX_ATTEMPTS)
            )
            .order_by("id")
        )

    @staticmethod
    def _resolve_order(sync_record):
        """``Order`` dari ``sync_record.resource_id`` (``None`` kalau tak ketemu).

        ``resource_id`` disimpan sebagai string, jadi divalidasi numerik dulu
        supaya tidak melempar ``ValueError`` di query.
        """
        resource_id = str(sync_record.resource_id or "")
        if not resource_id.isdigit():
            return None
        return (
            Order.objects.filter(pk=int(resource_id))
            .select_related("customer")
            .first()
        )
