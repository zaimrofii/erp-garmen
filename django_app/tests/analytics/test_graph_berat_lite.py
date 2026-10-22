"""Test Fase Berat-Lite — graph queries (TEMPORARY, recursive CTE)."""

from __future__ import annotations

from django.test import TestCase

from apps_industry.garment.models import BundleEvent
from apps_industry.garment.tests.factories import (
    make_bundle,
    make_order,
    make_order_line,
    make_scrap_accumulator,
    make_work_center,
    make_work_order,
)
from core.auth.models import Role, User
from integrations.ai_agent.data_access import graph_queries


class GraphTestBase(TestCase):
    def setUp(self):
        self.order = make_order()
        self.line = make_order_line(order=self.order)
        self.work_order = make_work_order(order_line=self.line)
        self.wc = make_work_center("SEWING-1")
        self.bundle_one = make_bundle(work_order=self.work_order, qty=10, current_work_center=self.wc)
        self.bundle_two = make_bundle(work_order=self.work_order, qty=5, current_work_center=self.wc)
        self.user = User.objects.create_user(
            username="graph-op",
            password="x",
            role=Role.objects.get(code=Role.Code.OPERATOR),
        )
        BundleEvent.objects.create(
            bundle=self.bundle_one, event_type="BUNDLE_START", actor=self.user
        )
        make_scrap_accumulator(bundle=self.bundle_one, work_center=self.wc, qty=2)


class OrderGraphTests(GraphTestBase):
    def test_order_graph_menelusuri_semua_bundle(self):
        graph = graph_queries.get_order_graph(self.order.pk)

        self.assertTrue(graph["found"])
        self.assertEqual(graph["summary"]["line_count"], 1)
        self.assertEqual(graph["summary"]["bundle_count"], 2)
        self.assertEqual(len(graph["bundles"]), 2)

    def test_order_graph_menyertakan_event_dan_scrap(self):
        graph = graph_queries.get_order_graph(self.order.pk)

        self.assertEqual(graph["summary"]["event_count"], 1)
        self.assertEqual(graph["summary"]["scrap_qty"], 2.0)
        self.assertEqual(graph["scrap"][0]["work_center__code"], "SEWING-1")

    def test_order_graph_nodes_berisi_order_dan_bundle(self):
        graph = graph_queries.get_order_graph(self.order.pk)
        types = {node["type"] for node in graph["nodes"]}

        self.assertIn("order", types)
        self.assertIn("bundle", types)
        self.assertIn("work_center", types)

    def test_order_tidak_ada(self):
        graph = graph_queries.get_order_graph(999999)

        self.assertFalse(graph["found"])
        self.assertEqual(graph["nodes"], [])


class BundleGraphTests(GraphTestBase):
    def test_bundle_graph_ke_order_customer(self):
        graph = graph_queries.get_bundle_graph(self.bundle_one.pk)

        self.assertTrue(graph["found"])
        self.assertEqual(graph["bundle"]["code"], self.bundle_one.code)
        self.assertEqual(graph["order"]["id"], self.order.pk)
        self.assertEqual(graph["summary"]["event_count"], 1)

    def test_bundle_graph_scrap(self):
        graph = graph_queries.get_bundle_graph(self.bundle_one.pk)

        self.assertEqual(graph["summary"]["scrap_qty"], 2.0)
        self.assertEqual(len(graph["scrap"]), 1)

    def test_bundle_tidak_ada(self):
        graph = graph_queries.get_bundle_graph(999999)

        self.assertFalse(graph["found"])
        self.assertEqual(graph["events"], [])


class WcGraphTests(GraphTestBase):
    def test_wc_graph_bundles_operator_scrap(self):
        graph = graph_queries.get_wc_graph(self.wc.pk)

        self.assertTrue(graph["found"])
        self.assertEqual(graph["summary"]["buffer_length"], 2)
        self.assertEqual(graph["operators"][0]["actor__username"], "graph-op")
        self.assertEqual(graph["summary"]["scrap_qty"], 2.0)

    def test_wc_tidak_ada(self):
        graph = graph_queries.get_wc_graph(999999)

        self.assertFalse(graph["found"])
        self.assertEqual(graph["bundles"], [])
