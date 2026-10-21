"""Test MCP odoo-rpc (H T1.2) — mock transport, read-only."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from integrations.ai_agent.mcp_servers import mcp_odoo_rpc

MODULE = "integrations.ai_agent.mcp_servers.mcp_odoo_rpc"


class _FakeTransport:
    def __init__(self, rows=None, error=None):
        self.rows = rows or {}
        self.error = error
        self.calls = []

    def search_read(self, model, domain, fields, limit=None):
        self.calls.append(("search_read", model, limit))
        if self.error is not None:
            raise self.error
        return list(self.rows.get(model, []))

    def fetch_stock_quants(self, location_ids, since=None, child_of=False):
        self.calls.append(("fetch_stock_quants", list(location_ids)))
        if self.error is not None:
            raise self.error
        return list(self.rows.get("stock.quant", []))


class _FakeClient:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def _user(role="SUPERVISOR"):
    return SimpleNamespace(role=SimpleNamespace(code=role))


def _run(method, params, rows=None, error=None, role="SUPERVISOR", adapter="odoo"):
    transport = _FakeTransport(rows=rows, error=error)
    client = _FakeClient()
    with override_settings(ERP_ADAPTER=adapter), patch(
        f"{MODULE}._make_transport", return_value=(transport, client)
    ):
        result = mcp_odoo_rpc.handle(method, params, user=_user(role))
    return result, transport, client


class OdooRpcTests(SimpleTestCase):
    def test_get_stock_valid(self):
        result, transport, client = _run(
            "get_stock",
            {"product_odoo_id": 10},
            rows={"stock.quant": [{"id": 1, "product_id": 10, "quantity": 5}]},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["method"], "get_stock")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["data"][0]["quantity"], 5)
        self.assertEqual(transport.calls[0][0], "search_read")
        self.assertTrue(client.closed)

    def test_get_stock_location_filter(self):
        result, _, _ = _run(
            "get_stock",
            {"product_odoo_id": 10, "location_id": 8},
            rows={
                "stock.quant": [
                    {"id": 1, "product_id": 10, "quantity": 5},
                    {"id": 2, "product_id": 99, "quantity": 7},
                ]
            },
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["data"][0]["product_id"], 10)

    def test_get_stock_tidak_ada(self):
        result, _, _ = _run("get_stock", {"product_odoo_id": 10}, rows={})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "not_found")

    def test_get_invoice_valid(self):
        result, transport, _ = _run(
            "get_invoice",
            {"invoice_odoo_id": 5},
            rows={"account.move": [{"id": 5, "state": "posted"}]},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["data"][0]["state"], "posted")
        self.assertEqual(transport.calls[0][1], "account.move")

    def test_get_purchase_order_dan_sale_order(self):
        for method, params, model in (
            ("get_purchase_order", {"purchase_order_odoo_id": 1}, "purchase.order"),
            ("get_sale_order", {"sale_order_odoo_id": 2}, "sale.order"),
        ):
            with self.subTest(method=method):
                result, transport, _ = _run(
                    method, params, rows={model: [{"id": params[next(iter(params))]}]}
                )
                self.assertTrue(result["ok"])
                self.assertEqual(transport.calls[0][1], model)

    def test_get_product_dan_partner(self):
        for method, params, model in (
            ("get_product_info", {"product_odoo_id": 3}, "product.product"),
            ("get_partner_info", {"partner_odoo_id": 4}, "res.partner"),
        ):
            with self.subTest(method=method):
                result, _, _ = _run(method, params, rows={model: [{"id": 3}]})
                self.assertTrue(result["ok"])

    def test_odoo_down(self):
        result, _, client = _run(
            "get_invoice",
            {"invoice_odoo_id": 1},
            error=ConnectionError("down"),
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "odoo_unavailable")
        self.assertEqual(result["detail"], "ConnectionError")
        self.assertTrue(client.closed)

    @override_settings(ERP_ADAPTER="null")
    def test_erp_adapter_null(self):
        with patch(f"{MODULE}._make_transport") as make:
            result = mcp_odoo_rpc.handle(
                "get_stock", {"product_odoo_id": 1}, user=_user()
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "erp_not_configured")
        make.assert_not_called()

    def test_role_operator_forbidden(self):
        result, transport, client = _run(
            "get_stock", {"product_odoo_id": 1}, role="OPERATOR"
        )

        self.assertEqual(result["error"], "forbidden")
        self.assertEqual(transport.calls, [])
        self.assertFalse(client.closed)

    def test_limit_dipaksa_20(self):
        rows = [{"id": index, "product_id": 1, "quantity": 1} for index in range(25)]
        result, transport, _ = _run(
            "get_stock", {"product_odoo_id": 1, "limit": 100}, rows={"stock.quant": rows}
        )

        self.assertEqual(result["count"], 20)
        self.assertEqual(transport.calls[0][2], 20)

    def test_read_only_tidak_ada_write(self):
        result, transport, _ = _run(
            "list_recent_moves", {"limit": 5}, rows={"stock.move": [{"id": 1}]}
        )

        self.assertTrue(result["ok"])
        methods = {call[0] for call in transport.calls}
        self.assertTrue(methods.issubset({"search_read", "fetch_stock_quants"}))
        self.assertFalse(methods & {"create", "write", "unlink"})

    def test_method_tidak_dikenal(self):
        result, _, _ = _run("delete_everything", {})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "method_tidak_dikenal")

