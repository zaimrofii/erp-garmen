"""Test endpoint inventory reporting (F5.4.2 / B30) — `GET /api/v1/inventory/reporting/`.

Read-only agregat stok **per lokasi** (tanpa model baru). Proksi yang dipakai
(dokumentasi lengkap di docstring view `InventoryReportingView`):

  * ``WH/WIP``             → bundle ``DRAFT`` (belum di-issue);
  * ``Virtual/Production`` → bundle di lantai (WC terisi, bukan DONE/CANCELLED);
  * ``WH/FG``              → bundle ``DONE`` (pakai ``qty_done``);
  * ``Virtual/Scrap``      → akumulasi ``ScrapAccumulator.qty``.

Test memakai ``override_settings`` untuk id lokasi supaya **deterministik**
(tidak tergantung nilai `.env` container); kasus "env kosong" diuji terpisah
sebagai fail-safe (harus 0, bukan error).

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_inventory_reporting.py -q
"""

from __future__ import annotations

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps_industry.garment.models import Bundle, ScrapAccumulator
from apps_industry.garment.tests.factories import (
    make_bundle,
    make_order,
    make_order_line,
    make_product,
    make_scrap_accumulator,
    make_work_center,
    make_work_order,
)
from core.auth.models import Role, User

REPORTING_URL = "/api/v1/inventory/reporting/"
ROW_KEYS = {"location_code", "location_name", "product_count", "total_qty", "last_updated"}
LOCATION_CODES = ["WH/WIP", "Virtual/Production", "WH/FG", "Virtual/Scrap"]

#: Id lokasi Odoo palsu (env) supaya laporan menghitung data MES di test.
LOCATION_ENV = {
    "ODOO_LOCATION_WIP_ID": "9001",
    "ODOO_LOCATION_PRODUCTION_ID": "9002",
    "ODOO_LOCATION_FG_ID": "9003",
    "ODOO_LOCATION_SCRAP_ID": "9004",
}


@override_settings(**LOCATION_ENV)
class InventoryReportingTests(TestCase):
    """Shape, agregat per lokasi, filter, dan fail-safe env kosong."""

    @classmethod
    def setUpTestData(cls):
        """1 produk, 3 bundle (DRAFT/lantai/DONE) + 1 catatan scrap."""
        cls.user = User.objects.create_user(
            username="inv1",
            email="inv1@klien.com",
            password="rahasia123",
            role=Role.objects.get(code=Role.Code.ADMIN),
        )

        work_center = make_work_center(code="IRF-WC")
        order_line = make_order_line(
            order=make_order(code="IRF-ORD"), product=make_product(code="IRF-TS")
        )
        work_order = make_work_order(order_line=order_line, code="IRF-WO")

        cls.draft = make_bundle(
            work_order=work_order, code="IRF-DRAFT", qty=10, state="DRAFT"
        )
        cls.floor = make_bundle(
            work_order=work_order,
            code="IRF-FLOOR",
            qty=7,
            state="SEWING",
            current_work_center=work_center,
        )
        cls.done = make_bundle(
            work_order=work_order,
            code="IRF-DONE",
            qty=5,
            qty_done=5,
            state="DONE",
            current_work_center=work_center,
        )
        cls.scrap = make_scrap_accumulator(
            work_center=work_center, bundle=cls.floor, qty=3, rework_qty=1, end_loss_qty=1
        )

    def setUp(self):
        """Klien terautentikasi (tanpa query sesi)."""
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    @staticmethod
    def _by_code(body: dict) -> dict:
        """``{location_code: row}`` dari respons."""
        return {row["location_code"]: row for row in body["rows"]}

    def test_shape_lengkap(self):
        """Bentuk: rows + total_locations + generated_at (4 lokasi, urut kontrak)."""
        response = self.api.get(REPORTING_URL)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), {"rows", "total_locations", "generated_at"})
        self.assertEqual(body["total_locations"], 4)
        self.assertEqual([row["location_code"] for row in body["rows"]], LOCATION_CODES)
        self.assertIn("T", body["generated_at"])

        for row in body["rows"]:
            self.assertEqual(set(row), ROW_KEYS)

    def test_anonim_403(self):
        """Tanpa login → 403."""
        self.assertEqual(APIClient().get(REPORTING_URL).status_code, 403)

    # --------------------------------------------------------------- agregat
    def test_agregat_per_lokasi(self):
        """Total qty & jumlah produk per lokasi sesuai sumber MES."""
        body = self.api.get(REPORTING_URL).json()
        rows = self._by_code(body)

        self.assertEqual(rows["WH/WIP"]["total_qty"], 10)  # bundle DRAFT
        self.assertEqual(rows["Virtual/Production"]["total_qty"], 7)  # di lantai
        self.assertEqual(rows["WH/FG"]["total_qty"], 5)  # qty_done bundle DONE
        self.assertEqual(rows["Virtual/Scrap"]["total_qty"], 3)  # ScrapAccumulator

        for code in LOCATION_CODES:
            self.assertEqual(rows[code]["product_count"], 1, code)
            self.assertIsNotNone(rows[code]["last_updated"], code)

    def test_filter_location_code(self):
        """`?location_code=` (case-insensitive) → satu baris."""
        body = self.api.get(f"{REPORTING_URL}?location_code=wh/fg").json()

        self.assertEqual(body["total_locations"], 1)
        self.assertEqual(body["rows"][0]["location_code"], "WH/FG")
        self.assertEqual(body["rows"][0]["total_qty"], 5)

    def test_filter_location_code_tidak_dikenal(self):
        """Kode lokasi tak dikenal → rows kosong (bukan 404)."""
        body = self.api.get(f"{REPORTING_URL}?location_code=WH/LANTAI-9").json()

        self.assertEqual(body["rows"], [])
        self.assertEqual(body["total_locations"], 0)

    # ------------------------------------------------------- kosong/fail-safe
    def test_kosong_semua_nol(self):
        """Belum ada data bundle/scrap → semua 0 (bukan error)."""
        Bundle.objects.all().delete()
        ScrapAccumulator.objects.all().delete()

        body = self.api.get(REPORTING_URL).json()

        self.assertEqual(body["total_locations"], 4)
        for row in body["rows"]:
            self.assertEqual(row["total_qty"], 0)
            self.assertEqual(row["product_count"], 0)
            self.assertIsNone(row["last_updated"])

    def test_fail_safe_env_kosong(self):
        """Env id lokasi kosong → baris tsb 0 & tidak crash; lokasi lain tetap."""
        with override_settings(ODOO_LOCATION_WIP_ID="", ODOO_LOCATION_FG_ID=""):
            body = self.api.get(REPORTING_URL).json()

        rows = self._by_code(body)
        self.assertEqual(body["total_locations"], 4)
        self.assertEqual(rows["WH/WIP"]["total_qty"], 0)
        self.assertIsNone(rows["WH/WIP"]["last_updated"])
        self.assertEqual(rows["WH/FG"]["total_qty"], 0)
        self.assertEqual(rows["Virtual/Production"]["total_qty"], 7)  # env terisi

    def test_payload_json_safe(self):
        """Nilai numerik bertipe int (JSON-safe) dan agregasi tidak error."""
        body = self.api.get(REPORTING_URL).json()

        for row in body["rows"]:
            self.assertIsInstance(row["total_qty"], int)
            self.assertIsInstance(row["product_count"], int)
