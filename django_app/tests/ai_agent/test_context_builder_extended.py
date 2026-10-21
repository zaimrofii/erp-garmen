"""Test extended context builder (FIX #2) — keyword → data nyata."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase

from apps_industry.garment.models import ScrapAccumulator
from apps_industry.garment.tests.factories import (
    make_bundle,
    make_order,
    make_order_line,
    make_product,
    make_work_center,
    make_work_order,
)
from integrations.ai_agent.orchestrator import context_builder
from master.models import Partner, Product

MODULE = "integrations.ai_agent.orchestrator.context_builder"


def _user(role="SUPERVISOR"):
    return SimpleNamespace(role=SimpleNamespace(code=role))


def _postgres(rows_by_table):
    def _handle(payload):
        table = payload.get("table")
        if table not in rows_by_table:
            return {"ok": False, "error": "table_not_allowed"}
        return {"ok": True, "rows": rows_by_table[table]}

    return _handle


class ContextBuilderExtendedTests(TestCase):
    def test_orders(self):
        order = make_order(code="ORD-CTX-1", state="CONFIRMED")
        make_order_line(order=order, qty=3, price_unit=100)
        rows = [
            {
                "id": order.pk,
                "code": order.code,
                "customer_id": None,
                "state": order.state,
                "created_at": "2026-10-20T00:00:00+00:00",
                "deadline": None,
            }
        ]
        lines = [{"id": 1, "order_id": order.pk, "product_id": None, "qty": 3}]
        with patch(
            f"{MODULE}.mcp_postgres_query.handle",
            side_effect=_postgres(
                {"garment_order": rows, "garment_orderline": lines}
            ),
        ):
            data = context_builder.build_context(
                "DATA_LOOKUP", [], "order terbaru?", {}, user=_user()
            )

        self.assertEqual(data["orders"][0]["code"], "ORD-CTX-1")
        self.assertEqual(data["orders"][0]["lines"][0]["qty"], 3)

    def test_work_orders(self):
        make_work_order(code="WO-CTX-1", qty_planned=10, qty_done=4, state="IN_PROGRESS")
        data = context_builder.build_context(
            "DATA_LOOKUP", [], "WO belum selesai?", {}, user=_user()
        )

        self.assertEqual(data["work_orders"][0]["code"], "WO-CTX-1")
        self.assertEqual(data["work_orders"][0]["product_name"], "Kaos Polos")

    def test_bundles(self):
        make_bundle(code="BND-CTX-1", qty=10, state="SEWING")
        data = context_builder.build_context(
            "DATA_LOOKUP", [], "bundle aktif?", {}, user=_user()
        )

        self.assertEqual(data["bundles"][0]["code"], "BND-CTX-1")

    def test_stock(self):
        product = make_product(code="STOCK-1")
        product.odoo_id = 77
        product.save(update_fields=["odoo_id"])
        rows = [
            {
                "id": product.pk,
                "code": product.code,
                "name": product.name,
                "odoo_id": 77,
                "cost_price": 1000,
            }
        ]
        with patch(
            f"{MODULE}.mcp_postgres_query.handle", return_value={"ok": True, "rows": rows}
        ), patch(
            f"{MODULE}.mcp_odoo_rpc.handle",
            return_value={"ok": True, "data": [{"quantity": 2}, {"quantity": 3}]},
        ):
            data = context_builder.build_context(
                "DATA_LOOKUP", [], "stok produk?", {}, user=_user("ADMIN")
            )

        self.assertEqual(data["stock"][0]["quantity"], 5)
        self.assertEqual(data["stock"][0]["odoo_id"], 77)

    def test_metrics_by_wc(self):
        rows = [{"key": "SEWING-2", "value": 20.0}]
        with patch(
            f"{MODULE}.mcp_analytics.handle_request",
            return_value={"ok": True, "rows": rows, "unit": "%"},
        ):
            data = context_builder.build_context(
                "DATA_LOOKUP", [], "WC paling sibuk?", {}, user=_user()
            )

        self.assertEqual(data["metrics_by_wc"][0]["rows"][0]["key"], "SEWING-2")

    def test_metrics_by_line(self):
        rows = [{"key": "Line-A", "value": 12.0}]
        with patch(
            f"{MODULE}.mcp_analytics.handle_request",
            return_value={"ok": True, "rows": rows, "unit": "jam"},
        ):
            data = context_builder.build_context(
                "DATA_LOOKUP", [], "line paling lambat?", {}, user=_user()
            )

        self.assertEqual(data["metrics_by_line"][0]["rows"][0]["key"], "Line-A")

    def test_customer_orders(self):
        partner = Partner.objects.create(code="CUST-CTX", name="PT Customer")
        order = make_order(code="ORD-CUST", customer=partner)
        make_order_line(order=order, qty=2, price_unit=100)

        data = context_builder.build_context(
            "DATA_LOOKUP", [], "customer paling banyak order?", {}, user=_user()
        )

        row = next(item for item in data["customer_orders"] if item["customer_id"] == partner.pk)
        self.assertEqual(row["order_count"], 1)
        self.assertEqual(row["amount"], 200.0)

    def test_product_production(self):
        bundle = make_bundle(code="BND-PROD", qty=10, qty_done=7, state="DONE")

        data = context_builder.build_context(
            "DATA_LOOKUP", [], "produk paling sering diproduksi?", {}, user=_user()
        )

        product_id = bundle.work_order.order_line.product_id
        row = next(
            item for item in data["product_production"] if item["product_id"] == product_id
        )
        self.assertEqual(row["qty_done"], 7.0)

    def test_product_quality(self):
        bundle = make_bundle(code="BND-QUALITY", qty=10, qty_done=3)
        ScrapAccumulator.objects.create(
            work_center=make_work_center(code="QC-QUALITY"),
            bundle=bundle,
            qty=4,
            rework_qty=2,
            notes="context-extended",
        )

        data = context_builder.build_context(
            "DATA_LOOKUP", [], "produk bermasalah?", {}, user=_user()
        )

        product_id = bundle.work_order.order_line.product_id
        row = next(
            item for item in data["product_quality"] if item["product_id"] == product_id
        )
        self.assertEqual(row["scrap_qty"], 4.0)
        self.assertEqual(row["rework_qty"], 2.0)

    def test_inventory_value(self):
        stock = [{"quantity": 5, "cost_price": 1000}]
        with patch(f"{MODULE}._collect_stock", return_value=(stock, [])):
            data = context_builder.build_context(
                "DATA_LOOKUP", [], "nilai gudang?", {}, user=_user("ADMIN")
            )

        self.assertEqual(data["inventory_value"]["total_value"], 5000.0)

