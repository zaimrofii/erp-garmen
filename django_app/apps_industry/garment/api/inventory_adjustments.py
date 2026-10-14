"""Endpoint **Inventory Adjustment** (H2.5) — `/api/v1/inventory/…`.

Resource **baru** (tidak menabrak B7/B8/B30 yang read-only):

  * `POST  /api/v1/inventory/adjust/`              — buat log adjustment (`DRAFT`);
    `?commit=true` = langsung `COMMITTED` + enqueue push ke Odoo;
  * `GET   /api/v1/inventory/adjustments/`         — daftar log (audit) + filter
    (`search`, `state`, `product_id`, `location_id`) & envelope §3;
  * `GET   /api/v1/inventory/adjustments/<id>/`    — detail + info ledger sync;
  * `POST  /api/v1/inventory/adjustments/<id>/commit/` — `DRAFT → COMMITTED` + push;
  * `GET   /api/v1/inventory/stock-qty/?product_id=&location_id=` — on-demand on-hand
    Odoo (`stock.quant.quantity`, **read-only**, tanpa cache di MES).

Izin: **`IsAuthenticated` tanpa role** (keputusan pemilik proyek H2.5, konsisten
H2.1–H2.4 + simulator). Frontend memakai guard `INVENTORY_ROLES` yang sudah ada.

⚠️ MES **tidak** menyimpan stok (`docs/CHANGES-DETAIL-H1H5.md` §4) — endpoint ini
hanya mengelola **log** adjustment + memicu sync satu arah ke Odoo.
"""

from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps_industry.garment.api.resources.list_view import ResourceListView
from apps_industry.garment.models import InventoryAdjustment
from apps_industry.garment.services import inventory_adjustment_services as services
from master.models import Location, Product

logger = logging.getLogger(__name__)

__all__ = (
    "InventoryAdjustmentListCreateView",
    "InventoryAdjustmentDetailView",
    "InventoryAdjustmentCommitView",
    "InventoryStockQtyView",
)

INDUSTRY = "garmen"
RESOURCE = "inventory_adjustments"
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


