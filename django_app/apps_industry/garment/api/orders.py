"""Endpoint **Sales Order** MES (H2.1) — `/api/v1/garmen/orders/…`.

Kontrak (transaksi, sync satu arah MES → Odoo):

  * ``GET  /api/v1/garmen/orders/``            — ListPage (IsAuthenticated);
    filter ``?search=`` (code/nama customer), ``?state=``, ``?customer_id=``;
  * ``POST /api/v1/garmen/orders/``            — create + ``lines[]`` nested (ADMIN/OWNER);
  * ``GET  /api/v1/garmen/orders/<id>/``       — detail (+ ``lines[]`` + ``odoo_sync_status``);
  * ``PUT  /api/v1/garmen/orders/<id>/``       — update (DRAFT-only, replace ``lines[]``);
  * ``DELETE /api/v1/garmen/orders/<id>/``     — hard delete (DRAFT-only);
  * ``POST /api/v1/garmen/orders/<id>/confirm|done|cancel/`` — transisi state §14.

Didaftarkan di ``config/urls.py`` **SEBELUM** ``include("apps_industry.garment.api.urls")``
supaya tidak tertangkap pola ``v1/<industry>/<resource>/<id>/<action>/`` (ActionView).

Izin: baca = ``IsAuthenticated`` (anon 403); tulis/transisi = **ADMIN/OWNER**
(konsisten master H1; endpoint lama ``/garmen/work-orders|bundles`` tidak diubah).
"""

from __future__ import annotations

import logging

from django.db.models import Q
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps_industry.garment.models import Order
from apps_industry.garment.services import order_services, work_order_services

logger = logging.getLogger(__name__)

__all__ = ("OrderActionView", "OrderDetailView", "OrdersView")

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
MAX_OFFSET = 100000

#: Role yang boleh menulis order (konsisten master H1: ADMIN/OWNER).
ORDER_WRITE_ROLE_CODES = ("ADMIN", "OWNER")

#: Aksi transisi yang dikenal endpoint ``/<id>/<action>/``.
ORDER_ACTIONS = ("confirm", "done", "cancel")


