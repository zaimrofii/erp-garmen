"""Test endpoint WhatsApp (Fase F) — `POST /api/v1/wa/send/`.

Gateway default adalah mock (tidak menyentuh jaringan), jadi test ini aman
dijalankan di CI: yang diperiksa bentuk response 200, validasi body 400, dan
bahwa gateway benar-benar dipanggil dengan `(to, message)`.
"""

from __future__ import annotations

from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from integrations.wa_bot.services import MockWAGateway, WAResponse

URL = "/api/v1/wa/send/"


class RecordingGateway(MockWAGateway):
    """Mock gateway + pencatat panggilan (memastikan argumen yang dikirim benar)."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, str]] = []

    def send_message(self, to: str, body: str) -> WAResponse:
        self.calls.append((to, body))
        return super().send_message(to, body)


class WASendTests(TestCase):
    """Kirim WA lewat gateway mock."""

    def setUp(self):
        self.client = APIClient()

    def test_sukses_200(self):
        response = self.client.post(
            URL,
            {"to": "628123456789", "message": "Bundle BND-0001 selesai"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["backend"], "mock")
        self.assertEqual(body["to"], "628123456789")
        self.assertEqual(body["chars"], len("Bundle BND-0001 selesai"))
        self.assertTrue(str(body["message_id"]).startswith("MOCK-"))

    def test_gateway_dipanggil_dengan_to_dan_message(self):
        gateway = RecordingGateway()

        with mock.patch("integrations.wa_bot.api.get_wa_gateway", return_value=gateway):
            response = self.client.post(URL, {"to": "628111", "message": "halo"}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(gateway.calls, [("628111", "halo")])

    def test_body_kosong_400(self):
        response = self.client.post(URL, {}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("wajib diisi", response.json()["detail"])

    def test_message_kosong_400_dan_gateway_tidak_dipanggil(self):
        with mock.patch("integrations.wa_bot.api.get_wa_gateway") as getter:
            response = self.client.post(URL, {"to": "628111", "message": "  "}, format="json")

        self.assertEqual(response.status_code, 400)
        getter.assert_not_called()

    def test_gateway_menolak_400(self):
        class FailingGateway(MockWAGateway):
            name = "vendor-x"

            def send_message(self, to: str, body: str) -> WAResponse:
                return WAResponse(ok=False, message_id=None, error="nomor tidak valid")

        with mock.patch("integrations.wa_bot.api.get_wa_gateway", return_value=FailingGateway()):
            response = self.client.post(URL, {"to": "x", "message": "halo"}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("nomor tidak valid", response.json()["detail"])

    def test_get_tidak_diizinkan(self):
        self.assertEqual(self.client.get(URL).status_code, 405)
