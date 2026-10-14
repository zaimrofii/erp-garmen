"""Test bentuk response list endpoint (Fase B.2) — kontrak `ListPage` §3.

Frontend memvalidasi dengan `parseListPageSafe` / `ListPageSchema`
(`frontend_app/src/lib/schemas/list.schema.ts`):

    {rows, total_count, has_more, next_cursor}

Key tambahan (`resource`, `industry`) boleh ada — Zod men-strip key asing.
"""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.tests.factories import (
    make_bundle,
    make_scrap_accumulator,
    make_work_center,
    make_work_order,
)

LISTPAGE_KEYS = {"rows", "total_count", "has_more", "next_cursor"}


class ListEndpointShapeTests(TestCase):
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

    def test_kunci_kontrak_ada_dan_total_lama_hilang(self):
        body = self.client.get("/api/v1/garmen/bundles/").json()

        for key in LISTPAGE_KEYS:
            self.assertIn(key, body)
        self.assertNotIn("total", body)  # diganti `total_count` (Fase B.2)
        self.assertEqual(body["total_count"], 3)
        self.assertFalse(body["has_more"])
        # Paginasi list masih offset-based → cursor selalu null (key tetap ada).
        self.assertIsNone(body["next_cursor"])

    def test_rows_punya_id_id_dan_tipe_kontrak(self):
        rows = self.client.get("/api/v1/garmen/bundles/").json()["rows"]

        self.assertTrue(rows)
        for row in rows:
            # `ListRow.id` = union(string|number) → frontend transform ke String.
            self.assertIn("id", row)
            self.assertIsInstance(row["id"], (int, str))
            self.assertTrue(str(row["id"]))

    def test_paginasi_limit_offset_has_more_konsisten(self):
        halaman_1 = self.client.get("/api/v1/garmen/bundles/", {"limit": 2}).json()
        halaman_2 = self.client.get(
            "/api/v1/garmen/bundles/", {"limit": 2, "offset": 2}
        ).json()

        self.assertEqual(len(halaman_1["rows"]), 2)
        self.assertTrue(halaman_1["has_more"])
        self.assertEqual(halaman_1["total_count"], 3)
        self.assertFalse(halaman_2["has_more"])
        self.assertEqual(halaman_2["total_count"], 3)

    def test_tiap_resource_bentuk_kontrak_sama(self):
        for path in (
            "/api/v1/garmen/bundles/",
            "/api/v1/garmen/work-orders/",
            "/api/v1/garmen/qc/",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                for key in LISTPAGE_KEYS:
                    self.assertIn(key, response.json())