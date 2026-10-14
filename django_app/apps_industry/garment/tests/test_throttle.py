"""Test rate limiter DRF (Fase 6): 429 saat kuota habis + pengecualian health.

Rate dipatok kecil lewat ``patch.object(..., "THROTTLE_RATES", ...)`` supaya test
tidak perlu mengirim 60 request; implementasi throttle tetap milik DRF.
"""

from __future__ import annotations

from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle

LIST_URL = "/api/v1/garmen/bundles/?limit=1"
HEALTH_URL = "/api/health/"
#: Rate sangat kecil untuk uji (dipakai kedua scope supaya tidak KeyError).
TINY_RATES = {"anon": "2/min", "user": "2/min"}
HEALTH_RATES = {"anon": "1/min", "user": "1/min"}


class ThrottleTests(TestCase):
    """Kuota request per IP (anon) ditegakkan dan health dikecualikan."""

    def setUp(self):
        # Cache throttle dibersihkan supaya hitungan tidak menyeberang ke test lain.
        cache.clear()
        self.api = APIClient()

    def get_many(self, url: str, count: int, rates: dict) -> list[int]:
        with patch.object(AnonRateThrottle, "THROTTLE_RATES", rates), patch.object(
            UserRateThrottle, "THROTTLE_RATES", rates
        ):
            return [self.api.get(url).status_code for _ in range(count)]

    def test_di_bawah_kuota_masih_200(self):
        self.assertEqual(self.get_many(LIST_URL, 2, TINY_RATES), [200, 200])

    def test_kuota_habis_dibalas_429(self):
        codes = self.get_many(LIST_URL, 3, TINY_RATES)

        self.assertEqual(codes[:2], [200, 200])
        self.assertEqual(codes[2], 429)

    def test_response_429_tetap_json_rapi(self):
        with patch.object(AnonRateThrottle, "THROTTLE_RATES", TINY_RATES), patch.object(
            UserRateThrottle, "THROTTLE_RATES", TINY_RATES
        ):
            for _ in range(3):
                response = self.api.get(LIST_URL)

        self.assertEqual(response.status_code, 429)
        body = response.json()
        # Pesan detail berasal dari DRF (dapat terlokalisasi, jadi tidak di-hardcode)
        # + request_id dari custom exception handler (Fase 6).
        self.assertIn("detail", body)
        self.assertTrue(body["detail"])
        self.assertIn("request_id", body)

    def test_health_dikecualikan_dari_throttle(self):
        self.assertEqual(self.get_many(HEALTH_URL, 4, HEALTH_RATES), [200, 200, 200, 200])

    def test_kelas_throttle_default_dari_settings(self):
        self.assertEqual(
            settings.REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"],
            [
                "rest_framework.throttling.AnonRateThrottle",
                "rest_framework.throttling.UserRateThrottle",
            ],
        )
