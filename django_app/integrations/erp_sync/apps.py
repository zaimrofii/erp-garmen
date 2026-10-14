from django.apps import AppConfig

import logging

logger = logging.getLogger(__name__)

#: State ``WorkOrder`` yang dianggap **selesai** untuk pemicu invoice.
#: ``CANCELLED`` ikut: WO batal tidak akan pernah ``DONE``, jadi tidak boleh
#: memblokir invoice order (utang teknis I8.2).
WO_STATES_SELESAI = ("DONE", "CANCELLED")


def _on_work_order_state_changed(*, event_name, payload):  # noqa: ARG001
    """Listener async: WO selesai (``state == "DONE"``) → enqueue invoice order.

    Dipanggil ``core.event_bus.tasks.dispatch_event`` dengan
    ``event_name=...`` & ``payload=...`` (kontrak di ``core/event_bus/registry.py``
    dan ``core/event_bus/tasks.py``).

    * payload ``WORK_ORDER_STATE_CHANGED`` = ``{"wo_id", "wo_code", "action",
      "state", "version"}`` (lihat ``garment/services/action_events.py``) →
      ``wo_id`` di-resolve ke ``WorkOrder`` → ``order_line.order``;
    * hanya ``state == "DONE"`` yang memicu aksi (``IN_PROGRESS``/``CANCELLED``
      tidak) — jadi WO yang baru saja dibatalkan **tidak** memicu invoice;
    * invoice di-enqueue hanya setelah **SEMUA** ``WorkOrder`` order itu
      **selesai** = ``DONE`` **atau** ``CANCELLED`` (``WO_STATES_SELESAI``);
      kalau masih ada WO lain yang belum selesai, listener berhenti (log info);
    * ``enqueue`` sendiri tetap idempoten (``SyncRecord`` unique per
      ``(order, stage)``) sebagai jaring kedua supaya invoice tidak dobel;
    * **semua exception ditelan** (cukup di-log) — listener tidak boleh
      membatalkan event bus / aksi produksi yang sudah tersimpan.

    Import di dalam fungsi supaya ``apps.py`` tetap aman di-import saat app
    loading (model & servis belum siap kalau diimpor di level modul).
    """
    try:
        data = dict(payload or {})
        if str(data.get("state") or "") != "DONE":
            return

        from apps_industry.garment.models import WorkOrder

        from .services import InvoiceSyncService

        work_order = (
            WorkOrder.objects.filter(pk=data.get("wo_id"))
            .select_related("order_line__order")
            .first()
        )
        if work_order is None:
            logger.warning(
                "erp_sync: WORK_ORDER_STATE_CHANGED wo_id=%s tidak ditemukan.",
                data.get("wo_id"),
            )
            return

        order = work_order.order_line.order

        # Invoice hanya dibuat setelah SEMUA WorkOrder order ini SELESAI.
        # "Selesai" = DONE **atau** CANCELLED (lihat WO_STATES_SELESAI): WO yang
        # dibatalkan tidak akan pernah diproduksi, jadi tidak boleh memblokir
        # invoice order ini (dulu `exclude(state="DONE")` membuat order ber-WO
        # CANCELLED tidak pernah dapat invoice — utang teknis I8.2).
        # (Event dikirim SETELAH state WO tersimpan, jadi WO pemicu sudah DONE
        #  saat baris ini dieksekusi — lihat `api/actions/executor.py`.)
        masih_ada_wo_belum_selesai = (
            WorkOrder.objects.filter(order_line__order=order)
            .exclude(state__in=WO_STATES_SELESAI)
            .exists()
        )
        if masih_ada_wo_belum_selesai:
            logger.info(
                "erp_sync: WO %s DONE, tapi masih ada WorkOrder lain order %s "
                "yang belum selesai (DONE/CANCELLED) -> invoice belum di-enqueue.",
                work_order.code,
                order.code,
            )
            return

        record = InvoiceSyncService().enqueue(order)
        logger.info(
            "erp_sync: semua WO order %s DONE -> invoice di-enqueue (WO %s, record=%s).",
            order.code,
            work_order.code,
            record.pk,
        )
    except Exception:  # noqa: BLE001 - listener tidak boleh mengganggu event bus
        logger.exception("erp_sync: gagal enqueue invoice dari event WO DONE.")


class ErpSyncConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations.erp_sync"
    verbose_name = "ERP Sync"

    def ready(self):
        """Import modul task & daftarkan listener event bus.

        ``config/celery.py`` memakai ``app.autodiscover_tasks()`` yang hanya
        mencari modul bernama ``tasks`` di tiap app; task master, SO, recompute
        readiness (di ``tasks_vendor_bill.py``), scrap, invoice, dan rekonsiliasi
        stok sengaja dipisah (``tasks_master.py``, ``tasks_order.py``,
        ``tasks_scrap.py``, ``tasks_invoice.py``, ``tasks_vendor_bill.py``,
        ``tasks_reconciliation.py``) supaya rapi, jadi modulnya
        harus di-import eksplisit agar ``@shared_task`` ter-registrasi di worker
        (kalau tidak → "Received unregistered task").

        Listener invoice (Fase I5) didaftarkan di sini: listener async dijalankan
        worker lewat task ``event_bus.dispatch_event`` (lihat
        ``core/event_bus/registry.py``).
        """
        from . import (  # noqa: F401
            tasks_invoice,
            tasks_master,
            tasks_order,
            tasks_reconciliation,
            tasks_scrap,
            tasks_vendor_bill,
        )

        from core.event_bus.registry import register_listener
        from core.event_bus.signals import WORK_ORDER_STATE_CHANGED

        register_listener(WORK_ORDER_STATE_CHANGED, _on_work_order_state_changed)
