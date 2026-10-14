"""Stub endpoint AI chat (Fase F).

Belum ada LLM di backend, dan `frontend_app/src/integrations/ai-chat.ts` butuh
respons **valid** (bukan 404/501) supaya jalur UI-nya bisa dikembangkan dan
di-bundle test. Karena itu endpoint ini selalu membalas **200** dengan:

    {"ok": false, "reason": "not_implemented", "schema_version": "1.0",
     "detail": "AI Chat belum diimplementasikan (stub Fase F)."}

Sengaja **tidak** memanggil LLM/API eksternal dan tidak menyimpan apa pun:
kontrak AI nyata (prompt, konteks, HITL) dibahas di fase berikutnya — lihat
`frontend_app/docs/project-current.json`.
"""

from __future__ import annotations

import logging

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)

__all__ = ("AiChatView", "REASON_NOT_IMPLEMENTED", "SCHEMA_VERSION")

#: Alasan yang dikenali frontend (`ai-chat.ts`) — jangan diganti tanpa kesepakatan.
REASON_NOT_IMPLEMENTED = "not_implemented"

#: Versi skema response (`schema_version` kontrak).
SCHEMA_VERSION = "1.0"


@extend_schema(
    summary="AI chat (stub)",
    description=(
        "Selalu membalas **200** `{\"ok\": false, \"reason\": \"not_implemented\", "
        "\"schema_version\": \"1.0\"}` supaya klien frontend (`ai-chat.ts`) mendapat "
        "respons valid walau LLM belum ada. Bukan 404/501."
    ),
    request=OpenApiTypes.OBJECT,
    responses={200: OpenApiTypes.OBJECT},
    tags=["ai"],
)
class AiChatView(APIView):
    """`POST /api/v1/ai/chat` — selalu 200 + `{ok:false, reason:'not_implemented'}`."""

    permission_classes = [AllowAny]  # auth menyusul Fase G

    def post(self, request):
        """Balas stub valid; body request (message/context) dicatat di log DEBUG."""
        logger.debug("ai/chat stub dipanggil: %s", request.data)
        return Response(
            {
                "ok": False,
                "reason": REASON_NOT_IMPLEMENTED,
                "schema_version": SCHEMA_VERSION,
                "detail": "AI Chat belum diimplementasikan (stub Fase F).",
            }
        )
