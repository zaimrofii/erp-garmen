"""DeviceTokenAuthentication — auth DRF berbasis **cookie binding** (Fase G).

Kenapa cookie, bukan header:
  * perangkat lantai (kios/scanner) tidak melewati alur login; yang mengikat
    mereka ke sebuah work center adalah *device binding* yang dibuat sekali lewat
    `POST /api/v1/devices/bind`, dan token-nya disimpan sebagai cookie
    **HttpOnly** (tidak bisa dibaca JavaScript → aman dari XSS) serta otomatis
    ikut di setiap request tanpa kode di klien;
  * header `Authorization: Bearer <token>` tetap didukung DRF lewat
    `SessionAuthentication`/penambahan authenticator di fase auth user nanti —
    frontend sudah mengirimnya (seam hidup), backend tinggal memakainya.

Alur `authenticate()` (fail-safe, **tidak pernah** raise):
  1. catat `X-Device-Id` (header opsional dari klien) untuk observability;
  2. baca cookie `device_token`; tidak ada/tidak dikenal/profil nonaktif → `None`
     (request tetap anonim, tidak ada 401/403);
  3. binding valid: `last_seen_at` di-touch, `request.device_binding` diisi
     (dipakai view/audit);
  4. kalau binding punya `user` aktif → autentikasi sebagai user itu, sehingga
     `UserRateThrottle` memakai kuota user (300/min) alih-alih anon (60/min);
     kalau tidak ada user → tetap anonim (kuota anon) tetapi binding tetap
     terlampir di request.

`X-Device-Id` **tidak** dipakai untuk autentikasi: nilainya id opaque dari klien
(bukan rahasia), jadi mempercayainya sebagai identitas = lubang keamanan.
"""

from __future__ import annotations

import logging

from rest_framework.authentication import BaseAuthentication

logger = logging.getLogger(__name__)

__all__ = ("DEVICE_ID_HEADER", "DeviceTokenAuthentication")

#: Header opsional yang dikirim klien (frontend `api-client.ts`). Redundan
#: dengan cookie — hanya dicatat untuk diagnosa/audit, bukan bukti identitas.
DEVICE_ID_HEADER = "X-Device-Id"


class DeviceTokenAuthentication(BaseAuthentication):
    """Autentikasi dari cookie `device_token` (device binding)."""

    def authenticate(self, request):
        """Kembalikan `(user, binding)` kalau binding punya user; selain itu `None`."""
        self._attach_device_id(request)

        binding = self._binding(request)
        if binding is None:
            return None

        # Selalu tempelkan binding ke request: view/audit bisa memakainya walau
        # binding-nya belum terhubung ke user.
        request.device_binding = binding

        user = getattr(binding, "user", None)
        if user is not None and user.is_active:
            logger.debug(
                "device binding %s autentik sebagai user %s.", binding.pk, user.get_username()
            )
            return (user, binding)

        logger.debug(
            "device binding %s terpasang tanpa user (profil=%s) -> request tetap anonim.",
            binding.pk,
            binding.device_profile.code,
        )
        return None

    def authenticate_header(self, request) -> str:
        """Tidak ada skema challenge (bukan skema token header) → `''`.

        Dikosongkan supaya DRF membalas **401** (bukan 403) bila suatu saat ada
        view yang mewajibkan autentikasi; saat sekarang semua view `AllowAny`.
        """
        return ""

    # --------------------------------------------------------------- internal
    @staticmethod
    def _attach_device_id(request) -> None:
        """Catat `X-Device-Id` di request (opsional, tanpa validasi/penolakan)."""
        try:
            headers = getattr(request, "headers", None)
            value = headers.get(DEVICE_ID_HEADER) if headers is not None else None
            if value is None:
                meta = getattr(request, "META", {}) or {}
                value = meta.get("HTTP_X_DEVICE_ID")
        except Exception:  # noqa: BLE001 - request eksotis jangan sampai bikin 500
            value = None

        request.device_id_header = str(value).strip() if value else ""

    @staticmethod
    def _binding(request):
        """Binding dari cookie `device_token`; exception apa pun → `None`."""
        try:
            from core.device_profile.services import binding_from_request

            return binding_from_request(request)
        except Exception:  # noqa: BLE001 - auth tidak boleh mematikan request
            logger.warning("gagal membaca device binding dari cookie.", exc_info=True)
            return None
