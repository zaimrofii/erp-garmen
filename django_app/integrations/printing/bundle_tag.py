"""Generator **BUNDLE TAG** (label QR + barcode untuk tiap bundle) — Fase 5.

Layout sengaja urut dari atas ke bawah: judul → QR → kode besar → info ukuran &
SKU → WO/WC → barcode → waktu cetak, lalu potong. Semua data diambil dari objek
domain (`Bundle`/`WorkCenter`/`WorkOrder`) apa adanya — generator tidak menyentuh
DB selain relasi yang sudah ada di instance.
"""

from __future__ import annotations

from django.utils import timezone

from .escpos import ESCPOSDriver

__all__ = ("BundleTagGenerator",)

#: Garis pemisah selebar kertas 58 mm (32 kolom).
SEPARATOR = "-" * 32


class BundleTagGenerator:
    """Susun bytes ESC/POS untuk satu bundle tag."""

    def __init__(self, bundle, work_order=None) -> None:
        """``work_order`` opsional; default diambil dari ``bundle.work_order``."""
        self.bundle = bundle
        self.work_order = (
            work_order if work_order is not None else getattr(bundle, "work_order", None)
        )

    def render(self) -> bytes:
        """Bangun layout lengkap dan kembalikan bytes siap kirim ke printer."""
        bundle = self.bundle
        code = str(getattr(bundle, "code", "") or "")
        size = str(getattr(bundle, "size", "") or "") or "-"
        sku = str(getattr(bundle, "sku_variant", "") or "") or "-"
        qty = getattr(bundle, "qty", 0) or 0

        driver = ESCPOSDriver()
        driver.init()

        # Header
        driver.align("center")
        driver.bold(True)
        driver.line("BUNDLE TAG")
        driver.bold(False)
        driver.line(SEPARATOR)

        # QR + kode (tebal)
        driver.qr(code)
        driver.bold(True)
        driver.line(code)
        driver.bold(False)

        # Info bundle
        driver.align("left")
        driver.line(f"Size: {size} | SKU: {sku}")
        driver.line(f"Qty: {qty}")
        work_order = self.work_order
        if work_order is not None:
            driver.line(f"Work Order: {work_order.code}")
        work_center = getattr(bundle, "current_work_center", None)
        if work_center is not None:
            driver.line(f"WC: {work_center.code}")

        # Barcode + waktu cetak
        driver.line(SEPARATOR)
        driver.align("center")
        driver.barcode(code)
        driver.line(f"Dicetak: {timezone.localtime():%Y-%m-%d %H:%M:%S}")

        driver.align("left")
        driver.feed(2)
        driver.cut()
        return driver.build()
