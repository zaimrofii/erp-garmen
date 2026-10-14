"""Endpoint health check & utilitas app `apps_industry.garment`.

Health check container (`GET /api/health/`) adalah utilitas infrastruktur yang
dipertahankan dari app `core` supaya healthcheck docker-compose tetap jalan.
Sejak Fase A route-nya didaftarkan di `config/urls.py` (bukan `api/urls.py`),
supaya urutan resolve-nya eksplisit di depan pola industri.
"""

import logging

from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

logger = logging.getLogger(__name__)


@api_view(["GET"])
@permission_classes([AllowAny])
@throttle_classes([])
def health(request):
    """Health check container Django: `GET /api/health/`.

    Sengaja **dikecualikan dari rate limit** (Fase 6): healthcheck docker-compose
    dan monitoring tidak boleh ikut terdampak kuota request pengguna.
    """
    payload = {
        "status": "ok",
        "django": "running",
        "timestamp": timezone.localtime(timezone.now()).isoformat(),
    }
    logger.debug("health check dipanggil dari %s", request.META.get("REMOTE_ADDR"))
    return Response(payload)

