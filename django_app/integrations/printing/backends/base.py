"""Kontrak backend printer + hasil cetak (:class:`PrintResult`).

Backend = "kemana bytes ESC/POS dikirim". Layout cetak (`bundle_tag.py`,
`coupon.py`) tidak tahu-menahu soal USB/jaringan; penggantian backend cukup
lewat ``settings.PRINTER_BACKEND`` atau injeksi instance ke pemanggil.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

__all__ = ("PrintResult", "PrinterBackend")


@dataclass
class PrintResult:
    """Hasil satu percobaan cetak."""

    ok: bool
    backend: str
    bytes_sent: int = 0
    error: str | None = None
    ref: str = ""

    def as_dict(self) -> dict[str, Any]:
        """Bentuk JSON-safe (untuk log, ``PrintJob``, atau respons API)."""
        return {
            "ok": self.ok,
            "backend": self.backend,
            "bytes_sent": self.bytes_sent,
            "error": self.error,
            "ref": self.ref,
        }

    def __str__(self) -> str:
        if self.ok:
            return f"PrintResult[{self.backend}] ok {self.bytes_sent} bytes"
        return f"PrintResult[{self.backend}] gagal: {self.error}"


class PrinterBackend(ABC):
    """Kontrak backend printer (mock/usb/network)."""

    #: Nama backend untuk log/diagnosa (di-override subclass).
    name = "printer"

    @abstractmethod
    def print_bytes(self, data: bytes, ref: str = "") -> PrintResult:
        """Kirim ``data`` (bytes ESC/POS) ke printer; ``ref`` = penanda job."""

    def close(self) -> None:
        """Tutup resource backend (opsional, default no-op)."""
        return None

    def _validate(self, data: Any, ref: Any) -> PrintResult | None:
        """Validasi input; kembalikan ``PrintResult`` gagal atau ``None`` kalau OK."""
        if not isinstance(data, (bytes, bytearray)) or len(data) == 0:
            return PrintResult(
                ok=False,
                backend=self.name,
                bytes_sent=0,
                error="Data cetak kosong atau bukan bytes.",
                ref=str(ref or ""),
            )
        return None

    def __repr__(self) -> str:
        return f"<{type(self).__name__} name={self.name}>"
