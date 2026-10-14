"""Klien HTTP async ke API Django (MES) — fase M2.

Pembungkus tipis ``httpx.AsyncClient`` yang menyembunyikan tiga hal dari agent:

* **penjoinan URL** — ``base_url`` + ``api_prefix`` + ``path`` selalu rapi
  (tanpa garis miring ganda, tanpa garis miring hilang);
* **X-Request-ID** — dibuat otomatis tiap request (uuid4) agar bisa ditelusuri
  end-to-end (Django sudah punya ``RequestIDMiddleware``);
* **retry** — exponential backoff (0.5s, 1s, 2s) HANYA untuk kegagalan
  transport (``httpx.HTTPError`` termasuk ``ConnectError``/``TimeoutException``).
  Status ``>= 400`` **tidak** di-retry: itu respons sah dari server, bukan
  gangguan jaringan;
* **CSRF** — token ``csrftoken`` dari cookie di-mirror ke header ``X-CSRFToken``
  untuk method non-aman (POST/PUT/...), karena Django memakai
  ``SessionAuthentication``. GET/HEAD/OPTIONS tidak butuh.

Catatan: ``last_trace_id`` bersifat **per-worker, bukan per-coroutine** — kalau
dua coroutine memakai klien yang sama, nilai terakhir bisa saling menimpa;
cukup untuk M2, refactor ke ``contextvars`` di M3 kalau perlu. Klien ini murni:
TIDAK menyimpan state ke mana pun (bukan DB, bukan file).
"""

from __future__ import annotations

import asyncio
import re
import uuid
from typing import Optional

import httpx

__all__ = ("MESClient", "refresh_session_cookie")

#: Jeda backoff (detik) untuk retry ke-1, ke-2, ke-3, ... (menggandakan).
_BACKOFF_SECONDS: tuple[float, ...] = (0.5, 1.0, 2.0)

#: Method "aman" (tanpa efek samping) — tidak butuh CSRF token.
_SAFE_METHODS: tuple[str, ...] = ("GET", "HEAD", "OPTIONS")

#: Nama cookie CSRF milik Django.
_CSRF_COOKIE_NAME = "csrftoken"


def _extract_csrf(cookie: str) -> "Optional[str]":
    """Ambil nilai ``csrftoken`` dari string cookie ``"k1=v1; k2=v2"``.

    ``None`` bila cookie kosong atau tidak memuat ``csrftoken``.
    """

    if not cookie:
        return None
    for part in cookie.split(";"):
        part = part.strip()
        if part.startswith(_CSRF_COOKIE_NAME + "="):
            return part[len(_CSRF_COOKIE_NAME) + 1:]
    return None