def is_order_writer(user) -> bool:
    """True untuk superuser **atau** user ber-role ADMIN/OWNER (case-insensitive)."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True

    role = getattr(user, "role", None)
    if role is None:
        return False

    return str(role.code or "").strip().upper() in ORDER_WRITE_ROLE_CODES


def require_order_writer(request) -> None:
    """Raise ``PermissionDenied`` (403) kalau pemanggil bukan ADMIN/OWNER."""
    if not is_order_writer(request.user):
        raise PermissionDenied(
            "Hanya user dengan role "
            f"{'/'.join(ORDER_WRITE_ROLE_CODES)} yang boleh mengubah Sales Order."
        )


def _list_params(request):
    """``(limit, offset, error)`` dari ``?limit``/``?cursor`` (pola B22)."""
    try:
        limit = int(request.query_params.get("limit") or DEFAULT_LIMIT)
        offset = int(request.query_params.get("cursor") or 0)
    except (TypeError, ValueError):
        return None, None, "Parameter 'limit'/'cursor' harus berupa angka."

    if limit < 1 or limit > MAX_LIMIT:
        return None, None, f"Parameter 'limit' harus antara 1 dan {MAX_LIMIT}."
    if offset < 0 or offset > MAX_OFFSET:
        return None, None, f"Parameter 'cursor' harus antara 0 dan {MAX_OFFSET}."

    return limit, offset, None


def _envelope(rows: list, total: int, offset: int) -> dict:
    """Amplop ListPage: ``{rows, total_count, has_more, next_cursor}``."""
    has_more = offset + len(rows) < total

    return {
        "rows": rows,
        "total_count": total,
        "has_more": has_more,
        "next_cursor": (offset + len(rows)) if has_more else None,
    }


def _write_body(result) -> dict:
    """Baris order + info tulis (``sync_record_id``/``task_id``/``queued``)."""
    body = order_services.order_detail_row(result.order)
    body.update(
        {
            "sync_record_id": result.sync_record_id,
            "task_id": result.task_id,
            "queued": result.queued,
        }
    )

    return body



class OrdersView(APIView):
    """``GET|POST /api/v1/garmen/orders/`` — daftar & buat Sales Order MES."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """List order + filter; lihat docstring modul."""
        limit, offset, error = _list_params(request)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        queryset = Order.objects.select_related("customer").prefetch_related("lines")

        state = str(request.query_params.get("state") or "").strip().upper()
        if state:
            if state not in order_services.ORDER_STATES:
                return Response(
                    {
                        "detail": (
                            f"Parameter 'state' harus salah satu: "
                            f"{', '.join(order_services.ORDER_STATES)}."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(state=state)

        customer_id = request.query_params.get("customer_id")
        if customer_id not in (None, ""):
            try:
                queryset = queryset.filter(customer_id=int(customer_id))
            except (TypeError, ValueError):
                return Response(
                    {"detail": "Parameter 'customer_id' harus berupa angka."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        search = str(request.query_params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(
                Q(code__icontains=search) | Q(customer__name__icontains=search)
            )

        queryset = queryset.order_by("-created_at")
        total = queryset.count()
        rows = list(queryset[offset : offset + limit])

        return Response(
            _envelope([order_services.order_row(row) for row in rows], total, offset)
        )

    def post(self, request):
        """Buat order (nomor otomatis ``SO-<TAHUN>-<SEQ>``) + ``lines[]`` nested."""
        require_order_writer(request)

        result = order_services.create_order(request.data or {}, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        return Response(_write_body(result), status=status.HTTP_201_CREATED)


class OrderDetailView(APIView):
    """``GET|PUT|DELETE /api/v1/garmen/orders/<id>/`` — detail, ubah, hapus (DRAFT)."""

    permission_classes = [IsAuthenticated]

    @staticmethod
    def _get_order(order_id: int):
        """Order atau ``None`` (→ 404)."""
        return (
            Order.objects.select_related("customer")
            .prefetch_related("lines__product", "lines__tax_ids")
            .filter(pk=order_id)
            .first()
        )

    def get(self, request, order_id: int):
        """Detail order; lihat docstring modul."""
        order = self._get_order(order_id)
        if order is None:
            return Response({"detail": "Order tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND)

        return Response(order_services.order_detail_row(order))

    def put(self, request, order_id: int):
        """Ubah order (hanya DRAFT) + replace ``lines[]``."""
        require_order_writer(request)

        order = self._get_order(order_id)
        if order is None:
            return Response({"detail": "Order tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND)

        result = order_services.update_order(order, request.data or {}, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        return Response(_write_body(result))

    def delete(self, request, order_id: int):
        """Hapus order (hanya DRAFT)."""
        require_order_writer(request)

        order = self._get_order(order_id)
        if order is None:
            return Response({"detail": "Order tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND)

        result = order_services.delete_order(order, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"deleted": True, "id": order_id})


class OrderActionView(APIView):
    """``POST /api/v1/garmen/orders/<id>/<action>/`` — transisi state (§14).

    ``action`` = ``confirm`` (DRAFT→CONFIRMED + push ke Odoo), ``done``
    (CONFIRMED→DONE bila semua WorkOrder selesai), ``cancel`` (→CANCELLED,
    + ``action_cancel`` Odoo bila sudah punya ``odoo_id``).
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, order_id: int, action: str):
        """Jalankan transisi; lihat docstring modul."""
        require_order_writer(request)

        if action not in ORDER_ACTIONS:
            return Response(
                {
                    "detail": (
                        f"Aksi '{action}' tidak dikenal "
                        f"(pilihan: {', '.join(ORDER_ACTIONS)})."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        order = OrderDetailView._get_order(order_id)
        if order is None:
            return Response({"detail": "Order tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND)

        if action == "confirm":
            result = order_services.confirm_order(order, request=request)
        elif action == "done":
            result = order_services.done_order(order, request=request)
        else:
            result = order_services.cancel_order(
                order, request=request, reason=(request.data or {}).get("reason", "")
            )

        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        return Response(_write_body(result))



class OrderGenerateWorkOrdersView(APIView):
    """``POST /api/v1/garmen/orders/<id>/generate-wo/`` — batch generate WO (H2.3).

    Membuat **satu WO per OrderLine** yang belum punya WO (`qty_planned = OrderLine.qty`),
    **idempoten** (baris yang sudah punya WO dilewati) — jadi tombol "Generate WO" boleh
    ditekan berulang tanpa duplikat. Izin mengikuti endpoint tulis order lain
    (ADMIN/OWNER) karena ini masih pintu masuk dokumen order; penulisan WO-nya sendiri
    lewat service `work_order_services` (ledger `SKIPPED`, MES-only).
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, order_id: int):
        """Generate WO untuk semua OrderLine order ini; lihat docstring kelas."""
        require_order_writer(request)

        order = OrderDetailView._get_order(order_id)
        if order is None:
            return Response({"detail": "Order tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND)

        result = work_order_services.generate_work_orders_for_order(order, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "order_id": order.pk,
                "order_code": order.code,
                "summary": result.summary,
                "work_orders": [work_order_services.wo_row(wo) for wo in result.work_orders],
            },
            status=status.HTTP_201_CREATED,
        )

