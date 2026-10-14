"""Endpoint **HITL Queue** (F5.4.2 / B29) — antrean approval manusia.

  * ``GET  /api/v1/ai/hitl/queue/``        → daftar permintaan (ListPage)
  * ``POST /api/v1/ai/hitl/<id>/approve/`` → setujui (admin/owner/supervisor)
  * ``POST /api/v1/ai/hitl/<id>/reject/``  → tolak (idem + ``note`` **wajib**)

Model: ``apps_industry.garment.models.HITLRequest`` (migration ``garment.0011``).

Aturan:

  * **default filter** ``?state=PENDING`` (kalau ``state`` tidak dikirim);
  * keputusan hanya sah dari state ``PENDING``; selain itu → **409 Conflict**;
  * ``reject`` tanpa ``note`` → **400** (alasan penolakan wajib untuk audit);
  * notifikasi WA ke peminta **best-effort**: kegagalan gateway hanya dicatat di
    log, **tidak pernah** menggagalkan keputusan (nomor tujuan diambil dari
    ``HITL_ALERT_WA_TO`` → fallback ``RECONCILIATION_ALERT_WA_TO``; kosong =
    notifikasi dilewati);
  * HITL **standalone** (keputusan F5.4.2): belum ada hook otomatis dari
    ``ActionExecutor`` — lihat docstring model.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps_industry.garment.models import HITLRequest
from integrations.wa_bot.services import get_wa_gateway

logger = logging.getLogger(__name__)

__all__ = (
    "APPROVER_ROLE_CODES",
    "HitlApproveView",
    "HitlQueueView",
    "HitlRejectView",
)

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
MAX_OFFSET = 100000

#: Role yang boleh memutuskan HITL (superuser selalu boleh).
APPROVER_ROLE_CODES = ("ADMIN", "OWNER", "SUPERVISOR")


def _list_params(request):
    """``(limit, offset, error)`` dari ``?limit``/``?cursor`` (offset-based)."""
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


def _iso(value) -> str | None:
    """ISO-8601 atau ``None``."""
    return value.isoformat() if value else None


def _is_approver(user) -> bool:
    """True untuk superuser **atau** user ber-role ADMIN/OWNER/SUPERVISOR."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    role = getattr(user, "role", None)
    return role is not None and str(role.code).upper() in APPROVER_ROLE_CODES


def _require_approver(request) -> None:
    """403 kalau pemanggil bukan admin/owner/supervisor (helper lokal)."""
    if not _is_approver(request.user):
        raise PermissionDenied(
            "Hanya user dengan role ADMIN/OWNER/SUPERVISOR yang boleh memutuskan HITL."
        )


def serialize_hitl(row: HITLRequest) -> dict:
    """Satu ``HITLRequest`` → JSON kontrak B29 (dipakai queue & keputusan)."""
    return {
        "id": row.pk,
        "request_type": row.request_type,
        "resource_type": row.resource_type,
        "resource_id": row.resource_id,
        "payload": row.payload or {},
        "reason": row.reason,
        "priority": row.priority,
        "state": row.state,
        "requested_by": row.requested_by.get_username() if row.requested_by_id else None,
        "requested_at": _iso(row.created_at),
        "expires_at": _iso(row.expires_at),
        # Aditif (dipakai layar keputusan/audit):
        "decided_by": row.decided_by.get_username() if row.decided_by_id else None,
        "decided_at": _iso(row.decided_at),
        "decision_note": row.decision_note,
    }


def _wa_recipient() -> str:
    """Nomor tujuan notifikasi HITL (``HITL_ALERT_WA_TO`` → RECONCILIATION_*)."""
    raw = getattr(settings, "HITL_ALERT_WA_TO", None) or getattr(
        settings, "RECONCILIATION_ALERT_WA_TO", None
    )
    if isinstance(raw, (list, tuple)):
        return ",".join(str(item).strip() for item in raw if str(item).strip())
    return str(raw or "").strip()


def _notify_decision(row: HITLRequest, note: str) -> None:
    """Kirim WA notifikasi keputusan (best-effort; tidak pernah melempar)."""
    recipient = _wa_recipient()
    if not recipient:
        logger.debug("hitl: nomor tujuan WA belum dikonfigurasi → notifikasi dilewati.")
        return

    try:
        actor = row.decided_by.get_username() if row.decided_by_id else "sistem"
        body = (
            f"[HITL] {row.request_type} #{row.pk} → {row.state} oleh {actor}."
            f" Catatan: {note or '-'}"
        )
        result = get_wa_gateway().send_message(recipient, body)
        if not result.ok:
            logger.warning("hitl: WA notifikasi gagal (%s).", result.error)
    except Exception:  # noqa: BLE001 - notifikasi TIDAK boleh memblokir keputusan
        logger.exception("hitl: gagal mengirim notifikasi WA (diabaikan).")


