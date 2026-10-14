"""Service sync **scrap** MES → Odoo (TX-SCRAP) — fase I4.

``ScrapAccumulator`` mencatat scrap/rework/end-loss per ``(work_center, bundle)``.
Service ini mengambil baris yang **belum terkirim**, menyiapkan payload
``push_scrap_wo`` (lihat ``docs/integrations/CONTRACT.md`` §TX-SCRAP), lalu
mengirimnya lewat **adapter** (``get_adapter()``) — bukan Odoo langsung.

Idempotensi (di **service**, bukan di adapter):

* satu ``SyncRecord`` per ``(resource="scrap_accumulator", resource_id=<pk>,
  stage="SCRAP")`` — unique constraint DB; retry meng-update baris yang sama,
  bukan membuat kiriman baru (stok tidak dobel);
* record ``SENT``/``DUPLICATE`` dilewati (``SyncIdempotency.is_already_sent``);
* gagal → ``FAILED`` + ``attempts`` + ``last_error`` (masih boleh di-retry).

Catatan desain (yang disengaja):

* ``ref`` deterministik: ``SCRAP-<accumulator_id>-<period_date>``;
* ``ScrapAccumulator`` **tidak punya kolom periode** (model tidak boleh
  diubah) → ``period_date`` hanya menjadi **label** ref/log, **bukan** filter
  tanggal; yang menentukan "pending" adalah status ``SyncRecord``;
* ``product_id`` = ``Product.odoo_id`` dari
  ``accumulator.bundle.work_order.order_line.product`` — **catatan**: ``Bundle``
  TIDAK punya field ``product`` (rantai yang benar lewat ``work_order`` →
  ``order_line``); salah satu mata rantai boleh kosong → baris di-``FAILED``
  dengan pesan jelas;
* ``uom_id`` dari setting ``ODOO_UOM_ID`` — ``master.Product`` tidak punya
  kolom UoM, sedangkan ``stock.scrap.product_uom_id`` wajib; kalau setting
  kosong → ``FAILED`` (bukan kirim payload setengah jadi);
* ``qty == 0`` tidak pernah dikirim.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.utils import timezone

from apps_industry.garment.models import ScrapAccumulator

from ..adapters.factory import get_adapter
from ..audit import ACTION_SCRAP, log_push
from ..idempotency import SyncIdempotency
from ..models import SyncRecord, SyncResource, SyncStage, SyncStatus

logger = logging.getLogger(__name__)

__all__ = ("ScrapSyncService",)

#: Resource & stage TX-SCRAP (kunci idempotensi di SyncRecord).
RESOURCE = SyncResource.SCRAP_ACCUMULATOR
STAGE = SyncStage.SCRAP


def _period_label(period_date=None) -> str:
    """Label periode untuk ``ref`` (default: tanggal hari ini, zona Django)."""
    return str(period_date or timezone.localdate())


class ScrapSyncService:
    """Agregasi ``ScrapAccumulator`` → payload TX-SCRAP → adapter (idempotent)."""

    def __init__(self, adapter=None):
        """``adapter`` opsional (untuk test); ``None`` → :func:`get_adapter`."""
        self.adapter = adapter

    # ---------------------------------------------------------------- collect
    def collect_pending(self, period_date=None):
        """``ScrapAccumulator`` yang masih perlu dikirim (``qty > 0``).

        Yang dilewati: baris dengan ``qty == 0`` dan baris yang ``SyncRecord``
        ``SCRAP``-nya sudah ``SENT``/``DUPLICATE`` (idempotensi). Kembalian
        berupa queryset (lazy) urut ``pk`` supaya hasil batch deterministik.

        ``period_date`` hanya dipakai sebagai label ref/audit — lihat docstring
        modul (model tidak punya kolom periode).
        """
        sent_ids = {
            int(value)
            for value in SyncRecord.objects.filter(
                resource=RESOURCE,
                stage=STAGE,
                status__in=(SyncStatus.SENT, SyncStatus.DUPLICATE),
            ).values_list("resource_id", flat=True)
            if str(value).isdigit()
        }
        return (
            ScrapAccumulator.objects.filter(qty__gt=0)
            .exclude(pk__in=sent_ids)
            .select_related("bundle__work_order__order_line__product")
            .order_by("pk")
        )

    # ------------------------------------------------------------------- push
    def sync_one(self, accumulator, period_date=None) -> SyncRecord:
        """Kirim satu ``ScrapAccumulator`` (idempotent) → ``SyncRecord``.

        **Tidak melempar** kalau data tidak lengkap atau adapter menolak: hasilnya
        disimpan di ``SyncRecord`` (``SENT``/``FAILED``) supaya batch bisa lanjut.
        ``period_date`` opsional — hanya untuk label ``ref`` (lihat docstring modul).
        """
        sync = SyncIdempotency()
        wo, error = self._build_wo(accumulator, period_date)
        record = sync.get_or_create_sync_record(RESOURCE, accumulator.pk, STAGE, wo)

        if sync.is_already_sent(record):
            logger.info(
                "scrap_sync: ScrapAccumulator %s sudah terkirim (status=%s) -> dilewati.",
                accumulator.pk,
                record.status,
            )
            return record

        if error:
            logger.warning(
                "scrap_sync: ScrapAccumulator %s tidak bisa dikirim: %s",
                accumulator.pk,
                error,
            )
            record = sync.mark_failed(record, error)
            log_push(  # I8.11 — payload tidak lengkap = percobaan kirim yang gagal
                ACTION_SCRAP,
                RESOURCE,
                accumulator.pk,
                status="failed",
                error=error,
                payload=wo,
            )
            return record

        adapter = self.adapter if self.adapter is not None else get_adapter()
        try:
            logger.info(
                "scrap_sync: push SCRAP %s lewat %s (record=%s).",
                wo["ref"],
                type(adapter).__name__,
                record.pk,
            )
            response = adapter.push_scrap_wo(wo)
        finally:
            if self.adapter is None:  # tutup hanya kalau kita yang membangunnya
                adapter.close()

        if response.ok:
            record = sync.mark_sent(record, response.erp_id)
            log_push(  # I8.11 — jejak audit percobaan kirim yang berhasil
                ACTION_SCRAP,
                RESOURCE,
                accumulator.pk,
                status="sent",
                erp_id=response.erp_id,
                payload=wo,
            )
            return record

        record = sync.mark_failed(record, response.error)
        log_push(  # I8.11 — jejak audit percobaan kirim yang gagal
            ACTION_SCRAP,
            RESOURCE,
            accumulator.pk,
            status="failed",
            error=response.error,
            payload=wo,
        )
        return record

    def sync_batch(self, period_date=None) -> dict:
        """Kirim semua yang pending; satu item gagal tidak menghentikan batch.

        Return ``{"sent", "failed", "skipped"}``. ``skipped`` = baris yang tidak
        masuk antrean: sudah ``SENT``/``DUPLICATE`` (idempotensi) atau ``qty == 0``.
        """
        pending = self.collect_pending(period_date)
        result = {"sent": 0, "failed": 0, "skipped": 0}

        for accumulator in pending:
            try:
                record = self.sync_one(accumulator, period_date=period_date)
            except Exception:  # noqa: BLE001 - satu baris gagal != batch gagal
                logger.exception(
                    "scrap_sync: gagal memproses ScrapAccumulator %s.", accumulator.pk
                )
                result["failed"] += 1
                continue

            if record.status == SyncStatus.SENT:
                result["sent"] += 1
            else:
                result["failed"] += 1

        result["skipped"] = max(ScrapAccumulator.objects.count() - pending.count(), 0)
        return result

    # ---------------------------------------------------------------- internal
    @staticmethod
    def _build_wo(accumulator, period_date=None):
        """Payload ``push_scrap_wo`` + pesan error (``None`` kalau payload siap)."""
        ref = f"SCRAP-{accumulator.pk}-{_period_label(period_date)}"
        wo = {"qty": accumulator.qty, "ref": ref}

        bundle = accumulator.bundle
        work_order = bundle.work_order if bundle is not None else None
        order_line = work_order.order_line if work_order is not None else None
        product = order_line.product if order_line is not None else None
        if product is None:
            return wo, (
                f"ScrapAccumulator {accumulator.pk} tanpa bundle/work_order/"
                "order_line/product -> product_id tidak bisa di-resolve."
            )
        if not product.odoo_id:
            return wo, f"Product {product.code} belum punya odoo_id (sync master dulu)."

        uom_id = getattr(settings, "ODOO_UOM_ID", None)
        if not uom_id:
            return wo, (
                "UoM default belum dikonfigurasi (ODOO_UOM_ID) — "
                "stock.scrap.product_uom_id wajib."
            )

        wo["product_id"] = product.pk
        wo["uom_id"] = int(uom_id)
        return wo, None
