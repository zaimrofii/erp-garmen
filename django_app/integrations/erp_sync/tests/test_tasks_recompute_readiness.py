"""Test task `erp_sync.recompute_readiness` (konsolidasi I3.4 + I6.3 → I7).

Cakupan: happy path (return counter ``compute_batch``), cakupan OrderLine yang
dikirim = **hanya yang belum READY** (READY dibuang; WAITING/PARTIAL/baris tanpa
readiness ikut), helper ``_order_lines_to_recompute``, registrasi nama task
(pengganti ``erp_sync.compute_readiness`` + ``erp_sync.sync_vendor_bills``), dan
retry yang hanya terpicu error transport (``httpx.HTTPError``/``ConnectionError``).

Catatan: ``TestCase`` (bukan ``SimpleTestCase``) karena task ini menyentuh DB
(``OrderLine.objects.exclude(...)`` + ``count()`` untuk log) — pola sama dengan
``test_tasks_invoice.py``/``test_tasks_scrap.py``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
from django.test import TestCase

from apps_industry.garment.models import MaterialReadiness, Order, OrderLine
from integrations.erp_sync import tasks_vendor_bill
from integrations.erp_sync.tasks_vendor_bill import (
    _order_lines_to_recompute,
    recompute_readiness,
)
from master.models import Product

SERVICE = "integrations.erp_sync.tasks_vendor_bill.MaterialReadinessService"
RESULT = {"processed": 3, "waiting": 1, "partial": 1, "ready": 1, "errors": 0}


class RecomputeReadinessTaskTests(TestCase):
    """4 OrderLine: READY (dibuang) + WAITING + PARTIAL + tanpa readiness (ikut)."""

    @classmethod
    def setUpTestData(cls):
        cls.product = Product.objects.create(code="TS-READY-1", name="Kaos Task")
        order = Order.objects.create(code="ORD-READY-1")
        cls.line_ready = OrderLine.objects.create(order=order, product=cls.product, qty=1)
        cls.line_waiting = OrderLine.objects.create(
            order=order, product=cls.product, qty=2
        )
        cls.line_partial = OrderLine.objects.create(
            order=order, product=cls.product, qty=3
        )
        cls.line_tanpa_readiness = OrderLine.objects.create(
            order=order, product=cls.product, qty=4
        )
        MaterialReadiness.objects.create(
            order_line=cls.line_ready,
            required_qty=1.0,
            received_qty=1.0,
            shortage_qty=0.0,
            status=MaterialReadiness.Status.READY,
        )
        MaterialReadiness.objects.create(
            order_line=cls.line_waiting,
            required_qty=5.0,
            received_qty=0.0,
            shortage_qty=5.0,
            status=MaterialReadiness.Status.WAITING,
        )
        MaterialReadiness.objects.create(
            order_line=cls.line_partial,
            required_qty=5.0,
            received_qty=2.0,
            shortage_qty=3.0,
            status=MaterialReadiness.Status.PARTIAL,
        )

    def run_task(self, service_result=RESULT):
        """Jalankan task dengan service di-patch; return (hasil, mock service)."""
        service = MagicMock()
        service.compute_batch.return_value = service_result
        with patch(SERVICE, return_value=service):
            result = recompute_readiness.apply().get()
        return result, service

    def queryset_dikirim(self, service):
        """QuerySet OrderLine yang diterima ``compute_batch``."""
        return service.compute_batch.call_args.args[0]

    # ------------------------------------------------------------------ tests
    def test_happy_path_mengembalikan_counter_service(self):
        result, service = self.run_task()

        self.assertEqual(result, RESULT)
        service.compute_batch.assert_called_once()

    def test_hanya_order_line_belum_ready_yang_dikirim(self):
        _, service = self.run_task()

        queryset = self.queryset_dikirim(service)
        # QuerySet OrderLine (lazy), bukan list hasil evaluasi.
        self.assertIs(queryset.model, OrderLine)
        self.assertEqual(
            sorted(queryset.values_list("pk", flat=True)),
            sorted(
                [
                    self.line_waiting.pk,
                    self.line_partial.pk,
                    self.line_tanpa_readiness.pk,
                ]
            ),
        )

    def test_line_ready_tidak_dikirim(self):
        _, service = self.run_task()

        pks = set(self.queryset_dikirim(service).values_list("pk", flat=True))
        self.assertNotIn(self.line_ready.pk, pks)

    def test_helper_membuang_ready_dan_menyertakan_tanpa_readiness(self):
        pks = set(_order_lines_to_recompute().values_list("pk", flat=True))

        self.assertNotIn(self.line_ready.pk, pks)
        self.assertIn(self.line_waiting.pk, pks)
        self.assertIn(self.line_partial.pk, pks)
        # Baris TANPA readiness ikut (exclude() = subquery NOT IN, bukan LEFT JOIN).
        self.assertIn(self.line_tanpa_readiness.pk, pks)

    def test_registrasi_nama_task_konsolidasi(self):
        self.assertEqual(recompute_readiness.name, "erp_sync.recompute_readiness")
        self.assertIn("recompute_readiness", tasks_vendor_bill.__all__)
        # Nama task lama (compute_readiness & sync_vendor_bills) sudah tidak ada.
        self.assertNotIn("sync_vendor_bills", tasks_vendor_bill.__all__)
        self.assertFalse(hasattr(tasks_vendor_bill, "compute_readiness"))

    def test_error_transport_memicu_retry(self):
        # Konfigurasi retry: HANYA error transport/jaringan (impor tasks_master).
        self.assertIn(httpx.HTTPError, recompute_readiness.autoretry_for)
        self.assertIn(ConnectionError, recompute_readiness.autoretry_for)
        self.assertEqual(recompute_readiness.max_retries, 3)

        service = MagicMock()
        service.compute_batch.side_effect = httpx.ConnectError("odoo mati")

        with patch(SERVICE, return_value=service):
            with self.assertRaises(httpx.HTTPError):
                recompute_readiness.apply().get()
