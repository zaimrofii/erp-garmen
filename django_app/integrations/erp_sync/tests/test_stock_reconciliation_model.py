"""Test model `StockReconciliation` — skema & tipe kolom (Fase I7, utang I8.4).

Fokus: ``product_odoo_id`` memakai ``PositiveBigIntegerField`` (konvensi repo
untuk kolom id Odoo; dulu ``BigIntegerField`` — utang teknis I8.4). Tipe dicek
lewat introspection ``_meta.get_field(...)`` supaya perubahan tipe tertangkap
test, ditambah guard kolom lain, default, dan ordering.
"""

from __future__ import annotations

from django.db import models
from django.test import TestCase

from apps_industry.garment.models import StockReconciliation
from master.models import Product


class StockReconciliationModelTests(TestCase):
    """Skema tabel ``garment_stockreconciliation`` (I7 + perbaikan I8.4)."""

    @classmethod
    def setUpTestData(cls):
        cls.product = Product.objects.create(
            code="FG-REC-1", name="Kaos Rekon", odoo_id=701
        )

    def make(self, **kwargs):
        """Baris rekonsiliasi minimal (produk + odoo id)."""
        defaults = {"product": self.product, "product_odoo_id": 701}
        defaults.update(kwargs)
        return StockReconciliation.objects.create(**defaults)

    # ------------------------------------------------------- I8.4 (tipe kolom)
    def test_product_odoo_id_positif_big_integer(self):
        field = StockReconciliation._meta.get_field("product_odoo_id")

        self.assertIsInstance(field, models.PositiveBigIntegerField)
        self.assertEqual(field.get_internal_type(), "PositiveBigIntegerField")
        self.assertFalse(field.null)

    def test_bisa_menyimpan_odoo_id_besar(self):
        row = self.make(product_odoo_id=2**40)

        self.assertEqual(
            StockReconciliation.objects.get(pk=row.pk).product_odoo_id, 2**40
        )

    def test_kolom_lain_tidak_ikut_berubah(self):
        """Guard regresi: tipe kolom I7 lain tetap seperti semula."""
        expected = {
            "mes_qty": models.FloatField,
            "odoo_qty": models.FloatField,
            "diff": models.FloatField,
            "is_alert": models.BooleanField,
            "notes": models.TextField,
            "run_at": models.DateTimeField,
        }
        for name, jenis_kolom in expected.items():
            with self.subTest(field=name):
                self.assertIsInstance(
                    StockReconciliation._meta.get_field(name), jenis_kolom
                )

        run_at = StockReconciliation._meta.get_field("run_at")
        self.assertTrue(run_at.auto_now_add)

    def test_product_nullable_dan_protect(self):
        field = StockReconciliation._meta.get_field("product")

        self.assertTrue(field.null)
        self.assertEqual(field.remote_field.on_delete, models.PROTECT)

    # ------------------------------------------------------------------ default
    def test_default_kolom(self):
        row = self.make()

        self.assertEqual(row.mes_qty, 0)
        self.assertEqual(row.odoo_qty, 0)
        self.assertEqual(row.diff, 0)
        self.assertFalse(row.is_alert)
        self.assertEqual(row.notes, "")
        self.assertIsNotNone(row.run_at)

    def test_ordering_terbaru_dulu(self):
        self.assertEqual(StockReconciliation._meta.ordering, ("-run_at",))
