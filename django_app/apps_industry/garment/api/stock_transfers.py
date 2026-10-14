"""Endpoint **Stock Transfer** (H2.6) — `/api/v1/inventory/transfer*`.

Resource **baru** (tidak menabrak B7/B8/B30 maupun H2.5):

  * `POST  /api/v1/inventory/transfer/`             — buat log transfer (`DRAFT`);
    `?commit=true` = langsung `COMMITTED` + enqueue push ke Odoo;
  * `GET   /api/v1/inventory/transfers/`            — daftar log (audit) + filter
    (`search`, `state`, `product_id`, `from_location_id`, `to_location_id`) & envelope §3;
  * `GET   /api/v1/inventory/transfers/<id>/`       — detail + info ledger sync;
  * `POST  /api/v1/inventory/transfers/<id>/commit/` — `DRAFT → COMMITTED` + push.

Pre-flight stok memakai endpoint H2.5 yang SUDAH ADA
(`GET /api/v1/inventory/stock-qty/`) — TIDAK ada endpoint baru untuk itu.

Izin: **`IsAuthenticated` tanpa role** (konsisten H2.1–H2.5). Frontend memakai guard
`INVENTORY_ROLES` yang sudah ada.
"""

from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps_industry.garment.api.resources.list_view import ResourceListView
from apps_industry.garment.models import StockTransfer
from apps_industry.garment.services import stock_transfer_services as services

logger = logging.getLogger(__name__)

__all__ = (
    "StockTransferListCreateView",
    "StockTransferDetailView",
    "StockTransferCommitView",
)

INDUSTRY = "garmen"
RESOURCE = "stock_transfers"
DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def _error_response(result) -> Response:
    """Peta error service → status (404 tidak ada / 409 konflik / 400 validasi)."""
    if result.not_found:
        code = status.HTTP_404_NOT_FOUND
    elif result.conflict:
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_400_BAD_REQUEST

    return Response({"detail": result.error}, status=code)


def _truthy(value) -> bool:
    """Parser query flag sederhana (`1/true/yes/on`)."""
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


class StockTransferListCreateView(APIView):
    """``GET`` daftar log transfer + ``POST`` create (H2.6)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """ListPage §3 + filter (`search`/`state`/produk/lokasi asal-tujuan)."""
        limit, error = ResourceListView._int_param(request, "limit", DEFAULT_LIMIT, 1, MAX_LIMIT)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        offset, error = ResourceListView._int_param(request, "offset", 0, 0, 100_000)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        queryset = StockTransfer.objects.select_related(
            "product", "from_location", "to_location", "created_by"
        )
        queryset = self._apply_filters(request, queryset)

        total = queryset.count()
        rows = [services.transfer_row(instance) for instance in queryset[offset : offset + limit]]

        return Response(
            {
                "rows": rows,
                "total_count": total,
                "has_more": offset + len(rows) < total,
                "next_cursor": None,
                "resource": RESOURCE,
                "industry": INDUSTRY,
            },
            status=status.HTTP_200_OK,
        )

    @staticmethod
    def _apply_filters(request, queryset):
        """Filter: ``search`` (kode/catatan), ``state``, produk, lokasi asal/tujuan."""
        search = str(request.query_params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(code__icontains=search) | queryset.filter(
                reason__icontains=search
            )

        state = str(request.query_params.get("state") or "").strip()
        if state:
            queryset = queryset.filter(state__iexact=state)

        for param, field in (
            ("product_id", "product_id"),
            ("from_location_id", "from_location_id"),
            ("to_location_id", "to_location_id"),
        ):
            raw = str(request.query_params.get(param) or "").strip()
            if not raw:
                continue
            parsed = services._first_id(raw)
            queryset = queryset.none() if parsed is None else queryset.filter(**{field: parsed})

        return queryset.order_by("-created_at", "-id")

    def post(self, request):
        """Buat log transfer; `?commit=true` → sekaligus kirim ke Odoo."""
        result = services.create_transfer(request.data or {}, request=request)
        if result.error:
            return _error_response(result)

        body: dict = services.transfer_detail_row(result.transfer)
        body["industry"] = INDUSTRY

        if _truthy(request.query_params.get("commit")):
            commit = services.commit_transfer(result.transfer, request=request)
            if commit.error:
                # Log tetap tersimpan (DRAFT) — kirim barisnya + alasan gagal commit.
                body["commit"] = {"ok": False, "detail": commit.error}
                return Response(body, status=status.HTTP_201_CREATED)

            body = services.transfer_detail_row(commit.transfer)
            body["industry"] = INDUSTRY
            body["commit"] = {
                "ok": True,
                "ledger_id": commit.ledger_id,
                "task_id": commit.task_id,
                "queued": commit.queued,
            }

        return Response(body, status=status.HTTP_201_CREATED)


class StockTransferDetailView(APIView):
    """``GET /api/v1/inventory/transfers/<id>/`` — detail log + info sync."""

    permission_classes = [IsAuthenticated]

    def get(self, request, transfer_id: int):
        """Baris detail (404 kalau tidak ada)."""
        transfer = (
            StockTransfer.objects.select_related(
                "product", "from_location", "to_location", "created_by"
            )
            .filter(pk=transfer_id)
            .first()
        )
        if transfer is None:
            return Response(
                {"detail": f"Stock transfer {transfer_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        body = services.transfer_detail_row(transfer)
        body["industry"] = INDUSTRY

        return Response(body, status=status.HTTP_200_OK)


class StockTransferCommitView(APIView):
    """``POST /api/v1/inventory/transfers/<id>/commit/`` — kirim ke Odoo."""

    permission_classes = [IsAuthenticated]

    def post(self, request, transfer_id: int):
        """``DRAFT → COMMITTED`` + enqueue push (404/409/400 sesuai guard)."""
        transfer = (
            StockTransfer.objects.select_related("product", "from_location", "to_location")
            .filter(pk=transfer_id)
            .first()
        )
        if transfer is None:
            return Response(
                {"detail": f"Stock transfer {transfer_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        result = services.commit_transfer(transfer, request=request)
        if result.error:
            return _error_response(result)

        body = services.transfer_detail_row(result.transfer)
        body["industry"] = INDUSTRY
        body["ledger_id"] = result.ledger_id
        body["task_id"] = result.task_id
        body["queued"] = result.queued

        return Response(body, status=status.HTTP_200_OK)
