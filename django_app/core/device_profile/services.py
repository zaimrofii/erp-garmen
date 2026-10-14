"""DeviceProfileResolver — resolusi profil device dari request (core, generik).

Urutan prioritas (kontrak §5.2) — level pertama yang "kena" dipakai:

  1. URL override    `?device=<CODE>` / header `X-Device-Profile`
                     -> source="url_override",    confidence="high"
  2. Device binding  cookie `device_token` cocok dengan `DeviceBinding`
                     -> source="device_binding",  confidence="high"
  3. User preference `request.user.preferred_device_profile` (kalau atribut ada)
                     -> source="user_preference", confidence="medium"
  4. Metadata hint   `resource_metadata["device_hint"]`
                     -> source="metadata_hint",   confidence="medium"
  5. Fallback        `OPERATOR_HP`
                     -> source="fallback",        confidence="low"

Kode profil dari level 1/3/4 divalidasi ke DB (harus ada & aktif); kalau tidak
dikenal level itu **dilewati** (tidak ada profil hantu). Fallback sengaja tidak
divalidasi supaya endpoint tetap berguna walau tabel profil masih kosong.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import DeviceBinding, DeviceProfile

logger = logging.getLogger(__name__)

DEVICE_COOKIE_NAME = "device_token"
DEVICE_QUERY_PARAM = "device"
DEVICE_HEADER_NAME = "X-Device-Profile"
FALLBACK_PROFILE_CODE = "OPERATOR_HP"

CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"

SOURCE_URL_OVERRIDE = "url_override"
SOURCE_DEVICE_BINDING = "device_binding"
SOURCE_USER_PREFERENCE = "user_preference"
SOURCE_METADATA_HINT = "metadata_hint"
SOURCE_FALLBACK = "fallback"

COOKIE_MAX_AGE = 60 * 60 * 24 * 365  # 1 tahun

#: Interval minimal update `last_seen_at` (detik) — hardening Fase H.
#: Temuan load test 100 RPS: menulis `last_seen_at` di SETIAP request authenticated
#: membuat write amplification + transaksi panjang sehingga koneksi Postgres cepat
#: habis ("too many clients"). Cukup sekali per menit per perangkat untuk jejak
#: "terakhir terlihat" — sisanya jalur baca murni.
LAST_SEEN_REFRESH_SECONDS = 60


class DeviceProfileError(ValidationError):
    """Error resolver (mis. profil tujuan `bind_device` tidak ada/nonaktif)."""


@dataclass(frozen=True)
class ResolvedDevice:
    """Profil yang dipakai + dari mana asalnya (untuk audit/telemetry UI)."""

    profile: str
    confidence: str
    source: str
    wc_code: str | None = None


class DeviceProfileResolver:
    """Resolver profil device: 4 level prioritas + fallback (stateless)."""

    def resolve(
        self, request, resource_metadata: Mapping[str, Any] | None = None
    ) -> ResolvedDevice:
        """Tentukan profil device untuk `request` (lihat urutan prioritas modul)."""
        metadata = dict(resource_metadata or {})
        wc_code = self._metadata_wc_code(metadata)

        # 1. Override eksplisit dari URL/header.
        override_code = self._override_code(request)
        if override_code and self._is_active_profile(override_code):
            return ResolvedDevice(
                profile=override_code,
                confidence=CONFIDENCE_HIGH,
                source=SOURCE_URL_OVERRIDE,
                wc_code=wc_code,
            )

        # 2. Binding perangkat (cookie) — paling akurat untuk kios/scanner.
        binding = self._binding_from_request(request)
        if binding is not None:
            return ResolvedDevice(
                profile=binding.device_profile.code,
                confidence=CONFIDENCE_HIGH,
                source=SOURCE_DEVICE_BINDING,
                wc_code=binding.wc_code,
            )

        # 3. Preferensi user (atribut opsional; dilewati kalau tidak ada).
        preference = self._user_preference_code(request)
        if preference and self._is_active_profile(preference):
            return ResolvedDevice(
                profile=preference,
                confidence=CONFIDENCE_MEDIUM,
                source=SOURCE_USER_PREFERENCE,
                wc_code=wc_code,
            )

        # 4. Hint dari metadata resource.
        hint = metadata.get("device_hint")
        if hint and self._is_active_profile(str(hint)):
            return ResolvedDevice(
                profile=str(hint),
                confidence=CONFIDENCE_MEDIUM,
                source=SOURCE_METADATA_HINT,
                wc_code=wc_code,
            )

        # 5. Fallback.
        return ResolvedDevice(
            profile=FALLBACK_PROFILE_CODE,
            confidence=CONFIDENCE_LOW,
            source=SOURCE_FALLBACK,
            wc_code=wc_code,
        )

    def bind_device(self, user, wc_code: str, device_profile_code: str) -> DeviceBinding:
        """Buat/update binding (user, wc_code, profil) + token cookie baru.

        Helper ini **tidak** menyentuh response — pemanggil memakai
        `set_device_cookie(...)` kalau ingin mengirim cookie ke browser.
        """
        profile = self._get_active_profile(device_profile_code)
        now = timezone.now()
        binding = DeviceBinding.objects.filter(
            user=user, wc_code=wc_code, device_profile=profile
        ).first()

        if binding is None:
            return DeviceBinding.objects.create(
                user=user,
                wc_code=wc_code,
                device_profile=profile,
                cookie_token=self._new_token(),
                last_seen_at=now,
            )

        # Binding sudah ada: token dirotasi + last_seen diperbarui.
        binding.cookie_token = self._new_token()
        binding.last_seen_at = now
        binding.save(update_fields=["cookie_token", "last_seen_at"])
        return binding

    def binding_from_request(self, request) -> DeviceBinding | None:
        """Nama publik `_binding_from_request` — dipakai `DeviceTokenAuthentication` (Fase G)."""
        return self._binding_from_request(request)

    def bind_current_device(
        self, request, device_profile_code: str, wc_code: str | None = None
    ) -> DeviceBinding:
        """Bind perangkat **ini** (idempotent): update binding cookie yang ada, atau buat baru.

        Beda dengan `bind_device()` (helper lama, mencari berdasarkan
        user+wc+profil): di sini binding yang sudah dimiliki request itulah yang
        di-update (profil/token dirotasi), sehingga browser tidak menumpuk
        binding lama yang tidak terpakai lagi. `wc_code` opsional — kalau tidak
        dikirim, nilai lama dipertahankan (`""` untuk binding baru).
        """
        profile = self._get_active_profile(device_profile_code)
        existing = self._binding_from_request(request)

        if existing is None:
            return self.bind_device(
                _authenticated_user(request), str(wc_code or ""), device_profile_code
            )

        existing.device_profile = profile
        if wc_code:
            existing.wc_code = str(wc_code)
        existing.cookie_token = self._new_token()
        existing.last_seen_at = timezone.now()
        existing.save(
            update_fields=["device_profile", "wc_code", "cookie_token", "last_seen_at"]
        )
        logger.info(
            "device binding %s di-bind ulang ke profil '%s'.", existing.pk, profile.code
        )
        return existing

    def revoke_binding(self, request) -> bool:
        """Hapus binding milik cookie request; `True` kalau ada yang dihapus (Fase G)."""
        binding = self._binding_from_request(request)
        if binding is None:
            return False

        binding.delete()
        logger.info("device binding %s dicabut (unbind).", binding.pk)
        return True

    @staticmethod
    def set_device_cookie(
        response, binding: DeviceBinding, max_age: int = COOKIE_MAX_AGE
    ):
        """Set cookie `device_token` dari binding (helper terpisah, opsional).

        `HttpOnly` (tidak bisa dibaca JavaScript) + `SameSite=Lax` (aman untuk
        navigasi normal, tidak ikut request lintas-situs). `Secure` mengikuti
        `settings.DEVICE_COOKIE_SECURE` (default: `not DEBUG`) — di dev
        `http://localhost` cookie tetap bisa disimpan browser.
        """
        response.set_cookie(
            DEVICE_COOKIE_NAME,
            binding.cookie_token,
            max_age=max_age,
            httponly=True,
            samesite="Lax",
            secure=device_cookie_secure(),
        )
        return response

    # ----------------------------------------------------------------- helpers
    @staticmethod
    def _override_code(request) -> str:
        """Kode override dari `?device=` (alternatif: header X-Device-Profile)."""
        params = getattr(request, "query_params", None) or getattr(request, "GET", {})
        code = params.get(DEVICE_QUERY_PARAM) if hasattr(params, "get") else None
        if not code:
            headers = getattr(request, "headers", None) or getattr(request, "META", {})
            code = headers.get(DEVICE_HEADER_NAME) or headers.get(
                "HTTP_X_DEVICE_PROFILE"
            )
        return str(code).strip() if code else ""

    def _binding_from_request(self, request) -> DeviceBinding | None:
        """Cari binding dari cookie `device_token` (sekalian update `last_seen_at`)."""
        cookies = getattr(request, "COOKIES", None) or {}
        token = str(cookies.get(DEVICE_COOKIE_NAME) or "").strip()
        if not token:
            return None

        binding = (
            DeviceBinding.objects.select_related("device_profile")
            .filter(cookie_token=token)
            .first()
        )
        if binding is None:
            logger.info(
                "cookie %s tidak dikenal -> lanjut ke level berikutnya.",
                DEVICE_COOKIE_NAME,
            )
            return None
        if not binding.device_profile.is_active:
            logger.info(
                "profil '%s' nonaktif -> lanjut ke level berikutnya.",
                binding.device_profile.code,
            )
            return None

        # Touch: jejak "perangkat terakhir terlihat". Dibatasi intervalnya supaya
        # jalur authenticated tidak menulis ke DB di setiap request (lihat
        # `LAST_SEEN_REFRESH_SECONDS`).
        if self._should_touch_last_seen(binding):
            DeviceBinding.objects.filter(pk=binding.pk).update(last_seen_at=timezone.now())
        return binding

    @staticmethod
    def _should_touch_last_seen(binding: DeviceBinding) -> bool:
        """True kalau `last_seen_at` kosong atau sudah lebih lama dari interval refresh."""
        last_seen = binding.last_seen_at
        if last_seen is None:
            return True

        return (timezone.now() - last_seen).total_seconds() >= LAST_SEEN_REFRESH_SECONDS

    @staticmethod
    def _user_preference_code(request) -> str:
        """Baca `request.user.preferred_device_profile` (dilewati kalau atribut tidak ada)."""
        user = getattr(request, "user", None)
        preference = getattr(user, "preferred_device_profile", None)
        if preference is None:
            return ""
        return getattr(preference, "code", None) or str(preference).strip()

    @staticmethod
    def _metadata_wc_code(metadata: Mapping[str, Any]) -> str | None:
        """`wc_code` dari metadata resource (kalau pemanggil mengirimkannya)."""
        wc_code = metadata.get("wc_code")
        return str(wc_code) if wc_code else None

    @staticmethod
    def _is_active_profile(code: str) -> bool:
        return DeviceProfile.objects.filter(code=str(code), is_active=True).exists()

    @staticmethod
    def _get_active_profile(code: str) -> DeviceProfile:
        profile = DeviceProfile.objects.filter(code=str(code), is_active=True).first()
        if profile is None:
            raise DeviceProfileError(
                f"device profile '{code}' tidak ditemukan atau tidak aktif."
            )
        return profile

    @staticmethod
    def _new_token() -> str:
        """Token cookie baru (url-safe, aman untuk kolom 64 karakter)."""
        return secrets.token_urlsafe(32)


def binding_from_request(request) -> DeviceBinding | None:
    """Binding aktif untuk `request` (cookie `device_token`); `None` kalau tidak ada.

    Dipakai `DeviceTokenAuthentication` (Fase G) supaya logika pembacaan cookie
    tetap **satu tempat** dengan resolver profil.
    """
    return DeviceProfileResolver().binding_from_request(request)


def allowed_profile_codes() -> list[str]:
    """Kode profil aktif di DB — sumber tunggal untuk validasi & pesan error 400.

    Kode **tidak** di-hardcode di kode Python: admin boleh menambah profil baru
    lewat admin tanpa deploy (blueprint: konfigurasi = data).
    """
    return list(
        DeviceProfile.objects.filter(is_active=True)
        .order_by("code")
        .values_list("code", flat=True)
    )


def _authenticated_user(request):
    """User terautentikasi dari request, atau `None` (AnonymousUser bukan FK valid)."""
    user = getattr(request, "user", None)
    return user if getattr(user, "is_authenticated", False) else None


def device_cookie_secure() -> bool:
    """Atribut `Secure` cookie device — default `not DEBUG` (Fase G).

    Di produksi (DEBUG=False) cookie hanya dikirim lewat HTTPS; di dev
    (DEBUG=True) tetap bisa disimpan browser saat diakses via http://localhost.
    Bisa dioverride eksplisit lewat `settings.DEVICE_COOKIE_SECURE`.
    """
    default = not bool(getattr(settings, "DEBUG", False))
    return bool(getattr(settings, "DEVICE_COOKIE_SECURE", default))


