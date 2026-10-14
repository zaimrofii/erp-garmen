"""Paginasi chatter (Kontrak §8).

`paginate_events()` = halaman mentah (`preview`/`has_more`/`next_cursor`);
`chatter_page_payload()` = bentuk `ChatterPage` lengkap (+`total_count`) yang
dipakai endpoint chatter DAN blok `chatter` di metadata (Fase B.2).
"""

from __future__ import annotations

from .paginator import (
    PAGE_SIZE,
    chatter_page_payload,
    decode_cursor,
    encode_cursor,
    paginate_events,
)

__all__ = [
    "PAGE_SIZE",
    "chatter_page_payload",
    "decode_cursor",
    "encode_cursor",
    "paginate_events",
]
