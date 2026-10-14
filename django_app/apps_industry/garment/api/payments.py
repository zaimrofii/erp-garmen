"""Endpoint **Payment** MES (H3.3) — `/api/v1/finance/payments/…`.

Kontrak (transaksi, sync satu arah MES → Odoo; payment dikirim **draft**):

  * ``GET  /api/v1/finance/payments/``             — ListPage (IsAuthenticated);
    filter ``?search=`` (kode/referensi/nama partner/kode sumber), ``?state=``,
    ``?payment_type=``, ``?partner_id=``, ``?customer_invoice_id=``, ``?vendor_bill_id=``;
  * ``POST /api/v1/finance/payments/``             — create (ADMIN/OWNER) → **201**
    (guard anti-overpay terhadap dokumen sumber);
  * ``GET  /api/v1/finance/payments/<id>/``        — detail (+ ``odoo_sync_status``,
    ``source_amount_total``, ``source_remaining_amount``, ``allowed_actions``);
  * ``PUT  /api/v1/finance/payments/<id>/``        — update (DRAFT-only);
  * ``DELETE /api/v1/finance/payments/<id>/``      — hard delete (DRAFT-only);
  * ``POST /api/v1/finance/payments/<id>/<action>/`` — transisi:
    ``confirm`` (DRAFT→CONFIRMED + push), ``done`` (CONFIRMED|SENT→DONE),
    ``cancel`` (DRAFT|CONFIRMED|SENT→CANCELLED, push ``action_cancel`` bila ``odoo_id``).

**Kenapa path-nya ``/finance/payments/…``**: konsisten H3.1/H3.2 dan **bebas bentrok**
(``/finance/invoices/`` = F15 read-only, ``/finance/customer-invoices/`` = H3.1,
``/finance/vendor-bills/`` = H3.2). Ledger memakai resource ``payment`` + stage
``PAYMENT`` (keduanya BARU) sehingga tidak menimpa baris `SyncRecord` jalur lain.

**Rekonsiliasi BUKAN di MES** (keputusan STEP 0): endpoint ini hanya membuat
``account.payment`` **draft** di Odoo; posting & rekonsiliasi dilakukan akuntan.

Izin: baca = ``IsAuthenticated`` (anon 403); tulis/transisi = **ADMIN/OWNER**
(selaras `FINANCE_ROLES` frontend; pola H3.1/H3.2/H3.5/H3.6).
"""

from __future__ import annotations

import logging

from django.db.models import Q
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps_industry.garment.models import Payment
from apps_industry.garment.services import payment_services

logger = logging.getLogger(__name__)

__all__ = (
    "PaymentActionView",
    "PaymentDetailView",
    "PaymentsView",
    "is_payment_writer",
    "require_payment_writer",
)

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
MAX_OFFSET = 100000

#: Role yang boleh menulis payment (selaras `FINANCE_ROLES` di frontend = admin/owner).
PAYMENT_WRITE_ROLE_CODES = ("ADMIN", "OWNER")

#: Aksi transisi yang dikenal endpoint ``/<id>/<action>/``.
PAYMENT_ACTIONS = ("confirm", "done", "cancel")


