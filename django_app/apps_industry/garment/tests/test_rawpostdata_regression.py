"""Regresi: `ActionView` tidak boleh menyentuh `request.body`.

Sama seperti `integrations/erp_sync/tests/test_rawpostdata_regression.py`:
di server ASGI live `request.body` melempar `RawPostDataException` (500).
`request.body` di-patch agar MELEMPAR saat diakses; action endpoint harus
tetap merespons normal (bukan 500) dan `request.body` tidak pernah diakses.

Bundle id di URL sengaja TIDAK ada: `_request_hash` dijalankan SEBELUM resolver
instance, jadi bug lama tetap ke-trigger di sini, sedangkan kode baru lanjut ke
executor (→ 404), bukan 500.
"""

from __future__ import annotations

from unittest.mock import PropertyMock, patch

from django.http import HttpRequest, RawPostDataException
from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.tests.auth import authenticate

URL_ACTION = "/api/v1/garmen/bundles/999999/BUNDLE_START/"


class ActionViewRawPostDataRegressionTests(TestCase):
    """Pastikan `ActionView` tidak pernah membaca `request.body` (anti-500 ASGI)."""

    def setUp(self):
        self.api = APIClient()
        # FASE 4.1: ActionView kini `IsAuthenticated` (dulu AllowAny) → butuh auth.
        authenticate(self.api)

    def test_action_tidak_500_dan_body_tak_disentuh(self):
        with patch.object(
            HttpRequest,
            "body",
            new_callable=PropertyMock,
            side_effect=RawPostDataException("stream sudah dikonsumsi (simulasi ASGI)"),
        ) as body_prop:
            response = self.api.post(URL_ACTION, {}, format="json")

        self.assertNotEqual(response.status_code, 500)
        # bundle tidak ada → executor balas 404 (bukan crash).
        self.assertEqual(response.status_code, 404)
        body_prop.assert_not_called()
