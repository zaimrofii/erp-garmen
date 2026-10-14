"""Task Celery **push Stock Transfer** MES → Odoo (H2.6) — transaksi satu arah.

`StockTransfer` `DRAFT` murni MES; hanya saat `COMMITTED` transfer dikirim (service
`stock_transfer_services.commit_transfer`). Jalur Odoo 17 (probe STEP 0 + sumber
`stock/models/stock_picking.py`):

  1. `stock.picking` **create** dengan `picking_type_id` tipe internal, `location_id`
     (asal) & `location_dest_id` (tujuan) eksplisit + `move_ids` (baris move);
  2. **`button_validate()`** (method PUBLIK) — di dalamnya `action_confirm()` →
     auto-isi `move.quantity = product_uom_qty` → auto-`picked` → `_action_done()`;
     context `skip_backorder=True` supaya tidak ada wizard backorder;
  3. verifikasi `state == 'done'` → simpan `odoo_picking_id`/`odoo_picking_name`;
  4. gagal (mis. stok asal kurang) → state `FAILED` + `last_error` (retry 3× backoff
     hanya untuk error transport, bukan error data).

⚠️ `stock.move` + `_action_done()` langsung **tidak bisa** via RPC (`_action_done`
private) — itu sebabnya jalur picking dipakai. Tipe picking internal diambil dari
settings `ODOO_PICKING_TYPE_INTERNAL_ID` atau dicari `code='internal'` (tanpa hardcode).

Task **tidak** memanggil Odoo langsung: memakai adapter (`get_adapter()`), pola I4/I5/H2.5.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from celery import shared_task

from apps_industry.garment.models import StockTransfer
from config.middleware import clear_request_id

from .adapters.factory import get_adapter
from .audit import log_push
from .idempotency import SyncIdempotency
from .models import SyncRecord
from .tasks import _bind_request_id
from .tasks_master import RETRY_EXCEPTIONS

logger = logging.getLogger(__name__)

__all__ = (
    "ACTION_STOCK_TRANSFER_PUSH",
    "is_noop_mode",
    "push_stock_transfer",
    "transfer_values",
)

#: Action audit untuk push transfer.
ACTION_STOCK_TRANSFER_PUSH = "stock_transfer.push"


def is_noop_mode() -> bool:
    """True kalau ``ERP_ADAPTER`` bukan ``"odoo"`` (dev/test tanpa Odoo)."""
    from django.conf import settings

    return (getattr(settings, "ERP_ADAPTER", "") or "").strip().lower() != "odoo"


def transfer_values(transfer: StockTransfer) -> dict:
    """Payload MES untuk adapter — **delegasi** ke payload kanonik service.

    Bentuknya satu sumber (`services.transfer_push_payload`) supaya payload ledger
    yang di-arm saat `COMMITTED` **identik** dengan yang dipakai task (proteksi
    "push ganda payload sama" di `SyncIdempotency`).
    """
    from apps_industry.garment.services import stock_transfer_services as services

    return services.transfer_push_payload(transfer)


@shared_task(
    bind=True,
    name="erp_sync.push_stock_transfer",
    autoretry_for=RETRY_EXCEPTIONS,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=3,
)
def push_stock_transfer(self, transfer_id: int, sync_record_id: int | None = None):
    """Kirim satu transfer ke Odoo (picking internal + `button_validate`).

    Error **data/prasyarat** (wizard, state bukan done, stok kurang) → `FAILED` +
    `last_error` **tanpa** retry; error transport di-raise supaya Celery retry.
    """
    _bind_request_id(self)
    from apps_industry.garment.services import stock_transfer_services as services

    try:
        transfer = (
            StockTransfer.objects.select_related("product", "from_location", "to_location")
            .filter(pk=transfer_id)
            .first()
        )
        if transfer is None:
            logger.warning("erp_sync.push_stock_transfer: transfer %s tidak ada.", transfer_id)
            return {"status": "not-found", "transfer_id": transfer_id}

        payload = transfer_values(transfer)
        sync = SyncIdempotency()
        record = (
            SyncRecord.objects.filter(pk=sync_record_id).first()
            if sync_record_id is not None
            else None
        )
        if record is None:
            record = sync.get_or_create_sync_record(
                services.TRF_RESOURCE, transfer.pk, services.TRF_STAGE, payload
            )

        if sync.is_already_sent(record) and dict(record.payload or {}) == payload:
            logger.info(
                "erp_sync.push_stock_transfer: %s sudah terkirim & payload sama -> diabaikan.",
                transfer.code,
            )
            return {
                "status": "duplicate-ignored",
                "erp_id": record.erp_id,
                "sync_record_id": record.pk,
                "transfer_id": transfer.pk,
            }

        response_raw: dict = {}
        try:
            if is_noop_mode():
                erp_id = f"NULL-{uuid4()}"
                logger.info(
                    "erp_sync.push_stock_transfer: no-op (ERP_ADAPTER bukan odoo) %s -> %s.",
                    transfer.code,
                    erp_id,
                )
            else:
                response = get_adapter().push_stock_transfer_wo(payload)
                if not response.ok:
                    message = response.error or "push stock transfer gagal."
                    services.mark_failed(transfer, message)
                    log_push(
                        ACTION_STOCK_TRANSFER_PUSH,
                        services.TRF_RESOURCE,
                        transfer.pk,
                        status="failed",
                        error=message,
                        task_id=self.request.id,
                        payload=payload,
                    )
                    return {
                        "status": "failed",
                        "error": message,
                        "sync_record_id": record.pk,
                        "transfer_id": transfer.pk,
                    }

                erp_id = response.erp_id
                response_raw = dict(response.raw or {})
        except Exception as exc:  # noqa: BLE001 - dicatat dulu, lalu di-raise untuk retry
            sync.mark_failed(record, exc)
            log_push(
                ACTION_STOCK_TRANSFER_PUSH,
                services.TRF_RESOURCE,
                transfer.pk,
                status="failed",
                error=exc,
                task_id=self.request.id,
                payload=payload,
            )
            raise

        picking_id = response_raw.get("picking_id")
        services.mark_synced(
            transfer,
            erp_id=erp_id,
            odoo_picking_id=int(picking_id) if picking_id not in (None, "") else None,
            odoo_picking_name=str(response_raw.get("picking_name") or ""),
        )
        log_push(
            ACTION_STOCK_TRANSFER_PUSH,
            services.TRF_RESOURCE,
            transfer.pk,
            status="sent",
            erp_id=erp_id,
            task_id=self.request.id,
            payload={**payload, "odoo_picking_id": picking_id},
        )

        return {
            "status": "sent",
            "erp_id": erp_id,
            "sync_record_id": record.pk,
            "transfer_id": transfer.pk,
            "odoo_picking_id": picking_id,
        }
    finally:
        clear_request_id()
