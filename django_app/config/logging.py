"""Formatter log JSON terstruktur — **tanpa dependency eksternal**.

Satu baris log = satu object JSON, sehingga log bisa langsung di-ingest oleh
Loki/ELK tanpa parser regex. Field yang selalu ada:

    timestamp, level, logger, message, module, funcName

Field kondisional: ``request_id`` (diisi RequestIDMiddleware/RequestIDFilter)
dan ``extra`` (semua atribut non-standar yang ditempelkan pemanggil, mis.
``status_code`` dari ``django.request``). ``exc_info``/``stack_info`` ikut
ditulis kalau ada supaya error tetap bisa di-debug dari log.

Dipakai lewat ``settings.LOGGING`` (formatter ``json`` pada handler ``console``).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

__all__ = ("REQUEST_ID_ATTR", "JsonFormatter")

#: Nama atribut pada LogRecord yang dipakai untuk korelasi request.
REQUEST_ID_ATTR = "request_id"

#: Atribut standar `logging.LogRecord` (lihat dokumentasi modul logging) yang
#: TIDAK dimasukkan ke `extra` karena sudah punya field sendiri di payload.
_STANDARD_ATTRS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


class JsonFormatter(logging.Formatter):
    """Format setiap ``LogRecord`` menjadi satu baris JSON."""

    def format(self, record: logging.LogRecord) -> str:
        """Bangun payload JSON untuk satu record log."""
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "funcName": record.funcName,
        }

        request_id = getattr(record, REQUEST_ID_ATTR, None)
        if request_id:
            payload[REQUEST_ID_ATTR] = str(request_id)

        extra = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _STANDARD_ATTRS and key != REQUEST_ID_ATTR
        }
        if extra:
            payload["extra"] = extra

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack_info"] = self.formatStack(record.stack_info)

        # `default=str` menjaga log tidak pernah gagal karena objek non-JSON
        # (mis. UUID/Decimal/datetime) — hardening: logging tidak boleh melempar.
        return json.dumps(payload, ensure_ascii=False, default=str)
