"""Konfigurasi pytest lintas-test (PRA-0A.4).

Isolasi **registry listener event bus** antar file test
-------------------------------------------------------
`core/event_bus/tests/test_event_bus.py` memanggil
`core.event_bus.registry.clear_listeners()` untuk menguji registry kosong.
Listener produksi didaftarkan **sekali** saat `AppConfig.ready()` (lihat
`integrations/erp_sync/apps.py`), jadi setelah file itu berjalan, file test
berikutnya kehilangan listener → `test_invoice_listener` gagal hanya ketika
dijalankan BERSAMA file lain (order-dependent).

Fixture autouse di bawah menyimpan salinan registry sebelum tiap test dan
memulihkannya sesudahnya, sehingga mutasi registry di satu test tidak bocor.
Akses `_listeners` disengaja: modul registry belum punya API snapshot publik
dan menambah API produksi hanya untuk test tidak sepadan.
"""

from __future__ import annotations

import pytest

from core.event_bus import registry


@pytest.fixture(autouse=True)
def _isolate_event_bus_listeners():
    """Snapshot registry listener sebelum test, restore setelah test selesai."""
    snapshot = {name: list(items) for name, items in registry._listeners.items()}

    yield

    registry._listeners.clear()
    registry._listeners.update(
        {name: list(items) for name, items in snapshot.items()}
    )
