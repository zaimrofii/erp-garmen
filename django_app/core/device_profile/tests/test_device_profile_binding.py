"""Test DeviceProfileResolver — level 3/4/5 + helper `bind_device`/cookie."""

from __future__ import annotations

from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from core.device_profile.models import DeviceBinding, DeviceProfile
from core.device_profile.services import (
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    DEVICE_COOKIE_NAME,
    FALLBACK_PROFILE_CODE,
    SOURCE_FALLBACK,
    SOURCE_METADATA_HINT,
    SOURCE_USER_PREFERENCE,
    DeviceProfileError,
    DeviceProfileResolver,
)


class DeviceProfileResolverLevelTests(TestCase):
    """Level 3 (user preference), level 4 (metadata hint), level 5 (fallback)."""

    @classmethod
    def setUpTestData(cls):
        # Profil bawaan dari migration `0002_seed_default_profiles`.
        cls.hp = DeviceProfile.objects.get(code="OPERATOR_HP")
        cls.kios = DeviceProfile.objects.get(code="KIOS")
        cls.scanner = DeviceProfile.objects.get(code="SCANNER_USB")

    def setUp(self):
        self.factory = RequestFactory()
        self.resolver = DeviceProfileResolver()

    def request_get(self, data=None, user=None, **meta):
        request = self.factory.get("/api/v1/devices/me", data or {}, **meta)
        request.user = user or AnonymousUser()
        return request

    # --------------------------------------------- level 3: user preference
    def test_user_preference_objek_profil(self):
        user = AnonymousUser()
        user.preferred_device_profile = self.scanner  # atribut opsional

        hasil = self.resolver.resolve(self.request_get(user=user))

        self.assertEqual(hasil.profile, "SCANNER_USB")
        self.assertEqual(hasil.source, SOURCE_USER_PREFERENCE)
        self.assertEqual(hasil.confidence, CONFIDENCE_MEDIUM)

    def test_user_preference_berupa_string_code(self):
        user = AnonymousUser()
        user.preferred_device_profile = "KIOS"

        hasil = self.resolver.resolve(self.request_get(user=user))

        self.assertEqual(hasil.profile, "KIOS")
        self.assertEqual(hasil.source, SOURCE_USER_PREFERENCE)

    def test_user_tanpa_atribut_preferensi_dilewati(self):
        hasil = self.resolver.resolve(self.request_get(user=AnonymousUser()))

        self.assertEqual(hasil.source, SOURCE_FALLBACK)

    # ----------------------------------------------- level 4: metadata hint
    def test_metadata_hint_dengan_wc_code(self):
        hasil = self.resolver.resolve(
            self.request_get(), {"device_hint": "SCANNER_USB", "wc_code": "WC-07"}
        )

        self.assertEqual(hasil.profile, "SCANNER_USB")
        self.assertEqual(hasil.source, SOURCE_METADATA_HINT)
        self.assertEqual(hasil.confidence, CONFIDENCE_MEDIUM)
        self.assertEqual(hasil.wc_code, "WC-07")

    def test_metadata_kosong_atau_hint_ngawur_dilewati(self):
        kosong = self.resolver.resolve(self.request_get(), {})
        self.assertEqual(kosong.source, SOURCE_FALLBACK)

        ngawur = self.resolver.resolve(self.request_get(), {"device_hint": "NGAWUR"})
        self.assertEqual(ngawur.source, SOURCE_FALLBACK)

    # ------------------------------------------------------- level 5: fallback
    def test_fallback_operator_hp(self):
        hasil = self.resolver.resolve(self.request_get())

        self.assertEqual(hasil.profile, FALLBACK_PROFILE_CODE)
        self.assertEqual(hasil.source, SOURCE_FALLBACK)
        self.assertEqual(hasil.confidence, CONFIDENCE_LOW)
        self.assertIsNone(hasil.wc_code)


class BindDeviceTests(TestCase):
    """Helper `bind_device` + `set_device_cookie` (tidak auto-set cookie)."""

    @classmethod
    def setUpTestData(cls):
        # Profil bawaan dari migration `0002_seed_default_profiles`.
        cls.kios = DeviceProfile.objects.get(code="KIOS")
        cls.scanner = DeviceProfile.objects.get(code="SCANNER_USB")

    def setUp(self):
        self.resolver = DeviceProfileResolver()

    def test_bind_device_bikin_lalu_update_binding(self):
        pertama = self.resolver.bind_device(None, "WC-01", "KIOS")
        token_awal = pertama.cookie_token
        self.assertIsNotNone(pertama.last_seen_at)

        kedua = self.resolver.bind_device(None, "WC-01", "KIOS")

        self.assertEqual(kedua.pk, pertama.pk)
        self.assertEqual(DeviceBinding.objects.count(), 1)
        self.assertNotEqual(kedua.cookie_token, token_awal)  # token dirotasi

    def test_bind_device_profil_tidak_dikenal_raise(self):
        with self.assertRaises(DeviceProfileError):
            self.resolver.bind_device(None, "WC-01", "PROFIL_GAIB")

    def test_bind_device_wc_berbeda_bikin_binding_baru(self):
        self.resolver.bind_device(None, "WC-01", "KIOS")
        self.resolver.bind_device(None, "WC-02", "KIOS")

        self.assertEqual(DeviceBinding.objects.count(), 2)

    def test_set_device_cookie_menulis_cookie_response(self):
        binding = self.resolver.bind_device(None, "WC-01", "SCANNER_USB")
        response = HttpResponse()

        DeviceProfileResolver.set_device_cookie(response, binding)

        cookie = response.cookies[DEVICE_COOKIE_NAME]
        self.assertEqual(cookie.value, binding.cookie_token)
        self.assertTrue(cookie["httponly"])
