"""Registry listener **async** per nama event (in-memory, load saat app ready).

Registry ini bukan pengganti Django Signal: signal dipakai untuk listener
sinkron (in-process), registry dipakai Celery task `event_bus.dispatch_event`
untuk listener yang boleh/ harus jalan di worker.

Fase 1.1 masih in-memory (didaftarkan dari `AppConfig.ready()` app masing-masing
atau dari test). Kalau nanti butuh persistensi, cukup ganti isi modul ini tanpa
mengubah pemanggilnya.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)

#: Tipe listener async: dipanggil dengan `event_name=...` & `payload=...`.
Listener = Callable[..., object]

# event_name -> daftar listener (urutan pendaftaran dipakai saat dispatch)
_listeners: dict[str, list[Listener]] = {}


def register_listener(event_name: str, listener: Listener) -> Listener:
    """Daftarkan listener async untuk `event_name`.

    Mengembalikan `listener` sehingga aman dipakai sebagai decorator::

        @register_listener(signals.BUNDLE_STATE_CHANGED)
        def on_bundle_state_changed(*, event_name, payload):
            ...
    """
    listeners = _listeners.setdefault(event_name, [])
    if listener not in listeners:
        listeners.append(listener)
        logger.debug("listener %r terdaftar untuk event '%s'.", listener, event_name)
    return listener


def get_listeners(event_name: str) -> tuple[Listener, ...]:
    """Salinan daftar listener untuk `event_name` (aman dari mutasi tak sengaja)."""
    return tuple(_listeners.get(event_name, ()))


def clear_listeners(event_name: str | None = None) -> None:
    """Hapus listener: satu event (kalau `event_name` diisi) atau semua (test)."""
    if event_name is None:
        _listeners.clear()
    else:
        _listeners.pop(event_name, None)
