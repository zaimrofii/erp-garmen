"""Test endpoint list resource: paginasi limit/offset + resource tidak dikenal."""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.tests.factories import (
    make_bundle,
    make_scrap_accumulator,
    make_work_center,
    make_work_order,
)


class ListEndpointTests(TestCase):
    """3 bundle + 1 work order + 1 catatan QC."""

    @classmethod
    def setUpTestData(cls):
        cls.work_order = make_work_order(code="WO-001")
        cls.work_center = make_work_center(code="SEWING-1")
        for index in range(3):
            make_bundle(
                work_order=cls.work_order,
                code=f"BND-{index:03d}",
                current_work_center=cls.work_center,
            )
        make_scrap_accumulator(work_center=cls.work_center, bundle=None, qty=4)

    def setUp(self):
        self.client = APIClient()

    def test_list_work_orders(self):
        response = self.client.get("/api/v1/garmen/work-orders/")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["resource"], "work-orders")
        self.assertEqual(body["total_count"], 1)
        self.assertFalse(body["has_more"])
        self.assertIsNone(body["next_cursor"])
        self.assertEqual(
            set(body["rows"][0]), {"id", "code", "state", "qty_planned", "qty_done"}
        )
        self.assertEqual(body["rows"][0]["code"], "WO-001")

    def test_list_bundles(self):
        response = self.client.get("/api/v1/garmen/bundles/")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total_count"], 3)
        self.assertEqual(
            [row["code"] for row in body["rows"]], ["BND-000", "BND-001", "BND-002"]
        )
        self.assertEqual(
            set(body["rows"][0]),
            {
                "id",
                "code",
                "state",
                "size",
                "qty",
                "qty_done",
                "version",
                "current_work_center_code",
                "allowed_actions",
            },
        )
        self.assertEqual(body["rows"][0]["current_work_center_code"], "SEWING-1")
        self.assertEqual(len(body["rows"][0]["version"]), 64)

    def test_paginasi_limit_offset(self):
        halaman_1 = self.client.get(
            "/api/v1/garmen/bundles/", {"limit": 2, "offset": 0}
        ).json()
        halaman_2 = self.client.get(
            "/api/v1/garmen/bundles/", {"limit": 2, "offset": 2}
        ).json()

        self.assertEqual(halaman_1["total_count"], 3)
        self.assertEqual(
            [row["code"] for row in halaman_1["rows"]], ["BND-000", "BND-001"]
        )
        self.assertTrue(halaman_1["has_more"])
        self.assertEqual([row["code"] for row in halaman_2["rows"]], ["BND-002"])
        self.assertFalse(halaman_2["has_more"])

    def test_limit_di_luar_batas_400(self):
        for params in ({"limit": 0}, {"limit": 999}, {"limit": "x"}):
            with self.subTest(params=params):
                response = self.client.get("/api/v1/garmen/bundles/", params)
                self.assertEqual(response.status_code, 400)
                self.assertIn("limit", response.json()["detail"])

    def test_list_qc(self):
        response = self.client.get("/api/v1/garmen/qc/")

        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["total_count"], 1)
        self.assertEqual(
            set(body["rows"][0]),
            {
                "id",
                "work_center_code",
                "bundle_code",
                "qty",
                "rework_qty",
                "end_loss_qty",
                "reason",
            },
        )
        self.assertIsNone(body["rows"][0]["bundle_code"])

    def test_resource_tidak_dikenal_404(self):
        # H2.1: `/garmen/orders/` kini endpoint nyata ⇒ placeholder diganti.
        self.assertEqual(self.client.get("/api/v1/garmen/tidak-ada/").status_code, 404)
