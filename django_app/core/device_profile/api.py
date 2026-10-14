"""Endpoint core device resolver (Fase G):

  * ``GET  /api/v1/devices/me``     -> resolve profil device (kontrak §5.1, read-only)
  * ``POST /api/v1/devices/bind``   -> bind perangkat ini + set cookie `device_token`
  * ``POST /api/v1/devices/unbind`` -> cabut binding + hapus cookie

**BASE ENDPOINT INI BUKAN API GARMEN.** Semuanya milik core engine (UI multi-device
adaptive) supaya semua app domain bisa tahu "perangkat ini harus tampil bagaimana".
Karena itu path-nya di bawah kontrak core `/api/v1/...`, bukan di bawah `/api/`
milik app garmen.

Param/header yang diterima `GET /devices/me` (semua opsional):

  * `?device=<CODE>`      -> override profil (prioritas tertinggi, level 1)
  * header `X-Device-Profile` -> alias override yang sama
  * cookie `device_token` -> device binding (level 2)
  * `?hint=<CODE>`        -> `device_hint` di resource metadata (level 4)
  * `?wc=<KODE_WC>`       -> `wc_code` di resource metadata
  * `?resource=<nama>`    -> nama resource, diteruskan apa adanya

Response 200 (persis kontrak §5.1)::

    {"device_profile": "OPERATOR_HP", "confidence": "low",
     "source": "fallback", "wc_code": null}
"""

from __future__ import annotations

import logging

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.audit.services import AuditLogger

from .services import (
    CONFIDENCE_HIGH,
    DEVICE_COOKIE_NAME,
    FALLBACK_PROFILE_CODE,
    SOURCE_DEVICE_BINDING,
    SOURCE_FALLBACK,
    DeviceProfileError,
    DeviceProfileResolver,
    allowed_profile_codes,
)

logger = logging.getLogger(__name__)

#: Nama resource untuk jejak audit device bind/unbind (FASE 4.1).
AUDIT_RESOURCE = "devices"
AUDIT_ACTION_BIND = "device.bind"
AUDIT_ACTION_UNBIND = "device.unbind"

#: `resource_id` audit untuk unbind: binding dicabut berdasarkan cookie `device_token`
#: dan `revoke_binding()` hanya mengembalikan bool, jadi tidak ada pk device yang
#: tersedia. User/IP/request_id tetap tercatat oleh `AuditLogger`.
UNBIND_RESOURCE_ID = "current-device"


def _audit_device_action(request, action: str, resource_id, metadata: dict) -> None:
    """Tulis :class:`~core.audit.models.AuditLog` untuk bind/unbind device.

    **Best-effort**: kegagalan audit TIDAK boleh menggagalkan bind/unbind yang
    sudah berhasil (pola sama dengan `ActionView._audit`).
    """

    try:
        AuditLogger().log(
            user=None,  # diambil dari request.user (endpoint kini IsAuthenticated)
            action=action,
            resource=AUDIT_RESOURCE,
            resource_id=resource_id,
            request=request,
            metadata=metadata,
        )
    except Exception:  # noqa: BLE001 - audit tidak boleh mematikan alur device
        logger.exception("audit: gagal mencatat %s (%s#%s)", action, AUDIT_RESOURCE, resource_id)


class DeviceMeView(APIView):
    """Resolve profil device untuk request saat ini (read-only, tanpa auth)."""

    # Perangkat (kios/scanner) perlu tahu profilnya SEBELUM login, jadi endpoint
    # ini sengaja terbuka; yang dikembalikan hanya nama profil, bukan data bisnis.
    permission_classes = [AllowAny]

    def get(self, request):
        """Kembalikan `{device_profile, confidence, source, wc_code}`."""
        metadata: dict = {}

        resource = request.query_params.get("resource")
        if resource:
            metadata["resource"] = resource

        device_hint = request.query_params.get("hint")
        if device_hint:
            metadata["device_hint"] = device_hint

        wc_code = request.query_params.get("wc")
        if wc_code:
            metadata["wc_code"] = wc_code

        resolved = DeviceProfileResolver().resolve(request, metadata or None)

        return Response(
            {
                "device_profile": resolved.profile,
                "confidence": resolved.confidence,
                "source": resolved.source,
                "wc_code": resolved.wc_code,
            },
            status=status.HTTP_200_OK,
        )


