"""Test endpoint detail resource: data mentah + version (untuk conflict detection)."""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.models import Bundle
from apps_industry.garment.tests.factories import make_bundle, make_work_center, make_work_order


class DetailEndpointTests(TestCase):
    """Bundle di state SEWING + work order-nya."""

    @classmethod
    def setUpTestData(cls):
        cls.work_order = make_work_order(code="WO-001", qty_planned=20, qty_done=5)
        cls.work_center = make_work_center(code="SEWING-1")
        cls.bundle = make_bundle(
            work_order=cls.work_order,
            code="BND-001",
            size="L",
            qty=5,
            qty_done=2,
            state="SEWING",
            current_work_center=cls.work_center,
        )

    def setUp(self):
        self.client = APIClient()

    def test_detail_bundle(self):
        response = self.client.get(f"/api/v1/garmen/bundles/{self.bundle.pk}/")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["code"], "BND-001")
        self.assertEqual(body["state"], "SEWING")
        self.assertEqual(body["size"], "L")
        self.assertEqual(body["qty_done"], 2)
        self.assertEqual(body["current_work_center_code"], "SEWING-1")
        self.assertEqual(body["work_order_id"], self.work_order.pk)
        self.assertEqual(
            body["version"], Bundle.objects.get(pk=self.bundle.pk).version
        )

    def test_detail_work_order(self):
        response = self.client.get(
            f"/api/v1/garmen/work-orders/{self.work_order.pk}/"
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["code"], "WO-001")
        self.assertEqual(body["state"], "DRAFT")
        self.assertEqual(body["qty_planned"], 20)
        self.assertEqual(body["qty_done"], 5)
        self.assertEqual(
            body["order_code"], self.work_order.order_line.order.code
        )
        self.assertEqual(
            body["product_code"], self.work_order.order_line.product.code
        )
        self.assertEqual(len(body["version"]), 64)

    def test_detail_id_tidak_ada_404(self):
        response = self.client.get("/api/v1/garmen/bundles/999999/")

        self.assertEqual(response.status_code, 404)
        self.assertIn("999999", response.json()["detail"])

    def test_detail_resource_tidak_dikenal_404(self):
        # H2.1: `/garmen/orders/<id>/` kini endpoint nyata ⇒ placeholder diganti.
        response = self.client.get("/api/v1/garmen/tidak-ada/1/")

        self.assertEqual(response.status_code, 404)
        self.assertIn("tidak-ada", response.json()["detail"])
