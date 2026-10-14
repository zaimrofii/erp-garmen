"""Backend jaringan (TCP raw ESC/POS) — implementasi minimal.

Printer thermal jaringan (mis. port 9100 "raw printing") menerima bytes ESC/POS
apa adanya lewat TCP. Implementasi ini sengaja minimal: connect → ``sendall`` →
``close``, tanpa retry/queue — retry/audit ada di lapisan pemanggil
(``PrintJob`` / task Celery kalau nanti dibutuhkan).
"""

from __future__ import annotations

import logging
import socket

from django.conf import settings

from .base import PrintResult, PrinterBackend

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 5.0


class NetworkBackend(PrinterBackend):
    """Kirim bytes ke printer jaringan via TCP."""

    name = "network"

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.host = (
            host if host is not None else getattr(settings, "PRINTER_NETWORK_HOST", None)
        )
        self.port = (
            port if port is not None else getattr(settings, "PRINTER_NETWORK_PORT", None)
        )
        self.timeout = float(timeout)

    def print_bytes(self, data: bytes, ref: str = "") -> PrintResult:
        """Kirim ``data`` ke ``host:port``; kegagalan jaringan -> ``ok=False``."""
        invalid = self._validate(data, ref)
        if invalid is not None:
            return invalid
        if not self.host or not self.port:
            return PrintResult(
                ok=False,
                backend=self.name,
                bytes_sent=0,
                error="PRINTER_NETWORK_HOST/PORT belum dikonfigurasi.",
                ref=str(ref or ""),
            )

        payload = bytes(data)
        try:
            with socket.create_connection(
                (str(self.host), int(self.port)), timeout=self.timeout
            ) as connection:
                connection.sendall(payload)
        except (OSError, ValueError) as exc:
            logger.warning(
                "[NetworkBackend] gagal mengirim %s bytes ke %s:%s -> %s",
                len(payload),
                self.host,
                self.port,
                exc,
            )
            return PrintResult(
                ok=False,
                backend=self.name,
                bytes_sent=0,
                error=str(exc),
                ref=str(ref or ""),
            )

        logger.info(
            "[NetworkBackend] %s bytes terkirim ke %s:%s", len(payload), self.host, self.port
        )
        return PrintResult(
            ok=True,
            backend=self.name,
            bytes_sent=len(payload),
            error=None,
            ref=str(ref or ""),
        )
