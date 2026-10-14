"""Endpoint **Vendor Bill** MES (H3.2) — `/api/v1/finance/vendor-bills/…`.

Kontrak (transaksi, sync satu arah MES → Odoo; bill dikirim **draft** `in_invoice`):

  * ``GET  /api/v1/finance/vendor-bills/``             — ListPage (IsAuthenticated);
    filter ``?search=`` (kode/ref/nama vendor/kode PO), ``?state=``, ``?vendor_id=``,
    ``?purchase_order_id=``;
  * ``POST /api/v1/finance/vendor-bills/``             — create (+ ``lines[]`` nested,
    auto-fill dari `PurchaseOrderLine` bila ``lines`` tidak dikirim) → **201** +
    ``duplicate_warning`` bila PO sudah punya bill aktif (termin/partial; tidak diblokir);
  * ``GET  /api/v1/finance/vendor-bills/<id>/``        — detail (+ ``lines[]``,
    ``odoo_sync_status``, ``allowed_actions``);
  * ``PUT  /api/v1/finance/vendor-bills/<id>/``        — update (DRAFT-only);
  * ``DELETE /api/v1/finance/vendor-bills/<id>/``      — hard delete (DRAFT-only);
  * ``POST /api/v1/finance/vendor-bills/<id>/<action>/`` — transisi:
    ``confirm`` (DRAFT→CONFIRMED + push), ``done`` (CONFIRMED|SENT→DONE),
    ``cancel`` (DRAFT|CONFIRMED|SENT→CANCELLED, push ``button_cancel`` bila ada ``odoo_id``).

**Kenapa path-nya ``/finance/vendor-bills/…``**: konsisten H3.1
(`/finance/customer-invoices/…`) dan **bebas bentrok** — ``/finance/invoices/``
sudah dipakai F10/F15, sedangkan ``/purchase/*`` dipakai B10/B11/B12 (read-only
Odoo) dan ``/garmen/purchase-orders/…`` dipakai H2.2. Jalur **I6** (tarik
``fetch_vendor_bills`` → `MaterialReadiness.vendor_bill_*`) **tidak disentuh**:
ia tidak punya endpoint CRUD di MES. Lihat `docs/integrations/CONTRACT.md`.

Izin: baca = ``IsAuthenticated`` (anon 403); tulis/transisi = **ADMIN/OWNER**
(selaras `FINANCE_ROLES` frontend; pola H3.1/H3.5/H3.6).
"""

from __future__ import annotations

import logging

from django.db.models import Q
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps_industry.garment.models import VendorBill
from apps_industry.garment.services import vendor_bill_services

logger = logging.getLogger(__name__)

__all__ = (
    "VendorBillActionView",
    "VendorBillDetailView",
    "VendorBillsView",
    "is_vendor_bill_writer",
    "require_vendor_bill_writer",
)

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
MAX_OFFSET = 100000

#: Role yang boleh menulis bill (selaras `FINANCE_ROLES` di frontend = admin/owner).
BILL_WRITE_ROLE_CODES = ("ADMIN", "OWNER")

#: Aksi transisi yang dikenal endpoint ``/<id>/<action>/``.
BILL_ACTIONS = ("confirm", "done", "cancel")


