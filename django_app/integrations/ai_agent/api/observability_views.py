"""Endpoint observability AI (F.3.2) — ADMIN/OWNER, cache 60 dtk."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from django.core.cache import cache
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..config import AI_CONFIG
from ..observability import decision_logger

ALLOWED_ROLES = {"ADMIN", "OWNER"}


def _role(user) -> str:
    return str(getattr(getattr(user, "role", None), "code", "") or "").upper()


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


class AiObservabilityView(APIView):
    """`GET /api/v1/ai/observability/` — agregat token/biaya/latensi/HITL."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if _role(request.user) not in ALLOWED_ROLES and not request.user.is_superuser:
            return Response({"detail": "Hanya ADMIN/OWNER."}, status=403)

        today = timezone.localdate()
        date_to = _parse_date(request.query_params.get("date_to")) or today
        date_from = _parse_date(request.query_params.get("date_from")) or (
            date_to - timedelta(days=6)
        )
        if date_from > date_to:
            return Response({"detail": "date_from harus <= date_to."}, status=400)

        group_by = str(request.query_params.get("group_by") or "day").lower()
        if group_by not in ("day", "tool"):
            return Response({"detail": "group_by harus day|tool."}, status=400)

        nocache = request.query_params.get("_nocache") in ("1", "true", "True")
        cache_key = f"ai:observability:{date_from}:{date_to}:{group_by}"

        if not nocache:
            cached = cache.get(cache_key)
            if cached is not None:
                return Response({**cached, "cached": True})

        start = timezone.make_aware(datetime.combine(date_from, time.min))
        end = timezone.make_aware(datetime.combine(date_to, time.max))
        stats = decision_logger.aggregate_stats(start, end, group_by)

        ttl = int(AI_CONFIG["observability"]["dashboard_cache_seconds"])
        cache.set(cache_key, stats, timeout=ttl)

        return Response({**stats, "cached": False})


__all__ = ("AiObservabilityView",)
