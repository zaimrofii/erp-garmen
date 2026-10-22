"""Regresi invariant data (Fase 0-cepat 2026-10-22).

Menguji `integrations.ai_agent.data_access.invariants`:
  B. produk di orderline harga <= 0 / NULL
  C. order tanpa orderline
  D. orderline tanpa product_id
  E. orderline qty <= 0

Plus smoke test bahwa seed (yang kini memanggil `assert_clean`) tetap lolos.
"""

from __future__ import annotations

from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps_industry.garment.models import Order, OrderLine
from integrations.ai_agent.data_access import invariants
from master.models import Partner, Product


class InvariantCheckerTests(TestCase):
    def _clean_order(self):
        partner = Partner.objects.create(
            code="C-INV", name="Customer Invariant", is_customer=True
        )
        product = Product.objects.create(
            code="P-INV", name="Produk Invariant", sale_price=Decimal("50000")
        )
        order = Order.objects.create(code="S-INV-1", customer=partner, state="DRAFT")
        OrderLine.objects.create(
            order=order, product=product, qty=1, price_unit=Decimal("50000")
        )
        return order, product

    def test_clean_dataset_tidak_punya_pelanggaran(self):
        self._clean_order()
        violations = invariants.collect_violations()
        for key in ("B", "C", "D", "E"):
            self.assertEqual(violations[key]["count"], 0, violations[key])
        invariants.assert_clean("test_clean")  # tidak raise

    def test_produk_harga_nol_di_orderline_terdeteksi(self):
        _order, product = self._clean_order()
        Product.objects.filter(pk=product.pk).update(sale_price=Decimal("0"))
        violations = invariants.collect_violations()
        self.assertEqual(violations["B"]["count"], 1)
        self.assertEqual(violations["B"]["sample"][0]["code"], "P-INV")
        with self.assertRaises(CommandError):
            invariants.assert_clean("test_zero_price")

    def test_orderline_tanpa_product_terdeteksi(self):
        order, _product = self._clean_order()
        OrderLine.objects.create(
            order=order, product=None, qty=2, price_unit=Decimal("10")
        )
        violations = invariants.collect_violations()
        self.assertEqual(violations["D"]["count"], 1)
        with self.assertRaises(CommandError):
            invariants.assert_clean("test_null_product")

    def test_order_tanpa_orderline_terdeteksi(self):
        partner = Partner.objects.create(
            code="C-INV2", name="Customer Tanpa Line", is_customer=True
        )
        Order.objects.create(code="S-INV-2", customer=partner, state="DRAFT")
        violations = invariants.collect_violations()
        self.assertEqual(violations["C"]["count"], 1)

    def test_orderline_qty_nol_terdeteksi(self):
        order, product = self._clean_order()
        OrderLine.objects.create(
            order=order, product=product, qty=0, price_unit=Decimal("1")
        )
        violations = invariants.collect_violations()
        self.assertEqual(violations["E"]["count"], 1)


class SeedGuardTests(TestCase):
    """Seed wajib lolos guard-nya sendiri (kalau tidak, seed memang rusak)."""

    def test_seed_demo_llm_lolos_guard(self):
        call_command("seed_demo_llm", stdout=StringIO())
        violations = invariants.collect_violations()
        for key in ("B", "C", "D", "E"):
            self.assertEqual(violations[key]["count"], 0, violations[key])

    def test_seed_rich_garment_lolos_guard(self):
        call_command("seed_rich_garment", stdout=StringIO())
        violations = invariants.collect_violations()
        for key in ("B", "C", "D", "E"):
            self.assertEqual(violations[key]["count"], 0, violations[key])