def is_vendor_bill_writer(user) -> bool:
    """True untuk superuser **atau** user ber-role ADMIN/OWNER."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True

    role = getattr(user, "role", None)
    if role is None:
        return False

    return str(role.code or "").strip().upper() in BILL_WRITE_ROLE_CODES


def require_vendor_bill_writer(request) -> None:
    """Raise ``PermissionDenied`` (403) kalau pemanggil bukan ADMIN/OWNER."""
    if not is_vendor_bill_writer(request.user):
        raise PermissionDenied(
            "Hanya user dengan role "
            f"{'/'.join(BILL_WRITE_ROLE_CODES)} yang boleh mengubah Vendor Bill."
        )


def _list_params(request):
    """``(limit, offset, error)`` dari ``?limit``/``?cursor`` (pola H2.1/H2.2/H3.1)."""
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
    """Baris detail bill + info tulis (``sync_record_id``/``task_id``/``queued``)."""
    body = vendor_bill_services.bill_detail_row(result.bill)
    body.update(
        {
            "sync_record_id": result.sync_record_id,
            "task_id": result.task_id,
            "queued": result.queued,
        }
    )

    return body


class VendorBillsView(APIView):
    """``GET|POST /api/v1/finance/vendor-bills/`` — daftar & buat bill MES."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """List bill + filter; lihat docstring modul."""
        limit, offset, error = _list_params(request)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        queryset = VendorBill.objects.select_related("vendor", "purchase_order").prefetch_related(
            "lines"
        )

        state = str(request.query_params.get("state") or "").strip().upper()
        if state:
            if state not in vendor_bill_services.BILL_STATES:
                return Response(
                    {
                        "detail": (
                            "Parameter 'state' harus salah satu: "
                            f"{', '.join(vendor_bill_services.BILL_STATES)}."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(state=state)

        for param, field in (
            ("vendor_id", "vendor_id"),
            ("purchase_order_id", "purchase_order_id"),
        ):
            raw = request.query_params.get(param)
            if raw in (None, ""):
                continue
            try:
                queryset = queryset.filter(**{field: int(raw)})
            except (TypeError, ValueError):
                return Response(
                    {"detail": f"Parameter '{param}' harus berupa angka."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        search = str(request.query_params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(
                Q(code__icontains=search)
                | Q(ref__icontains=search)
                | Q(vendor__name__icontains=search)
                | Q(purchase_order__code__icontains=search)
            )

        queryset = queryset.order_by("-created_at")
        total = queryset.count()
        rows = list(queryset[offset : offset + limit])

        return Response(
            _envelope([vendor_bill_services.bill_row(row) for row in rows], total, offset)
        )

    def post(self, request):
        """Buat bill (nomor ``VB-<TAHUN>-<SEQ>``) + ``lines[]`` nested/auto-fill."""
        require_vendor_bill_writer(request)

        result = vendor_bill_services.create_bill(request.data or {}, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        body = _write_body(result)
        if result.duplicate_warning:
            # Peringatan (bukan error): PO sudah punya bill aktif → termin/partial?
            body["duplicate_warning"] = result.duplicate_warning

        return Response(body, status=status.HTTP_201_CREATED)


class VendorBillDetailView(APIView):
    """``GET|PUT|DELETE /api/v1/finance/vendor-bills/<id>/`` (DRAFT untuk ubah/hapus)."""

    permission_classes = [IsAuthenticated]

    @staticmethod
    def _get_bill(bill_id: int):
        """Bill atau ``None`` (→ 404)."""
        return (
            VendorBill.objects.select_related("vendor", "purchase_order")
            .prefetch_related("lines__product", "lines__tax_ids")
            .filter(pk=bill_id)
            .first()
        )

    def get(self, request, bill_id: int):
        """Detail bill; lihat docstring modul."""
        bill = self._get_bill(bill_id)
        if bill is None:
            return Response(
                {"detail": "Vendor Bill tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND
            )

        return Response(vendor_bill_services.bill_detail_row(bill))

    def put(self, request, bill_id: int):
        """Ubah bill (hanya DRAFT) + replace ``lines[]`` bila dikirim."""
        require_vendor_bill_writer(request)

        bill = self._get_bill(bill_id)
        if bill is None:
            return Response(
                {"detail": "Vendor Bill tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND
            )

        result = vendor_bill_services.update_bill(bill, request.data or {}, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        return Response(_write_body(result))

    def delete(self, request, bill_id: int):
        """Hapus bill (hanya DRAFT)."""
        require_vendor_bill_writer(request)

        bill = self._get_bill(bill_id)
        if bill is None:
            return Response(
                {"detail": "Vendor Bill tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND
            )

        result = vendor_bill_services.delete_bill(bill, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        logger.info("vendor_bills: bill %s dihapus lewat API.", bill_id)
        return Response({"id": bill_id, "deleted": True}, status=status.HTTP_200_OK)


class VendorBillActionView(APIView):
    """``POST /api/v1/finance/vendor-bills/<id>/<action>/`` — transisi state.

    ``action`` ∈ ``confirm`` | ``done`` | ``cancel`` (lihat docstring modul).
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, bill_id: int, action: str):
        """Jalankan transisi; lihat docstring modul."""
        require_vendor_bill_writer(request)

        if action not in BILL_ACTIONS:
            return Response(
                {"detail": f"Aksi '{action}' tidak dikenal (pilih: {', '.join(BILL_ACTIONS)})."},
                status=status.HTTP_404_NOT_FOUND,
            )

        bill = VendorBillDetailView._get_bill(bill_id)
        if bill is None:
            return Response(
                {"detail": "Vendor Bill tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND
            )

        service = {
            "confirm": vendor_bill_services.confirm_bill,
            "done": vendor_bill_services.done_bill,
            "cancel": vendor_bill_services.cancel_bill,
        }[action]

        result = service(bill, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        logger.info("vendor_bills: bill %s aksi '%s' lewat API.", bill_id, action)
        return Response(_write_body(result), status=status.HTTP_200_OK)


