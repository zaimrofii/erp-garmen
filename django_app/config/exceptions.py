"""Handler exception DRF project ini: response bersih, log lengkap.

Aturan:

  * ``DEBUG=True`` (dev) -> perilaku default DRF apa adanya, supaya stack trace
    tetap kelihatan waktu ngoding;
  * ``DEBUG=False`` (produksi):
      - error yang dikenali DRF (validasi 400, 404, 405, 429 throttle, ...)
        dikembalikan rapi apa adanya + ``request_id`` sebagai penanda korelasi;
      - exception tak terduga -> **500** ``{"detail": "Internal server error",
        "request_id": "..."}``; stack trace penuh hanya masuk log
        (``django.request``) dan **tidak pernah** dikirim ke klien.
"""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

__all__ = ("custom_exception_handler",)

logger = logging.getLogger("django.request")

#: Pesan generik untuk klien (tidak membocorkan detail internal).
INTERNAL_ERROR_DETAIL = "Internal server error"


def custom_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    """Handler exception untuk ``REST_FRAMEWORK["EXCEPTION_HANDLER"]``."""
    response = drf_exception_handler(exc, context)

    if settings.DEBUG:
        return response

    request = context.get("request")
    request_id = getattr(request, "request_id", None)

    if response is not None:
        # Error yang memang sudah rapi dari DRF: lengkapi dengan request_id.
        if isinstance(response.data, dict) and request_id:
            response.data.setdefault("request_id", request_id)
        return response

    # Exception di luar dugaan -> jangan pernah tampilkan stack trace ke klien.
    view = context.get("view")
    logger.error(
        "Unhandled exception di %s (request_id=%s): %s",
        type(view).__name__ if view is not None else "-",
        request_id,
        exc,
        exc_info=exc,
    )
    payload: dict[str, Any] = {"detail": INTERNAL_ERROR_DETAIL}
    if request_id:
        payload["request_id"] = request_id
    return Response(payload, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
