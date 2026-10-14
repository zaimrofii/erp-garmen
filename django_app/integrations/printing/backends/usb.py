"""Backend USB (stub).

Mencetak lewat USB butuh library ``python-escpos`` + ``libusb`` — keduanya belum
ada di image container, dan menambahkannya berarti mengubah Dockerfile (di luar
batasan sprint). Karena itu setiap upaya cetak melempar
:class:`NotImplementedError` dengan pesan jelas, supaya salah konfigurasi
(``PRINTER_BACKEND=usb``) ketahuan langsung alih-alih diam-diam tidak mencetak.
"""

from __future__ import annotations

import logging

from django.conf import settings

from .base import PrintResult, PrinterBackend

logger = logging.getLogger(__name__)

#: Pesan standar (dipakai juga oleh test).
MESSAGE = "Implementasi USB butuh python-escpos + libusb"


class UsbBackend(PrinterBackend):
    """Stub backend USB: menyimpan konfigurasi, belum bisa mengirim data."""

    name = "usb"

    def __init__(self, vendor_id: int | None = None, product_id: int | None = None) -> None:
        self.vendor_id = (
            vendor_id if vendor_id is not None else getattr(settings, "PRINTER_USB_VENDOR_ID", None)
        )
        self.product_id = (
            product_id
            if product_id is not None
            else getattr(settings, "PRINTER_USB_PRODUCT_ID", None)
        )

    def print_bytes(self, data: bytes, ref: str = "") -> PrintResult:
        """Belum tersedia — lihat pesan error untuk paket yang dibutuhkan."""
        logger.warning("[UsbBackend] print_bytes dipanggil, tetapi backend masih stub.")
        raise NotImplementedError(MESSAGE)
