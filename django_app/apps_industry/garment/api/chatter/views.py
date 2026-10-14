"""Endpoint chatter: `GET /api/chatter/<resource>/<id>?cursor=` (Kontrak §3 & §8).

Chatter = jejak audit satu resource dengan paginasi cursor (preview 5 event sudah
dikirim di metadata schema — lihat `api/chatter/paginator.py`).

Sumber event saat ini hanya `BundleEvent`, jadi:
  * `bundles` -> event milik bundle itu;
  * `work-orders` -> event semua bundle di work order tersebut;
  * resource lain -> 404.

Catatan path (Fase A): route chatter sekarang didaftarkan di `config/urls.py`
sebelum include industri — dengan dan tanpa trailing slash, plus alias lama di
root `api/chatter/...` — supaya `/api/v1/chatter/bundles/1/` tidak pernah jatuh
ke `ResourceDetailView` (yang akan menganggap `industry="chatter"`).
"""

from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps_industry.garment.api.chatter.paginator import (
    PAGE_SIZE,
    chatter_page_payload,
)
from apps_industry.garment.models import BundleEvent

logger = logging.getLogger(__name__)

#: Default = `PAGE_SIZE` (= 5, sama dengan `CHATTER_PREVIEW_LIMIT` frontend) supaya
#: response lolos `ChatterPageSchema` (`preview` maks 5). Pemanggil masih boleh
#: minta lebih banyak lewat `?limit=N` (maks `MAX_LIMIT`).
DEFAULT_LIMIT = PAGE_SIZE
MAX_LIMIT = 100


def events_for(resource_name: str, instance_id: int):
    """Queryset event untuk resource+id, atau `None` kalau resource tak didukung."""
    if resource_name == "bundles":
        return BundleEvent.objects.filter(bundle_id=instance_id)
    if resource_name == "work-orders":
        return BundleEvent.objects.filter(bundle__work_order_id=instance_id)
    return None


class ChatterView(APIView):
    """Halaman chatter (paginasi cursor) untuk satu instance resource."""

    permission_classes = [AllowAny]  # auth menyusul Fase 6

    def get(self, request, resource: str, id: int):
        """Kembalikan halaman `ChatterPage` §8: `{preview, total_count, has_more, next_cursor}`."""
        resource_key = str(resource).strip().lower()
        queryset = events_for(resource_key, id)
        if queryset is None:
            return Response(
                {"detail": f"Chatter resource '{resource}' tidak dikenal."},
                status=status.HTTP_404_NOT_FOUND,
            )

        limit, error = self._int_param(request, "limit", DEFAULT_LIMIT)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        page = chatter_page_payload(
            queryset,
            cursor=request.query_params.get("cursor"),
            limit=limit,
        )
        return Response(page, status=status.HTTP_200_OK)

    @staticmethod
    def _int_param(request, name: str, default: int):
        """Baca query param angka; return `(value, error_message)`."""
        raw = request.query_params.get(name)
        if raw in (None, ""):
            return default, None
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return None, f"Parameter '{name}' harus berupa angka."
        if value < 1 or value > MAX_LIMIT:
            return None, f"Parameter '{name}' harus antara 1 dan {MAX_LIMIT}."
        return value, None