def _decide(request, request_id: int, new_state: str, require_note: bool):
    """Logika bersama approve/reject → ``Response`` (200/400/404/409).

    Urutan cek: permission → 404 (tidak ada) → 400 (note wajib) → 409 (state
    bukan PENDING) → simpan keputusan → notifikasi WA best-effort.
    """
    _require_approver(request)

    row = (
        HITLRequest.objects.select_related("requested_by", "decided_by")
        .filter(pk=request_id)
        .first()
    )
    if row is None:
        return Response(
            {"detail": f"HITL request {request_id} tidak ditemukan."},
            status=status.HTTP_404_NOT_FOUND,
        )

    data = request.data if isinstance(request.data, dict) else {}
    note = str(data.get("note") or "").strip()
    if require_note and not note:
        return Response(
            {"detail": "Field 'note' wajib diisi untuk reject."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if row.state != HITLRequest.State.PENDING:
        return Response(
            {
                "detail": (
                    f"Permintaan sudah {row.state}; hanya state PENDING yang bisa diputuskan."
                ),
                "state": row.state,
            },
            status=status.HTTP_409_CONFLICT,
        )

    row.state = new_state
    row.decided_by = request.user
    row.decided_at = timezone.now()
    row.decision_note = note
    row.save(
        update_fields=["state", "decided_by", "decided_at", "decision_note", "updated_at"]
    )

    _notify_decision(row, note)
    logger.info(
        "hitl: request %s → %s oleh %s.", row.pk, new_state, request.user.get_username()
    )
    return Response(serialize_hitl(row), status=status.HTTP_200_OK)


class HitlQueueView(APIView):
    """``GET /api/v1/ai/hitl/queue/`` — daftar permintaan approval (F5.4.2 / B29).

    Bentuk ListPage::

        {"rows": [{"id", "request_type", "resource_type", "resource_id", "payload",
                   "reason", "priority", "state", "requested_by", "requested_at",
                   "expires_at", "decided_by", "decided_at", "decision_note"}],
         "total_count": N, "has_more": bool, "next_cursor": int|null}

    Query: ``?state=`` (default **PENDING**; nilai lain → 400),
    ``?priority=`` (LOW/MEDIUM/HIGH/URGENT), ``?resource_type=`` (case-insensitive),
    ``?limit``, ``?cursor``. Urut ``-created_at``.

    Permission ``IsAuthenticated`` (semua role boleh melihat antrean) → anonim **403**.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """List antrean HITL; lihat docstring kelas."""
        limit, offset, error = _list_params(request)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        queryset = HITLRequest.objects.select_related("requested_by", "decided_by")

        state_value = str(request.query_params.get("state") or "").strip().upper()
        if not state_value:
            state_value = HITLRequest.State.PENDING
        if state_value not in set(HITLRequest.State.values):
            return Response(
                {
                    "detail": (
                        f"Parameter 'state'={state_value!r} tidak dikenal "
                        f"({', '.join(HITLRequest.State.values)})."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        queryset = queryset.filter(state=state_value)

        priority = str(request.query_params.get("priority") or "").strip().upper()
        if priority:
            if priority not in set(HITLRequest.Priority.values):
                return Response(
                    {
                        "detail": (
                            f"Parameter 'priority'={priority!r} tidak dikenal "
                            f"({', '.join(HITLRequest.Priority.values)})."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(priority=priority)

        resource_type = str(request.query_params.get("resource_type") or "").strip()
        if resource_type:
            queryset = queryset.filter(resource_type__iexact=resource_type)

        queryset = queryset.order_by("-created_at")
        total = queryset.count()
        rows = list(queryset[offset : offset + limit])
        return Response(_envelope([serialize_hitl(row) for row in rows], total, offset))


class HitlApproveView(APIView):
    """``POST /api/v1/ai/hitl/<id>/approve/`` — setujui permintaan (F5.4.2 / B29).

    Body opsional ``{"note": "..."}``. State harus ``PENDING`` (kalau tidak →
    **409**); id tak dikenal → **404**. Setelah tersimpan, notifikasi WA dikirim
    **best-effort** (kegagalan tidak menggagalkan respons).

    Permission: admin/owner/supervisor (superuser selalu boleh) → selain itu **403**.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, request_id: int):
        """Setujui permintaan; lihat docstring kelas."""
        return _decide(
            request, request_id, HITLRequest.State.APPROVED, require_note=False
        )


class HitlRejectView(APIView):
    """``POST /api/v1/ai/hitl/<id>/reject/`` — tolak permintaan (F5.4.2 / B29).

    Body ``{"note": "..."}`` — **wajib** (untuk audit alasan penolakan); tanpa note
    → **400**. State harus ``PENDING`` (selain itu → **409**); id tak dikenal → **404**.

    Permission: admin/owner/supervisor (superuser selalu boleh) → selain itu **403**.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, request_id: int):
        """Tolak permintaan (note wajib); lihat docstring kelas."""
        return _decide(
            request, request_id, HITLRequest.State.REJECTED, require_note=True
        )
