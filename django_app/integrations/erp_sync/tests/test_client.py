"""Test OdooClient + factory client (anggap `httpx.MockTransport` = Odoo palsu)."""

from __future__ import annotations

import json

import httpx
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings

from integrations.erp_sync.adapters.null import NullAdapter
from integrations.erp_sync.adapters.odoo import OdooJSONRPCAdapter
from integrations.erp_sync.client import OdooClient, get_odoo_client, get_odoo_rpc_client

CREDS = {
    "ODOO_URL": "http://odoo.test:8069",
    "ODOO_DB": "garmen-test",
    "ODOO_USER": "sync@example.com",
    "ODOO_API_KEY": "kunci-rahasia",
}


def mock_http(handler) -> httpx.Client:
    """HTTP client httpx yang tidak keluar jaringan."""
    return httpx.Client(transport=httpx.MockTransport(handler))


def rpc(result, request_id: int = 1, body: dict | None = None) -> httpx.Response:
    """Respons JSON-RPC sukses ala Odoo."""
    payload = body or {"jsonrpc": "2.0", "id": request_id, "result": result}
    return httpx.Response(200, json=payload)


class OdooClientTests(SimpleTestCase):
    """`authenticate` / `execute_kw` / `ping` + sumber kredensial."""

    def make_client(self, handler) -> OdooClient:
        return OdooClient(
            url="http://odoo.test:8069",
            db="garmen-test",
            user="sync@example.com",
            api_key="kunci-rahasia",
            http_client=mock_http(handler),
        )

    def test_authenticate_kirim_common_login(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["payload"] = json.loads(request.content)
            captured["url"] = str(request.url)
            return rpc(7)

        client = self.make_client(handler)

        self.assertEqual(client.authenticate(), 7)
        self.assertEqual(captured["url"], "http://odoo.test:8069/jsonrpc")
        params = captured["payload"]["params"]
        self.assertEqual((params["service"], params["method"]), ("common", "login"))
        self.assertEqual(params["args"], ["garmen-test", "sync@example.com", "kunci-rahasia"])
        self.assertEqual(client.uid, 7)

    def test_execute_kw_login_otomatis_lalu_object_execute_kw(self):
        requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            requests.append(payload["params"])
            if payload["params"]["method"] == "login":
                return rpc(9, payload["id"])
            return rpc([{"id": 42}], payload["id"])

        client = self.make_client(handler)

        rows = client.execute_kw(
            "stock.move", "search_read", [[["state", "=", "done"]]], {"fields": ["id"]}
        )

        self.assertEqual(rows, [{"id": 42}])
        self.assertEqual(len(requests), 2)
        execute = requests[-1]
        self.assertEqual((execute["service"], execute["method"]), ("object", "execute_kw"))
        self.assertEqual(
            execute["args"][:5], ["garmen-test", 9, "kunci-rahasia", "stock.move", "search_read"]
        )
        self.assertEqual(execute["args"][5], [[["state", "=", "done"]]])
        self.assertEqual(execute["args"][6], {"fields": ["id"]})

    def test_execute_kw_tidak_login_lagi_kalau_uid_ada(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            calls.append(payload["params"]["method"])
            if payload["params"]["method"] == "login":
                return rpc(3, payload["id"])
            return rpc(True, payload["id"])

        client = self.make_client(handler)
        client.authenticate()
        client.execute_kw("stock.move", "create", [{"product_id": 1}])

        self.assertEqual(calls, ["login", "execute_kw"])

    def test_ping_true_kalau_common_version_menjawab(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["payload"] = json.loads(request.content)
            return rpc({"server_version": "17.0"})

        self.assertTrue(self.make_client(handler).ping())
        params = captured["payload"]["params"]
        self.assertEqual((params["service"], params["method"]), ("common", "version"))

    def test_ping_false_kalau_tidak_terhubung(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        self.assertFalse(self.make_client(handler).ping())

    def test_ping_false_kalau_odoo_balas_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return rpc(
                None,
                body={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "error": {"code": 200, "message": "Access Denied"},
                },
            )

        self.assertFalse(self.make_client(handler).ping())

    def test_ping_false_kalau_transport_tidak_mendukung(self):
        client = OdooClient(
            url="http://odoo.test:8069", db="d", user="u", api_key="k", transport=object()
        )

        self.assertFalse(client.ping())

    def test_kredensial_dibaca_dari_settings(self):
        with override_settings(**CREDS):
            client = OdooClient()
            try:
                self.assertEqual(client.url, "http://odoo.test:8069")
                self.assertEqual(client.db, "garmen-test")
                self.assertEqual(client.user, "sync@example.com")
                self.assertEqual(client.api_key, "kunci-rahasia")
                self.assertGreater(client.timeout, 0)
                self.assertIsNone(client.uid)
            finally:
                client.close()

    def test_tidak_ada_kredensial_di_repr(self):
        with override_settings(**CREDS):
            client = OdooClient()
            try:
                self.assertNotIn("kunci-rahasia", repr(client))
            finally:
                client.close()

    def test_parameter_menimpa_settings(self):
        client = OdooClient(url="http://odoo.lain:8069/", db="db-x", api_key="k")
        try:
            self.assertEqual(client.url, "http://odoo.lain:8069")
            self.assertEqual(client.db, "db-x")
            self.assertEqual(client.api_key, "k")
        finally:
            client.close()

    def test_close_dan_context_manager(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return rpc({"server_version": "17.0"})

        client = OdooClient(
            url="http://odoo.test:8069",
            db="d",
            user="u",
            api_key="k",
            http_client=mock_http(handler),
        )
        with client as opened:
            self.assertIs(opened, client)
            self.assertTrue(opened.ping())
        self.assertTrue(client.transport._client.is_closed)  # type: ignore[attr-defined]


class ClientFactoryTests(SimpleTestCase):
    """Factory `get_odoo_rpc_client()` (baru) & `get_odoo_client()` (lama, tetap)."""

    @override_settings(**CREDS)
    def test_get_odoo_rpc_client_sesuai_settings(self):
        client = get_odoo_rpc_client()
        try:
            self.assertIsInstance(client, OdooClient)
            self.assertIsInstance(client.transport, OdooJSONRPCAdapter)
            self.assertEqual(client.db, "garmen-test")
        finally:
            client.close()

    @override_settings(
        ODOO_URL="http://odoo.test:8069", ODOO_DB="", ODOO_USER="", ODOO_API_KEY=""
    )
    def test_get_odoo_rpc_client_raise_kalau_kredensial_kosong(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "ODOO_DB"):
            get_odoo_rpc_client()

    @override_settings(**CREDS)
    def test_get_odoo_rpc_client_bisa_override(self):
        client = get_odoo_rpc_client(db="db-lain")
        try:
            self.assertEqual(client.db, "db-lain")
        finally:
            client.close()

    @override_settings(ERP_ADAPTER="null")
    def test_get_odoo_client_null(self):
        self.assertIsInstance(get_odoo_client(), NullAdapter)

    @override_settings(ERP_ADAPTER="odoo", **CREDS)
    def test_get_odoo_client_odoo(self):
        transport = get_odoo_client()
        try:
            self.assertIsInstance(transport, OdooJSONRPCAdapter)
            self.assertEqual(transport.db, "garmen-test")
        finally:
            transport.close()

    @override_settings(
        ERP_ADAPTER="odoo",
        ODOO_URL="http://odoo.test:8069",
        ODOO_DB="",
        ODOO_USER="",
        ODOO_API_KEY="",
    )
    def test_get_odoo_client_raise_kalau_kredensial_kosong(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "ODOO_API_KEY"):
            get_odoo_client()

    @override_settings(ERP_ADAPTER="sap")
    def test_get_odoo_client_vendor_lain_tetap_raise(self):
        """Perilaku lama dipertahankan: vendor selain odoo/null -> error jelas."""
        with self.assertRaisesMessage(ImproperlyConfigured, "tidak dikenal"):
            get_odoo_client()

