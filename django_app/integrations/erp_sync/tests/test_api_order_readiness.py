"""Test endpoint readiness per Order (Fase I3) — DRF, tanpa Odoo.

Cakupan:

* ``GET /api/v1/garmen/orders/<id>/readiness/`` — 200 + struktur dict per
  OrderLine (**11 kunci**, termasuk agregat vendor bill dari I6); order tak ada →
  404; anonim → 403;
* ``POST /api/v1/garmen/orders/<id>/recompute-readiness/`` — service di-mock:
  200 + counter, queryset yang dikirim HANYA OrderLine yang belum ``READY``
  (termasuk yang belum punya readiness); order tak ada → 404; anonim → 403.

Auth memakai ``force_authenticate`` (endpoint ``IsAuthenticated``, sama seperti
``test_api_sync_master.py``); request anonim diuji dengan ``APIClient()`` baru.
"""

from __future__ import annotations

from datetime import date, datetime
from datetime import timezone as dt_timezone
from unittest.mock import MagicMock, patch

from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.models import MaterialReadiness, Order, OrderLine
from core.auth.models import User
from master.models import Product

#: Service di-import di api.py → patch nama di modul itu.
SERVICE = "integrations.erp_sync.api.MaterialReadinessService"
LINE_KEYS = {
    "order_line_id",
    "product_code",
    "required_qty",
    "received_qty",
    "shortage_qty",
    "status",
    "expected_date",
    "last_computed_at",
    "vendor_bill_status",
    "vendor_bill_ids",
    "vendor_bill_amount",
}


