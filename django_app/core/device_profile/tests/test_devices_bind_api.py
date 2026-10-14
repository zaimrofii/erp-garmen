"""Test endpoint `POST /api/v1/devices/bind` + `/unbind` (Fase G).

Bukti yang dijaga:
  * bind valid → 200 `{device_profile, source:"device_binding"}` + cookie
    `device_token` (HttpOnly, SameSite=Lax);
  * `GET /api/v1/devices/me` sesudah bind → `source:"device_binding"` (rantai
    kontrak §5.1 benar-benar tercapai lewat API, bukan hanya di service);
  * unbind → cookie dihapus + baris binding hilang → resolver kembali `fallback`;
  * kode profil mengikuti enum kontrak UI (OPERATOR_HP/KIOSK_TABLET/SCANNER_USB/DESKTOP);
  * semua jalur gagal = 400 dengan daftar kode yang sah (tanpa 500).
"""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from core.audit.models import AuditLog
from core.auth.models import User
from core.device_profile.api import read_profile_code
from core.device_profile.models import DeviceBinding, DeviceProfile
from core.device_profile.services import (
    DEVICE_COOKIE_NAME,
    SOURCE_DEVICE_BINDING,
    device_cookie_secure,
)

BIND_URL = "/api/v1/devices/bind"
UNBIND_URL = "/api/v1/devices/unbind"
ME_URL = "/api/v1/devices/me"


class ReadProfileCodeTests(TestCase):
    """Helper murni pembaca body bind."""

    def test_kode_dinormalisasi_uppercase(self):
        code, error = read_profile_code({"device_profile": " kiosk_tablet "})

        self.assertEqual(code, "KIOSK_TABLET")
        self.assertIsNone(error)

    def test_kosong_atau_hilang_menghasilkan_error_berisi_daftar_kode(self):
        for body in ({}, {"device_profile": ""}, {"device_profile": "   "}):
            code, error = read_profile_code(body)
            self.assertIsNone(code)
            self.assertIn("wajib diisi", error["detail"])
            self.assertIn("KIOSK_TABLET", error["allowed"])


