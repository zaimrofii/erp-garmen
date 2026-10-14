"""Generator **KUPON** piece-rate (dari ``OrderLine``) — Fase 5.

Kupon = bukti kerja per order line: satu lembar per line, berisi kode kupon unik
yang dipakai admin untuk menghitung upah (piece-rate). Karena itu kupon **wajib**
punya ``ticket_code``; kalau belum ada, pencetakan digagalkan dengan
:class:`CouponError` supaya tidak ada kupon tanpa identitas di lantai produksi.
"""

from __future__ import annotations

from django.utils import timezone

from .escpos import ESCPOSDriver

__all__ = ("CouponError", "CouponGenerator")

#: Garis pemisah selebar kertas 58 mm (32 kolom).
SEPARATOR = "-" * 32


class CouponError(ValueError):
    """Kupon tidak bisa dicetak karena data sumbernya belum lengkap."""


class CouponGenerator:
    """Susun bytes ESC/POS untuk satu kupon piece-rate."""

    def __init__(self, order_line) -> None:
        self.order_line = order_line

    def render(self) -> bytes:
        """Bangun layout kupon; raise :class:`CouponError` kalau ticket kosong."""
        order_line = self.order_line
        ticket_code = str(getattr(order_line, "ticket_code", "") or "").strip()
        if not ticket_code:
            raise CouponError(
                "Order line belum punya ticket_code; kupon tanpa kode tidak boleh dicetak."
            )

        tag = str(getattr(order_line, "tag", "") or "") or "-"
        order = getattr(order_line, "order", None)
        order_code = str(getattr(order, "code", "") or "") or "-"
        qty = getattr(order_line, "qty", 0) or 0

        driver = ESCPOSDriver()
        driver.init()

        # Header
        driver.align("center")
        driver.bold(True)
        driver.line("KUPON")
        driver.bold(False)
        driver.line(SEPARATOR)

        # Kode kupon (identitas utama)
        driver.bold(True)
        driver.line(ticket_code)
        driver.bold(False)

        # Info piece-rate
        driver.align("left")
        driver.line(f"Tag: {tag}")
        driver.line(f"Qty: {qty}")
        driver.line(f"Order: {order_code}")
        driver.line(SEPARATOR)

        driver.align("center")
        driver.line(f"Dicetak: {timezone.localtime():%Y-%m-%d %H:%M:%S}")

        driver.align("left")
        driver.feed(2)
        driver.cut()
        return driver.build()
