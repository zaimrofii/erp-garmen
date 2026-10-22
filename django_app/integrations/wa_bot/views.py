"""Webhook WhatsApp masuk (F.2.3) — approval HITL via balasan WA."""

from __future__ import annotations

import logging
import re

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from integrations.ai_agent.hitl import hitl_services
from integrations.wa_bot.services import get_wa_gateway

logger = logging.getLogger(__name__)

_APPROVE_RE = re.compile(r"^APPROVE\s+(\d+)\s*$", re.IGNORECASE)
_REJECT_RE = re.compile(r"^REJECT\s+(\d+)\s+(.+)$", re.IGNORECASE | re.DOTALL)


def _approver_for(sender: str):
    """Nomor WA → user approver (mapping `AI_HITL_WA_APPROVERS`)."""
    from core.auth.models import User

    mapping = getattr(settings, "AI_HITL_WA_APPROVERS", {}) or {}

    if isinstance(mapping, dict):
        username = mapping.get(sender)
        if not username:
            return None
        return User.objects.filter(username=username, is_active=True).first()

    if isinstance(mapping, (list, tuple)) and sender in mapping:
        return (
            User.objects.filter(is_active=True, role__code__in=["SUPERVISOR", "OWNER"])
            .order_by("id")
            .first()
        )

    return None


def _reply(sender: str, body: str) -> None:
    """Balas konfirmasi via WA (best-effort, tidak pernah throw)."""
    if not sender:
        return
    try:
        get_wa_gateway().send_message(sender, body)
    except Exception:  # noqa: BLE001 - balasan tidak boleh menggagalkan webhook
        logger.exception("wa_webhook: gagal membalas pesan.")


class WaWebhookView(APIView):
    """`POST /api/v1/wa/webhook/` — parse APPROVE/REJECT dari WA."""

    permission_classes = [AllowAny]

    def post(self, request):
        payload = request.data if isinstance(request.data, dict) else {}

        try:
            message = get_wa_gateway().parse_incoming(payload)
        except Exception:  # noqa: BLE001 - payload vendor berbeda-beda
            logger.exception("wa_webhook: payload tidak bisa diparse.")
            return Response(
                {"ok": False, "error": "invalid_payload"}, status=400
            )

        sender = str(message.sender or "").strip()
        text = str(message.body or "").strip()

        user = _approver_for(sender)
        if user is None:
            logger.info("wa_webhook: nomor %r tidak terdaftar → ditolak.", sender)
            return Response({"ok": False, "error": "forbidden"}, status=403)

        approve_match = _APPROVE_RE.match(text)
        if approve_match:
            hitl_id = int(approve_match.group(1))
            try:
                result = hitl_services.approve(hitl_id, user, note="WA")
            except hitl_services.HitlNotFound:
                return Response({"ok": False, "error": "not_found", "id": hitl_id}, status=404)
            except (PermissionDenied, hitl_services.HitlConflict) as exc:
                return Response({"ok": False, "error": str(exc)}, status=409)

            _reply(sender, f"HITL #{hitl_id} disetujui.")
            return Response(
                {
                    "ok": True,
                    "action": "approve",
                    "id": hitl_id,
                    "status": (result or {}).get("status", "APPROVED"),
                    "execution": (result or {}).get("execution"),
                }
            )

        reject_match = _REJECT_RE.match(text)
        if reject_match:
            hitl_id = int(reject_match.group(1))
            reason = reject_match.group(2).strip()
            try:
                result = hitl_services.reject(hitl_id, user, reason=reason)
            except ValidationError as exc:
                return Response({"ok": False, "error": exc.messages[0]}, status=400)
            except hitl_services.HitlNotFound:
                return Response({"ok": False, "error": "not_found", "id": hitl_id}, status=404)
            except (PermissionDenied, hitl_services.HitlConflict) as exc:
                return Response({"ok": False, "error": str(exc)}, status=409)

            _reply(sender, f"HITL #{hitl_id} ditolak.")
            return Response(
                {
                    "ok": True,
                    "action": "reject",
                    "id": hitl_id,
                    "status": (result or {}).get("status", "REJECTED"),
                }
            )

        logger.info("wa_webhook: format tidak dikenal dari %r → ditolak.", sender)
        return Response({"ok": False, "error": "invalid_format"}, status=400)


__all__ = ("WaWebhookView",)
