"""Rate limiter endpoint auth (F6.1) — **manual**, memakai Django cache.

Kenapa tidak `django-ratelimit` / `DRF Throttle`:

  * `django-ratelimit` = dependency baru untuk satu kebutuhan kecil (5 & 10
    request/menit di dua view);
  * DRF `SimpleRateThrottle` **tidak bisa dipakai**: mode test menaikkan kuota
    `DEFAULT_THROTTLE_RATES` ke 100000/min (`config/settings.py`) supaya ratusan
    test lama tidak kena 429 palsu — konsekuensinya kuota login pun hilang di
    test, sementara brief F6.1 justru minta bukti 429 setelah 5x/10x.

Implementasi: fixed window di cache (Redis di produksi, LocMem di mode test —
lihat `CACHES`). Fixed window dipilih (bukan sliding) karena murah (2 operasi
cache/request) dan batasnya mudah dijelaskan ke operator: "maksimal N kali per
menit".

Fail-safe: kalau backend cache error (mis. Redis mati), limiter **meloloskan**
request (kembali `True`) — login yang macet total lebih buruk daripada limit
yang sementara tidak aktif; kejadiannya dicatat di log.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

__all__ = ("client_ip", "consume", "limit_for")

#: Default kalau `settings.AUTH_RATE_LIMITS` tidak memuat scope tsb.
DEFAULT_LIMITS: dict[str, dict[str, int]] = {
    "login": {"limit": 5, "window": 60},
    "login_operator": {"limit": 10, "window": 60},
}

#: Prefix key cache — memisahkan limiter ini dari throttle DRF & data lain.
KEY_PREFIX = "auth-rl"


def limit_for(scope: str) -> tuple[int, int]:
    """``(limit, window)`` untuk sebuah scope; fallback ke `DEFAULT_LIMITS`."""
    configured = getattr(settings, "AUTH_RATE_LIMITS", None) or {}
    entry = configured.get(scope) or DEFAULT_LIMITS.get(scope) or {}
    limit = int(entry.get("limit") or DEFAULT_LIMITS["login"]["limit"])
    window = int(entry.get("window") or DEFAULT_LIMITS["login"]["window"])
    return max(limit, 1), max(window, 1)


def client_ip(request) -> str:
    """IP klien untuk kunci limiter.

    Urutan: `X-Real-IP` → entri **terakhir** `X-Forwarded-For` → `REMOTE_ADDR`.

    * `X-Real-IP` di-set Nginx kita sendiri (`nginx/conf.d/mes.conf`) jadi tidak
      bisa dipalsukan klien;
    * entri terakhir XFF (bukan pertama) dipilih karena Nginx memakai
      `$proxy_add_x_forwarded_for` yang **menambahkan** IP asli di ujung —
      entri pertama bisa saja dikirim klien;
    * tanpa proxy (dev/`runserver`) → IP koneksi langsung.
    """
    meta = getattr(request, "META", None) or {}

    real_ip = str(meta.get("HTTP_X_REAL_IP") or "").strip()
    if real_ip:
        return real_ip

    forwarded = str(meta.get("HTTP_X_FORWARDED_FOR") or "").strip()
    if forwarded:
        last = forwarded.split(",")[-1].strip()
        if last:
            return last

    return str(meta.get("REMOTE_ADDR") or "unknown").strip() or "unknown"


def consume(scope: str, identity: str) -> tuple[bool, int]:
    """Catat satu percobaan; ``(allowed, retry_after_detik)``.

    Request ke-`limit` masih **diizinkan**; request ke-`limit+1` (dalam window
    yang sama) ditolak dengan `retry_after` = sisa TTL window.
    """
    limit, window = limit_for(scope)
    key = f"{KEY_PREFIX}:{scope}:{identity}"

    try:
        if cache.add(key, 1, timeout=window):
            return True, 0  # percobaan pertama di window ini
        count = cache.incr(key)
    except ValueError:
        # Key kedaluwarsa tepat di antara `add` dan `incr` → anggap window baru.
        cache.set(key, 1, timeout=window)
        return True, 0
    except Exception:  # noqa: BLE001 - cache error tidak boleh mematikan login
        logger.warning("rate limit '%s' dilewati: cache error.", scope, exc_info=True)
        return True, 0

    if count <= limit:
        return True, 0

    return False, _retry_after(key, window)


def _retry_after(key: str, window: int) -> int:
    """Sisa TTL key (detik) untuk header `Retry-After`; gagal → `window`."""
    try:
        ttl = int(cache.ttl(key))
    except Exception:  # noqa: BLE001 - backend tanpa `ttl()` → pakai window penuh
        return max(window, 1)
    return ttl if ttl > 0 else 1
