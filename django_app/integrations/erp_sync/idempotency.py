"""Idempotency two-stage sync — `SyncRecord` sebagai buku besar pengiriman.

Aturan:

* satu kombinasi ``(resource, resource_id, stage)`` hanya punya **satu** baris.
  Retry meng-*update* baris itu (``attempts`` naik), bukan membuat kiriman baru
  → tidak ada stok dobel di ERP walau request diulang;
* ``status = SENT`` atau ``DUPLICATE`` berarti ERP sudah pernah menerima
  pergerakan ini, jadi ``is_already_sent()`` True dan task sync boleh berhenti;
* kegagalan **tidak** menghapus baris: status ``FAILED`` + ``attempts`` +
  ``last_error`` disimpan supaya Celery bisa retry dengan backoff dan
  supervisor bisa melihat riwayatnya (Sprint 4.2).

Stage yang valid: ``WIP`` (issue bahan), ``FG`` (receipt barang jadi),
``SCRAP`` (TX-SCRAP, barang rusak/afval), dan ``INVOICE`` (Fase I5: invoice
penjualan untuk satu ``Order``).
"""

from __future__ import annotations

import logging
from typing import Any

from django.db import transaction
from django.utils import timezone

from .adapters.base import STAGE_FG, STAGE_WIP
from .adapters.odoo import STAGE_INVOICE, STAGE_SCRAP
from .models import (
    STAGE_BUNDLE_PUSH,
    STAGE_INVENTORY_ADJUST,
    STAGE_MASTER_PULL,
    STAGE_MASTER_PUSH,
    STAGE_PURCHASE_ORDER_PUSH,
    STAGE_SALE_ORDER_PUSH,
    STAGE_STOCK_TRANSFER,
    STAGE_VENDOR_BILL,
    STAGE_PAYMENT,
    STAGE_JOURNAL_ENTRY,
    STAGE_WORK_ORDER_PUSH,
    SyncRecord,
    SyncStatus,
)

logger = logging.getLogger(__name__)

__all__ = (
    "STAGE_BUNDLE_PUSH",
    "STAGE_FG",
    "STAGE_INVENTORY_ADJUST",
    "STAGE_INVOICE",
    "STAGE_MASTER_PULL",
    "STAGE_MASTER_PUSH",
    "STAGE_PURCHASE_ORDER_PUSH",
    "STAGE_SALE_ORDER_PUSH",
    "STAGE_SCRAP",
    "STAGE_STOCK_TRANSFER",
    "STAGE_VENDOR_BILL",
    "STAGE_PAYMENT",
    "STAGE_JOURNAL_ENTRY",
    "STAGE_WIP",
    "STAGE_WORK_ORDER_PUSH",
    "SyncIdempotency",
    "VALID_STAGES",
)

#: Stage yang dikenal: two-stage sync (WIP/FG) + scrap + invoice + master
#: (push/pull) + Sales Order (H2.1) + Purchase Order (H2.2) + Work Order MES-only
#: (H2.3) + Bundle MES-only (H2.4) + Inventory Adjustment (H2.5) + Stock Transfer
#: (H2.6) + Vendor Bill (H3.2 — `in_invoice`, stage BARU di samping `INVOICE`) +
#: Payment (H3.3 — `account.payment` draft) + Journal Entry (H3.4 — `account.move`
#: `move_type='entry'` draft, stage BARU).
VALID_STAGES = (
    STAGE_WIP,
    STAGE_FG,
    STAGE_SCRAP,
    STAGE_INVOICE,
    STAGE_MASTER_PUSH,
    STAGE_MASTER_PULL,
    STAGE_SALE_ORDER_PUSH,
    STAGE_PURCHASE_ORDER_PUSH,
    STAGE_WORK_ORDER_PUSH,
    STAGE_BUNDLE_PUSH,
    STAGE_INVENTORY_ADJUST,
    STAGE_STOCK_TRANSFER,
    STAGE_VENDOR_BILL,
    STAGE_PAYMENT,
    STAGE_JOURNAL_ENTRY,
)

#: Field yang di-update tiap perubahan status (selalu sertakan `updated_at`).
_STATUS_FIELDS = ("status", "updated_at")


