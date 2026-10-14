"""Endpoint **Journal Entry** MES (H3.4) — `/api/v1/finance/journal-entries/…`.

Kontrak (transaksi, sync satu arah MES → Odoo; entry dikirim **draft**):

  * ``GET  /api/v1/finance/journal-entries/``            — ListPage (IsAuthenticated);
    filter ``?search=`` (kode/ref/memo/kode+nama journal), ``?state=``,
    ``?journal_id=``, ``?date_from=``/``?date_to=`` (ISO ``YYYY-MM-DD``);
  * ``POST /api/v1/finance/journal-entries/``           — create (ADMIN/OWNER) → **201**
    (guard: journal, tanggal, ≥ 2 baris, debit XOR credit, Σ debit = Σ kredit);
  * ``GET  /api/v1/finance/journal-entries/<id>/``      — detail (+ ``lines``,
    ``odoo_sync_status``, ``allowed_actions``);
  * ``PUT  /api/v1/finance/journal-entries/<id>/``      — update (DRAFT-only; baris diganti);
  * ``DELETE /api/v1/finance/journal-entries/<id>/``    — hard delete (DRAFT-only);
  * ``POST /api/v1/finance/journal-entries/<id>/<action>/`` — transisi:
    ``confirm`` (DRAFT→CONFIRMED + push), ``done`` (CONFIRMED|SENT→DONE),
    ``cancel`` (DRAFT|CONFIRMED|SENT→CANCELLED, ``button_cancel`` bila ``odoo_id``).

**Kenapa path-nya ``/finance/journal-entries/…``**: konsisten H3.1–H3.3 dan **bebas
bentrok** (``/finance/invoices/`` = F15 read-only, ``/finance/customer-invoices/`` =
H3.1, ``/finance/vendor-bills/`` = H3.2, ``/finance/payments/`` = H3.3). Ledger
memakai resource ``journal_entry`` + stage ``JOURNAL_ENTRY`` (keduanya BARU).

**Posting BUKAN di MES** (keputusan STEP 0): endpoint ini hanya membuat
``account.move`` ``move_type='entry'`` **draft** di Odoo; akuntan yang mem-posting.

Izin: baca = ``IsAuthenticated`` (anon 403); tulis/transisi = **ADMIN/OWNER**
(selaras `FINANCE_ROLES` frontend; pola H3.1–H3.3/H3.5/H3.6).
"""

from __future__ import annotations

import logging

from django.db.models import Q
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps_industry.garment.models import JournalEntry
from apps_industry.garment.services import journal_entry_services

logger = logging.getLogger(__name__)

__all__ = (
    "JournalEntriesView",
    "JournalEntryActionView",
    "JournalEntryDetailView",
    "is_journal_entry_writer",
    "require_journal_entry_writer",
)

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
MAX_OFFSET = 100000

#: Role yang boleh menulis journal entry (selaras `FINANCE_ROLES` = admin/owner).
JOURNAL_ENTRY_WRITE_ROLE_CODES = ("ADMIN", "OWNER")

#: Aksi transisi yang dikenal endpoint ``/<id>/<action>/``.
JOURNAL_ENTRY_ACTIONS = ("confirm", "done", "cancel")


