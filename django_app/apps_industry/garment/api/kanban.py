"""Endpoint **Kanban** MES (FASE K2) — `/api/v1/garmen/<resource>/kanban/`.

Satu request = satu papan: kolom (dari `core.state_machine.State`), kartu tiap
kolom, dan transisi aktif mesin. Ini menggantikan pola "N request per kolom"
(`GET /bundles/?state=…` untuk tiap state) yang dipakai halaman list biasa.

Didaftarkan (`api/urls.py`):

  * ``GET /api/v1/garmen/bundles/kanban/``     -> `BundleKanbanView`
  * ``GET /api/v1/garmen/work-orders/kanban/`` -> `WorkOrderKanbanView`

Query param (lihat `services/kanban_services.py`):

  * ``?state=`` / ``?search=`` — sama seperti list H2.4 (`state` tunggal berguna
    untuk deep-link ke satu kolom);
  * ``?work_center_id=`` / ``?line_id=`` / ``?work_order_id=`` — hanya berlaku di
    resource yang punya FK-nya (bundles); param yang tidak berlaku dilaporkan di
    ``filters.ignored`` (bukan dibuang diam-diam);
  * ``?limit=`` — batas kartu **per kolom** (default 50, maks 200). `count` tetap
    jumlah sebenarnya dan `truncated` menandai pemotongan.

Izin: **`IsAuthenticated`** (anonim -> 403) — papan memuat data produksi + tombol
aksi `POST …/<id>/<ACTION_ID>/`, jadi levelnya disamakan dengan `ActionView`
(FASE 4.1). Bentuk balasan lengkap ada di docstring `kanban_services`.
"""

from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps_industry.garment.api.industries import require_industry
from apps_industry.garment.api.resources.list_view import ResourceListView
from apps_industry.garment.services import kanban_services

logger = logging.getLogger(__name__)

__all__ = ("BundleKanbanView", "KanbanView", "WorkOrderKanbanView")


class KanbanView(APIView):
    """Papan kanban satu resource (kolom + kartu + transisi) — basis dua subclass."""

    permission_classes = [IsAuthenticated]

    #: Resource kanonik (`MACHINE_CODES` di service) — diisi subclass.
    RESOURCE = ""

    def get(self, request, industry: str):
        """Balas `{columns, transitions, ...}` untuk SELURUH kolom (kontrak K2)."""
        # Fase A: industri divalidasi lebih dulu (404 eksplisit) sebelum data.
        industry_code = require_industry(industry)

        limit, error = ResourceListView._int_param(
            request,
            "limit",
            kanban_services.DEFAULT_LIMIT_PER_COLUMN,
            1,
            kanban_services.MAX_LIMIT_PER_COLUMN,
        )
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        try:
            machine = kanban_services.get_state_machine_for_resource(self.RESOURCE)
        except (
            kanban_services.UnknownKanbanResource,
            kanban_services.KanbanMachineNotFound,
        ) as exc:
            # Fail-closed: resource tanpa definisi state machine tidak boleh
            # menebak kolom dari data (itu hardcode terselubung).
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)

        queryset, filter_info = kanban_services.apply_kanban_filters(
            self.RESOURCE,
            kanban_services.get_kanban_queryset(self.RESOURCE),
            request.query_params,
        )
        payload = kanban_services.build_kanban_response(
            self.RESOURCE,
            queryset,
            machine,
            industry=industry_code,
            limit=limit,
            query_params=request.query_params,
        )
        payload["filters"] = filter_info

        return Response(payload, status=status.HTTP_200_OK)


class BundleKanbanView(KanbanView):
    """``GET /api/v1/garmen/bundles/kanban/`` — mesin `garment.bundle`."""

    RESOURCE = "bundles"


class WorkOrderKanbanView(KanbanView):
    """``GET /api/v1/garmen/work-orders/kanban/`` — mesin `garment.work_order`."""

    RESOURCE = "work-orders"
