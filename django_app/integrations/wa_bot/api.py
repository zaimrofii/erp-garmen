"""Endpoint WhatsApp (Fase F) — `POST /api/v1/wa/send/`.

Body::

    {"to": "628123456789", "message": "Bundle BND-0001 selesai"}

Response 200::

    {"ok": true, "backend": "mock", "message_id": "MOCK-<uuid>",
     "to": "628123456789", "chars": 24}

Response 400 (field kosong atau gateway menolak)::

    {"detail": "Field 'to' dan 'message' wajib diisi."}

Belum ada tombol WA di UI (Fase F hanya membuka jalurnya di backend); pengiriman
notifikasi otomatis menyusul lewat listener event bus. Gateway diambil dari
`integrations/wa_bot/services.get_wa_gateway()` (`settings.WA_BACKEND`, default
mock) — implementasi penyedia sungguhan cukup ditambahkan di sana.
"""

from __future__ import annotations

import logging

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from integrations.wa_bot.services import get_wa_gateway

logger = logging.getLogger(__name__)

__all__ = ("WASendView",)


@extend_schema(
    summary="Kirim pesan WhatsApp (gateway default: mock)",
    description=(
        "Body `{to, message}`. Gateway diambil dari `settings.WA_BACKEND` "
        "(default `mock` → tidak menyentuh jaringan). 400 kalau field kosong atau "
        "gateway menolak."
    ),
    request=OpenApiTypes.OBJECT,
    responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT},
    tags=["wa"],
)
class WASendView(APIView):
    """Kirim satu pesan WhatsApp lewat gateway aktif (mock secara default)."""

    permission_classes = [AllowAny]  # auth menyusul Fase G

    def post(self, request):
        data = request.data or {}
        to = str(data.get("to") or "").strip()
        message = str(data.get("message") or "").strip()

        if to == "" or message == "":
            return Response(
                {"detail": "Field 'to' dan 'message' wajib diisi."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        gateway = get_wa_gateway()
        # NB: kontrak gateway memakai `send_message(to, body)` (bukan `send`) —
        # lihat `integrations/wa_bot/services.py`.
        result = gateway.send_message(to, message)

        if not result.ok or result.message_id is None:
            logger.warning("WA gagal dikirim ke %s: %s", to, result.error)
            return Response(
                {"detail": result.error or "Gagal mengirim pesan WhatsApp."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "ok": True,
                "backend": str(getattr(gateway, "name", "") or "wa"),
                "message_id": result.message_id,
                "to": to,
                "chars": len(message),
            },
            status=status.HTTP_200_OK,
        )