def read_profile_code(data: dict) -> tuple[str | None, dict | None]:
    """PURE — baca `device_profile` dari body; return `(code, error_body)`.

    Kosong → error 400 berisi daftar kode yang **ada di DB** supaya operator tahu
    pilihan yang sah (bukan daftar hardcode yang bisa basi).
    """
    raw = data.get("device_profile")
    code = str(raw).strip().upper() if raw is not None else ""
    if code == "":
        return None, {
            "detail": "Field 'device_profile' wajib diisi.",
            "allowed": allowed_profile_codes(),
        }
    return code, None


@extend_schema(
    summary="Bind perangkat ini ke sebuah profil device",
    description=(
        "Membuat/meng-update device binding untuk perangkat ini lalu mengirim cookie "
        "`device_token` (HttpOnly, SameSite=Lax). Butuh login (`IsAuthenticated`) — "
        "kode profil harus ada & aktif di DB, dan aksi ini tercatat di `AuditLog`."
    ),
    request=OpenApiTypes.OBJECT,
    responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT},
    tags=["devices"],
)
class DeviceBindView(APIView):
    """`POST /api/v1/devices/bind` — body `{device_profile, wc_code?}` (Fase G)."""

    # FASE 4.1 (hardening): bind mengikat PROFIL + work center ke cookie perangkat
    # → wajib login (kios pairing harus login dulu). Dulu `AllowAny`.
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """Set cookie `device_token` + balas profil yang baru di-bind."""
        data = request.data if isinstance(request.data, dict) else {}
        profile_code, error = read_profile_code(data)
        if error is not None:
            return Response(error, status=status.HTTP_400_BAD_REQUEST)

        wc_code = str(data.get("wc_code") or request.query_params.get("wc") or "").strip()

        try:
            binding = DeviceProfileResolver().bind_current_device(
                request, profile_code, wc_code or None
            )
        except DeviceProfileError as exc:
            return Response(
                {"detail": str(exc), "allowed": allowed_profile_codes()},
                status=status.HTTP_400_BAD_REQUEST,
            )

        response = Response(
            {
                "device_profile": binding.device_profile.code,
                "confidence": CONFIDENCE_HIGH,
                "source": SOURCE_DEVICE_BINDING,
                "wc_code": binding.wc_code or None,
            },
            status=status.HTTP_200_OK,
        )
        DeviceProfileResolver.set_device_cookie(response, binding)
        _audit_device_action(
            request,
            AUDIT_ACTION_BIND,
            binding.device_profile.code,
            {
                # DeviceBinding tidak punya field `device_code` terpisah: yang
                # mengidentifikasi perangkat adalah cookie token. `device_code`
                # di sini = kode profil device yang di-bind (maksud audit).
                "device_code": binding.device_profile.code,
                "device_type": binding.device_profile.code,
                "wc_code": binding.wc_code or None,
                "binding_id": binding.pk,
            },
        )
        return response


@extend_schema(
    summary="Cabut device binding perangkat ini",
    description="Menghapus baris `DeviceBinding` milik cookie + menghapus cookie `device_token`.",
    request=None,
    responses={200: OpenApiTypes.OBJECT},
    tags=["devices"],
)
class DeviceUnbindView(APIView):
    """`POST /api/v1/devices/unbind` — cabut binding device ini (Fase G)."""

    # FASE 4.1 (hardening): mencabut binding = aksi yang MENGUBAH data → wajib login.
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """Hapus binding (kalau ada) + hapus cookie → resolver kembali ke fallback."""
        revoked = DeviceProfileResolver().revoke_binding(request)

        response = Response(
            {
                "ok": True,
                "revoked": revoked,
                "device_profile": FALLBACK_PROFILE_CODE if revoked else None,
                "source": SOURCE_FALLBACK,
                "wc_code": None,
            },
            status=status.HTTP_200_OK,
        )
        response.delete_cookie(DEVICE_COOKIE_NAME)
        _audit_device_action(
            request,
            AUDIT_ACTION_UNBIND,
            UNBIND_RESOURCE_ID,
            {"revoked": bool(revoked)},
        )
        return response

