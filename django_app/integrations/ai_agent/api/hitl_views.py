"""Endpoint HITL AI nyata (F.1.6) — AIHitlQueue (bukan HITLRequest lama)."""

from __future__ import annotations

import logging

from django.core.exceptions import PermissionDenied, ValidationError
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..hitl import hitl_services

logger = logging.getLogger(__name__)

APPROVER_ROLES = {"ADMIN", "OWNER", "SUPERVISOR"}


def _require_approver(user) -> None:
    if hitl_services.user_role(user) not in APPROVER_ROLES:
        raise PermissionDenied(
            "Hanya ADMIN/OWNER/SUPERVISOR yang boleh mengakses antrean HITL AI."
        )


class AiHitlQueueView(APIView):
    """`GET /api/v1/ai/hitl/queue/` — PENDING untuk role approver."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        _require_approver(request.user)

        try:
            limit = int(request.query_params.get("limit") or 50)
            offset = int(request.query_params.get("offset") or 0)
        except (TypeError, ValueError):
            return Response({"detail": "'limit'/'offset' harus angka."}, status=400)
        limit = max(1, min(limit, 200))
        offset = max(0, offset)

        status_filter = str(request.query_params.get("status") or "PENDING").upper()
        if status_filter not in {"PENDING", "APPROVED", "REJECTED", "EXPIRED", "ALL"}:
            return Response({"detail": "'status' tidak dikenal."}, status=400)

        risk_filter = str(
            request.query_params.get("risk_level")
            or request.query_params.get("risk")
            or ""
        ).upper()
        if risk_filter and risk_filter not in {"LOW", "MEDIUM", "HIGH", "ALL"}:
            return Response({"detail": "'risk' tidak dikenal."}, status=400)

        rows, total = hitl_services.get_queue(
            hitl_services.user_role(request.user),
            status_filter,
            risk_filter or None,
            limit,
            offset,
        )
        next_offset = offset + len(rows)
        return Response(
            {
                "rows": rows,
                "total_count": total,
                "has_more": next_offset < total,
                "next_cursor": next_offset if next_offset < total else None,
            }
        )


class AiHitlApproveView(APIView):
    """`POST /api/v1/ai/hitl/<id>/approve/` — setujui (body note opsional)."""

    permission_classes = [IsAuthenticated]

    def post(self, request, request_id: int):
        _require_approver(request.user)
        note = str((request.data or {}).get("note") or "").strip()

        try:
            row = hitl_services.approve(request_id, request.user, note or None)
        except hitl_services.HitlNotFound:
            return Response({"detail": "HITL request tidak ditemukan."}, status=404)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=403)
        except hitl_services.HitlConflict as exc:
            return Response(
                {"detail": str(exc), "status": exc.status},
                status=status.HTTP_409_CONFLICT,
            )

        return Response(row)


class AiHitlRejectView(APIView):
    """`POST /api/v1/ai/hitl/<id>/reject/` — tolak (reason WAJIB)."""

    permission_classes = [IsAuthenticated]

    def post(self, request, request_id: int):
        _require_approver(request.user)
        reason = str((request.data or {}).get("reason") or "").strip()

        try:
            row = hitl_services.reject(request_id, request.user, reason)
        except ValidationError as exc:
            return Response(
                {"detail": exc.messages[0] if exc.messages else "reason wajib."},
                status=400,
            )
        except hitl_services.HitlNotFound:
            return Response({"detail": "HITL request tidak ditemukan."}, status=404)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=403)
        except hitl_services.HitlConflict as exc:
            return Response(
                {"detail": str(exc), "status": exc.status},
                status=status.HTTP_409_CONFLICT,
            )

        return Response(row)


__all__ = ("AiHitlApproveView", "AiHitlQueueView", "AiHitlRejectView")