def is_journal_entry_writer(user) -> bool:
    """True untuk superuser **atau** user ber-role ADMIN/OWNER."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True

    role = getattr(user, "role", None)
    if role is None:
        return False

    return str(role.code or "").strip().upper() in JOURNAL_ENTRY_WRITE_ROLE_CODES


def require_journal_entry_writer(request) -> None:
    """Raise ``PermissionDenied`` (403) kalau pemanggil bukan ADMIN/OWNER."""
    if not is_journal_entry_writer(request.user):
        raise PermissionDenied(
            "Hanya user dengan role "
            f"{'/'.join(JOURNAL_ENTRY_WRITE_ROLE_CODES)} yang boleh mengubah Journal Entry."
        )


def _list_params(request):
    """``(limit, offset, error)`` dari ``?limit``/``?cursor`` (pola H2.1–H3.3)."""
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
    """Baris detail entry + info tulis (``sync_record_id``/``task_id``/``queued``)."""
    body = journal_entry_services.entry_detail_row(result.entry)
    body.update(
        {
            "sync_record_id": result.sync_record_id,
            "task_id": result.task_id,
            "queued": result.queued,
        }
    )

    return body


def _queryset():
    """Query dasar: header + journal (baris di-prefetch untuk detail/row)."""
    return JournalEntry.objects.select_related("journal").prefetch_related(
        "lines__account", "lines__partner"
    )


def _get_entry(entry_id: int):
    """JournalEntry atau ``None`` (→ 404)."""
    return _queryset().filter(pk=entry_id).first()


def _apply_date_filter(queryset, request, param: str, lookup: str):
    """``(queryset, error)`` — filter tanggal ISO opsional (``?date_from``/``?date_to``)."""
    raw = request.query_params.get(param)
    if raw in (None, ""):
        return queryset, None

    parsed = parse_date(str(raw))
    if parsed is None:
        return queryset, f"Parameter '{param}' harus format ISO (YYYY-MM-DD)."

    return queryset.filter(**{lookup: parsed}), None


class JournalEntriesView(APIView):
    """``GET|POST /api/v1/finance/journal-entries/`` — daftar & buat entry MES."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """List journal entry + filter; lihat docstring modul."""
        limit, offset, error = _list_params(request)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        queryset = _queryset()

        state = str(request.query_params.get("state") or "").strip().upper()
        if state:
            if state not in journal_entry_services.JOURNAL_ENTRY_STATES:
                return Response(
                    {
                        "detail": (
                            "Parameter 'state' harus salah satu: "
                            f"{', '.join(journal_entry_services.JOURNAL_ENTRY_STATES)}."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(state=state)

        raw_journal = request.query_params.get("journal_id")
        if raw_journal not in (None, ""):
            try:
                queryset = queryset.filter(journal_id=int(raw_journal))
            except (TypeError, ValueError):
                return Response(
                    {"detail": "Parameter 'journal_id' harus berupa angka."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        queryset, error = _apply_date_filter(queryset, request, "date_from", "entry_date__gte")
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        queryset, error = _apply_date_filter(queryset, request, "date_to", "entry_date__lte")
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        search = str(request.query_params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(
                Q(code__icontains=search)
                | Q(ref__icontains=search)
                | Q(memo__icontains=search)
                | Q(journal__code__icontains=search)
                | Q(journal__name__icontains=search)
            )

        queryset = queryset.order_by("-created_at")
        total = queryset.count()
        rows = list(queryset[offset : offset + limit])

        return Response(
            _envelope([journal_entry_services.entry_row(row) for row in rows], total, offset)
        )

    def post(self, request):
        """Buat journal entry (nomor ``JE-<TAHUN>-<SEQ>``) + guard double-entry."""
        require_journal_entry_writer(request)

        result = journal_entry_services.create_entry(request.data or {}, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        return Response(_write_body(result), status=status.HTTP_201_CREATED)


class JournalEntryDetailView(APIView):
    """``GET|PUT|DELETE /api/v1/finance/journal-entries/<id>/`` (DRAFT untuk ubah/hapus)."""

    permission_classes = [IsAuthenticated]

    @staticmethod
    def _get_entry(entry_id: int):
        """JournalEntry atau ``None`` (→ 404)."""
        return _get_entry(entry_id)

    def get(self, request, entry_id: int):
        """Detail entry (termasuk baris jurnal); lihat docstring modul."""
        entry = self._get_entry(entry_id)
        if entry is None:
            return Response(
                {"detail": "Journal Entry tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND
            )

        return Response(journal_entry_services.entry_detail_row(entry))

    def put(self, request, entry_id: int):
        """Ubah entry (hanya DRAFT; baris jurnal diganti menyatu)."""
        require_journal_entry_writer(request)

        entry = self._get_entry(entry_id)
        if entry is None:
            return Response(
                {"detail": "Journal Entry tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND
            )

        result = journal_entry_services.update_entry(entry, request.data or {}, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        return Response(_write_body(result))

    def delete(self, request, entry_id: int):
        """Hapus entry (hanya DRAFT)."""
        require_journal_entry_writer(request)

        entry = self._get_entry(entry_id)
        if entry is None:
            return Response(
                {"detail": "Journal Entry tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND
            )

        result = journal_entry_services.delete_entry(entry, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        logger.info("journal_entries: entry %s dihapus lewat API.", entry_id)
        return Response({"id": entry_id, "deleted": True}, status=status.HTTP_200_OK)


class JournalEntryActionView(APIView):
    """``POST /api/v1/finance/journal-entries/<id>/<action>/`` — transisi state.

    ``action`` ∈ ``confirm`` | ``done`` | ``cancel`` (lihat docstring modul).
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, entry_id: int, action: str):
        """Jalankan transisi; lihat docstring modul."""
        require_journal_entry_writer(request)

        if action not in JOURNAL_ENTRY_ACTIONS:
            return Response(
                {
                    "detail": (
                        f"Aksi '{action}' tidak dikenal "
                        f"(pilih: {', '.join(JOURNAL_ENTRY_ACTIONS)})."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        entry = _get_entry(entry_id)
        if entry is None:
            return Response(
                {"detail": "Journal Entry tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND
            )

        service = {
            "confirm": journal_entry_services.confirm_entry,
            "done": journal_entry_services.done_entry,
            "cancel": journal_entry_services.cancel_entry,
        }[action]

        result = service(entry, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        logger.info("journal_entries: entry %s aksi '%s' lewat API.", entry_id, action)
        return Response(_write_body(result), status=status.HTTP_200_OK)
