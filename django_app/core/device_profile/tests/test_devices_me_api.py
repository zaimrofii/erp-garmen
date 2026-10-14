"""Test endpoint core `GET /api/v1/devices/me` (kontrak §5.1) via DRF APIClient."""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from core.device_profile.models import DeviceBinding, DeviceProfile
from core.device_profile.services import DEVICE_COOKIE_NAME

URL = "/api/v1/devices/me"


class DeviceMeApiTests(TestCase):
    """Bentuk response harus persis: 4 key kontrak, status 200."""

    @classmethod
    def setUpTestData(cls):
        # Profil bawaan dari migration `0002_seed_default_profiles`.
        cls.hp = DeviceProfile.objects.get(code="OPERATOR_HP")
        cls.kios = DeviceProfile.objects.get(code="KIOS")

    def setUp(self):
        self.client = APIClient()

    def test_fallback_operator_hp_tanpa_param(self):
        response = self.client.get(URL)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "device_profile": "OPERATOR_HP",
                "confidence": "low",
                "source": "fallback",
                "wc_code": None,
            },
        )
        self.assertEqual(
            set(response.json()),
            {"device_profile", "confidence", "source", "wc_code"},
        )

    def test_url_override_lewat_query_param(self):
        response = self.client.get(URL, {"device": "KIOS"})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["device_profile"], "KIOS")
        self.assertEqual(body["confidence"], "high")
        self.assertEqual(body["source"], "url_override")

    def test_url_override_lewat_header(self):
        response = self.client.get(URL, HTTP_X_DEVICE_PROFILE="KIOS")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["device_profile"], "KIOS")
        self.assertEqual(response.json()["source"], "url_override")

    def test_cookie_binding(self):
        binding = DeviceBinding.objects.create(
            wc_code="WC-01", device_profile=self.kios, cookie_token="token-api-01"
        )
        self.client.cookies[DEVICE_COOKIE_NAME] = binding.cookie_token

        response = self.client.get(URL)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["device_profile"], "KIOS")
        self.assertEqual(body["source"], "device_binding")
        self.assertEqual(body["confidence"], "high")
        self.assertEqual(body["wc_code"], "WC-01")

    def test_cookie_tidak_dikenal_fallback(self):
        self.client.cookies[DEVICE_COOKIE_NAME] = "token-palsu"

        response = self.client.get(URL)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["source"], "fallback")

    def test_param_resource_hint_dan_wc(self):
        response = self.client.get(
            URL, {"resource": "bundle", "hint": "KIOS", "wc": "WC-09"}
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["device_profile"], "KIOS")
        self.assertEqual(body["source"], "metadata_hint")
        self.assertEqual(body["wc_code"], "WC-09")

    def test_override_menang_atas_cookie(self):
        DeviceBinding.objects.create(
            wc_code="WC-01", device_profile=self.hp, cookie_token="token-api-02"
        )
        self.client.cookies[DEVICE_COOKIE_NAME] = "token-api-02"

        response = self.client.get(URL, {"device": "KIOS"})

        body = response.json()
        self.assertEqual(body["device_profile"], "KIOS")
        self.assertEqual(body["source"], "url_override")
