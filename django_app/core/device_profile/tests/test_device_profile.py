"""Test DeviceProfileResolver — level 1 (URL override) & level 2 (binding cookie)."""

from __future__ import annotations

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase

from core.device_profile.models import DeviceBinding, DeviceProfile
from core.device_profile.services import (
    CONFIDENCE_HIGH,
    DEVICE_COOKIE_NAME,
    FALLBACK_PROFILE_CODE,
    SOURCE_DEVICE_BINDING,
    SOURCE_FALLBACK,
    SOURCE_URL_OVERRIDE,
    DeviceProfileResolver,
)


class DeviceProfileResolverTestCase(TestCase):
    """Base: data profil + helper request/binding."""

    @classmethod
    def setUpTestData(cls):
        # Tiga profil bawaan sudah dibuat migration
        # `0002_seed_default_profiles` -> diambil, bukan dibuat ulang.
        cls.hp = DeviceProfile.objects.get(code="OPERATOR_HP")
        cls.kios = DeviceProfile.objects.get(code="KIOS")
        cls.scanner = DeviceProfile.objects.get(code="SCANNER_USB")
        cls.nonaktif = DeviceProfile.objects.create(
            code="TABLET_LAWAS", name="Tablet Lama", is_active=False
        )

    def setUp(self):
        self.factory = RequestFactory()
        self.resolver = DeviceProfileResolver()

    def request_get(self, data=None, cookies=None, user=None, **meta):
        """RequestFactory + `user` default AnonymousUser (seperti DRF anonim)."""
        request = self.factory.get("/api/v1/devices/me", data or {}, **meta)
        request.user = user or AnonymousUser()
        if cookies:
            request.COOKIES.update(cookies)
        return request

    def make_binding(self, profile, wc_code="WC-01", token="token-wc01"):
        return DeviceBinding.objects.create(
            wc_code=wc_code, device_profile=profile, cookie_token=token
        )


class UrlOverrideTests(DeviceProfileResolverTestCase):
    """Level 1: `?device=` / header X-Device-Profile -> confidence high."""

    def test_url_override(self):
        hasil = self.resolver.resolve(self.request_get(data={"device": "KIOS"}))

        self.assertEqual(hasil.profile, "KIOS")
        self.assertEqual(hasil.source, SOURCE_URL_OVERRIDE)
        self.assertEqual(hasil.confidence, CONFIDENCE_HIGH)
        self.assertIsNone(hasil.wc_code)

    def test_header_override(self):
        hasil = self.resolver.resolve(
            self.request_get(HTTP_X_DEVICE_PROFILE="SCANNER_USB")
        )

        self.assertEqual(hasil.profile, "SCANNER_USB")
        self.assertEqual(hasil.source, SOURCE_URL_OVERRIDE)

    def test_kode_tidak_dikenal_dilewati(self):
        hasil = self.resolver.resolve(self.request_get(data={"device": "TIDAK_ADA"}))

        self.assertEqual(hasil.source, SOURCE_FALLBACK)
        self.assertEqual(hasil.profile, FALLBACK_PROFILE_CODE)

    def test_override_menang_atas_cookie_binding(self):
        self.make_binding(self.kios)

        hasil = self.resolver.resolve(
            self.request_get(
                data={"device": "SCANNER_USB"},
                cookies={DEVICE_COOKIE_NAME: "token-wc01"},
            )
        )

        self.assertEqual(hasil.profile, "SCANNER_USB")
        self.assertEqual(hasil.source, SOURCE_URL_OVERRIDE)


class DeviceBindingTests(DeviceProfileResolverTestCase):
    """Level 2: cookie `device_token` -> confidence high + wc_code dari binding."""

    def test_cookie_binding(self):
        self.make_binding(self.kios)

        hasil = self.resolver.resolve(
            self.request_get(cookies={DEVICE_COOKIE_NAME: "token-wc01"})
        )

        self.assertEqual(hasil.profile, "KIOS")
        self.assertEqual(hasil.source, SOURCE_DEVICE_BINDING)
        self.assertEqual(hasil.confidence, CONFIDENCE_HIGH)
        self.assertEqual(hasil.wc_code, "WC-01")

    def test_cookie_binding_update_last_seen_at(self):
        binding = self.make_binding(self.scanner)

        self.resolver.resolve(
            self.request_get(cookies={DEVICE_COOKIE_NAME: "token-wc01"})
        )

        binding.refresh_from_db()
        self.assertIsNotNone(binding.last_seen_at)

    def test_cookie_invalid_dilewati(self):
        hasil = self.resolver.resolve(
            self.request_get(cookies={DEVICE_COOKIE_NAME: "token-palsu"})
        )

        self.assertEqual(hasil.source, SOURCE_FALLBACK)

    def test_profil_nonaktif_dilewati(self):
        self.make_binding(self.nonaktif, token="token-lawas")

        hasil = self.resolver.resolve(
            self.request_get(cookies={DEVICE_COOKIE_NAME: "token-lawas"})
        )

        self.assertEqual(hasil.source, SOURCE_FALLBACK)

    def test_mismatch_wc_tetap_return_bukan_menolak(self):
        # Binding WC-99, metadata resource WC-01 -> tetap kembalikan binding.
        self.make_binding(self.kios, wc_code="WC-99", token="token-wc99")

        hasil = self.resolver.resolve(
            self.request_get(cookies={DEVICE_COOKIE_NAME: "token-wc99"}),
            {"wc_code": "WC-01"},
        )

        self.assertEqual(hasil.profile, "KIOS")
        self.assertEqual(hasil.wc_code, "WC-99")
