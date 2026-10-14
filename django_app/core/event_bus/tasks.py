"""Task Celery event bus: dispatcher listener async.

Task ini sengaja tipis: ia hanya mengambil listener yang terdaftar di
`core.event_bus.registry` lalu memanggilnya. Listener asli (mis. sinkronisasi
Odoo, proyeksi dashboard) didaftarkan pada fase berikutnya lewat
`registry.register_listener(...)` — biasanya di `AppConfig.ready()`.
"""

from __future__ import annotations

import logging

from celery import shared_task

from . import registry

logger = logging.getLogger(__name__)


@shared_task(name="event_bus.dispatch_event")
def dispatch_event(event_name: str, payload: dict | None = None) -> dict:
    """Catat event ke log lalu jalankan semua listener async-nya.

    Mengembalikan ringkasan (`event_name`, jumlah listener, jumlah yang berhasil)
    supaya gampang di-assert di test / dilihat di result backend Celery.
    """
    event_payload = dict(payload or {})
    listeners = registry.get_listeners(event_name)

    logger.info(
        "event bus: '%s' diterima (listener async: %d) payload=%s",
        event_name,
        len(listeners),
        event_payload,
    )

    executed = 0
    for listener in listeners:
        try:
            listener(event_name=event_name, payload=event_payload)
        except Exception:  # noqa: BLE001 - satu listener gagal tidak mematikan sisanya
            logger.exception("listener %r gagal saat menangani event '%s'.", listener, event_name)
        else:
            executed += 1

    return {
        "event_name": event_name,
        "listeners": len(listeners),
        "executed": executed,
    }
