"""Test model master minimal — happy path `create` + `__str__`.

6 model mirror Odoo (Fase 1): ``UoM``, ``Location``, ``Warehouse``, ``Tax``,
``Journal``, ``Currency`` — memakai pola ``Product`` (Meta, ``__str__``,
``ordering=("code",)``) dan field minimal ``odoo_id``/``code``/``name``/``is_active``.
"""

from __future__ import annotations

from django.test import TestCase

from master.models import BOM, BOMLine, Currency, Journal, Location, Product, Tax, UoM, Warehouse


class MasterMinimalModelsTests(TestCase):
    """Satu happy path (create + str) per model."""

    def test_uom_create_dan_str(self):
        obj = UoM.objects.create(odoo_id=33, code="PCS", name="Pieces")

        self.assertEqual(obj.name, "Pieces")
        self.assertTrue(obj.is_active)  # default True
        self.assertEqual(str(obj), "PCS - Pieces")

    def test_location_create_dan_str(self):
        obj = Location.objects.create(odoo_id=53, code="WH/WIP", name="WIP")

        self.assertEqual(obj.name, "WIP")
        self.assertTrue(obj.is_active)
        self.assertEqual(str(obj), "WH/WIP - WIP")

    def test_warehouse_create_dan_str(self):
        obj = Warehouse.objects.create(odoo_id=1, code="WH", name="YourCompany")

        self.assertEqual(obj.name, "YourCompany")
        self.assertTrue(obj.is_active)
        self.assertEqual(str(obj), "WH - YourCompany")

    def test_tax_create_dan_str(self):
        obj = Tax.objects.create(odoo_id=5, code="PPN11", name="PPN 11%")

        self.assertEqual(obj.name, "PPN 11%")
        self.assertTrue(obj.is_active)
        self.assertEqual(str(obj), "PPN11 - PPN 11%")

    def test_journal_create_dan_str(self):
        obj = Journal.objects.create(odoo_id=7, code="SALE", name="Sales Journal")

        self.assertEqual(obj.name, "Sales Journal")
        self.assertTrue(obj.is_active)
        self.assertEqual(str(obj), "SALE - Sales Journal")

    def test_currency_create_dan_str(self):
        obj = Currency.objects.create(odoo_id=12, code="IDR", name="Rupiah")

        self.assertEqual(obj.name, "Rupiah")
        self.assertTrue(obj.is_active)
        self.assertEqual(str(obj), "IDR - Rupiah")


class BOMLineModelTests(TestCase):
    """`BOMLine`: create, `__str__`, dan relasi FK ke `BOM` + `Product`."""

    def setUp(self):
        self.product = Product.objects.create(
            code="KTS-EXPORT-L", name="Kaos Export L", odoo_id=100
        )
        self.material = Product.objects.create(
            code="KAIN-COTTON-30S", name="Kain Cotton 30s", odoo_id=99
        )
        self.bom = BOM.objects.create(
            odoo_id=7, product=self.product, code="BOM-KTS-L", name="BOM Kaos L"
        )

    def test_bomline_create(self):
        line = BOMLine.objects.create(
            odoo_id=70, bom=self.bom, product=self.material, product_qty=1.5
        )

        self.assertEqual(line.product_qty, 1.5)
        self.assertTrue(line.is_active)  # default True
        self.assertEqual(line.code, "")  # default ""
        self.assertEqual(line.product, self.material)

    def test_bomline_str(self):
        line = BOMLine.objects.create(bom=self.bom, product=self.material, product_qty=2)

        self.assertEqual(str(line), "BOM-KTS-L - KAIN-COTTON-30S")

    def test_bomline_fk_ke_bom_dan_product(self):
        line = BOMLine.objects.create(bom=self.bom, product=self.material, product_qty=3)

        # related_name: BOM.lines & Product.bom_lines
        self.assertIn(line, self.bom.lines.all())
        self.assertIn(line, self.material.bom_lines.all())

        # product null diperbolehkan (SET_NULL) untuk bahan yang belum tersinkron.
        line.product = None
        line.save()
        line.refresh_from_db()
        self.assertIsNone(line.product)


class BOMModelTests(TestCase):
    """`BOM.product` nullable — BOM tetap valid kalau produk belum tersinkron."""

    def test_bom_product_none_tetap_valid(self):
        bom = BOM.objects.create(
            odoo_id=7, product=None, code="BOM-KTS-L", name="BOM Kaos L"
        )

        self.assertIsNone(bom.product)
        self.assertEqual(str(bom), "BOM-KTS-L - BOM Kaos L")

    def test_bom_str_tanpa_product_dan_nama(self):
        bom = BOM.objects.create(odoo_id=8, product=None, code="BOM-X", name="")

        self.assertEqual(str(bom), "BOM-X - ")


class ProductOdooTmplIdTests(TestCase):
    """`Product.odoo_tmpl_id` boleh duplikat — varian berbagi template yang sama."""

    def test_dua_product_odoo_tmpl_id_sama_tetap_valid(self):
        first = Product.objects.create(
            code="KTS-EXPORT-L", name="Kaos Export L", odoo_id=100, odoo_tmpl_id=10
        )
        second = Product.objects.create(
            code="KTS-EXPORT-M", name="Kaos Export M", odoo_id=101, odoo_tmpl_id=10
        )

        self.assertEqual(first.odoo_tmpl_id, 10)
        self.assertEqual(second.odoo_tmpl_id, 10)
        self.assertEqual(Product.objects.filter(odoo_tmpl_id=10).count(), 2)
