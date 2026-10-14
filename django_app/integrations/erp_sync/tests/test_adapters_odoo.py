"""Test OdooAdapter (kontrak & fail-safe) + health probe transport JSON-RPC.

Fase 4.2: implementasi penuh ``push_*`` diuji di ``test_odoo_adapter.py``; di
sini diuji kontrak dasar + perilaku kalau kredensial Odoo belum lengkap.
Tidak ada panggilan jaringan: client adapter di-mock / kredensial dikosongkan,
dan transport JSON-RPC diuji dengan ``httpx.MockTransport``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
from django.test import SimpleTestCase, override_settings

from integrations.erp_sync.adapters.base import ERPAdapter, ERPResponse
from integrations.erp_sync.adapters.odoo import OdooAdapter, OdooJSONRPCAdapter

CREDS = {
    "url": "http://odoo.test:8069",
    "db": "garmen-test",
    "user": "sync@example.com",
    "api_key": "kunci-rahasia",
}


def make_transport(handler) -> OdooJSONRPCAdapter:
    """Transport JSON-RPC dengan HTTP client palsu (tanpa jaringan)."""
    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    return OdooJSONRPCAdapter(**CREDS, client=http_client)


class OdooAdapterKontrakTests(SimpleTestCase):
    """OdooAdapter (Fase 4.2): kontrak penuh + fail-safe tanpa kredensial."""

    NOCREDS = {
        "ODOO_URL": "",
        "ODOO_DB": "",
        "ODOO_USER": "",
        "ODOO_API_KEY": "",
    }

    def test_default_tanpa_kredensial_client_none(self):
        with override_settings(**self.NOCREDS):
            adapter = OdooAdapter()

        self.assertIsInstance(adapter, ERPAdapter)
        self.assertIsNone(adapter.client)
        self.assertEqual(adapter.name, "odoo")

    def test_client_bisa_di_inject(self):
        client = MagicMock()

        self.assertIs(OdooAdapter(client=client).client, client)

    def test_push_wip_issue_bukan_lagi_skeleton(self):
        """Sejak Fase 4.2 push_* mengembalikan ERPResponse (detail: test_odoo_adapter.py)."""
        with override_settings(**self.NOCREDS):
            response = OdooAdapter().push_wip_issue({"qty": 1})

        self.assertIsInstance(response, ERPResponse)
        self.assertFalse(response.ok)

    def test_push_fg_receipt_bukan_lagi_skeleton(self):
        with override_settings(**self.NOCREDS):
            response = OdooAdapter().push_fg_receipt({"qty": 1})

        self.assertIsInstance(response, ERPResponse)
        self.assertFalse(response.ok)

    def test_health_check_false_tanpa_kredensial(self):
        with override_settings(**self.NOCREDS):
            self.assertFalse(OdooAdapter().health_check())

    def test_health_check_true_dengan_mock_client(self):
        client = MagicMock()
        client.ping.return_value = True

        self.assertTrue(OdooAdapter(client=client).health_check())
        client.ping.assert_called_once_with()

    def test_health_check_false_kalau_ping_error(self):
        client = MagicMock()
        client.ping.side_effect = RuntimeError("koneksi putus")

        self.assertFalse(OdooAdapter(client=client).health_check())

    def test_health_check_false_kalau_client_tidak_punya_ping(self):
        self.assertFalse(OdooAdapter(client=object()).health_check())

    def test_close_menutup_client(self):
        client = MagicMock()

        OdooAdapter(client=client).close()

        client.close.assert_called_once_with()

    def test_close_tanpa_kredensial_aman(self):
        with override_settings(**self.NOCREDS):
            self.assertIsNone(OdooAdapter().close())


class OdooJSONRPCHealthProbeTests(SimpleTestCase):
    """`version()` / `ping()` pada transport JSON-RPC (tanpa autentikasi)."""

    def test_version_memanggil_common_version(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            body = request.read().decode()
            captured["body"] = body
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"server_version": "17.0"}})

        transport = make_transport(handler)

        self.assertEqual(transport.version(), {"server_version": "17.0"})
        self.assertIn('"service": "common"', captured["body"])
        self.assertIn('"method": "version"', captured["body"])

    def test_ping_true_kalau_odoo_menjawab(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"server_version": "17.0"}})

        self.assertTrue(make_transport(handler).ping())

    def test_ping_false_kalau_tidak_terhubung(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        self.assertFalse(make_transport(handler).ping())

    def test_ping_false_kalau_odoo_balas_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "error": {"code": 200, "message": "Access Denied"},
                },
            )

        self.assertFalse(make_transport(handler).ping())

    def test_ping_false_kalau_bukan_json(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html>bukan json</html>")

        self.assertFalse(make_transport(handler).ping())
