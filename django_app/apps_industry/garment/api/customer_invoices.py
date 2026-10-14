"""Endpoint **Customer Invoice** MES (H3.1) — `/api/v1/finance/customer-invoices/…`.

Kontrak (transaksi, sync satu arah MES → Odoo; invoice dikirim **draft**):

  * ``GET  /api/v1/finance/customer-invoices/``             — ListPage (IsAuthenticated);
    filter ``?search=`` (kode/nama customer), ``?state=``, ``?customer_id=``, ``?order_id=``;
  * ``POST /api/v1/finance/customer-invoices/``             — create (+ ``lines[]`` nested,
    auto-fill dari `OrderLine` bila ``lines`` tidak dikirim) → **201** + `duplicate_warning`
    bila order sudah punya invoice aktif (termin/DP; tidak diblokir);
  * ``GET  /api/v1/finance/customer-invoices/<id>/``        — detail (+ ``lines[]``,
    ``odoo_sync_status``, ``allowed_actions``);
  * ``PUT  /api/v1/finance/customer-invoices/<id>/``        — update (DRAFT-only);
  * ``DELETE /api/v1/finance/customer-invoices/<id>/``      — hard delete (DRAFT-only);
  * ``POST /api/v1/finance/customer-invoices/<id>/<action>/`` — transisi:
    ``confirm`` (DRAFT→CONFIRMED + push), ``done`` (CONFIRMED|SENT→DONE),
    ``cancel`` (DRAFT|CONFIRMED|SENT→CANCELLED, push ``button_cancel`` bila ada ``odoo_id``).

**Kenapa path-nya ``/finance/customer-invoices/…``**: ``GET /api/v1/finance/invoices/``
SUDAH DIPAKAI F10/F15 (`monitoring.InvoiceListView`, read-only dari ``SyncRecord``
dengan amplop ``has_next``) ⇒ CRUD MES tidak boleh menempati path itu (akan memecah
monitoring + test F15). Dua jalur invoice **coexist**: I5 otomatis (harga 0) vs H3.1
manual (harga nyata) — lihat `docs/integrations/CONTRACT.md`.

Izin: baca = ``IsAuthenticated`` (anon 403); tulis/transisi = **ADMIN/OWNER**
(selaras `FINANCE_ROLES` frontend; pola H3.5/H3.6).
"""

from __future__ import annotations

import logging

from django.db.models import Q
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps_industry.garment.models import CustomerInvoice
from apps_industry.garment.services import customer_invoice_services

logger = logging.getLogger(__name__)

__all__ = (
    "CustomerInvoiceActionView",
    "CustomerInvoiceDetailView",
    "CustomerInvoicesView",
    "is_customer_invoice_writer",
    "require_customer_invoice_writer",
)

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
MAX_OFFSET = 100000

#: Role yang boleh menulis invoice (selaras `FINANCE_ROLES` di frontend = admin/owner).
INVOICE_WRITE_ROLE_CODES = ("ADMIN", "OWNER")

#: Aksi transisi yang dikenal endpoint ``/<id>/<action>/``.
INVOICE_ACTIONS = ("confirm", "done", "cancel")


