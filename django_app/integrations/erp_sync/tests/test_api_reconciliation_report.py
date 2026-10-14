"""Test endpoint riwayat rekonsiliasi stok (Fase I7) — DRF, tanpa Odoo.

Cakupan ``GET /api/v1/reconciliation/report/?days=N``:

* happy path → 200 + struktur ``{days, count, entries}``; ``days`` default 7;
* ``days=30`` → diteruskan apa adanya ke ``ReconciliationService.report(days=30)``;
* ``days`` di luar ``1..90`` (100/0/-5) atau bukan angka → **400** dan service
  **tidak** dipanggil;
* batas ``1`` dan ``90`` diterima;
* anonim → **403**;
* ``POST`` → **405** (``APIView`` tanpa ``post()``);
* tanpa mock (service asli) → baris ``StockReconciliation`` di DB benar-benar
  terbaca (endpoint ini read-only, tidak menyentuh Odoo).

Auth memakai ``force_authenticate`` (endpoint ``IsAuthenticated``, pola
``test_api_order_readiness.py``); request anonim diuji dengan ``APIClient()`` baru.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.models import StockReconciliation
from core.auth.models import User
from master.models import Product

#: Service di-import di api.py → patch nama di modul itu.
SERVICE = "integrations.erp_sync.api.ReconciliationService"
URL = "/api/v1/reconciliation/report/"

#: Satu entri `report()` (bentuk asli dari service: dict siap JSON).
ENTRY = {
    "run_at": "2026-10-06T03:00:00+00:00",
    "product_code": "FG-001",
    "product_odoo_id": 501,
    "mes_qty": 10.0,
    "odoo_qty": 4.0,
    "diff": 6.0,
    "is_alert": True,
    "notes": "toleransi=5",
}


class ReconciliationReportApiTests(TestCase):
    """Satu baris `StockReconciliation` di DB (untuk test tanpa mock)."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="supervisor", password="rahasia")
        cls.product = Product.objects.create(code="FG-API-9", name="Kaos API")
        cls.row = StockReconciliation.objects.create(
            product=cls.product,
            product_odoo_id=509,
            mes_qty=10.0,
            odoo_qty=4.0,
            diff=6.0,
            is_alert=True,
            notes="toleransi=5",
        )

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(user=self.user)

    # ------------------------------------------------------------------ helper
    def get_with_service(self, service_report, query=""):
        """GET dengan ``ReconciliationService`` di-patch; return (response, service)."""
        service = MagicMock()
        service.report.return_value = service_report
        with patch(SERVICE, return_value=service):
            response = self.api.get(f"{URL}{query}")
        return response, service

    # ------------------------------------------------------------------- tests
    def test_get_happy_path_struktur_dan_default_days(self):
        response, service = self.get_with_service([ENTRY])

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), {"days", "count", "entries"})
        self.assertEqual(body["days"], 7)
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["entries"], [ENTRY])
        service.report.assert_called_once_with(days=7)

    def test_get_riwayat_kosong_count_nol(self):
        response, service = self.get_with_service([])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"days": 7, "count": 0, "entries": []})
        service.report.assert_called_once_with(days=7)

    def test_get_days_30_diteruskan_ke_service(self):
        response, service = self.get_with_service([ENTRY], "?days=30")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["days"], 30)
        service.report.assert_called_once_with(days=30)

    def test_get_days_100_di_luar_rentang_400_tanpa_panggil_service(self):
        response, service = self.get_with_service([ENTRY], "?days=100")

        self.assertEqual(response.status_code, 400)
        self.assertIn("days", response.json()["detail"])
        service.report.assert_not_called()

    def test_get_batas_1_dan_90_diterima(self):
        for days in (1, 90):
            with self.subTest(days=days):
                response, service = self.get_with_service([], f"?days={days}")

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["days"], days)
                service.report.assert_called_once_with(days=days)

    def test_get_days_nol_dan_negatif_400(self):
        for raw in ("0", "-5"):
            with self.subTest(days=raw):
                response, service = self.get_with_service([ENTRY], f"?days={raw}")

                self.assertEqual(response.status_code, 400)
                service.report.assert_not_called()

    def test_get_days_bukan_angka_400(self):
        response, service = self.get_with_service([ENTRY], "?days=abc")

        self.assertEqual(response.status_code, 400)
        service.report.assert_not_called()

    def test_get_days_kosong_pakai_default_7(self):
        response, service = self.get_with_service([ENTRY], "?days=")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["days"], 7)
        service.report.assert_called_once_with(days=7)

    def test_get_tanpa_auth_403(self):
        response = APIClient().get(URL)

        self.assertEqual(response.status_code, 403)

    def test_post_method_tidak_diizinkan_405(self):
        response = self.api.post(URL)

        self.assertEqual(response.status_code, 405)

    # ------------------------------------------- tanpa mock (service asli, DB)
    def test_get_tanpa_mock_membaca_baris_db(self):
        response = self.api.get(URL)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["days"], 7)
        self.assertEqual(body["count"], 1)
        entry = body["entries"][0]
        self.assertEqual(
            set(entry),
            {
                "run_at",
                "product_code",
                "product_odoo_id",
                "mes_qty",
                "odoo_qty",
                "diff",
                "is_alert",
                "notes",
            },
        )
        self.assertEqual(entry["product_code"], "FG-API-9")
        self.assertEqual(entry["product_odoo_id"], 509)
        self.assertEqual(entry["mes_qty"], 10.0)
        self.assertEqual(entry["odoo_qty"], 4.0)
        self.assertEqual(entry["diff"], 6.0)
        self.assertTrue(entry["is_alert"])
        self.assertEqual(entry["notes"], "toleransi=5")
