"""Test model `MaterialReadiness` (I2) — kesiapan material per OrderLine.

Fokus: pembuatan + ``__str__``, kunci idempotensi OneToOne ke ``OrderLine``,
default ``status``/``shortage_qty``, CHECK ``shortage_qty >= 0``, CASCADE, dan
``Meta.ordering``.
"""

from __future__ import annotations

from datetime import timedelta

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from apps_industry.garment.models import MaterialReadiness, Order, OrderLine
from master.models import Partner, Product


class MaterialReadinessTests(TestCase):
    """Data minimum: partner/product (master) -> order -> line -> readiness."""

    @classmethod
    def setUpTestData(cls):
        cls.customer = Partner.objects.create(code="CUST-MR", name="PT Klien MR")
        cls.product = Product.objects.create(code="TS-MR-001", name="Kaos Material")
        cls.order = Order.objects.create(code="ORD-MR-0001", customer=cls.customer)
        cls.line = OrderLine.objects.create(
            order=cls.order, product=cls.product, tag="FAST_TRACK", qty=100
        )

    def test_create_dan_str(self):
        readiness = MaterialReadiness.objects.create(
            order_line=self.line, required_qty=12.5
        )
        # Ambil representasi dari DB: FloatField kembali sebagai float (0.0),
        # sedangkan default int di memori akan tampil "0".
        readiness.refresh_from_db()

        self.assertEqual(str(readiness), "ORD-MR-0001/TS-MR-001 x100 - WAITING (0.0)")
        # related_name 'readiness' = akses balik dari OrderLine.
        self.assertEqual(self.line.readiness, readiness)

    def test_str_ikut_status_dan_shortage(self):
        readiness = MaterialReadiness.objects.create(
            order_line=self.line,
            required_qty=100,
            received_qty=40,
            shortage_qty=60,
            status=MaterialReadiness.Status.PARTIAL,
        )
        readiness.refresh_from_db()

        self.assertEqual(str(readiness), "ORD-MR-0001/TS-MR-001 x100 - PARTIAL (60.0)")

    def test_satu_readiness_per_order_line(self):
        MaterialReadiness.objects.create(order_line=self.line)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MaterialReadiness.objects.create(order_line=self.line)

    def test_status_default_waiting(self):
        readiness = MaterialReadiness.objects.create(order_line=self.line)

        self.assertEqual(readiness.status, "WAITING")
        self.assertEqual(readiness.status, MaterialReadiness.Status.WAITING)

    def test_shortage_qty_default_nol(self):
        readiness = MaterialReadiness.objects.create(order_line=self.line)

        self.assertEqual(readiness.shortage_qty, 0)
        self.assertEqual(readiness.required_qty, 0)
        self.assertEqual(readiness.received_qty, 0)

    def test_field_opsional_default_kosong(self):
        readiness = MaterialReadiness.objects.create(order_line=self.line)

        self.assertIsNone(readiness.expected_date)
        self.assertIsNone(readiness.last_computed_at)
        self.assertEqual(readiness.po_ids, [])
        self.assertEqual(readiness.po_line_ids, [])

    def test_shortage_negatif_ditolak_constraint(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MaterialReadiness.objects.create(order_line=self.line, shortage_qty=-1)

    def test_ikut_terhapus_kalau_order_line_dihapus(self):
        MaterialReadiness.objects.create(order_line=self.line)

        self.line.delete()

        self.assertEqual(MaterialReadiness.objects.count(), 0)

    def test_ordering_last_computed_terbaru_dulu(self):
        line_a = OrderLine.objects.create(order=self.order, product=self.product, qty=1)
        line_b = OrderLine.objects.create(order=self.order, product=self.product, qty=2)
        lama = MaterialReadiness.objects.create(
            order_line=line_a, last_computed_at=timezone.now() - timedelta(hours=1)
        )
        terbaru = MaterialReadiness.objects.create(
            order_line=line_b, last_computed_at=timezone.now()
        )

        self.assertEqual(list(MaterialReadiness.objects.all()), [terbaru, lama])
