"""Paket backend printer (Fase 5) + factory :func:`get_backend`.

Isi:

  * ``base``    : ``PrinterBackend`` (kontrak) + ``PrintResult``
  * ``mock``    : ``MockBackend``    (memori + file ``.bin``) — default dev/test
  * ``usb``     : ``UsbBackend``     (stub; butuh python-escpos + libusb)
  * ``network`` : ``NetworkBackend`` (TCP raw, implementasi minimal)

Pemilihan backend dari ``settings.PRINTER_BACKEND``; nilai tidak dikenal
**fail-safe** ke mock + log warning supaya alur cetak tidak mati karena salah tulis.
"""

from __future__ import annotations

import logging

from django.conf import settings

from .base import PrintResult, PrinterBackend
from .mock import MockBackend
from .network import NetworkBackend
from .usb import UsbBackend

logger = logging.getLogger(__name__)

#: Nama backend (lowercase) -> kelasnya.
BACKENDS: dict[str, type[PrinterBackend]] = {
    "mock": MockBackend,
    "usb": UsbBackend,
    "network": NetworkBackend,
}

#: Backend yang dipakai kalau `PRINTER_BACKEND` tidak dikenal/kosong.
DEFAULT_BACKEND = "mock"


def get_backend(name: str | None = None) -> PrinterBackend:
    """Instance backend printer sesuai ``settings.PRINTER_BACKEND``.

    Parameter ``name`` dipakai untuk override eksplisit (test atau pilihan manual
    dari UI admin).
    """
    requested = (name or getattr(settings, "PRINTER_BACKEND", "") or "").strip().lower()
    backend_cls = BACKENDS.get(requested)
    if backend_cls is None:
        logger.warning(
            "PRINTER_BACKEND %r tidak dikenal -> fallback %s (fail-safe).",
            requested or None,
            DEFAULT_BACKEND,
        )
        return MockBackend()
    logger.debug("Printer backend aktif: %s", backend_cls.name)
    return backend_cls()


__all__ = (
    "BACKENDS",
    "DEFAULT_BACKEND",
    "MockBackend",
    "NetworkBackend",
    "PrintResult",
    "PrinterBackend",
    "UsbBackend",
    "get_backend",
)
