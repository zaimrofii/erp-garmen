"""Endpoint **auth hybrid** (F6.1) — 6 route di section kontrak core `api/v1/auth/*`.

Tiga cara masuk ke MES (dan kenapa dipisah):

  1. **session login** (``POST /login/``) — admin/supervisor memakai
     username+password. Cookie `sessionid` di-set Django; inilah yang membuat
     halaman real (mis. B26) tidak lagi membalas 403 tanpa jalan keluar.
  2. **kode operator** (``POST /login-operator/``) — operator/QC di HP pribadi
     cukup mengetik 4 digit (`User.operator_code`), umur sesi 8 jam.
  3. **device cookie** (``device_token``, Fase G) — perangkat bersama tetap masuk
     lewat ``POST /api/v1/devices/bind``; ``GET /me/`` mengembalikan
     ``device_profile`` supaya klien tahu perangkat ini "milik" profil apa.

Ringkas:

  ============================================ =============== ================
  Route                                        Auth            Rate limit
  ============================================ =============== ================
  ``POST /api/v1/auth/login/``                 AllowAny        5/menit per IP
  ``POST /api/v1/auth/login-operator/``        AllowAny        10/menit per IP
  ``POST /api/v1/auth/logout/``                IsAuthenticated —
  ``GET  /api/v1/auth/me/``                    IsAuthenticated —
  ``POST /api/v1/auth/change-password/``       IsAuthenticated —
  ``POST /api/v1/auth/reset-password/<id>/``   admin/owner     —
  ============================================ =============== ================

Keputusan yang perlu diketahui pembaca berikutnya:

  * **Rate limit manual** (`core.auth.ratelimit`) — alasan lengkap ada di
    docstring modul itu (terutama: kuota DRF dimatikan di mode test sehingga
    429 sulit dibuktikan lewat throttle bawaan).
  * **CSRF**: cookie `csrftoken` selalu di-set/di-rotasi saat login, dan token
    header (`X-CSRFToken`) **wajib** begitu klien memegang cookie itu. Untuk
    request dengan sesi aktif, DRF `SessionAuthentication` sudah menolak request
    tanpa CSRF (403). Login pertama dari browser yang belum punya cookie CSRF
    sengaja **tidak** dipaksa: kalau dipaksa, keluhan "403 tanpa jalan keluar"
    justru terulang (browser belum punya token untuk dikirim); `login()` Django
    tetap merotasi token (mitigasi login-CSRF/session fixation).
  * **Password** selalu lewat `set_password`/`check_password` (tidak ada jalur
    plaintext); `update_session_auth_hash` dipanggil setelah ganti password agar
    sesi yang sedang dipakai tidak ikut ter-logout.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.contrib.auth import (
    authenticate,
    login,
    logout,
    update_session_auth_hash,
)
from django.middleware.csrf import CsrfViewMiddleware, get_token
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.auth.authentication import DeviceTokenAuthentication
from core.auth.models import User
from core.auth.ratelimit import client_ip, consume
from core.auth.services import require_admin

logger = logging.getLogger(__name__)

__all__ = (
    "AuthChangePasswordView",
    "AuthLoginOperatorView",
    "AuthLoginView",
    "AuthLogoutView",
    "AuthMeView",
    "AuthResetPasswordView",
)

#: Panjang minimum password baru (sama dengan B26 di endpoint settings users).
MIN_PASSWORD_LENGTH = 8

#: Umur sesi login operator (detik) — 8 jam; bisa di-override lewat env.
DEFAULT_OPERATOR_SESSION_AGE = 8 * 60 * 60

#: Pesan 401 (disamakan untuk kredensial salah/nonaktif → tidak membocorkan status akun).
INVALID_CREDENTIALS_DETAIL = "Username atau password salah"
INVALID_OPERATOR_CODE_DETAIL = "Kode operator tidak valid"

TAG = "auth"


class AuthSessionAuthentication(SessionAuthentication):
    """`SessionAuthentication` + `WWW-Authenticate` supaya anonim dibalas **401**.

    DRF memilih 401 vs 403 dari `authenticate_header` authenticator
    **pertama**; `SessionAuthentication` bawaan mengembalikan `None` → statusnya
    403 (perilaku yang memang diinginkan endpoint settings lama seperti B26).
    Kontrak F6.1 meminta "belum login → 401" di `/auth/*`, jadi header diisi di
    subclass ini — implementasi session-nya sendiri tidak diubah.
    """

    def authenticate_header(self, request) -> str:
        return "Session"


#: Authenticator endpoint `/auth/*` (session dulu, lalu cookie device binding).
AUTH_CLASSES = (AuthSessionAuthentication, DeviceTokenAuthentication)


class _CsrfRejection(CsrfViewMiddleware):
    """`CsrfViewMiddleware` yang mengembalikan **alasan** penolakan, bukan response.

    Middleware dipanggil manual (bukan lewat middleware stack) supaya view DRF
    bisa membalas 403 dengan bentuk JSON yang seragam dengan endpoint lain.
    """

    def _reject(self, request, reason):
        return reason


_csrf_checker = _CsrfRejection(lambda request: None)


# --------------------------------------------------------------------------- #
# Helper
# --------------------------------------------------------------------------- #
def _role_code(user) -> str | None:
    """`Role.code` (UPPERCASE) atau `None` untuk akun teknis tanpa role."""
    role = getattr(user, "role", None)
    return str(role.code) if role is not None else None


def serialize_session_user(user) -> dict:
    """Bentuk user untuk E1/E4 (`role_code` = `Role.code`, bukan objek role)."""
    return {
        "id": user.pk,
        "username": user.username,
        "email": user.email,
        "full_name": user.get_full_name(),
        "role_code": _role_code(user),
        "is_superuser": user.is_superuser,
        "is_staff": user.is_staff,
    }


def _json_body(request) -> dict:
    """Body request sebagai dict (selain dict → dict kosong, bukan 500)."""
    data = getattr(request, "data", None)
    return data if isinstance(data, dict) else {}


def _operator_session_age() -> int:
    """Umur sesi operator (E2), default 8 jam."""
    configured = getattr(settings, "AUTH_OPERATOR_SESSION_AGE", DEFAULT_OPERATOR_SESSION_AGE)
    try:
        return int(configured)
    except (TypeError, ValueError):  # pragma: no cover - konfigurasi salah
        return DEFAULT_OPERATOR_SESSION_AGE


def _rate_limited(request, scope: str) -> Response | None:
    """`Response` 429 (+`Retry-After`) kalau kuota scope habis; selain itu `None`."""
    allowed, retry_after = consume(scope, client_ip(request))
    if allowed:
        return None

    response = Response(
        {"detail": "Terlalu banyak percobaan. Coba lagi beberapa saat lagi."},
        status=status.HTTP_429_TOO_MANY_REQUESTS,
    )
    response["Retry-After"] = str(retry_after)
    return response


def _csrf_error(request) -> Response | None:
    """`Response` 403 kalau klien memegang cookie `csrftoken` tanpa token header sah.

    Bersyarat (lihat docstring modul): browser yang belum pernah menerima cookie
    CSRF tetap boleh login — setelah login, cookie selalu ada dan token header
    menjadi wajib.
    """
    http_request = getattr(request, "_request", request)
    cookies = getattr(http_request, "COOKIES", None) or {}
    if not cookies.get(settings.CSRF_COOKIE_NAME):
        return None

    reason = _csrf_checker.process_view(http_request, None, (), {})
    if reason is None:
        return None

    logger.info("auth: CSRF ditolak (%s).", reason)
    return Response({"detail": "CSRF token tidak valid."}, status=status.HTTP_403_FORBIDDEN)


def _start_session(request, user, *, max_age: int | None = None) -> None:
    """Login Django: isi session + rotasi token CSRF (+ umur sesi opsional).

    `login()` juga mengirim sinyal `user_logged_in` → `last_login` diperbarui
    (dipakai halaman admin user). Cookie CSRF di-set lewat `get_token()` supaya
    request berikutnya (logout/ganti password) bisa mengirim `X-CSRFToken`.
    """
    http_request = request._request
    login(http_request, user)
    if max_age:
        http_request.session.set_expiry(max_age)
    request.user = user  # DRF Request: `request.user` konsisten di request ini
    get_token(http_request)


# --------------------------------------------------------------------------- #
# E1 — login (session)
# --------------------------------------------------------------------------- #
@extend_schema(
    summary="Login username+password (session cookie)",
    description=(
        "Body `{username, password}`. Sukses → cookie `sessionid` + data user. "
        "Salah/nonaktif → 401. Lebih dari 5 percobaan/menit per IP → 429."
    ),
    request=OpenApiTypes.OBJECT,
    responses={
        200: OpenApiTypes.OBJECT,
        401: OpenApiTypes.OBJECT,
        429: OpenApiTypes.OBJECT,
    },
    tags=[TAG],
)
class AuthLoginView(APIView):
    """`POST /api/v1/auth/login/` — login admin/supervisor (E1)."""

    permission_classes = [AllowAny]
    authentication_classes = list(AUTH_CLASSES)

    #: Scope rate limit (lihat `settings.AUTH_RATE_LIMITS`).
    rate_limit_scope = "login"

    def post(self, request):
        """Autentikasi username+password, lalu set cookie session."""
        blocked = _rate_limited(request, self.rate_limit_scope)
        if blocked is not None:
            return blocked

        csrf_error = _csrf_error(request)
        if csrf_error is not None:
            return csrf_error

        data = _json_body(request)
        username = str(data.get("username") or "").strip()
        password = str(data.get("password") or "")
        if not username or not password:
            return Response(
                {"detail": "Field 'username' dan 'password' wajib diisi."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = authenticate(request=request._request, username=username, password=password)
        if user is None:
            # `authenticate()` juga mengembalikan None untuk user nonaktif →
            # pesannya disamakan supaya status akun tidak bocor.
            logger.info("auth: login gagal untuk username '%s'.", username)
            return Response(
                {"detail": INVALID_CREDENTIALS_DETAIL},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        _start_session(request, user)
        return Response(serialize_session_user(user), status=status.HTTP_200_OK)


# --------------------------------------------------------------------------- #
# E2 — login operator (kode 4/6 digit)
# --------------------------------------------------------------------------- #
@extend_schema(
    summary="Login dengan kode operator (HP pribadi)",
    description=(
        "Body `{operator_code}`. Sukses → cookie session (umur 8 jam) + data ringkas. "
        "Kode tak dikenal / user nonaktif → 401. >10 percobaan/menit per IP → 429."
    ),
    request=OpenApiTypes.OBJECT,
    responses={
        200: OpenApiTypes.OBJECT,
        401: OpenApiTypes.OBJECT,
        429: OpenApiTypes.OBJECT,
    },
    tags=[TAG],
)
class AuthLoginOperatorView(APIView):
    """`POST /api/v1/auth/login-operator/` — login cepat operator/QC (E2)."""

    permission_classes = [AllowAny]
    authentication_classes = list(AUTH_CLASSES)

    rate_limit_scope = "login_operator"

    def post(self, request):
        """Cari user dari `operator_code` aktif, lalu set cookie session 8 jam."""
        blocked = _rate_limited(request, self.rate_limit_scope)
        if blocked is not None:
            return blocked

        csrf_error = _csrf_error(request)
        if csrf_error is not None:
            return csrf_error

        operator_code = str(_json_body(request).get("operator_code") or "").strip()
        if not operator_code:
            return Response(
                {"detail": "Field 'operator_code' wajib diisi."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = (
            User.objects.select_related("role")
            .filter(operator_code=operator_code, is_active=True)
            .first()
        )
        if user is None:
            logger.info("auth: kode operator '%s' tidak dikenal/nonaktif.", operator_code)
            return Response(
                {"detail": INVALID_OPERATOR_CODE_DETAIL},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        _start_session(request, user, max_age=_operator_session_age())
        return Response(
            {
                "id": user.pk,
                "username": user.username,
                "full_name": user.get_full_name(),
                "role_code": _role_code(user),
            },
            status=status.HTTP_200_OK,
        )


# --------------------------------------------------------------------------- #
# E3 — logout
# --------------------------------------------------------------------------- #
@extend_schema(
    summary="Logout (hapus session)",
    description="Menghapus session server + cookie `sessionid`. Tanpa login → 401.",
    request=None,
    responses={200: OpenApiTypes.OBJECT, 401: OpenApiTypes.OBJECT},
    tags=[TAG],
)
class AuthLogoutView(APIView):
    """`POST /api/v1/auth/logout/` — tutup sesi perangkat ini (E3)."""

    permission_classes = [IsAuthenticated]
    authentication_classes = list(AUTH_CLASSES)

    def post(self, request):
        """Flush session + hapus cookie `sessionid`."""
        csrf_error = _csrf_error(request)
        if csrf_error is not None:
            return csrf_error

        logout(request._request)
        response = Response({"ok": True}, status=status.HTTP_200_OK)
        # `logout()` sudah flush session; cookie ikut dihapus supaya browser
        # tidak menyimpan sessionid kosong (menghindari 401 membingungkan).
        response.delete_cookie(settings.SESSION_COOKIE_NAME)
        return response


# --------------------------------------------------------------------------- #
# E4 — me
# --------------------------------------------------------------------------- #
@extend_schema(
    summary="Profil user aktif (session ATAU device token)",
    description=(
        "Mengembalikan user yang sedang aktif. Bila request masuk lewat cookie "
        "`device_token`, `device_profile` (+`wc_code`) ikut diisi; tanpa kredensial → 401."
    ),
    responses={200: OpenApiTypes.OBJECT, 401: OpenApiTypes.OBJECT},
    tags=[TAG],
)
class AuthMeView(APIView):
    """`GET /api/v1/auth/me/` — frontend memakainya untuk tahu siapa yang login (E4)."""

    permission_classes = [IsAuthenticated]
    authentication_classes = list(AUTH_CLASSES)

    def get(self, request):
        """Data user + info perangkat (bila request datang dari device binding)."""
        body = serialize_session_user(request.user)

        binding = getattr(request, "device_binding", None)
        body["device_profile"] = (
            binding.device_profile.code if binding is not None else None
        )
        body["wc_code"] = (binding.wc_code or None) if binding is not None else None
        return Response(body, status=status.HTTP_200_OK)


# --------------------------------------------------------------------------- #
# E5 — ganti password sendiri
# --------------------------------------------------------------------------- #
@extend_schema(
    summary="Ganti password sendiri",
    description=(
        "Body `{old_password, new_password}`. Password lama salah → 400; password baru "
        "kurang dari 8 karakter → 400. Sesi yang sedang dipakai tetap hidup."
    ),
    request=OpenApiTypes.OBJECT,
    responses={
        200: OpenApiTypes.OBJECT,
        400: OpenApiTypes.OBJECT,
        401: OpenApiTypes.OBJECT,
    },
    tags=[TAG],
)
class AuthChangePasswordView(APIView):
    """`POST /api/v1/auth/change-password/` — ganti password user yang login (E5)."""

    permission_classes = [IsAuthenticated]
    authentication_classes = list(AUTH_CLASSES)

    def post(self, request):
        """`check_password` lama → `set_password` baru (selalu lewat hash Django)."""
        csrf_error = _csrf_error(request)
        if csrf_error is not None:
            return csrf_error

        data = _json_body(request)
        old_password = str(data.get("old_password") or "")
        new_password = str(data.get("new_password") or "")
        if not old_password or not new_password:
            return Response(
                {"detail": "Field 'old_password' dan 'new_password' wajib diisi."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(new_password) < MIN_PASSWORD_LENGTH:
            return Response(
                {"detail": f"Password baru minimal {MIN_PASSWORD_LENGTH} karakter."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = request.user
        if not user.check_password(old_password):
            return Response(
                {"detail": "Password lama salah"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(new_password)
        user.save(update_fields=["password"])
        # Tanpa ini hash sesi ikut berubah → user yang baru ganti password
        # langsung ter-logout sendiri.
        update_session_auth_hash(request._request, user)
        return Response({"ok": True}, status=status.HTTP_200_OK)


# --------------------------------------------------------------------------- #
# E6 — admin reset password user lain
# --------------------------------------------------------------------------- #
@extend_schema(
    summary="Reset password user lain (admin/owner)",
    description=(
        "Body `{new_password}`. Admin/owner → 200 `{ok, user_id}`; bukan admin → 403; "
        "user tidak ada → 404."
    ),
    request=OpenApiTypes.OBJECT,
    responses={
        200: OpenApiTypes.OBJECT,
        400: OpenApiTypes.OBJECT,
        403: OpenApiTypes.OBJECT,
        404: OpenApiTypes.OBJECT,
    },
    tags=[TAG],
)
class AuthResetPasswordView(APIView):
    """`POST /api/v1/auth/reset-password/<user_id>/` — admin ganti password user (E6)."""

    permission_classes = [IsAuthenticated]
    authentication_classes = list(AUTH_CLASSES)

    def post(self, request, user_id: int):
        """Set password baru tanpa password lama (wewenang admin/owner)."""
        csrf_error = _csrf_error(request)
        if csrf_error is not None:
            return csrf_error

        require_admin(request)  # non-admin/owner → 403

        new_password = str(_json_body(request).get("new_password") or "")
        if len(new_password) < MIN_PASSWORD_LENGTH:
            return Response(
                {"detail": f"Password baru minimal {MIN_PASSWORD_LENGTH} karakter."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        target = User.objects.filter(pk=user_id).first()
        if target is None:
            return Response(
                {"detail": "User tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        target.set_password(new_password)
        target.save(update_fields=["password"])
        logger.info(
            "auth: password user '%s' (id=%s) di-reset oleh '%s'.",
            target.get_username(),
            target.pk,
            request.user.get_username(),
        )
        return Response({"ok": True, "user_id": target.pk}, status=status.HTTP_200_OK)