class MESClient:
    """Pembungkus ``httpx.AsyncClient`` untuk memanggil REST API Django."""

    def __init__(
        self,
        base_url: str,
        api_prefix: str = "/api/v1",
        timeout: float = 10.0,
        max_retries: int = 3,
        auth_headers: Optional[dict] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_prefix = self._normalize_prefix(api_prefix)
        self.timeout = float(timeout)
        self.max_retries = max(int(max_retries), 0)
        #: Header auth opsional, di-merge ke setiap request (M2 belum butuh auth
        #: Django nyata — default kosong; test pakai dummy server / MockTransport).
        self.auth_headers = dict(auth_headers or {})
        #: CSRF token di-mirror dari cookie ``csrftoken`` (Django SessionAuthentication
        #: butuh header ``X-CSRFToken`` untuk method non-aman). ``None`` bila absen.
        self.csrf_token = _extract_csrf(self.auth_headers.get("Cookie", ""))
        #: Trace ID request terakhir (per-worker, bukan per-coroutine) — lihat docstring modul.
        self.last_trace_id: Optional[str] = None
        self._client = httpx.AsyncClient(timeout=self.timeout)

    def set_auth_cookie(self, cookie: str) -> None:
        """Ganti cookie sesi di tempat (FASE 3.1.1: refresh sesi multi-hari).

        ``csrf_token`` turunan ikut disegarkan supaya konsisten dengan cookie
        baru — kalau tidak, POST berikutnya bisa 403 CSRF walau ``sessionid`` ok.
        """

        self.auth_headers["Cookie"] = cookie or ""
        self.csrf_token = _extract_csrf(self.auth_headers.get("Cookie", ""))

    # ------------------------------------------------------------------ helper
    @staticmethod
    def _normalize_prefix(prefix: str) -> str:
        """Jadikan prefix selalu ``/segmen`` (garis miring awal ada, akhir tidak)."""

        cleaned = (prefix or "").strip().strip("/")
        return f"/{cleaned}" if cleaned else ""

    def _build_url(self, path: str) -> str:
        """Gabung ``base_url`` + ``api_prefix`` + ``path`` tanpa double/hilang slash."""

        p = (path or "").strip()
        if p and not p.startswith("/"):
            p = "/" + p
        return f"{self.base_url}{self.api_prefix}{p}"

    def _headers(self, extra: Optional[dict]) -> dict:
        """Auth + header tambahan + ``X-Request-ID`` baru (selalu di-generate)."""

        merged = dict(self.auth_headers)
        if extra:
            merged.update(extra)
        self.last_trace_id = str(uuid.uuid4())
        merged["X-Request-ID"] = self.last_trace_id
        return merged

    def _delay_for(self, attempt: int) -> float:
        """Jeda backoff percobaan ke-``attempt`` (0-based), di-cap di nilai terakhir."""

        if not _BACKOFF_SECONDS:
            return 0.0
        return _BACKOFF_SECONDS[min(attempt, len(_BACKOFF_SECONDS) - 1)]

    # --------------------------------------------------------------- eksekusi
    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> httpx.Response:
        url = self._build_url(path)

        # Mirror cookie csrftoken → header X-CSRFToken untuk method non-aman
        # (per-request; BUKAN di __init__). ``setdefault`` supaya header per-call
        # yang sudah ada tidak tertimpa; _headers lalu me-merge auth(Cookie) +
        # per-call + X-Request-ID tanpa saling menimpa.
        req_headers = dict(headers or {})
        if method.upper() not in _SAFE_METHODS and self.csrf_token:
            req_headers.setdefault("X-CSRFToken", self.csrf_token)
        req_headers = self._headers(req_headers)

        last_exc: Optional[BaseException] = None
        for attempt in range(self.max_retries + 1):
            try:
                return await self._client.request(
                    method, url, json=json, headers=req_headers
                )
            except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError) as exc:
                # httpx.HTTPError sudah mencakup ConnectError/TimeoutException;
                # dipertegas agar niat jelas. Status >= 400 TIDAK masuk sini.
                last_exc = exc
                if attempt >= self.max_retries:
                    raise
                await asyncio.sleep(self._delay_for(attempt))

        raise last_exc  # pragma: no cover - tidak tercapai secara logis

    async def post(
        self,
        path: str,
        json: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> httpx.Response:
        """POST ke ``path``; status apa pun dikembalikan apa adanya (>=400 tidak di-retry)."""

        return await self._request("POST", path, json=json, headers=headers)

    async def get(self, path: str, headers: Optional[dict] = None) -> httpx.Response:
        """GET ke ``path``; status >= 400 dikembalikan apa adanya (tidak di-retry)."""

        return await self._request("GET", path, headers=headers)

    # ----------------------------------------------------------- daur hidup
    async def close(self) -> None:
        """Tutup koneksi klien."""

        await self._client.aclose()

    async def __aenter__(self) -> "MESClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()


async def refresh_session_cookie(
    base_url: str,
    username: str,
    password: str,
    timeout: float = 10.0,
) -> "Optional[str]":
    """Login ke ``/admin/login/`` → string cookie baru, atau ``None`` kalau gagal.

    FASE 3.1.1 (multi-hari): ``sessionid`` bisa kedaluwarsa (~2 minggu). Helper
    ini melakukan alur login Django admin:

    1. ``GET /admin/login/`` → ambil ``csrftoken`` cookie (atau token hidden form);
    2. ``POST /admin/login/`` (username/password + csrf + ``next``);
    3. sesi sukses ditandai munculnya cookie ``sessionid``.

    Return ``"csrftoken=<c>; sessionid=<s>"`` (siap dipakai sebagai header
    ``Cookie``), atau ``None`` bila kredensial kosong / server menolak / error
    transport. Tidak melempar exception ke pemanggil.
    """

    if not username or not password:
        return None
    base = (base_url or "").rstrip("/")
    if not base:
        return None
    try:
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=False
        ) as client:
            login_url = f"{base}/admin/login/"
            page = await client.get(login_url)
            csrf = client.cookies.get(_CSRF_COOKIE_NAME)
            if not csrf:
                match = re.search(
                    r'name="csrfmiddlewaretoken"\s+value="([^"]+)"', page.text
                )
                csrf = match.group(1) if match else None
            if not csrf:
                return None

            await client.post(
                login_url,
                data={
                    "username": username,
                    "password": password,
                    "csrfmiddlewaretoken": csrf,
                    "next": "/admin/",
                },
                headers={"Referer": login_url},
            )
            session_id = client.cookies.get("sessionid")
            if not session_id:
                return None
            new_csrf = client.cookies.get(_CSRF_COOKIE_NAME) or csrf
            return f"{_CSRF_COOKIE_NAME}={new_csrf}; sessionid={session_id}"
    except httpx.HTTPError:
        return None
