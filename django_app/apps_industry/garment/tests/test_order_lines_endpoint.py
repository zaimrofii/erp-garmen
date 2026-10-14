"""Test resource `order-lines` (FASE 3.4 P1) — list, detail, metadata.

Menutup celah FASE 3.4: tanpa resource ini, agent `cutting` tidak punya cara
menemukan OrderLine lewat HTTP (`GET /garmen/order-lines/` dulu 404) sehingga
alur "order baru → WorkOrder → Bundle" mustahil.

OrderLine **bukan** resource aksi: ia tidak punya state machine (blok
`state_machine` kosong dengan `current_state = "N/A"` dan `allowed_actions = []`).
"""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.tests.factories import make_order_line

LIST_URL = "/api/v1/garmen/order-lines/"


class OrderLinesEndpointTests(TestCase):
    """List + detail order line (kontrak §3) untuk jalur "order baru"."""

    @classmethod
    def setUpTestData(cls):
        cls.order_line = make_order_line(qty=20)

    def setUp(self):
        self.client = APIClient()

    def test_list_order_lines(self):
        response = self.client.get(LIST_URL)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["resource"], "order-lines")
        rows = body["rows"]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["id"], self.order_line.pk)
        self.assertEqual(row["order_code"], self.order_line.order.code)
        self.assertEqual(row["product_code"], self.order_line.product.code)
        self.assertEqual(row["qty"], 20)

    def test_list_order_lines_anonim(self):
        # AllowAny — konsisten dengan endpoint list lain (dipakai bootstrap simulator).
        self.assertEqual(self.client.get(LIST_URL).status_code, 200)

    def test_order_lines_detail(self):
        response = self.client.get(f"{LIST_URL}{self.order_line.pk}/")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["id"], self.order_line.pk)
        self.assertEqual(body["order_code"], self.order_line.order.code)
        self.assertEqual(body["product_code"], self.order_line.product.code)
        self.assertEqual(body["qty"], 20)
        self.assertEqual(body["work_order_ids"], [])
        self.assertIn("version", body)

    def test_order_lines_detail_tidak_ada_404(self):
        self.assertEqual(self.client.get(f"{LIST_URL}999999/").status_code, 404)

    def test_order_lines_metadata_tanpa_state_machine(self):
        response = self.client.get(f"{LIST_URL}{self.order_line.pk}/schema/")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["resource"]["name"], "order-lines")
        self.assertEqual(body["state_machine"]["current_state"], "N/A")
        self.assertEqual(body["state_machine"]["possible_states"], [])
        self.assertEqual(body["state_machine"]["allowed_actions"], [])

    def test_industri_tidak_dikenal_404(self):
        self.assertEqual(
            self.client.get("/api/v1/ngawur/order-lines/").status_code, 404
        )
