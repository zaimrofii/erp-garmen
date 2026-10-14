"""Regression BUGFIX-403 — ``/api/v1/master/*`` **butuh sesi** + CORS credentials (H3.4).

Latar (bug nyata di dev, user ``zaimrofii`` superuser): halaman ``/inventory/*`` memuat
master (uoms/taxes/locations/partners/work-centers/production-lines) lewat **React Query** dan
selalu menerima **403**, padahal ``fetch()`` manual di console 200. Penyebabnya bukan backend
dan bukan role (semua view master hanya ``IsAuthenticated``): klien HTTP frontend mengirim
``credentials: 'include'`` HANYA untuk prefix yang terdaftar di allowlist, dan ``/master/``
(tambah ``/routing/``) belum terdaftar → browser lintas origin (5173 → 8000) TIDAK mengirim
cookie ``sessionid`` → DRF membalas 403.

Dua sisi kontrak yang dipin di sini:

  1. backend: GET master **anonim = 403**, **ber-sesi = 200** (tanpa cek role apa pun);
  2. CORS dev: respons 403 **sekalipun** sudah membawa
     ``Access-Control-Allow-Origin: <origin frontend>`` + ``Access-Control-Allow-Credentials:
     true`` (F1.5) — artinya begitu frontend mengirim cookie, browser TIDAK memblokir respons
     dan permintaan yang sama menjadi 200 (dua ``test_*_session_*`` di bawah).

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_master_cors_credentials.py -q
"""

from __future__ import annotations

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.auth.models import Role, User

ORIGIN = "http://localhost:5173"
MASTER_UOMS_URL = "/api/v1/master/uoms/"
MASTER_TAXES_URL = "/api/v1/master/taxes/"
ROUTING_GRAPH_URL = "/api/v1/routing/graph/"


@override_settings(
    CORS_ALLOWED_ORIGINS=[ORIGIN],
    CORS_ALLOW_CREDENTIALS=True,
    CORS_ALLOW_ALL_ORIGINS=False,
)
class MasterCorsCredentialsTests(TestCase):
    """403 anonim (bukan role) + CORS siap-credentials + 200 ber-sesi."""

    @classmethod
    def setUpTestData(cls):
        """Satu user ber-sesi; superuser tanpa role meniru user pelapor (``role_code=None``)."""
        cls.user = User.objects.create_user(
            username="master-403-user",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.ADMIN),
            is_staff=True,
        )

    def session_api(self) -> APIClient:
        """Klien dengan SESI (cookie) — meniru browser yang mengirim ``sessionid``."""
        api = APIClient()
        api.force_login(self.user)

        return api

    def test_anonim_get_master_403_data_autentikasi(self):
        """Tanpa cookie: 403 (``NotAuthenticated``) — inilah 403 yang dilaporkan di UI."""
        for url in (MASTER_UOMS_URL, MASTER_TAXES_URL, ROUTING_GRAPH_URL):
            with self.subTest(url=url):
                self.assertEqual(APIClient().get(url).status_code, 403)

    def test_anonim_403_tetap_membawa_header_cors_credentials(self):
        """Browser boleh membaca respons 403 lintas origin (ACAO echo + ACAC true)."""
        response = APIClient().get(MASTER_UOMS_URL, HTTP_ORIGIN=ORIGIN)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), ORIGIN)
        self.assertEqual(response.headers.get("Access-Control-Allow-Credentials"), "true")

    def test_ber_sesi_get_master_200(self):
        """Begitu cookie terkirim, endpoint yang sama → 200 (tanpa cek role)."""
        response = self.session_api().get(MASTER_UOMS_URL, HTTP_ORIGIN=ORIGIN)

        self.assertEqual(response.status_code, 200)
        self.assertIn("rows", response.json())
        self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), ORIGIN)
        self.assertEqual(response.headers.get("Access-Control-Allow-Credentials"), "true")

    def test_ber_sesi_get_master_tanpa_role_khusus(self):
        """User tanpa role pun boleh: master hanya ``IsAuthenticated`` (role bukan penyebab 403)."""
        plain = User.objects.create_user(  # noqa: S106 - kredensial test
            username="master-403-no-role",
            password="rahasia123",
        )
        api = APIClient()
        api.force_login(plain)

        self.assertIsNone(plain.role_id)
        self.assertEqual(api.get(MASTER_TAXES_URL).status_code, 200)
