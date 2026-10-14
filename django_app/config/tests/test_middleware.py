"""Test ``RequestIDMiddleware`` + filter request id (Fase 6)."""

from __future__ import annotations

import uuid

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase
from rest_framework.test import APIClient

from config.middleware import (
    REQUEST_ID_HEADER,
    RequestIDMiddleware,
    get_request_id,
    sanitize_request_id,
)

HEALTH_URL = "/api/health/"


class SanitizeRequestIdTests(SimpleTestCase):
    """Header dari klien harus dibersihkan sebelum dipakai/di-log."""

    def test_kosong_menjadi_none(self):
        for value in (None, "", "   "):
            self.assertIsNone(sanitize_request_id(value))

    def test_karakter_kontrol_dibuang(self):
        self.assertEqual(sanitize_request_id("rid\n123\t"), "rid123")

    def test_panjang_dibatasi(self):
        self.assertEqual(len(sanitize_request_id("x" * 500)), 255)

    def test_nilai_normal_dipertahankan(self):
        self.assertEqual(sanitize_request_id("  abc-1  "), "abc-1")


class RequestIDMiddlewareUnitTests(SimpleTestCase):
    """Perilaku middleware tanpa lewat URL."""

    def test_request_id_ditempel_di_request_dan_response(self):
        seen = {}

        def get_response(request):
            seen["request_id"] = request.request_id
            return HttpResponse("ok")

        response = RequestIDMiddleware(get_response)(RequestFactory().get("/apa-saja/"))

        self.assertTrue(seen["request_id"])
        self.assertEqual(response[REQUEST_ID_HEADER], seen["request_id"])

    def test_header_klien_dipakai_dan_masuk_context_log(self):
        captured = {}

        def get_response(request):
            captured["context"] = get_request_id()
            return HttpResponse("ok")

        middleware = RequestIDMiddleware(get_response)
        request = RequestFactory().get("/x/", HTTP_X_REQUEST_ID="rid-ctx")

        response = middleware(request)

        self.assertEqual(captured["context"], "rid-ctx")
        self.assertEqual(response[REQUEST_ID_HEADER], "rid-ctx")

    def test_context_dibersihkan_setelah_response(self):
        middleware = RequestIDMiddleware(lambda request: HttpResponse("ok"))

        middleware(RequestFactory().get("/x/", HTTP_X_REQUEST_ID="rid-ctx"))

        self.assertIsNone(get_request_id())


class RequestIDHeaderTests(TestCase):
    """Verifikasi lewat HTTP (DRF API client) — header muncul di response."""

    def setUp(self):
        self.api = APIClient()

    def test_header_dibuat_otomatis_kalau_tidak_ada(self):
        response = self.api.get(HEALTH_URL)

        self.assertEqual(response.status_code, 200)
        request_id = response[REQUEST_ID_HEADER]
        self.assertEqual(str(uuid.UUID(request_id)), request_id)  # UUID4 valid

    def test_header_dari_klien_dipertahankan(self):
        response = self.api.get(HEALTH_URL, HTTP_X_REQUEST_ID="rid-dari-klien")

        self.assertEqual(response[REQUEST_ID_HEADER], "rid-dari-klien")

    def test_header_klien_dibersihkan(self):
        response = self.api.get(HEALTH_URL, HTTP_X_REQUEST_ID="rid\tkotor")

        self.assertNotIn("\t", response[REQUEST_ID_HEADER])

    def test_request_id_berbeda_tiap_request(self):
        pertama = self.api.get(HEALTH_URL)[REQUEST_ID_HEADER]
        kedua = self.api.get(HEALTH_URL)[REQUEST_ID_HEADER]

        self.assertNotEqual(pertama, kedua)
