"""Driver ESC/POS minimal untuk bundle tag & kupon — **tanpa library eksternal**.

Paket ``python-escpos`` butuh libusb (memaksa perubahan Dockerfile), jadi
perintah ESC/POS ditulis sendiri di sini. Hanya perintah yang dipakai layout
cetak kita yang diimplementasikan, mengikuti urutan byte standar Epson:

  ==============================  ==========================================
  Perintah                        Byte
  ==============================  ==========================================
  Initialize                      ``1B 40``              (ESC @)
  Bold on / off                   ``1B 45 01`` / ``1B 45 00``
  Align left / center / right     ``1B 61 00`` / ``01`` / ``02``
  Feed n baris                    ``1B 64 n``
  Cut full / partial              ``1D 56 00`` / ``1D 56 01``
  QR code                         ``1D 28 6B …``         (GS ( k)
  Barcode CODE128 / CODE39        ``1D 6B 49 …`` / ``1D 6B 45 …``
  ==============================  ==========================================

Semua input divalidasi dan kesalahan dilempar sebagai :class:`ESCPOSError`
supaya masalah layout ketahuan waktu test/dev, bukan di printer lantai produksi.

Contoh::

    data = ESCPOSDriver().init().align("center").bold(True).line("BUNDLE TAG").build()
"""

from __future__ import annotations

from typing import Final

__all__ = ("ESCPOSDriver", "ESCPOSError")


class ESCPOSError(ValueError):
    """Input layout tidak valid (bukan kegagalan printer)."""