class InventoryAdjustmentListCreateView(APIView):
    """``GET`` daftar log adjustment + ``POST`` create (H2.5)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """ListPage §3 + filter (`search`/`state`/`product_id`/`location_id`)."""
        limit, error = ResourceListView._int_param(request, "limit", DEFAULT_LIMIT, 1, MAX_LIMIT)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        offset, error = ResourceListView._int_param(request, "offset", 0, 0, 100_000)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        queryset = InventoryAdjustment.objects.select_related("product", "location", "created_by")
        queryset = self._apply_filters(request, queryset)

        total = queryset.count()
        rows = [services.adjustment_row(instance) for instance in queryset[offset : offset + limit]]

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
        """Filter: ``search`` (kode/alasan), ``state``, ``product_id``, ``location_id``."""
        search = str(request.query_params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(code__icontains=search) | queryset.filter(
                reason__icontains=search
            )

        state = str(request.query_params.get("state") or "").strip()
        if state:
            queryset = queryset.filter(state__iexact=state)

        product_id = str(request.query_params.get("product_id") or "").strip()
        if product_id:
            parsed = services._first_id(product_id)
            queryset = queryset.none() if parsed is None else queryset.filter(product_id=parsed)

        location_id = str(request.query_params.get("location_id") or "").strip()
        if location_id:
            parsed = services._first_id(location_id)
            queryset = queryset.none() if parsed is None else queryset.filter(location_id=parsed)

        return queryset.order_by("-created_at", "-id")

    def post(self, request):
        """Buat log adjustment; `?commit=true` → sekaligus kirim ke Odoo."""
        result = services.create_adjustment(request.data or {}, request=request)
        if result.error:
            return _error_response(result)

        body: dict = services.adjustment_detail_row(result.adjustment)
        body["industry"] = INDUSTRY

        if _truthy(request.query_params.get("commit")):
            commit = services.commit_adjustment(result.adjustment, request=request)
            if commit.error:
                # Log tetap tersimpan (DRAFT) — kirim barisnya + alasan gagal commit.
                body["commit"] = {"ok": False, "detail": commit.error}
                return Response(body, status=status.HTTP_201_CREATED)

            body = services.adjustment_detail_row(commit.adjustment)
            body["industry"] = INDUSTRY
            body["commit"] = {
                "ok": True,
                "ledger_id": commit.ledger_id,
                "task_id": commit.task_id,
                "queued": commit.queued,
            }

        return Response(body, status=status.HTTP_201_CREATED)


class InventoryAdjustmentDetailView(APIView):
    """``GET /api/v1/inventory/adjustments/<id>/`` — detail log + info sync."""

    permission_classes = [IsAuthenticated]

    def get(self, request, adjustment_id: int):
        """Baris detail (404 kalau tidak ada)."""
        adj = (
            InventoryAdjustment.objects.select_related("product", "location", "created_by")
            .filter(pk=adjustment_id)
            .first()
        )
        if adj is None:
            return Response(
                {"detail": f"Inventory adjustment {adjustment_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        body = services.adjustment_detail_row(adj)
        body["industry"] = INDUSTRY

        return Response(body, status=status.HTTP_200_OK)


class InventoryAdjustmentCommitView(APIView):
    """``POST /api/v1/inventory/adjustments/<id>/commit/`` — kirim ke Odoo."""

    permission_classes = [IsAuthenticated]

    def post(self, request, adjustment_id: int):
        """``DRAFT → COMMITTED`` + enqueue push (404/409/400 sesuai guard)."""
        adj = (
            InventoryAdjustment.objects.select_related("product", "location")
            .filter(pk=adjustment_id)
            .first()
        )
        if adj is None:
            return Response(
                {"detail": f"Inventory adjustment {adjustment_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        result = services.commit_adjustment(adj, request=request)
        if result.error:
            return _error_response(result)

        body = services.adjustment_detail_row(result.adjustment)
        body["industry"] = INDUSTRY
        body["ledger_id"] = result.ledger_id
        body["task_id"] = result.task_id
        body["queued"] = result.queued

        return Response(body, status=status.HTTP_200_OK)


class InventoryStockQtyView(APIView):
    """``GET /api/v1/inventory/stock-qty/`` — on-hand Odoo **on-demand** (read-only).

    MES tidak menyimpan stok: nilai dibaca langsung dari `stock.quant.quantity`
    (lokasi harus `usage='internal'`). ``qty`` = ``null`` kalau Odoo belum bisa dibaca
    (mis. `odoo_id` belum ada / kredensial kosong) — UI menampilkan statusnya apa adanya.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """`?product_id=&location_id=` → ``{product_id, location_id, qty, source}``."""
        product_id = services._first_id(request.query_params.get("product_id"))
        location_id = services._first_id(request.query_params.get("location_id"))
        if product_id is None or location_id is None:
            return Response(
                {"detail": "Parameter 'product_id' & 'location_id' wajib diisi (angka)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        product = Product.objects.filter(pk=product_id).first()
        if product is None:
            return Response(
                {"detail": f"Product {product_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )
        location = Location.objects.filter(pk=location_id).first()
        if location is None:
            return Response(
                {"detail": f"Location {location_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if location.usage != services.ALLOWED_LOCATION_USAGE:
            return Response(
                {
                    "detail": (
                        f"Location usage='{location.usage}'; stok hanya dibaca untuk lokasi "
                        f"usage='{services.ALLOWED_LOCATION_USAGE}'."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        qty = services.fetch_stock_qty(product, location)

        return Response(
            {
                "product_id": product.pk,
                "product_code": product.code,
                "product_odoo_id": product.odoo_id,
                "location_id": location.pk,
                "location_code": location.code,
                "location_odoo_id": location.odoo_id,
                "qty": None if qty is None else str(qty),
                "source": "odoo",
                "stock_owner": "odoo",
                "industry": INDUSTRY,
            },
            status=status.HTTP_200_OK,
        )

