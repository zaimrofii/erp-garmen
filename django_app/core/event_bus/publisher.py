"""Publisher event bus generik (satu-satunya pintu masuk pengiriman event).

`publish()` mengirim satu event ke **tiga** jalur sekaligus:

  1. **Sinkron** — Django Signal `Signal.send()` sehingga listener in-process
     (mis. update cache, validasi lanjutan) langsung jalan di request yang sama.
  2. **Async** — Celery task `event_bus.dispatch_event.delay()` sehingga listener
     berat (mis. sinkronisasi ERP, kirim WA) jalan di worker.
  3. **Real-time (Fase E)** — `core.event_bus.websocket.broadcast()` ke group
     Channels (`bundle.<id>`, `work_order.<id>`) supaya klien WebSocket menerima
     perubahan tanpa polling. Jalur ini **fail-safe**: tanpa CHANNEL_LAYERS/Redis
     hanya dicatat warning (lihat `broadcast()`).

Catatan: `payload` wajib JSON-serializable karena melewati Celery
(serializer JSON — lihat `CELERY_TASK_SERIALIZER` di settings), jadi jangan
mengirim objek model/ORM; kirim id + data primitif saja.
"""

from __future__ import annotations

import logging

from . import signals, websocket
from .tasks import dispatch_event

logger = logging.getLogger(__name__)

#: Nilai `sender` saat signal dikirim. Receiver boleh memfilter dengan ini:
#: `signals.bundle_state_changed.connect(receiver, sender=SENDER)`.
SENDER = "core.event_bus.publisher"


def publish(event_name: str, payload: dict | None = None) -> None:
    """Publikasikan satu event domain generik.

    Args:
        event_name: salah satu konstanta di `core.event_bus.signals`
            (mis. `signals.BUNDLE_STATE_CHANGED`).
        payload: data event (dict, JSON-serializable). `None` dianggap `{}`.

    Raises:
        ValueError: kalau `event_name` bukan string non-kosong.
    """
    if not isinstance(event_name, str) or not event_name:
        raise ValueError("event_name harus string non-kosong.")

    event_payload = dict(payload or {})

    # Jalur real-time (Fase E) — selalu dicoba, terlepas dari ada/tidaknya Django
    # Signal: klien WebSocket hanya butuh nama event + payload (+ `event` chatter).
    websocket.broadcast(event_name, event_payload)

    django_signal = signals.get_signal(event_name)
    if django_signal is None:
        logger.warning(
            "event '%s' belum punya Django Signal terdaftar; "
            "hanya listener async yang dijalankan.",
            event_name,
        )
    else:
        responses = django_signal.send(
            sender=SENDER,
            event_name=event_name,
            payload=event_payload,
        )
        logger.debug(
            "event '%s' dikirim ke %d listener sinkron.",
            event_name,
            len(responses),
        )

        # Jalur async: listener yang terdaftar di registry dijalankan di worker.
        dispatch_event.delay(event_name, event_payload)
    logger.debug("event '%s' di-enqueue ke Celery 'event_bus.dispatch_event'.", event_name)
