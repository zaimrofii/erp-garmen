"""Test pembagian rate limit anon vs user (Fase G.2).

Kenapa ada: kuota anon (60/min) vs user (300/min) hanya benar-benar berbeda kalau
autentikasi mengisi `request.user` — dan itu baru terbukti kalau diuji. Test ini
memakai kuota kecil (3/min & 5/min) supaya perilakunya terlihat cepat, lalu
membuktikan:

  1. anonim → **429** setelah kuota anon habis;
  2. user (session/force_authenticate) → punya kuota **sendiri** (tidak terpengaruh
     kuota anon yang sudah habis);
  3. cookie device binding **ber-user** → ikut dihitung sebagai user, artinya
     `DeviceTokenAuthentication` benar-benar dipakai DRF (bukan hanya lolos unit).

Catatan teknis (temuan Fase G): `override_settings(REST_FRAMEWORK=...)` **tidak**
mengubah rate throttle, karena `SimpleRateThrottle.THROTTLE_RATES` mengikat dict
`api_settings.DEFAULT_THROTTLE_RATES` **saat modul di-import** (dict baru hasil
reload tidak menggantikan ikatan itu). Karena itu test ini mem-patch atribut
`rate` kelas throttle langsung; rate produksi tetap diatur di `settings.py`
(anon 60/min, user 300/min).
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest import mock

from django.core.cache import cache
from django.conf import settings
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle

from core.auth.models import User
from core.device_profile.models import DeviceBinding, DeviceProfile
from core.device_profile.services import DEVICE_COOKIE_NAME

#: Endpoint AllowAny + throttled oleh DEFAULT_THROTTLE_CLASSES.
URL = "/api/v1/devices/me"


@contextmanager
def small_rates(anon: str = "3/min", user: str = "5/min"):
    """Kecilkan kuota throttle untuk durasi test (lihat catatan modul).

    `create=True`: DRF menyetel `rate` sebagai atribut **instance**
    (`SimpleRateThrottle.__init__`), jadi kelasnya belum punya atribut itu —
    patch tetap perlu membuat atribut kelas agar instance membacanya.
    """
    with mock.patch.object(AnonRateThrottle, "rate", anon, create=True):
        with mock.patch.object(UserRateThrottle, "rate", user, create=True):
            yield


class ThrottleSplitTests(TestCase):
    """Kuota anon dan user terpisah."""

    def setUp(self):
        cache.clear()  # LocMem di mode test → bersihkan riwayat throttle antar test
        self.addCleanup(cache.clear)
        self.client = APIClient()
        self.user = User.objects.create_user(username="operator-rl", password="rahasia-rl")

    def hit(self, times: int) -> list[int]:
        """Panggil endpoint `times` kali; kembalikan daftar status."""
        return [self.client.get(URL).status_code for _ in range(times)]

    def test_scope_throttle_anon_dan_user_terpisah(self):
        """Scope berbeda = anggaran berbeda; angka PRODUKSI dibuktikan di load test.

        Di mode test kuota dinaikkan (100000/min) supaya ratusan test lama tidak
        kena 429 palsu — nilai produksi (anon 60/min, user 300/min) ada di
        `config/settings.py` dan diverifikasi lewat `scripts/load_test.py`.
        """
        self.assertEqual(AnonRateThrottle.scope, "anon")
        self.assertEqual(UserRateThrottle.scope, "user")

        rates = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
        self.assertIn("anon", rates)
        self.assertIn("user", rates)
        self.assertEqual(AnonRateThrottle().num_requests, 100000)  # mode test
        self.assertEqual(UserRateThrottle().num_requests, 100000)

    def test_anon_kena_429_setelah_kuota_anon(self):
        with small_rates():
            statuses = self.hit(4)

        self.assertEqual(statuses[:3], [200, 200, 200])
        self.assertEqual(statuses[3], 429)

    def test_user_punya_kuota_sendiri_walau_kuota_anon_habis(self):
        with small_rates():
            anon = self.hit(4)  # kuota anon (3) habis
            self.client.force_authenticate(user=self.user)
            user = self.hit(6)  # kuota user (5) masih utuh

        self.assertEqual(anon[3], 429)
        self.assertEqual(user[:5], [200] * 5)
        self.assertEqual(user[5], 429)

    def test_cookie_device_binding_ber_user_dihitung_sebagai_user(self):
        """Device binding ber-user → UserRateThrottle, bukan AnonRateThrottle."""
        profil = DeviceProfile.objects.get(code="KIOS")
        DeviceBinding.objects.create(
            wc_code="WC-RL",
            device_profile=profil,
            cookie_token="token-rate-limit",
            user=self.user,
        )

        with small_rates(anon="1/min", user="3/min"):
            self.assertEqual(self.client.get(URL).status_code, 200)  # kuota anon terpakai
            self.assertEqual(self.client.get(URL).status_code, 429)  # kuota anon habis

            perangkat = APIClient()
            perangkat.cookies[DEVICE_COOKIE_NAME] = "token-rate-limit"
            statuses = [perangkat.get(URL).status_code for _ in range(3)]

        self.assertEqual(statuses, [200, 200, 200])

    def test_kuota_user_habis_tetap_membalas_429(self):
        with small_rates(anon="50/min", user="2/min"):
            self.client.force_authenticate(user=self.user)
            statuses = self.hit(3)

        self.assertEqual(statuses, [200, 200, 429])
