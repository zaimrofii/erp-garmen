"""Backend mock: "mencetak" ke memori (+ opsional file ``.bin``) untuk dev/test.

Dipilih default lewat ``settings.PRINTER_BACKEND="mock"`` sehingga developer dan
test suite bisa memverifikasi isi perintah ESC/POS tanpa printer fisik.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from django.conf import settings

from .base import PrintResult, PrinterBackend

logger = logging.getLogger(__name__)

#: Folder default hasil "cetak" mock (di /tmp supaya tidak masuk repo).
DEFAULT_DIRECTORY = "/tmp/print_mock"


class MockBackend(PrinterBackend):
    """Backend palsu: menyimpan bytes di memori dan menuliskannya ke file."""

    name = "mock"

    def __init__(self, directory: str | Path | None = None, write_file: bool = True) -> None:
        self.directory = Path(
            directory or getattr(settings, "PRINTER_MOCK_DIR", DEFAULT_DIRECTORY)
        )
        self.write_file = write_file
        #: Riwayat cetak (untuk diagnosa & assertion test).
        self.printed: list[dict[str, Any]] = []

    def print_bytes(self, data: bytes, ref: str = "") -> PrintResult:
        """Simpan ``data`` ke memori + file ``<dir>/<ref>.bin``; selalu sukses."""
        invalid = self._validate(data, ref)
        if invalid is not None:
            return invalid

        payload = bytes(data)
        label = str(ref or "")
        self.printed.append({"ref": label, "bytes": payload})
        path = self._write_file(payload, label)
        logger.info(
            "[MockBackend] %s bytes dicetak (ref=%s, file=%s)",
            len(payload),
            label or "-",
            path or "-",
        )
        return PrintResult(
            ok=True,
            backend=self.name,
            bytes_sent=len(payload),
            error=None,
            ref=label,
        )

    # ---------------------------------------------------------------- internal
    def _write_file(self, payload: bytes, ref: str) -> str | None:
        """Tulis bytes ke file mock; kegagalan I/O tidak menggagalkan cetak."""
        if not self.write_file:
            return None
        name = ref.strip() or "print"
        safe = "".join(char if char.isalnum() or char in "-_." else "_" for char in name)
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self.directory / f"{safe}.bin"
            path.write_bytes(payload)
        except OSError as exc:
            logger.warning("[MockBackend] gagal menulis file mock: %s", exc)
            return None
        return str(path)
