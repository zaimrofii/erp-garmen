"""Middleware **request id** + filter logging untuk korelasi log.

Satu request = satu id:

  * header ``X-Request-ID`` dari klien dipakai kalau ada (dibersihkan dari
    karakter kontrol supaya tidak bisa dipakai untuk log injection);
  * kalau tidak ada -> UUID4 dibuat di sini;
  * id ditempelkan ke ``request.request_id`` (dipakai exception handler & audit
    log) dan dikembalikan di response header ``X-Request-ID``;
  * selama request berjalan, ``RequestIDFilter`` menyalin id ke setiap record
    log (thread-local) sehingga semua log satu request punya id yang sama.
"""

from __future__ import annotations

import logging
import threading
import uuid

__all__ = (
    "REQUEST_ID_HEADER",
    "RequestIDFilter",
    "RequestIDMiddleware",
    "clear_request_id",
    "get_request_id",
    "set_request_id",
)

REQUEST_ID_HEADER = "X-Request-ID"

#: Maksimal panjang id yang diterima dari klien (melindungi dari header raksasa).
MAX_REQUEST_ID_LENGTH = 255

logger = logging.getLogger(__name__)

_local = threading.local()


def set_request_id(value: str | None) -> None:
    """Simpan request id aktif untuk thread ini (dipakai filter logging)."""
    _local.request_id = value


def get_request_id() -> str | None:
    """Request id yang sedang aktif di thread ini (``None`` kalau di luar request)."""
    return getattr(_local, "request_id", None)


def clear_request_id() -> None:
    """Hapus request id thread-local (mis. di akhir eksekusi task Celery worker).

    Pelengkap :func:`set_request_id` supaya id request lama tidak "bocor" ke
    task berikutnya yang dieksekusi di thread worker yang sama.
    """
    set_request_id(None)


def sanitize_request_id(raw: str | None) -> str | None:
    """Buang karakter kontrol & batasi panjang; ``None`` kalau tidak ada isinya."""
    if not raw:
        return None
    cleaned = "".join(char for char in str(raw) if char.isprintable()).strip()
    return cleaned[:MAX_REQUEST_ID_LENGTH] or None


class RequestIDMiddleware:
    """Beri setiap request sebuah id dan kembalikan lewat response header."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = sanitize_request_id(request.headers.get(REQUEST_ID_HEADER)) or str(
            uuid.uuid4()
        )
        request.request_id = request_id
        set_request_id(request_id)
        try:
            response = self.get_response(request)
        finally:
            # Jangan tinggalkan id request lama di thread worker.
            set_request_id(None)
        response[REQUEST_ID_HEADER] = request_id
        return response


class RequestIDFilter(logging.Filter):
    """Tempelkan request id aktif ke setiap record log (kalau ada)."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Selalu lolos; hanya melengkapi atribut ``request_id``."""
        if not getattr(record, "request_id", None):
            record.request_id = get_request_id()
        return True
