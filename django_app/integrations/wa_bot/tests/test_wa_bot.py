"""Test WhatsApp gateway mock (Fase 5) — tanpa jaringan & tanpa nomor WA nyata."""

from __future__ import annotations

from datetime import datetime

from django.test import TestCase, override_settings

from integrations.wa_bot.services import (
    MockWAGateway,
    WAGateway,
    WAMessage,
    WAResponse,
    get_wa_gateway,
)

WA_LOGGER = "integrations.wa_bot.services"


class MockWAGatewayTests(TestCase):
    """Kirim, parse pesan masuk, health check."""

    def setUp(self):
        self.gateway = MockWAGateway()

    def test_send_message_sukses(self):
        response = self.gateway.send_message("+628123", "halo")

        self.assertIsInstance(response, WAResponse)
        self.assertTrue(response.ok)
        self.assertTrue(str(response.message_id).startswith("MOCK-"))
        self.assertIsNone(response.error)
        self.assertEqual(response.raw["to"], "+628123")

    def test_message_id_unik_per_pesan(self):
        ids = {
            self.gateway.send_message("+628123", f"pesan {index}").message_id
            for index in range(5)
        }

        self.assertEqual(len(ids), 5)

    def test_pesan_tersimpan_di_memori(self):
        self.gateway.send_message("+6281", "satu")
        self.gateway.send_message("+6282", "dua")

        self.assertEqual([item["body"] for item in self.gateway.sent], ["satu", "dua"])

    def test_nomor_atau_body_kosong_ditolak(self):
        self.assertFalse(self.gateway.send_message("", "halo").ok)
        self.assertFalse(self.gateway.send_message("+628123", "   ").ok)
        self.assertEqual(self.gateway.sent, [])

    def test_parse_incoming(self):
        message = self.gateway.parse_incoming(
            {"from": "+628999", "text": "OK", "timestamp": "2026-09-23T10:00:00+07:00"}
        )

        self.assertIsInstance(message, WAMessage)
        self.assertEqual(message.sender, "+628999")
        self.assertEqual(message.body, "OK")
        self.assertEqual(message.timestamp, datetime.fromisoformat("2026-09-23T10:00:00+07:00"))
        self.assertEqual(message.raw["text"], "OK")

    def test_parse_incoming_timestamp_datetime(self):
        now = datetime(2026, 9, 23, 10, 0)

        self.assertEqual(self.gateway.parse_incoming({"timestamp": now}).timestamp, now)

    def test_parse_incoming_timestamp_aneh_tidak_error(self):
        self.assertIsNone(self.gateway.parse_incoming({"timestamp": "bukan-waktu"}).timestamp)
        self.assertIsNone(self.gateway.parse_incoming({}).timestamp)

    def test_parse_incoming_payload_kosong(self):
        message = self.gateway.parse_incoming({})

        self.assertEqual((message.sender, message.body), ("", ""))
        self.assertEqual(message.raw, {})

    def test_health_check_true(self):
        self.assertTrue(self.gateway.health_check())

    def test_implement_kontrak_gateway(self):
        self.assertIsInstance(self.gateway, WAGateway)
        self.assertEqual(self.gateway.name, "mock")


class GetWAGatewayTests(TestCase):
    """Factory memilih implementasi dari settings.WA_BACKEND."""

    def test_default_mock(self):
        with override_settings(WA_BACKEND="mock"):
            self.assertIsInstance(get_wa_gateway(), MockWAGateway)

    def test_backend_kosong_fallback_mock(self):
        with override_settings(WA_BACKEND=""):
            self.assertIsInstance(get_wa_gateway(), MockWAGateway)

    def test_backend_belum_diimplementasikan_fallback_mock(self):
        with override_settings(WA_BACKEND="cloud-api"), self.assertLogs(
            WA_LOGGER, level="WARNING"
        ) as logs:
            gateway = get_wa_gateway()

        self.assertIsInstance(gateway, MockWAGateway)
        self.assertIn("belum diimplementasikan", logs.output[0])

    def test_parameter_menimpa_settings(self):
        with override_settings(WA_BACKEND="cloud-api"):
            self.assertIsInstance(get_wa_gateway("mock"), MockWAGateway)

    def test_mock_gateway_bisa_dipakai_untuk_alur_notifikasi(self):
        gateway = get_wa_gateway()

        response = gateway.send_message("+628111", "Bottleneck di WC SEWING-1")

        self.assertTrue(response.ok)
        self.assertEqual(len(gateway.sent), 1)


class WAResponseTests(TestCase):
    """Representasi response (dipakai log/API)."""

    def test_as_dict_json_safe(self):
        data = WAResponse(ok=True, message_id="MOCK-1", raw={"to": "+62"}).as_dict()

        self.assertEqual(
            set(data), {"ok", "message_id", "error", "raw"}
        )
        self.assertTrue(data["ok"])
        self.assertEqual(data["message_id"], "MOCK-1")
        self.assertIsNone(data["error"])