def is_payment_writer(user) -> bool:
    """True untuk superuser **atau** user ber-role ADMIN/OWNER."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True

    role = getattr(user, "role", None)
    if role is None:
        return False

    return str(role.code or "").strip().upper() in PAYMENT_WRITE_ROLE_CODES


def require_payment_writer(request) -> None:
    """Raise ``PermissionDenied`` (403) kalau pemanggil bukan ADMIN/OWNER."""
    if not is_payment_writer(request.user):
        raise PermissionDenied(
            "Hanya user dengan role "
            f"{'/'.join(PAYMENT_WRITE_ROLE_CODES)} yang boleh mengubah Payment."
        )


def _list_params(request):
    """``(limit, offset, error)`` dari ``?limit``/``?cursor`` (pola H2.1/H2.2/H3.1/H3.2)."""
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
    """Baris detail payment + info tulis (``sync_record_id``/``task_id``/``queued``)."""
    body = payment_services.payment_detail_row(result.payment)
    body.update(
        {
            "sync_record_id": result.sync_record_id,
            "task_id": result.task_id,
            "queued": result.queued,
        }
    )

    return body


class PaymentsView(APIView):
    """``GET|POST /api/v1/finance/payments/`` — daftar & buat payment MES."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """List payment + filter; lihat docstring modul."""
        limit, offset, error = _list_params(request)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        queryset = Payment.objects.select_related(
            "partner", "customer_invoice", "vendor_bill"
        )

        state = str(request.query_params.get("state") or "").strip().upper()
        if state:
            if state not in payment_services.PAYMENT_STATES:
                return Response(
                    {
                        "detail": (
                            "Parameter 'state' harus salah satu: "
                            f"{', '.join(payment_services.PAYMENT_STATES)}."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(state=state)

        payment_type = str(request.query_params.get("payment_type") or "").strip().upper()
        if payment_type:
            if payment_type not in (
                payment_services.PAYMENT_INBOUND,
                payment_services.PAYMENT_OUTBOUND,
            ):
                return Response(
                    {
                        "detail": (
                            "Parameter 'payment_type' harus 'INBOUND' atau 'OUTBOUND'."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(payment_type=payment_type)

        for param, field in (
            ("partner_id", "partner_id"),
            ("customer_invoice_id", "customer_invoice_id"),
            ("vendor_bill_id", "vendor_bill_id"),
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
                | Q(reference__icontains=search)
                | Q(partner__name__icontains=search)
                | Q(customer_invoice__code__icontains=search)
                | Q(vendor_bill__code__icontains=search)
            )

        queryset = queryset.order_by("-created_at")
        total = queryset.count()
        rows = list(queryset[offset : offset + limit])

        return Response(
            _envelope([payment_services.payment_row(row) for row in rows], total, offset)
        )

    def post(self, request):
        """Buat payment (nomor ``PAY-<TAHUN>-<SEQ>``) + guard anti-overpay."""
        require_payment_writer(request)

        result = payment_services.create_payment(request.data or {}, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        return Response(_write_body(result), status=status.HTTP_201_CREATED)


class PaymentDetailView(APIView):
    """``GET|PUT|DELETE /api/v1/finance/payments/<id>/`` (DRAFT untuk ubah/hapus)."""

    permission_classes = [IsAuthenticated]

    @staticmethod
    def _get_payment(payment_id: int):
        """Payment atau ``None`` (→ 404)."""
        return (
            Payment.objects.select_related("partner", "customer_invoice", "vendor_bill")
            .filter(pk=payment_id)
            .first()
        )

    def get(self, request, payment_id: int):
        """Detail payment; lihat docstring modul."""
        payment = self._get_payment(payment_id)
        if payment is None:
            return Response(
                {"detail": "Payment tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND
            )

        return Response(payment_services.payment_detail_row(payment))

    def put(self, request, payment_id: int):
        """Ubah payment (hanya DRAFT)."""
        require_payment_writer(request)

        payment = self._get_payment(payment_id)
        if payment is None:
            return Response(
                {"detail": "Payment tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND
            )

        result = payment_services.update_payment(payment, request.data or {}, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        return Response(_write_body(result))

    def delete(self, request, payment_id: int):
        """Hapus payment (hanya DRAFT)."""
        require_payment_writer(request)

        payment = self._get_payment(payment_id)
        if payment is None:
            return Response(
                {"detail": "Payment tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND
            )

        result = payment_services.delete_payment(payment, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        logger.info("payments: payment %s dihapus lewat API.", payment_id)
        return Response({"id": payment_id, "deleted": True}, status=status.HTTP_200_OK)


class PaymentActionView(APIView):
    """``POST /api/v1/finance/payments/<id>/<action>/`` — transisi state.

    ``action`` ∈ ``confirm`` | ``done`` | ``cancel`` (lihat docstring modul).
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, payment_id: int, action: str):
        """Jalankan transisi; lihat docstring modul."""
        require_payment_writer(request)

        if action not in PAYMENT_ACTIONS:
            return Response(
                {"detail": f"Aksi '{action}' tidak dikenal (pilih: {', '.join(PAYMENT_ACTIONS)})."},
                status=status.HTTP_404_NOT_FOUND,
            )

        payment = PaymentDetailView._get_payment(payment_id)
        if payment is None:
            return Response(
                {"detail": "Payment tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND
            )

        service = {
            "confirm": payment_services.confirm_payment,
            "done": payment_services.done_payment,
            "cancel": payment_services.cancel_payment,
        }[action]

        result = service(payment, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        logger.info("payments: payment %s aksi '%s' lewat API.", payment_id, action)
        return Response(_write_body(result), status=status.HTTP_200_OK)


