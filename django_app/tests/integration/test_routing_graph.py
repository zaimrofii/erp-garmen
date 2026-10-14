"""Test endpoint routing graph (F1 / B3) — `GET /api/v1/routing/graph/`.

Read-only dari `ProcessRouting` + `RoutingStep`. ``IsAuthenticated`` → 403.

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_routing_graph.py -q
"""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.tests.factories import (
    make_routing,
    make_step,
    make_work_center,
)
from core.auth.models import User

GRAPH_URL = "/api/v1/routing/graph/"

TOP_KEYS = {"routing_id", "routing_name", "version", "nodes", "edges"}
NODE_KEYS = {"id", "label", "step_no"}
EDGE_KEYS = {"from", "to", "overlap_pct", "is_rework"}


class RoutingGraphAuthTests(TestCase):
    def test_anonim_403(self):
        self.assertEqual(APIClient().get(GRAPH_URL).status_code, 403)


class RoutingGraphTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="route-graph", password="x")

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def test_shape_lengkap(self):
        routing = make_routing(code="R-01")
        make_step(routing, "CUTTING", 1, is_initial=True, label="Cutting")
        step2 = make_step(routing, "SEWING", 2, label="Sewing")
        step1 = routing.steps.get(code="CUTTING")
        step1.allowed_next_steps.add(step2)

        body = self.api.get(GRAPH_URL).json()

        self.assertEqual(set(body), TOP_KEYS)
        self.assertEqual(body["routing_id"], routing.pk)
        self.assertEqual(body["routing_name"], routing.name)
        self.assertEqual(body["version"], 1)
        self.assertEqual(len(body["nodes"]), 2)
        self.assertEqual(len(body["edges"]), 1)
        self.assertEqual(set(body["nodes"][0]), NODE_KEYS)
        self.assertEqual(set(body["edges"][0]), EDGE_KEYS)

    def test_product_id_invalid_404(self):
        response = self.api.get(GRAPH_URL, {"product_id": 999999})

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "routing not found")

    def test_no_active_routing_404(self):
        response = self.api.get(GRAPH_URL)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "no active routing")

    def test_linear_3_step_2_edges_non_rework(self):
        routing = make_routing(code="R-LINEAR")
        make_work_center(code="WC-1")
        step1 = make_step(routing, "CUTTING", 1, is_initial=True, label="Cutting")
        step2 = make_step(routing, "SEWING", 2, label="Sewing")
        step3 = make_step(routing, "PACKING", 3, is_terminal=True, label="Packing")
        step1.allowed_next_steps.add(step2)
        step2.allowed_next_steps.add(step3)

        body = self.api.get(GRAPH_URL).json()

        self.assertEqual([node["step_no"] for node in body["nodes"]], [1, 2, 3])
        self.assertEqual([node["label"] for node in body["nodes"]], ["Cutting", "Sewing", "Packing"])
        self.assertEqual(len(body["edges"]), 2)
        self.assertTrue(all(edge["is_rework"] is False for edge in body["edges"]))
        self.assertEqual(
            body["edges"][0],
            {"from": step1.pk, "to": step2.pk, "overlap_pct": 0, "is_rework": False},
        )

    def test_rework_edge_is_rework_true(self):
        routing = make_routing(code="R-REWORK")
        step1 = make_step(routing, "CUTTING", 1, is_initial=True)
        step2 = make_step(routing, "SEWING", 2)
        step3 = make_step(routing, "QC", 3, is_terminal=True)
        step1.allowed_next_steps.add(step2)
        step2.allowed_next_steps.add(step3)
        step3.rework_target_step = step2
        step3.save(update_fields=["rework_target_step"])

        body = self.api.get(GRAPH_URL).json()

        self.assertEqual(len(body["edges"]), 3)  # 2 normal + 1 rework
        rework = [edge for edge in body["edges"] if edge["is_rework"]]
        self.assertEqual(len(rework), 1)
        self.assertEqual(
            rework[0],
            {"from": step3.pk, "to": step2.pk, "overlap_pct": 0, "is_rework": True},
        )
