"""Definisi Django Signal untuk event domain generik (core engine).

Signal di sini **generik** — tidak tahu menahu soal garmen. App domain
(mis. `apps_industry.garment` di Fase 2) mengirim event lewat
`core.event_bus.publisher.publish()`, sedangkan listener (sinkron maupun async)
mendaftar di tempat lain:

  * listener sinkron  -> `signal.connect(receiver)` (Django receiver biasa);
  * listener async    -> `core.event_bus.registry.register_listener(...)`.

Semua nama di bawah adalah instance `django.dispatch.Signal` (bukan fungsi),
dikirim dengan `signal.send(sender=..., event_name=..., payload=...)`.
"""

from __future__ import annotations

from django.dispatch import Signal

#: Nama event (string) — dipakai publisher, registry, dan Celery task.
BUNDLE_STATE_CHANGED = "BUNDLE_STATE_CHANGED"
WORK_ORDER_STATE_CHANGED = "WORK_ORDER_STATE_CHANGED"
SCRAP_RECORDED = "SCRAP_RECORDED"
ERP_SYNC_COMPLETED = "ERP_SYNC_COMPLETED"

# Signal sinkron: dipakai `core.event_bus.publisher.publish()`.
bundle_state_changed = Signal()
work_order_state_changed = Signal()
scrap_recorded = Signal()
erp_sync_completed = Signal()

#: Peta nama event -> Signal, supaya pemanggil cukup menyebut nama event.
SIGNALS: dict[str, Signal] = {
    BUNDLE_STATE_CHANGED: bundle_state_changed,
    WORK_ORDER_STATE_CHANGED: work_order_state_changed,
    SCRAP_RECORDED: scrap_recorded,
    ERP_SYNC_COMPLETED: erp_sync_completed,
}


def get_signal(event_name: str) -> Signal | None:
    """Ambil objek Signal dari nama event (`None` kalau event belum terdaftar)."""
    return SIGNALS.get(event_name)