class DeviceBindApiTests(TestCase):
    """Bind via API + cookie yang dikirim ke klien."""

    def setUp(self):
        self.client = APIClient()
        # FASE 4.1: `POST /devices/bind` kini `IsAuthenticated` (dulu AllowAny).
        self.user = User.objects.create_user(username="kios-bind", password="x")
        self.client.force_authenticate(self.user)

    def test_bind_sukses_mengirim_cookie(self):
        response = self.client.post(
            BIND_URL, {"device_profile": "SCANNER_USB", "wc_code": "WC-SEWING"}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["device_profile"], "SCANNER_USB")
        self.assertEqual(body["source"], SOURCE_DEVICE_BINDING)
        self.assertEqual(body["confidence"], "high")
        self.assertEqual(body["wc_code"], "WC-SEWING")

        cookie = response.cookies[DEVICE_COOKIE_NAME]
        binding = DeviceBinding.objects.get()
        self.assertEqual(cookie.value, binding.cookie_token)
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Lax")
        self.assertEqual(bool(cookie["secure"]), device_cookie_secure())

    def test_devices_me_setelah_bind_mengembalikan_source_device_binding(self):
        bind = self.client.post(BIND_URL, {"device_profile": "KIOSK_TABLET"}, format="json")
        token = bind.cookies[DEVICE_COOKIE_NAME].value

        # Klien baru yang membawa cookie hasil bind (seperti browser/tablet).
        klien = APIClient()
        klien.cookies[DEVICE_COOKIE_NAME] = token
        response = klien.get(ME_URL)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        # shape kontrak §5.1 TIDAK berubah (4 key yang sama)
        self.assertEqual(set(body), {"device_profile", "confidence", "source", "wc_code"})
        self.assertEqual(body["device_profile"], "KIOSK_TABLET")
        self.assertEqual(body["source"], "device_binding")
        self.assertEqual(body["confidence"], "high")

    def test_bind_diulang_mengupdate_binding_yang_sama_dan_rotasi_token(self):
        pertama = self.client.post(BIND_URL, {"device_profile": "OPERATOR_HP"}, format="json")
        token_awal = pertama.cookies[DEVICE_COOKIE_NAME].value

        self.client.cookies[DEVICE_COOKIE_NAME] = token_awal
        kedua = self.client.post(BIND_URL, {"device_profile": "DESKTOP"}, format="json")

        self.assertEqual(kedua.status_code, 200)
        self.assertEqual(kedua.json()["device_profile"], "DESKTOP")
        self.assertEqual(DeviceBinding.objects.count(), 1)  # tidak menumpuk binding
        self.assertNotEqual(kedua.cookies[DEVICE_COOKIE_NAME].value, token_awal)

    def test_keempat_kode_kontrak_ui_diterima(self):
        for code in ("OPERATOR_HP", "KIOSK_TABLET", "SCANNER_USB", "DESKTOP"):
            klien = APIClient()
            # FASE 4.1: bind kini `IsAuthenticated` (klien baru perlu auth juga).
            klien.force_authenticate(self.user)
            response = klien.post(BIND_URL, {"device_profile": code}, format="json")

            self.assertEqual(response.status_code, 200, f"{code} ditolak")
            self.assertEqual(response.json()["device_profile"], code)
            self.assertTrue(DeviceProfile.objects.filter(code=code).exists(), code)

    def test_profil_tidak_dikenal_400_dengan_daftar_kode(self):
        response = self.client.post(BIND_URL, {"device_profile": "PROFIL_GAIB"}, format="json")

        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertIn("tidak ditemukan", body["detail"])
        self.assertIn("SCANNER_USB", body["allowed"])
        self.assertEqual(DeviceBinding.objects.count(), 0)

    def test_field_kosong_400(self):
        response = self.client.post(BIND_URL, {}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("wajib diisi", response.json()["detail"])

    def test_profil_nonaktif_400(self):
        profile = DeviceProfile.objects.get(code="DESKTOP")
        profile.is_active = False
        profile.save(update_fields=["is_active"])

        response = self.client.post(BIND_URL, {"device_profile": "DESKTOP"}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertNotIn("DESKTOP", response.json()["allowed"])

    def test_trailing_slash_juga_dilayani(self):
        response = self.client.post(
            f"{BIND_URL}/", {"device_profile": "KIOS"}, format="json"
        )

        self.assertEqual(response.status_code, 200)


class DeviceUnbindApiTests(TestCase):
    """Unbind: hapus binding + cookie, resolver kembali ke fallback."""

    def setUp(self):
        self.client = APIClient()
        # FASE 4.1: `POST /devices/unbind` kini `IsAuthenticated`.
        self.user = User.objects.create_user(username="kios-unbind", password="x")
        self.client.force_authenticate(self.user)

    def bind(self, code: str = "SCANNER_USB"):
        response = self.client.post(BIND_URL, {"device_profile": code}, format="json")
        self.client.cookies[DEVICE_COOKIE_NAME] = response.cookies[DEVICE_COOKIE_NAME].value
        return response

    def test_unbind_menghapus_binding_dan_cookie(self):
        self.bind()
        self.assertEqual(DeviceBinding.objects.count(), 1)

        response = self.client.post(UNBIND_URL, {}, format="json")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["revoked"])
        self.assertEqual(body["source"], "fallback")
        self.assertEqual(DeviceBinding.objects.count(), 0)

        cookie = response.cookies[DEVICE_COOKIE_NAME]
        self.assertEqual(cookie.value, "")
        self.assertEqual(cookie["max-age"], 0)

        # Tanpa binding, /devices/me kembali ke fallback.
        klien = APIClient()
        self.assertEqual(klien.get(ME_URL).json()["source"], "fallback")

    def test_unbind_tanpa_cookie_tetap_200(self):
        response = self.client.post(UNBIND_URL, {}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["revoked"])
        self.assertIsNone(response.json()["device_profile"])

    def test_unbind_menghapus_binding_di_db(self):
        """Token lama tidak bisa dipakai lagi setelah unbind (bukan hanya cookie)."""
        self.bind("KIOS")
        token = self.client.cookies[DEVICE_COOKIE_NAME].value

        self.client.post(UNBIND_URL, {}, format="json")

        klien = APIClient()
        klien.cookies[DEVICE_COOKIE_NAME] = token
        self.assertEqual(klien.get(ME_URL).json()["source"], "fallback")


class DeviceAuthAndAuditTests(TestCase):
    """FASE 4.1: bind/unbind wajib login + jejak `AuditLog` (best-effort)."""

    def setUp(self):
        self.client = APIClient()

    def test_bind_anonim_403(self):
        response = self.client.post(BIND_URL, {"device_profile": "KIOS"}, format="json")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(DeviceBinding.objects.count(), 0)

    def test_unbind_anonim_403(self):
        response = self.client.post(UNBIND_URL, {}, format="json")

        self.assertEqual(response.status_code, 403)

    def test_bind_sukses_mencatat_audit(self):
        user = User.objects.create_user(username="kios-audit", password="x")
        self.client.force_authenticate(user)

        response = self.client.post(
            BIND_URL,
            {"device_profile": "KIOSK_TABLET", "wc_code": "WC-PACKING"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        log = AuditLog.objects.get(action="device.bind")
        self.assertEqual(log.resource, "devices")
        self.assertEqual(log.resource_id, "KIOSK_TABLET")
        self.assertEqual(log.user, user)
        self.assertEqual(log.result, AuditLog.Result.OK)
        self.assertEqual(log.metadata["device_code"], "KIOSK_TABLET")
        self.assertEqual(log.metadata["device_type"], "KIOSK_TABLET")
        self.assertEqual(log.metadata["wc_code"], "WC-PACKING")

    def test_unbind_sukses_mencatat_audit(self):
        user = User.objects.create_user(username="kios-audit-2", password="x")
        self.client.force_authenticate(user)
        self.client.post(BIND_URL, {"device_profile": "KIOS"}, format="json")

        response = self.client.post(UNBIND_URL, {}, format="json")

        self.assertEqual(response.status_code, 200)
        log = AuditLog.objects.get(action="device.unbind")
        self.assertEqual(log.user, user)
        self.assertTrue(log.metadata["revoked"])

    def test_bind_gagal_tidak_mencatat_audit(self):
        user = User.objects.create_user(username="kios-audit-3", password="x")
        self.client.force_authenticate(user)

        response = self.client.post(BIND_URL, {"device_profile": "GAIB"}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertFalse(AuditLog.objects.filter(action="device.bind").exists())