class OrderReadinessApiTests(TestCase):
    """1 order (2 line: 1 READY, 1 WAITING) + line tambahan dibuat per test."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="supervisor", password="rahasia")
        cls.product = Product.objects.create(code="FG-API-1", name="Kaos API")
        cls.order = Order.objects.create(code="ORD-API-1")
        cls.line_ready = OrderLine.objects.create(
            order=cls.order, product=cls.product, qty=4
        )
        cls.line_waiting = OrderLine.objects.create(
            order=cls.order, product=cls.product, qty=2
        )
        MaterialReadiness.objects.create(
            order_line=cls.line_ready,
            required_qty=10.0,
            received_qty=10.0,
            shortage_qty=0.0,
            status=MaterialReadiness.Status.READY,
            expected_date=date(2026, 10, 15),
            last_computed_at=datetime(2026, 10, 6, 3, 0, tzinfo=dt_timezone.utc),
            po_ids=[12],
            po_line_ids=[23],
            vendor_bill_ids=[900, 901],
            vendor_bill_status=MaterialReadiness.VendorBillStatus.POSTED,
            vendor_bill_amount=150.0,
        )
        MaterialReadiness.objects.create(
            order_line=cls.line_waiting,
            required_qty=5.0,
            received_qty=0.0,
            shortage_qty=5.0,
            status=MaterialReadiness.Status.WAITING,
        )

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(user=self.user)

    # ------------------------------------------------------------------ helper
    @staticmethod
    def url(order_id, action="readiness"):
        """URL kontrak (lihat config/urls.py section kontrak core)."""
        return f"/api/v1/garmen/orders/{order_id}/{action}/"

    @staticmethod
    def line_of(body, order_line):
        """Ambil payload satu OrderLine dari response GET."""
        return next(
            line for line in body["lines"] if line["order_line_id"] == order_line.pk
        )

    # --------------------------------------------------------------- GET (baca)
    def test_get_happy_path_struktur_response(self):
        response = self.api.get(self.url(self.order.pk))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["order_id"], self.order.pk)
        self.assertEqual(len(body["lines"]), 2)

        ready = self.line_of(body, self.line_ready)
        self.assertEqual(set(ready), LINE_KEYS)
        self.assertEqual(ready["product_code"], "FG-API-1")
        self.assertEqual(ready["required_qty"], 10.0)
        self.assertEqual(ready["received_qty"], 10.0)
        self.assertEqual(ready["shortage_qty"], 0.0)
        self.assertEqual(ready["status"], "READY")
        self.assertEqual(ready["expected_date"], "2026-10-15")
        self.assertTrue(ready["last_computed_at"].startswith("2026-10-06T03:00:00"))
        # Agregat vendor bill (I6) ikut terekspos ke API.
        self.assertEqual(ready["vendor_bill_status"], "POSTED")
        self.assertEqual(ready["vendor_bill_ids"], [900, 901])
        self.assertEqual(ready["vendor_bill_amount"], 150.0)

        waiting = self.line_of(body, self.line_waiting)
        self.assertEqual(waiting["status"], "WAITING")
        self.assertEqual(waiting["shortage_qty"], 5.0)
        self.assertIsNone(waiting["expected_date"])
        self.assertIsNone(waiting["last_computed_at"])
        # Belum ada vendor bill → nilai default model (bukan None).
        self.assertEqual(waiting["vendor_bill_status"], "NONE")
        self.assertEqual(waiting["vendor_bill_ids"], [])
        self.assertEqual(waiting["vendor_bill_amount"], 0.0)

    def test_get_order_tidak_ada_404(self):
        response = self.api.get(self.url(999_999))

        self.assertEqual(response.status_code, 404)

    def test_get_tanpa_auth_403(self):
        response = APIClient().get(self.url(self.order.pk))

        self.assertEqual(response.status_code, 403)

    def test_get_line_tanpa_readiness_mengembalikan_null(self):
        line_baru = OrderLine.objects.create(
            order=self.order, product=self.product, qty=1
        )

        body = self.api.get(self.url(self.order.pk)).json()

        self.assertEqual(len(body["lines"]), 3)
        payload = self.line_of(body, line_baru)
        self.assertIsNone(payload["status"])
        self.assertIsNone(payload["required_qty"])
        self.assertIsNone(payload["shortage_qty"])
        self.assertIsNone(payload["last_computed_at"])
        # Line tanpa readiness → 3 kunci vendor bill juga None (bukan default).
        self.assertIsNone(payload["vendor_bill_status"])
        self.assertIsNone(payload["vendor_bill_ids"])
        self.assertIsNone(payload["vendor_bill_amount"])
        self.assertEqual(payload["product_code"], "FG-API-1")

    # ------------------------------------------------------- POST (recompute)
    def test_post_recompute_hanya_line_belum_ready(self):
        service = MagicMock()
        service.compute_batch.return_value = {
            "processed": 1,
            "waiting": 1,
            "partial": 0,
            "ready": 0,
            "errors": 0,
        }

        with patch(SERVICE, return_value=service):
            response = self.api.post(self.url(self.order.pk, "recompute-readiness"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"processed": 1, "waiting": 1, "partial": 0, "ready": 0, "errors": 0},
        )
        # HANYA line WAITING yang dikirim (line READY tidak dihitung ulang).
        queryset = service.compute_batch.call_args.args[0]
        self.assertEqual(
            list(queryset.values_list("pk", flat=True)), [self.line_waiting.pk]
        )

    def test_post_recompute_termasuk_line_tanpa_readiness(self):
        line_baru = OrderLine.objects.create(
            order=self.order, product=self.product, qty=1
        )
        service = MagicMock()
        service.compute_batch.return_value = {
            "processed": 2,
            "waiting": 1,
            "partial": 0,
            "ready": 1,
            "errors": 0,
        }

        with patch(SERVICE, return_value=service):
            response = self.api.post(self.url(self.order.pk, "recompute-readiness"))

        self.assertEqual(response.status_code, 200)
        # "belum punya readiness" harus IKUT (bukan cuma status != READY).
        pks = sorted(
            service.compute_batch.call_args.args[0].values_list("pk", flat=True)
        )
        self.assertEqual(pks, sorted([self.line_waiting.pk, line_baru.pk]))

    def test_post_order_tidak_ada_404_tanpa_panggil_service(self):
        service = MagicMock()

        with patch(SERVICE, return_value=service):
            response = self.api.post(self.url(999_999, "recompute-readiness"))

        self.assertEqual(response.status_code, 404)
        service.compute_batch.assert_not_called()

    def test_post_tanpa_auth_403(self):
        response = APIClient().post(self.url(self.order.pk, "recompute-readiness"))

        self.assertEqual(response.status_code, 403)
