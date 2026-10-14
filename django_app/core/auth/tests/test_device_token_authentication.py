"""Test `DeviceTokenAuthentication` (Fase G) — auth cookie binding, fail-safe.

Yang dijaga:
  * tanpa cookie / cookie tak dikenal → `None` (request tetap anonim, tanpa error);
  * binding valid yang punya user → autentikasi sebagai user itu (dasar rate limit
    user 300/min alih-alih anon 60/min);
  * binding valid tanpa user → tetap anonim tetapi binding terlampir di request;
  * header `X-Device-Id` dicatat untuk diagnosa, **tidak** dipakai autentikasi.
"""

from __future__ import annotations

from django.test import RequestFactory, TestCase

from core.auth.authentication import DEVICE_ID_HEADER, DeviceTokenAuthentication
from core.auth.models import User
from core.device_profile.models import DeviceBinding, DeviceProfile
from core.device_profile.services import DEVICE_COOKIE_NAME


class DeviceTokenAuthenticationTests(TestCase):
    """Auth dari cookie `device_token` (tanpa view — unit murni authenticator)."""

    @classmethod
    def setUpTestData(cls):
        # Profil bawaan migration `0002`/`0003`.
        cls.kios = DeviceProfile.objects.get(code="KIOS")
        cls.hp = DeviceProfile.objects.get(code="OPERATOR_HP")
        cls.user = User.objects.create_user(username="operator-g", password="rahasia-g")

    def setUp(self):
        self.factory = RequestFactory()
        self.auth = DeviceTokenAuthentication()

    def request_with(self, token: str | None = None, device_id: str | None = None):
        """Request GET dengan cookie/header opsional.

        Cookie dikirim lewat header `Cookie` (bukan kwarg `cookies` RequestFactory)
        supaya benar-benar diparsing Django menjadi `request.COOKIES` — sama seperti
        request nyata dari browser.
        """
        headers = {}
        if token:
            headers["Cookie"] = f"{DEVICE_COOKIE_NAME}={token}"
        if device_id:
            headers[DEVICE_ID_HEADER] = device_id

        return self.factory.get("/api/v1/devices/me", headers=headers)

    # -------------------------------------------------------------- tanpa kredensial
    def test_tanpa_cookie_kembali_none(self):
        request = self.request_with()

        self.assertIsNone(self.auth.authenticate(request))
        self.assertFalse(hasattr(request, "device_binding"))

    def test_cookie_tidak_dikenal_kembali_none(self):
        request = self.request_with(token="token-palsu")

        self.assertIsNone(self.auth.authenticate(request))
        self.assertFalse(hasattr(request, "device_binding"))

    def test_profil_nonaktif_dilewati(self):
        self.kios.is_active = False
        self.kios.save(update_fields=["is_active"])
        DeviceBinding.objects.create(
            wc_code="WC-00", device_profile=self.kios, cookie_token="token-nonaktif"
        )

        self.assertIsNone(self.auth.authenticate(self.request_with(token="token-nonaktif")))

    # ----------------------------------------------------------- binding tanpa user
    def test_binding_tanpa_user_tetap_anonim_tapi_binding_terlampir(self):
        binding = DeviceBinding.objects.create(
            wc_code="WC-01", device_profile=self.kios, cookie_token="token-anon"
        )

        request = self.request_with(token="token-anon")
        self.assertIsNone(self.auth.authenticate(request))

        self.assertEqual(request.device_binding.pk, binding.pk)
        self.assertEqual(request.device_binding.device_profile.code, "KIOS")

    def test_last_seen_at_di_touch(self):
        binding = DeviceBinding.objects.create(
            wc_code="WC-02", device_profile=self.kios, cookie_token="token-touch"
        )
        self.assertIsNone(binding.last_seen_at)

        self.auth.authenticate(self.request_with(token="token-touch"))

        binding.refresh_from_db()
        self.assertIsNotNone(binding.last_seen_at)

    # ------------------------------------------------------------- binding ber-user
    def test_binding_dengan_user_mengautentikasi_sebagai_user_itu(self):
        binding = DeviceBinding.objects.create(
            wc_code="WC-03",
            device_profile=self.hp,
            cookie_token="token-user",
            user=self.user,
        )

        result = self.auth.authenticate(self.request_with(token="token-user"))

        self.assertIsNotNone(result)
        user, auth = result
        self.assertEqual(user.pk, self.user.pk)
        self.assertTrue(user.is_authenticated)
        self.assertEqual(auth.pk, binding.pk)

    def test_user_nonaktif_tidak_diautentikasi(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        DeviceBinding.objects.create(
            wc_code="WC-04",
            device_profile=self.hp,
            cookie_token="token-user-off",
            user=self.user,
        )

        request = self.request_with(token="token-user-off")

        self.assertIsNone(self.auth.authenticate(request))
        self.assertTrue(hasattr(request, "device_binding"))

    # ----------------------------------------------------------------- header opsional
    def test_header_device_id_dicatat_tapi_tidak_mengautentikasi(self):
        request = self.request_with(device_id="device-id-abc")

        self.assertIsNone(self.auth.authenticate(request))
        self.assertEqual(request.device_id_header, "device-id-abc")

    def test_header_device_id_saja_tanpa_cookie_tetap_anonim(self):
        request = self.request_with(device_id="device-id-only")

        self.assertIsNone(self.auth.authenticate(request))
        self.assertFalse(hasattr(request, "device_binding"))

    def test_authenticate_header_kosong_supaya_401_bukan_403(self):
        self.assertEqual(self.auth.authenticate_header(self.request_with()), "")
