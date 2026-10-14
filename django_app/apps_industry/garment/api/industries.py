"""Whitelist industri untuk pola URL `/api/v1/<industry>/...` (Fase A).

Latar belakang: pola `<str:industry>` menerima **string apa pun**, sehingga
`/api/v1/metadata/bundles/` dulu cocok sebagai `industry="metadata"` dan menjawab
**200 dengan payload salah** (ListPage) — kegagalan senyap yang sulit dilacak.
Sejak Fase A, segment industri divalidasi lebih dulu di setiap view berindustri;
yang tidak dikenal → **404 eksplisit**.

Menambah industri baru = buat folder industri + tambahkan kodenya di `INDUSTRIES`.
"""

from __future__ import annotations

import logging

from django.http import Http404

logger = logging.getLogger(__name__)

#: Kode industri kanonik (lowercase) yang dilayani API resource saat ini.
INDUSTRIES: tuple[str, ...] = ("garmen",)

#: Industri default kalau pemanggil tidak menyebut (mis. `metadata` tanpa `?industry=`).
DEFAULT_INDUSTRY = INDUSTRIES[0]

#: Body 404 standar (kontrak Fase A: industri tak dikenal → 404 eksplisit).
INDUSTRY_NOT_FOUND_DETAIL = "industry tidak dikenal"


def normalize_industry(value: str | None) -> str | None:
    """Kode industri kanonik (lowercase) kalau dikenal; `None` kalau tidak."""
    if not value:
        return None

    candidate = str(value).strip().lower()
    return candidate if candidate in INDUSTRIES else None


def require_industry(value: str | None) -> str:
    """Kembalikan kode industri kanonik; **raise Http404** kalau tidak dikenal.

    Fail-closed: dipanggil di awal setiap view berindustri supaya permintaan
    dengan segment industri palsu tidak pernah menyentuh data bisnis.
    """
    industry = normalize_industry(value)
    if industry is None:
        logger.info("industri '%s' tidak dikenal -> 404.", value)
        raise Http404(INDUSTRY_NOT_FOUND_DETAIL)

    return industry
