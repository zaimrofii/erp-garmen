"""Endpoint **Purchase Order** MES (H2.2) — `/api/v1/garmen/purchase-orders/…`.

Kontrak (transaksi, sync satu arah MES → Odoo):

  * ``GET  /api/v1/garmen/purchase-orders/``            — ListPage (IsAuthenticated);
    filter ``?search=`` (kode/nama vendor), ``?state=``, ``?vendor_id=``;
  * ``POST /api/v1/garmen/purchase-orders/``            — create + ``lines[]`` nested;
  * ``GET  /api/v1/garmen/purchase-orders/<id>/``       — detail (+ ``lines[]``/``odoo_sync_status``);
  * ``PUT  /api/v1/garmen/purchase-orders/<id>/``       — update (DRAFT-only, replace ``lines[]``);
  * ``DELETE /api/v1/garmen/purchase-orders/<id>/``     — hard delete (DRAFT-only);
  * ``POST /api/v1/garmen/purchase-orders/<id>/confirm|done|cancel/`` — transisi §14;
  * ``POST /api/v1/garmen/purchase-orders/<id>/sync-odoo-state/``     — **read-only**:
    baca state PO di Odoo on-demand (untuk cek apakah sudah di-confirm di Odoo;
    TIDAK menulis field MES).

**Kenapa path-nya `/garmen/purchase-orders/…` dan bukan `/purchase/orders/`**:
`GET /api/v1/purchase/orders/` SUDAH DIPAKAI B10 (`monitoring.PurchaseOrdersView`,
read-only dari Odoo, bentuk baris di-pin 9 key oleh `tests/integration/test_purchase_orders.py`)
⇒ CRUD MES tidak boleh menempati path itu (akan memecah monitoring + test). Pola path
mengikuti H2.1 (`/api/v1/garmen/orders/…`) dan didaftarkan di `config/urls.py`
**SEBELUM** ``include("apps_industry.garment.api.urls")``.

Izin: baca = ``IsAuthenticated`` (anon 403); tulis/transisi = **PURCHASING/ADMIN/OWNER**
(selaras `PURCHASING_ROLES` frontend; role `purchasing` sudah ada sejak CHANGES-DETAIL §7).
"""

from __future__ import annotations

import logging

from django.db.models import Q
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps_industry.garment.models import PurchaseOrder
from apps_industry.garment.services import purchase_order_services

logger = logging.getLogger(__name__)

__all__ = (
    "PurchaseOrderActionView",
    "PurchaseOrderDetailView",
    "PurchaseOrderSyncStateView",
    "PurchaseOrdersView",
)

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
MAX_OFFSET = 100000

#: Role yang boleh menulis PO (selaras `PURCHASING_ROLES` di frontend).
PURCHASE_ORDER_WRITE_ROLE_CODES = ("PURCHASING", "ADMIN", "OWNER")

#: Aksi transisi yang dikenal endpoint ``/<id>/<action>/``.
PURCHASE_ORDER_ACTIONS = ("confirm", "done", "cancel")


