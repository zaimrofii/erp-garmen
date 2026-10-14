"""Task Celery **push Inventory Adjustment** MES → Odoo (H2.5) — transaksi satu arah.

`InventoryAdjustment` `DRAFT` murni MES; hanya saat `COMMITTED` adjustment dikirim
(service `inventory_adjustment_services.commit_adjustment`). Jalur Odoo 17
(probe STEP 0 + sumber `stock/models/stock_quant.py` & `wizard/stock_change_product_qty.py`):

  1. **baca on-hand** `stock.quant.quantity` untuk (product, location);
  2. hitung **target absolut** = on-hand + `qty_delta` (MES menyimpan delta, Odoo
     memakai nilai absolut — itu sebabnya pembacaan dilakukan tepat sebelum apply);
  3. tulis `inventory_quantity` pada quant dengan context **`inventory_mode=True`**;
  4. panggil **`action_apply_inventory()`** (method PUBLIK; di dalamnya Odoo membuat
     `stock.move` dari/ke `product.property_stock_inventory` lalu `_action_done()`),
     dengan context **`inventory_name`** = `<kode MES> <reason>` supaya jejaknya
     bisa dicari kembali (`odoo_move_id`);
  5. simpan hasil: `SYNCED` + `odoo_move_id` + `qty_after`, atau `FAILED` + `last_error`.

⚠️ **Prerequisite**: user API Odoo harus punya `stock.group_stock_manager`
(`_apply_inventory()` melempar `UserError` tanpa grup itu) — lihat
`docs/integrations/CONTRACT.md` §TX-INVENTORY-ADJUST.

Task **tidak** memanggil Odoo langsung: ia memakai adapter (`get_adapter()`) seperti
task I4/I5 (`push_scrap_wo`, `push_customer_invoice_wo`).
"""

from __future__ import annotations

import logging
from uuid import uuid4

from celery import shared_task

from apps_industry.garment.models import InventoryAdjustment
from config.middleware import clear_request_id

from .adapters.factory import get_adapter
from .audit import log_push
from .idempotency import SyncIdempotency
from .models import SyncRecord
from .tasks import _bind_request_id
from .tasks_master import RETRY_EXCEPTIONS

logger = logging.getLogger(__name__)

__all__ = (
    "ACTION_INVENTORY_ADJUST_PUSH",
    "GROUP_REQUIRED_HINT",
    "adjustment_values",
    "is_noop_mode",
    "push_inventory_adjustment",
)

#: Action audit untuk push adjustment.
ACTION_INVENTORY_ADJUST_PUSH = "inventory_adjustment.push"

#: Petunjuk operasional kalau Odoo menolak karena grup (dikirim ke `last_error`).
GROUP_REQUIRED_HINT = (
    "Odoo UserError: user API tidak punya stock.group_stock_manager. "
    "Hubungi admin Odoo untuk set grup Inventory/Manager."
)


def is_noop_mode() -> bool:
    """True kalau ``ERP_ADAPTER`` bukan ``"odoo"`` (dev/test tanpa Odoo)."""
    from django.conf import settings

    return (getattr(settings, "ERP_ADAPTER", "") or "").strip().lower() != "odoo"


def adjustment_values(adj: InventoryAdjustment) -> dict:
    """Payload MES untuk adapter — **delegasi** ke payload kanonik service.

    Bentuknya satu sumber (`services.adjustment_push_payload`) supaya payload ledger
    yang di-arm saat `COMMITTED` **identik** dengan yang dipakai task (proteksi
    \"push ganda payload sama\" di `SyncIdempotency`).
    """
    from apps_industry.garment.services import inventory_adjustment_services as services

    return services.adjustment_push_payload(adj)


@shared_task(
    bind=True,
    name="erp_sync.push_inventory_adjustment",
    autoretry_for=RETRY_EXCEPTIONS,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=3,
)
def push_inventory_adjustment(self, adjustment_id: int, sync_record_id: int | None = None):
    """Kirim satu adjustment ke Odoo; state MES diperbarui lewat service.

    Error **data/prasyarat** (tanpa `odoo_id`, tracking lot/serial, UserError grup)
    dicatat ke `FAILED` lalu **tidak** di-retry; error transport di-raise supaya
    Celery retry (3× backoff).
    """
    _bind_request_id(self)
    from apps_industry.garment.services import inventory_adjustment_services as services

    try:
        adj = (
            InventoryAdjustment.objects.select_related("product", "location")
            .filter(pk=adjustment_id)
            .first()
        )
        if adj is None:
            logger.warning(
                "erp_sync.push_inventory_adjustment: adjustment %s tidak ada.", adjustment_id
            )
            return {"status": "not-found", "adjustment_id": adjustment_id}

        payload = adjustment_values(adj)
        sync = SyncIdempotency()
        record = (
            SyncRecord.objects.filter(pk=sync_record_id).first()
            if sync_record_id is not None
            else None
        )
        if record is None:
            record = sync.get_or_create_sync_record(
                services.ADJ_RESOURCE, adj.pk, services.ADJ_STAGE, payload
            )

        if sync.is_already_sent(record) and dict(record.payload or {}) == payload:
            logger.info(
                "erp_sync.push_inventory_adjustment: %s sudah terkirim & payload sama -> diabaikan.",
                adj.code,
            )
            return {
                "status": "duplicate-ignored",
                "erp_id": record.erp_id,
                "sync_record_id": record.pk,
                "adjustment_id": adj.pk,
            }

        response_raw: dict = {}
        try:
            if is_noop_mode():
                erp_id = f"NULL-{uuid4()}"
                logger.info(
                    "erp_sync.push_inventory_adjustment: no-op (ERP_ADAPTER bukan odoo) %s -> %s.",
                    adj.code,
                    erp_id,
                )
            else:
                response = get_adapter().push_inventory_adjustment(payload)
                if not response.ok:
                    message = response.error or "push inventory adjustment gagal."
                    if "group_stock_manager" in message or "stock manager" in message.lower():
                        message = GROUP_REQUIRED_HINT

                    services.mark_failed(adj, message)
                    log_push(
                        ACTION_INVENTORY_ADJUST_PUSH,
                        services.ADJ_RESOURCE,
                        adj.pk,
                        status="failed",
                        error=message,
                        task_id=self.request.id,
                        payload=payload,
                    )
                    return {
                        "status": "failed",
                        "error": message,
                        "sync_record_id": record.pk,
                        "adjustment_id": adj.pk,
                    }

                erp_id = response.erp_id
                response_raw = dict(response.raw or {})
        except Exception as exc:  # noqa: BLE001 - dicatat dulu, lalu di-raise untuk retry
            sync.mark_failed(record, exc)
            log_push(
                ACTION_INVENTORY_ADJUST_PUSH,
                services.ADJ_RESOURCE,
                adj.pk,
                status="failed",
                error=exc,
                task_id=self.request.id,
                payload=payload,
            )
            raise

        move_id = response_raw.get("move_id")
        services.mark_synced(
            adj,
            erp_id=erp_id,
            odoo_move_id=int(move_id) if move_id not in (None, "") else None,
            qty_after=response_raw.get("target"),
        )
        log_push(
            ACTION_INVENTORY_ADJUST_PUSH,
            services.ADJ_RESOURCE,
            adj.pk,
            status="sent",
            erp_id=erp_id,
            task_id=self.request.id,
            payload={**payload, "odoo_move_id": move_id},
        )

        return {
            "status": "sent",
            "erp_id": erp_id,
            "sync_record_id": record.pk,
            "adjustment_id": adj.pk,
            "odoo_move_id": move_id,
        }
    finally:
        clear_request_id()
