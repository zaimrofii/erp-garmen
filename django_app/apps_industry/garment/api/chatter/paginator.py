"""Paginasi cursor untuk chatter (Kontrak §8, bentuk Fase B.2).

Satu halaman chatter = **bentuk kontrak** `ChatterPage` frontend:

    {preview: [...], total_count: <int>, has_more: <bool>, next_cursor: <str|null>}

Serializer event-nya **satu-satunya** `builder.chatter_event_payload`
(`{id, actor:{id,name}, type, summary, payload, created_at}`) supaya chatter yang
di-embed di metadata (Fase B.1) dan endpoint `GET /chatter/<resource>/<id>`
identik — frontend memvalidasi keduanya dengan `ChatterPageSchema` yang sama.

Cursor = base64 dari ``"<ts ISO>|<id>"`` (opaque bagi frontend). Urutan event
**terbaru dulu** (``-ts``, ``-id``); halaman berikutnya = event yang lebih lama
daripada cursor. `-id` jadi tie-break supaya urutan deterministik saat `ts` sama.
"""

from __future__ import annotations

import base64
import binascii
import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from django.db.models import Q, QuerySet

from apps_industry.garment.api.schema.builder import chatter_event_payload

logger = logging.getLogger(__name__)

#: Jumlah event per halaman default (= `CHATTER_PREVIEW_LIMIT` frontend, §8).
PAGE_SIZE = 5


def encode_cursor(ts: datetime, identifier: Any) -> str:
    """Encode pasangan `(ts, id)` menjadi cursor base64 (url-safe)."""
    raw = f"{ts.isoformat()}|{identifier}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str | None) -> tuple[datetime, str] | None:
    """Decode cursor menjadi `(ts, id)`; `None` kalau kosong/invalid (tanpa exception)."""
    if not cursor:
        return None

    try:
        raw = base64.urlsafe_b64decode(str(cursor).encode("ascii")).decode("utf-8")
        ts_text, separator, identifier = raw.partition("|")
        if not separator or not identifier:
            return None
        return datetime.fromisoformat(ts_text), identifier
    except (ValueError, TypeError, binascii.Error, UnicodeDecodeError):
        return None


def paginate_events(
    queryset: QuerySet,
    cursor: str | None = None,
    limit: int = PAGE_SIZE,
    serializer: Callable[[Any], dict] = chatter_event_payload,
) -> dict:
    """Ambil satu halaman event (terbaru dulu) + `has_more` + `next_cursor`.

    Args:
        queryset: queryset `BundleEvent` (boleh sudah difilter per bundle).
        cursor: cursor dari halaman sebelumnya (`None` = halaman pertama).
        limit: jumlah event per halaman (minimal 1).
        serializer: fungsi `event -> dict`; default `chatter_event_payload`
            (bentuk kontrak §8). Bisa diganti bila suatu saat butuh bentuk lain.

    Return `{preview, has_more, next_cursor}` (tanpa `total_count`); untuk bentuk
    `ChatterPage` lengkap pakai `chatter_page_payload()`.

    Cursor invalid/kadaluarsa diperlakukan sebagai **halaman pertama** dan
    dicatat di log (frontend tetap dapat data, bukan error).
    """
    try:
        page_size = max(1, int(limit))
    except (TypeError, ValueError) as exc:
        raise ValueError("limit harus bilangan bulat > 0.") from exc

    ordered = queryset.order_by("-ts", "-id")
    decoded = decode_cursor(cursor)
    if decoded is not None:
        ts, identifier = decoded
        # Halaman berikutnya = event yang lebih lama (ts < cursor, atau ts sama
        # tapi id lebih kecil sesuai urutan `-ts, -id`).
        ordered = queryset.filter(
            Q(ts__lt=ts) | Q(ts=ts, id__lt=identifier)
        ).order_by("-ts", "-id")
    elif cursor:
        logger.warning("cursor chatter tidak valid -> pakai halaman pertama: %r", cursor)

    events = list(ordered.select_related("actor")[: page_size + 1])
    has_more = len(events) > page_size
    page = events[:page_size]

    next_cursor = None
    if has_more and page:
        next_cursor = encode_cursor(page[-1].ts, page[-1].pk)

    return {
        "preview": [serializer(event) for event in page],
        "has_more": has_more,
        "next_cursor": next_cursor,
    }


def chatter_page_payload(
    queryset: QuerySet, cursor: str | None = None, limit: int = PAGE_SIZE
) -> dict:
    """Halaman chatter bentuk `ChatterPage` (kontrak §8, Fase B.2)::

        {"preview": [...], "total_count": <int>,
         "has_more": <bool>, "next_cursor": <str|null>}

    Dipakai BERSAMA oleh endpoint chatter dan blok `chatter` di metadata supaya
    keduanya tidak mungkin berbeda bentuk (`total_count` = jumlah seluruh event,
    bukan hanya halaman ini).
    """
    page = paginate_events(queryset, cursor=cursor, limit=limit)
    return {
        "preview": page["preview"],
        "total_count": queryset.count(),
        "has_more": page["has_more"],
        "next_cursor": page["next_cursor"],
    }