class ESCPOSDriver:
    """Pembangun buffer ESC/POS dengan state minimal (satu bytearray)."""

    # ------------------------------------------------------------- komponen byte
    ESC: Final = 0x1B
    GS: Final = 0x1D

    #: Inisialisasi printer (reset + clear buffer printer).
    INIT: Final = b"\x1b@"
    BOLD_ON: Final = b"\x1bE\x01"
    BOLD_OFF: Final = b"\x1bE\x00"
    ALIGN_LEFT: Final = b"\x1ba\x00"
    ALIGN_CENTER: Final = b"\x1ba\x01"
    ALIGN_RIGHT: Final = b"\x1ba\x02"
    FEED: Final = b"\x1bd"  # diikuti 1 byte jumlah baris
    CUT_FULL: Final = b"\x1dV\x00"
    CUT_PARTIAL: Final = b"\x1dV\x01"

    #: GS ( k — set ukuran modul & level koreksi error lalu cetak.
    QR_MODEL: Final = b"\x1d(k\x04\x001A\x02\x00"
    QR_SIZE: Final = b"\x1d(k\x03\x001C"
    QR_ERROR_CORRECTION: Final = b"\x1d(k\x03\x001E\x31"
    QR_STORE: Final = b"\x1d(k"  # mendahului panjang data + "1P0"
    QR_PRINT: Final = b"\x1d(k\x03\x001Q\x30"

    #: GS h n / GS w n — tinggi & lebar modul barcode.
    BARCODE_HEIGHT: Final = b"\x1dh"
    BARCODE_WIDTH: Final = b"\x1dw"
    BARCODE_CODE128: Final = b"\x1dk\x49"  # GS k 73 (didahului 1 byte panjang)
    BARCODE_CODE39: Final = b"\x1dk\x45"  # GS k 69 (diakhiri NUL)

    def __init__(self) -> None:
        self._buffer = bytearray()

    # ------------------------------------------------------------------- output
    @property
    def buffer(self) -> bytes:
        """Snapshot buffer saat ini (tidak mengubah isi)."""
        return bytes(self._buffer)

    def build(self) -> bytes:
        """Kembalikan seluruh perintah sebagai ``bytes`` (buffer tetap utuh)."""
        return bytes(self._buffer)

    # --------------------------------------------------------------- perintah
    def init(self) -> "ESCPOSDriver":
        """Reset printer ke kondisi awal."""
        self._buffer += self.INIT
        return self

    def text(self, value: str) -> "ESCPOSDriver":
        """Tulis teks tanpa baris baru."""
        self._buffer += self._encode(value)
        return self

    def line(self, value: str = "") -> "ESCPOSDriver":
        """Tulis teks + baris baru (``value`` boleh kosong = baris kosong)."""
        self._buffer += self._encode(value) + b"\n"
        return self

    def feed(self, n: int = 1) -> "ESCPOSDriver":
        """Majukan kertas ``n`` baris (0-255)."""
        if isinstance(n, bool) or not isinstance(n, int) or not 0 <= n <= 255:
            raise ESCPOSError(f"feed(n) harus int 0-255, dapat {n!r}.")
        self._buffer += self.FEED + bytes([n])
        return self

    def cut(self, full: bool = True) -> "ESCPOSDriver":
        """Potong kertas (default: potong penuh)."""
        if not isinstance(full, bool):
            raise ESCPOSError(f"cut(full) butuh bool, dapat {full!r}.")
        self._buffer += self.CUT_FULL if full else self.CUT_PARTIAL
        return self

    def bold(self, on: bool) -> "ESCPOSDriver":
        """Nyalakan/matikan huruf tebal."""
        if not isinstance(on, bool):
            raise ESCPOSError(f"bold(on) butuh bool, dapat {on!r}.")
        self._buffer += self.BOLD_ON if on else self.BOLD_OFF
        return self

    def align(self, value: str = "left") -> "ESCPOSDriver":
        """Rata kiri / tengah / kanan."""
        commands = {
            "left": self.ALIGN_LEFT,
            "center": self.ALIGN_CENTER,
            "right": self.ALIGN_RIGHT,
        }
        command = commands.get(str(value).strip().lower())
        if command is None:
            raise ESCPOSError(
                f"align({value!r}) tidak dikenal; pakai 'left', 'center', atau 'right'."
            )
        self._buffer += command
        return self

    def qr(self, data: str, size: int = 6) -> "ESCPOSDriver":
        """Cetak QR code dari ``data`` (ukuran modul 1-8, koreksi error level M)."""
        payload = self._ascii(data, "qr")
        if isinstance(size, bool) or not isinstance(size, int) or not 1 <= size <= 8:
            raise ESCPOSError(f"qr(size) harus int 1-8, dapat {size!r}.")
        length = len(payload) + 3  # 3 byte header (cn, fn, m) setelah panjang
        self._buffer += self.QR_MODEL
        self._buffer += self.QR_SIZE + bytes([size])
        self._buffer += self.QR_ERROR_CORRECTION
        self._buffer += (
            self.QR_STORE
            + bytes([length & 0xFF, (length >> 8) & 0xFF])
            + b"\x001P0"
            + payload
        )
        self._buffer += self.QR_PRINT
        return self

    def barcode(self, data: str, type: str = "CODE128") -> "ESCPOSDriver":  # noqa: A002
        """Cetak barcode 1D (default CODE128; tinggi 80, lebar modul 2)."""
        commands = {"CODE128": self.BARCODE_CODE128, "CODE39": self.BARCODE_CODE39}
        kind = str(type).strip().upper()
        if kind not in commands:
            raise ESCPOSError(
                f"barcode type {type!r} tidak didukung; pakai {', '.join(sorted(commands))}."
            )
        payload = self._ascii(data, "barcode")
        self._buffer += self.BARCODE_HEIGHT + bytes([80])
        self._buffer += self.BARCODE_WIDTH + bytes([2])
        if kind == "CODE128":
            # GS k 73: satu byte panjang data mendahului isinya.
            self._buffer += commands[kind] + bytes([len(payload)]) + payload
        else:
            # GS k 69 (CODE39): data diakhiri NUL.
            self._buffer += commands[kind] + payload + b"\x00"
        return self

    # ---------------------------------------------------------------- internal
    @staticmethod
    def _encode(value: str) -> bytes:
        """Teks -> CP437 (codepage default printer); karakter tak dikenal -> '?'."""
        if not isinstance(value, str):
            raise ESCPOSError(f"Teks harus str, dapat {type(value).__name__}.")
        return value.encode("cp437", errors="replace")

    @staticmethod
    def _ascii(value: str, what: str) -> bytes:
        """Validasi data QR/barcode: wajib ``str`` dan tidak kosong."""
        if not isinstance(value, str):
            raise ESCPOSError(f"Data {what} harus str, dapat {type(value).__name__}.")
        if not value.strip():
            raise ESCPOSError(f"Data {what} tidak boleh kosong.")
        return value.encode("ascii", errors="replace")

