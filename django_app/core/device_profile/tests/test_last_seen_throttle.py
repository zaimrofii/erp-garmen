"""Test pembatasan update `last_seen_at` (Fase H hardening).

Temuan load test 100 RPS Fase H: menulis `last_seen_at` di setiap request
authenticated membuat koneksi Postgres habis ("too many clients"). Solusinya:
refresh `last_seen_at` maksimal sekali per `LAST_SEEN_REFRESH_SECONDS` (60 detik),
sehingga mayoritas request authenticated hanya membaca.
"""

from __future__ import annotations

from datetime import timedelta

from django.test import RequestFactory, TestCase
from django.utils import timezone

from core.device_profile.models import DeviceBinding, DeviceProfile
from core.device_profile.services import LAST_SEEN_REFRESH_SECONDS, DeviceProfileResolver
from core.device_profile.services import DEVICE_COOKIE_NAME

TOKEN = "token-last-seen"


class LastSeenThrottleTests(TestCase):
    """`resolve()` hanya menulis `last_seen_at` kalau sudah basi."""

    @classmethod
    def setUpTestData(cls):
        cls.profil = DeviceProfile.objects.get(code="KIOS")

    def setUp(self):
        self.factory = RequestFactory()
        self.resolver = DeviceProfileResolver()

    def request(self):
        return self.factory.get(
            "/api/v1/devices/me", headers={"Cookie": f"{DEVICE_COOKIE_NAME}={TOKEN}"}
        )

    def make_binding(self, last_seen):
        return DeviceBinding.objects.create(
            wc_code="WC-LS",
            device_profile=self.profil,
            cookie_token=TOKEN,
            last_seen_at=last_seen,
        )

    def test_last_seen_kosong_diisi(self):
        binding = self.make_binding(None)

        self.resolver.resolve(self.request())

        binding.refresh_from_db()
        self.assertIsNotNone(binding.last_seen_at)

    def test_last_seen_masih_baru_tidak_ditulis_ulang(self):
        baru = timezone.now() - timedelta(seconds=LAST_SEEN_REFRESH_SECONDS / 2)
        binding = self.make_binding(baru)

        self.resolver.resolve(self.request())

        binding.refresh_from_db()
        self.assertEqual(binding.last_seen_at, baru)

    def test_last_seen_basi_diperbarui(self):
        basi = timezone.now() - timedelta(seconds=LAST_SEEN_REFRESH_SECONDS * 2)
        binding = self.make_binding(basi)

        self.resolver.resolve(self.request())

        binding.refresh_from_db()
        self.assertGreater(binding.last_seen_at, basi)

    def test_binding_tanpa_cookie_tidak_menyentuh_apa_pun(self):
        binding = self.make_binding(None)

        hasil = self.resolver.resolve(self.factory.get("/api/v1/devices/me"))

        binding.refresh_from_db()
        self.assertIsNone(hasil.wc_code)  # fallback (tanpa cookie)
        self.assertIsNone(binding.last_seen_at)