def is_customer_invoice_writer(user) -> bool:
    """True untuk superuser **atau** user ber-role ADMIN/OWNER."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True

    role = getattr(user, "role", None)
    if role is None:
        return False

    return str(role.code or "").strip().upper() in INVOICE_WRITE_ROLE_CODES


def require_customer_invoice_writer(request) -> None:
    """Raise ``PermissionDenied`` (403) kalau pemanggil bukan ADMIN/OWNER."""
    if not is_customer_invoice_writer(request.user):
        raise PermissionDenied(
            "Hanya user dengan role "
            f"{'/'.join(INVOICE_WRITE_ROLE_CODES)} yang boleh mengubah Customer Invoice."
        )


def _list_params(request):
    """``(limit, offset, error)`` dari ``?limit``/``?cursor`` (pola H2.1/H2.2)."""
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
    """Baris detail invoice + info tulis (``sync_record_id``/``task_id``/``queued``)."""
    body = customer_invoice_services.invoice_detail_row(result.invoice)
    body.update(
        {
            "sync_record_id": result.sync_record_id,
            "task_id": result.task_id,
            "queued": result.queued,
        }
    )

    return body



class CustomerInvoicesView(APIView):
    """``GET|POST /api/v1/finance/customer-invoices/`` — daftar & buat invoice MES."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """List invoice + filter; lihat docstring modul."""
        limit, offset, error = _list_params(request)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        queryset = CustomerInvoice.objects.select_related("customer", "order").prefetch_related(
            "lines"
        )

        state = str(request.query_params.get("state") or "").strip().upper()
        if state:
            if state not in customer_invoice_services.INVOICE_STATES:
                return Response(
                    {
                        "detail": (
                            "Parameter 'state' harus salah satu: "
                            f"{', '.join(customer_invoice_services.INVOICE_STATES)}."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(state=state)

        for param, field in (("customer_id", "customer_id"), ("order_id", "order_id")):
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
                | Q(customer__name__icontains=search)
                | Q(order__code__icontains=search)
            )

        queryset = queryset.order_by("-created_at")
        total = queryset.count()
        rows = list(queryset[offset : offset + limit])

        return Response(
            _envelope(
                [customer_invoice_services.invoice_row(row) for row in rows], total, offset
            )
        )

    def post(self, request):
        """Buat invoice (nomor ``INV-<TAHUN>-<SEQ>``) + ``lines[]`` nested/auto-fill."""
        require_customer_invoice_writer(request)

        result = customer_invoice_services.create_invoice(request.data or {}, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        body = _write_body(result)
        if result.duplicate_warning:
            # Peringatan (bukan error): order sudah punya invoice aktif → termin/DP?
            body["duplicate_warning"] = result.duplicate_warning

        return Response(body, status=status.HTTP_201_CREATED)



class CustomerInvoiceDetailView(APIView):
    """``GET|PUT|DELETE /api/v1/finance/customer-invoices/<id>/`` (DRAFT untuk ubah/hapus)."""

    permission_classes = [IsAuthenticated]

    @staticmethod
    def _get_invoice(invoice_id: int):
        """Invoice atau ``None`` (→ 404)."""
        return (
            CustomerInvoice.objects.select_related("customer", "order")
            .prefetch_related("lines__product", "lines__tax_ids")
            .filter(pk=invoice_id)
            .first()
        )

    def get(self, request, invoice_id: int):
        """Detail invoice; lihat docstring modul."""
        invoice = self._get_invoice(invoice_id)
        if invoice is None:
            return Response(
                {"detail": "Customer Invoice tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND
            )

        return Response(customer_invoice_services.invoice_detail_row(invoice))

    def put(self, request, invoice_id: int):
        """Ubah invoice (hanya DRAFT) + replace ``lines[]`` bila dikirim."""
        require_customer_invoice_writer(request)

        invoice = self._get_invoice(invoice_id)
        if invoice is None:
            return Response(
                {"detail": "Customer Invoice tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND
            )

        result = customer_invoice_services.update_invoice(
            invoice, request.data or {}, request=request
        )
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        return Response(_write_body(result))

    def delete(self, request, invoice_id: int):
        """Hapus invoice (hanya DRAFT)."""
        require_customer_invoice_writer(request)

        invoice = self._get_invoice(invoice_id)
        if invoice is None:
            return Response(
                {"detail": "Customer Invoice tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND
            )

        result = customer_invoice_services.delete_invoice(invoice, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        logger.info("customer_invoices: invoice %s dihapus lewat API.", invoice_id)
        return Response({"id": invoice_id, "deleted": True}, status=status.HTTP_200_OK)


class CustomerInvoiceActionView(APIView):
    """``POST /api/v1/finance/customer-invoices/<id>/<action>/`` — transisi state.

    ``action`` ∈ ``confirm`` | ``done`` | ``cancel`` (lihat docstring modul).
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, invoice_id: int, action: str):
        """Jalankan transisi; lihat docstring modul."""
        require_customer_invoice_writer(request)

        if action not in INVOICE_ACTIONS:
            return Response(
                {"detail": f"Aksi '{action}' tidak dikenal (pilih: {', '.join(INVOICE_ACTIONS)})."},
                status=status.HTTP_404_NOT_FOUND,
            )

        invoice = CustomerInvoiceDetailView._get_invoice(invoice_id)
        if invoice is None:
            return Response(
                {"detail": "Customer Invoice tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND
            )

        service = {
            "confirm": customer_invoice_services.confirm_invoice,
            "done": customer_invoice_services.done_invoice,
            "cancel": customer_invoice_services.cancel_invoice,
        }[action]

        result = service(invoice, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        logger.info("customer_invoices: invoice %s aksi '%s' lewat API.", invoice_id, action)
        return Response(_write_body(result), status=status.HTTP_200_OK)
