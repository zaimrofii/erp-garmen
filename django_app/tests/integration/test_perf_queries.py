"""Budget jumlah query endpoint agregat (F5.2) — pencegah regresi N+1.

Ambang di bawah = hasil optimasi F5.2 (lihat ``docs/perf-benchmark.md``) + margin.
Yang diuji **batas atas** (``<=``), bukan angka eksak: tujuannya menangkap N+1
(query yang tumbuh seiring jumlah baris), bukan mengunci implementasi.

Baseline SEBELUM optimasi (data uji yang sama, N=10 bundle & 3 WC):

    /dashboard/summary/          45  → budget 30
    /production/buffer-queue/   242  → budget 20
    /reports/wip/                23  → budget 15
    /reports/line-efficiency/    27  → budget 15
    /inventory/products/         33  → budget 10

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_perf_queries.py -q
"""

from __future__ import annotations

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps_industry.garment.models import BundleEvent
from apps_industry.garment.tests.factories import (
    make_bundle,
    make_order,
    make_order_line,
    make_product,
    make_routing,
    make_scrap_accumulator,
    make_step,
    make_work_center,
    make_work_order,
)
from core.auth.models import User

DASHBOARD_URL = "/api/v1/dashboard/summary/"
BUFFER_URL = "/api/v1/production/buffer-queue/"
WIP_URL = "/api/v1/reports/wip/"
LINE_EFFICIENCY_URL = "/api/v1/reports/line-efficiency/"
PRODUCTS_URL = "/api/v1/inventory/products/"

#: Budget query (batas atas) hasil optimasi F5.2.
MAX_DASHBOARD_QUERIES = 30
MAX_BUFFER_QUEUE_QUERIES = 20
MAX_WIP_QUERIES = 15
MAX_LINE_EFFICIENCY_QUERIES = 15
MAX_PRODUCTS_QUERIES = 10


def seed_perf_data() -> None:
    """Seed minimal: 3 WC + routing 3 step + 10 bundle + event + 1 scrap.

    Semua endpoint di bawah membaca data yang sama supaya perbandingan query
    antar endpoint adil (data sama, hanya jumlah query yang diuji).
    """
    wc_cutting = make_work_center(code="PERF-WC-CUT")
    wc_sewing = make_work_center(code="PERF-WC-SEW")
    wc_packing = make_work_center(code="PERF-WC-PACK")

    routing = make_routing(code="PERF-ROUTE")
    make_step(routing, "PERF-STEP-1", 1, work_center=wc_cutting)
    make_step(routing, "PERF-STEP-2", 2, work_center=wc_sewing)
    make_step(routing, "PERF-STEP-3", 3, work_center=wc_packing, is_terminal=True)

    order = make_order(code="PERF-ORD")
    product = make_product(code="PERF-TS")
    order_line = make_order_line(order=order, product=product, qty=500)
    work_order = make_work_order(order_line=order_line, code="PERF-WO")

    work_centers = (wc_cutting, wc_sewing, wc_packing)
    states = ("CUTTING", "SEWING", "QC")
    bundles = []
    for index in range(10):
        work_center = work_centers[index % len(work_centers)]
        bundle = make_bundle(
            work_order=work_order,
            code=f"PERF-BND-{index + 1:03d}",
            qty=10 + index,
            qty_done=0,
            state=states[index % len(states)],
            current_work_center=work_center,
        )
        BundleEvent.objects.create(bundle=bundle, event_type="BUNDLE_START", text="perf")
        BundleEvent.objects.create(bundle=bundle, event_type="BUNDLE_FINISH", text="perf")
        bundles.append(bundle)

    make_scrap_accumulator(work_center=wc_sewing, bundle=bundles[0], qty=3)


class PerfQueryBudgetTests(TestCase):
    """Satu test per endpoint kritikal: jumlah query <= budget."""

    @classmethod
    def setUpTestData(cls):
        """Seed sekali per class (data sama untuk semua endpoint)."""
        cls.user = User.objects.create_user(username="perf-budget", password="x")
        seed_perf_data()

    def setUp(self):
        """Klien terautentikasi (tanpa query sesi)."""
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def test_anonim_403_semua_endpoint(self):
        """Kelima endpoint wajib menolak anonim (kontrol keamanan tetap)."""
        anon = APIClient()
        for url in (
            DASHBOARD_URL,
            BUFFER_URL,
            WIP_URL,
            LINE_EFFICIENCY_URL,
            PRODUCTS_URL,
        ):
            with self.subTest(url=url):
                self.assertEqual(anon.get(url).status_code, 403)

    def assert_query_budget(self, url: str, budget: int):
        """GET `url` lalu pastikan jumlah query **<=** `budget` (bukan eksak)."""
        with CaptureQueriesContext(connection) as captured:
            response = self.api.get(url)

        executed = len(captured.captured_queries)
        self.assertLessEqual(
            executed,
            budget,
            f"{url} memakai {executed} query (budget {budget}). "
            "Penyebab umum: loop yang menembak query per baris (N+1).",
        )
        return response

    def test_dashboard_summary_query_budget(self):
        """`/dashboard/summary/` <= 30 query (sebelum optimasi: 45)."""
        response = self.assert_query_budget(DASHBOARD_URL, MAX_DASHBOARD_QUERIES)

        self.assertEqual(response.status_code, 200)

    def test_buffer_queue_query_budget(self):
        """`/production/buffer-queue/` <= 20 query (sebelum optimasi: 242)."""
        response = self.assert_query_budget(BUFFER_URL, MAX_BUFFER_QUEUE_QUERIES)

        self.assertEqual(response.status_code, 200)
        self.assertIn("rows", response.json())

    def test_reports_wip_query_budget(self):
        """`/reports/wip/` <= 15 query (sebelum optimasi: 23)."""
        response = self.assert_query_budget(WIP_URL, MAX_WIP_QUERIES)

        self.assertEqual(response.status_code, 200)

    def test_reports_line_efficiency_query_budget(self):
        """`/reports/line-efficiency/` <= 15 query (sebelum optimasi: 27)."""
        response = self.assert_query_budget(LINE_EFFICIENCY_URL, MAX_LINE_EFFICIENCY_QUERIES)

        self.assertEqual(response.status_code, 200)

    def test_inventory_products_query_budget(self):
        """`/inventory/products/` <= 10 query (sebelum optimasi: 33)."""
        response = self.assert_query_budget(PRODUCTS_URL, MAX_PRODUCTS_QUERIES)

        self.assertEqual(response.status_code, 200)