class SyncIdempotency:
    """Akses ``SyncRecord`` (stateless; seluruh state ada di DB)."""

    # ------------------------------------------------------------------ write
    def get_or_create_sync_record(
        self,
        resource: str,
        resource_id: Any,
        stage: str,
        payload: dict,
    ) -> SyncRecord:
        """Ambil record sync untuk (resource, id, stage); buat kalau belum ada.

        Payload hanya dipakai saat baris **dibuat** — kalau baris sudah ada
        (mis. retry), payload lama dipertahankan supaya jejak audit tidak
        tertimpa data yang lebih baru.
        """
        self._validate_stage(stage)
        resource = str(resource)
        resource_id = str(resource_id)

        with transaction.atomic():
            record, created = SyncRecord.objects.get_or_create(
                resource=resource,
                resource_id=resource_id,
                stage=str(stage),
                defaults={
                    "payload": dict(payload or {}),
                    "status": SyncStatus.PENDING,
                },
            )

        if created:
            logger.info("sync: record baru %s#%s:%s dibuat.", resource, resource_id, stage)
        else:
            logger.info(
                "sync: record %s#%s:%s sudah ada (status=%s, attempts=%s) -> dipakai ulang.",
                resource,
                resource_id,
                stage,
                record.status,
                record.attempts,
            )
        return record

    def mark_sent(self, record: SyncRecord, erp_id: Any) -> SyncRecord:
        """Tandai record sukses dikirim ke ERP (simpan erp_id + waktu kirim)."""
        record.status = SyncStatus.SENT
        record.erp_id = None if erp_id is None else str(erp_id)
        record.sent_at = timezone.now()
        record.last_error = ""
        record.save(update_fields=("status", "erp_id", "sent_at", "last_error", "updated_at"))
        logger.info(
            "sync: %s terkirim ke ERP (erp_id=%s).", record, record.erp_id
        )
        return record

    def mark_failed(self, record: SyncRecord, error: Any) -> SyncRecord:
        """Tandai record gagal; ``attempts`` naik dan error terakhir disimpan."""
        record.status = SyncStatus.FAILED
        record.attempts = int(record.attempts or 0) + 1
        record.last_error = str(error)
        record.save(update_fields=("status", "attempts", "last_error", "updated_at"))
        logger.warning(
            "sync: %s gagal (attempts=%s): %s", record, record.attempts, record.last_error
        )
        return record

    def mark_duplicate(self, record: SyncRecord) -> SyncRecord:
        """Tandai record sebagai duplikat (ERP bilang pergerakan sudah ada)."""
        record.status = SyncStatus.DUPLICATE
        record.save(update_fields=_STATUS_FIELDS)
        logger.info("sync: %s ditandai DUPLICATE (sudah ada di ERP).", record)
        return record

    def mark_skipped(self, record: SyncRecord, reason: str = "") -> SyncRecord:
        """Tandai record **tidak perlu dikirim** ke ERP (resource MES-only).

        Dipakai H1.7 untuk `master.work_center`: `mrp.workcenter` Odoo mewajibkan
        `resource_id` (bukan konsep MES) sehingga push akan mengarang data. Ledger
        tetap ditulis (aturan "setiap CUD master → SyncRecord") dan `last_error`
        diisi alasan supaya monitor sync bisa menjelaskan kenapa statusnya SKIPPED.
        """
        record.status = SyncStatus.SKIPPED
        record.last_error = str(reason or "")
        record.save(update_fields=("status", "last_error", "updated_at"))
        logger.info("sync: %s ditandai SKIPPED (MES-only): %s", record, record.last_error)
        return record

    # ------------------------------------------------------------------- read
    def is_already_sent(self, record: SyncRecord) -> bool:
        """True kalau ERP sudah menerima pergerakan ini (SENT atau DUPLICATE)."""
        if record is None:
            return False
        return record.status in (SyncStatus.SENT, SyncStatus.DUPLICATE)

    # --------------------------------------------------------------- internal
    @staticmethod
    def _validate_stage(stage: str) -> None:
        """Stage harus WIP, FG, SCRAP, atau INVOICE (fail-fast daripada stage ngawur)."""
        if str(stage) not in VALID_STAGES:
            raise ValueError(
                f"Stage sync tidak dikenal: {stage!r}. Pilihan: {', '.join(VALID_STAGES)}."
            )