def is_purchase_order_writer(user) -> bool:
    """True untuk superuser **atau** user ber-role PURCHASING/ADMIN/OWNER."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True

    role = getattr(user, "role", None)
    if role is None:
        return False

    return str(role.code or "").strip().upper() in PURCHASE_ORDER_WRITE_ROLE_CODES


def require_purchase_order_writer(request) -> None:
    """Raise ``PermissionDenied`` (403) kalau pemanggil bukan PURCHASING/ADMIN/OWNER."""
    if not is_purchase_order_writer(request.user):
        raise PermissionDenied(
            "Hanya user dengan role "
            f"{'/'.join(PURCHASE_ORDER_WRITE_ROLE_CODES)} yang boleh mengubah Purchase Order."
        )


def _list_params(request):
    """``(limit, offset, error)`` dari ``?limit``/``?cursor`` (pola H2.1/B22)."""
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
    """Baris PO + info tulis (``sync_record_id``/``task_id``/``queued``)."""
    body = purchase_order_services.purchase_order_detail_row(result.po)
    body.update(
        {
            "sync_record_id": result.sync_record_id,
            "task_id": result.task_id,
            "queued": result.queued,
        }
    )

    return body


class PurchaseOrdersView(APIView):
    """``GET|POST /api/v1/garmen/purchase-orders/`` — daftar & buat PO MES."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """List PO + filter; lihat docstring modul."""
        limit, offset, error = _list_params(request)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        queryset = PurchaseOrder.objects.select_related("vendor").prefetch_related("lines")

        state = str(request.query_params.get("state") or "").strip().upper()
        if state:
            if state not in purchase_order_services.PO_STATES:
                return Response(
                    {
                        "detail": (
                            f"Parameter 'state' harus salah satu: "
                            f"{', '.join(purchase_order_services.PO_STATES)}."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(state=state)

        vendor_id = request.query_params.get("vendor_id")
        if vendor_id not in (None, ""):
            try:
                queryset = queryset.filter(vendor_id=int(vendor_id))
            except (TypeError, ValueError):
                return Response(
                    {"detail": "Parameter 'vendor_id' harus berupa angka."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        search = str(request.query_params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(
                Q(code__icontains=search)
                | Q(vendor__name__icontains=search)
                | Q(partner_ref__icontains=search)
            )

        queryset = queryset.order_by("-created_at")
        total = queryset.count()
        rows = list(queryset[offset : offset + limit])

        return Response(
            _envelope(
                [purchase_order_services.purchase_order_row(row) for row in rows], total, offset
            )
        )

    def post(self, request):
        """Buat PO (nomor otomatis ``PO-<TAHUN>-<SEQ>``) + ``lines[]`` nested."""
        require_purchase_order_writer(request)

        result = purchase_order_services.create_purchase_order(request.data or {}, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        return Response(_write_body(result), status=status.HTTP_201_CREATED)


class PurchaseOrderDetailView(APIView):
    """``GET|PUT|DELETE /api/v1/garmen/purchase-orders/<id>/`` (DRAFT untuk ubah/hapus)."""

    permission_classes = [IsAuthenticated]

    @staticmethod
    def _get_po(po_id: int):
        """PO atau ``None`` (→ 404)."""
        return (
            PurchaseOrder.objects.select_related("vendor")
            .prefetch_related("lines__product", "lines__tax_ids")
            .filter(pk=po_id)
            .first()
        )

    def get(self, request, purchase_order_id: int):
        """Detail PO; lihat docstring modul."""
        po = self._get_po(purchase_order_id)
        if po is None:
            return Response(
                {"detail": "Purchase Order tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND
            )

        return Response(purchase_order_services.purchase_order_detail_row(po))

    def put(self, request, purchase_order_id: int):
        """Ubah PO (hanya DRAFT) + replace ``lines[]``."""
        require_purchase_order_writer(request)

        po = self._get_po(purchase_order_id)
        if po is None:
            return Response(
                {"detail": "Purchase Order tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND
            )

        result = purchase_order_services.update_purchase_order(
            po, request.data or {}, request=request
        )
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        return Response(_write_body(result))

    def delete(self, request, purchase_order_id: int):
        """Hapus PO (hanya DRAFT)."""
        require_purchase_order_writer(request)

        po = self._get_po(purchase_order_id)
        if po is None:
            return Response(
                {"detail": "Purchase Order tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND
            )

        result = purchase_order_services.delete_purchase_order(po, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"deleted": True, "id": purchase_order_id})


class PurchaseOrderActionView(APIView):
    """``POST /api/v1/garmen/purchase-orders/<id>/<action>/`` — transisi state (§14).

    ``action`` = ``confirm`` (DRAFT→CONFIRMED + push ke Odoo), ``done``
    (CONFIRMED→DONE, MES-only), ``cancel`` (→CANCELLED + ``action_cancel`` bila
    sudah punya ``odoo_id``).
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, purchase_order_id: int, action: str):
        """Jalankan transisi; lihat docstring modul."""
        require_purchase_order_writer(request)

        if action not in PURCHASE_ORDER_ACTIONS:
            return Response(
                {
                    "detail": (
                        f"Aksi '{action}' tidak dikenal "
                        f"(pilihan: {', '.join(PURCHASE_ORDER_ACTIONS)})."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        po = PurchaseOrderDetailView._get_po(purchase_order_id)
        if po is None:
            return Response(
                {"detail": "Purchase Order tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND
            )

        if action == "confirm":
            result = purchase_order_services.confirm_purchase_order(po, request=request)
        elif action == "done":
            result = purchase_order_services.done_purchase_order(po, request=request)
        else:
            result = purchase_order_services.cancel_purchase_order(
                po, request=request, reason=(request.data or {}).get("reason", "")
            )

        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        return Response(_write_body(result))


class PurchaseOrderSyncStateView(APIView):
    """``POST /api/v1/garmen/purchase-orders/<id>/sync-odoo-state/`` — baca state Odoo.

    **Read-only** (tidak memicu push dan tidak menulis field MES): berguna untuk
    memastikan purchasing sudah men-*confirm* PO di UI Odoo — syarat agar PO ikut
    dihitung `material_readiness` (I3 hanya membaca state ``purchase``/``done``).
    Respons: ``{odoo_id, odoo_state, odoo_name}``.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, purchase_order_id: int):
        """Baca state PO di Odoo; lihat docstring kelas."""
        require_purchase_order_writer(request)

        po = PurchaseOrderDetailView._get_po(purchase_order_id)
        if po is None:
            return Response(
                {"detail": "Purchase Order tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND
            )

        try:
            info = purchase_order_services.fetch_odoo_state(po)
        except purchase_order_services.PurchaseOrderError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(info)


