"""Test Fix #16 — seed ODOO-64, dedup kandidat, resolver ordinal lengkap."""

from __future__ import annotations

from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from integrations.ai_agent.clarification import resolver
from integrations.ai_agent.clarification.resolver import ResolutionType
from integrations.ai_agent.demo_products import (
    DEMO_POLOS_PRODUCTS,
    ensure_demo_polos_products,
)
from integrations.ai_agent.orchestrator import context_builder
from integrations.ai_agent.orchestrator.text_normalizer import normalize
from master.models import Product


def _product_row(row_id: int, name: str, price: str) -> dict:
    return {
        "id": row_id,
        "code": f"ODOO-{60 + row_id}",
        "name": name,
        "sale_price": price,
        "category": "Kaos",
    }


class SeedOdoo64Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_demo_polos_products()

    def test_odoo64_punya_nama_harga_kategori(self):
        product = Product.objects.get(code="ODOO-64")

        self.assertEqual(product.name, "Kaos Polos Basic")
        self.assertEqual(product.sale_price, Decimal("40000"))
        self.assertEqual(product.category, "Kaos")

    def test_odoo64_nama_unik(self):
        names = list(
            Product.objects.filter(
                code__in=[spec[0] for spec in DEMO_POLOS_PRODUCTS]
            ).values_list("name", flat=True)
        )

        self.assertEqual(len(names), 6)
        self.assertEqual(len(set(names)), 6)


class DedupCandidateTests(SimpleTestCase):
    def _candidates(self):
        rows = [
            _product_row(1, "Kaos Polos Basic", "40000"),
            _product_row(2, "Kaos Polos Basic", "40000"),  # duplikat
            _product_row(3, "Kaos Polos Premium", "75000"),
            _product_row(4, "Kaos Polos Anak", "35000"),
            _product_row(5, "Kaos Polos Lengan Panjang", "60000"),
        ]
        return context_builder._collect_candidates(
            normalize("produk kaos polos"), {"product_list": rows}
        )

    def test_duplikat_dibuang(self):
        candidates, entity = self._candidates()

        self.assertEqual(entity, "product")
        self.assertEqual(len(candidates), 4)

    def test_label_dan_harga_unik(self):
        candidates, _entity = self._candidates()
        keys = {
            (candidate["label"], candidate["attrs"]["harga"])
            for candidate in candidates
        }

        self.assertEqual(len(keys), len(candidates))


class OrdinalResolverTests(SimpleTestCase):
    CANDIDATES = [
        {"id": index, "label": f"Kaos {index}", "attrs": {}, "score": 0.7}
        for index in range(1, 6)
    ]

    def _resolve(self, message: str):
        return resolver.resolve(message, self.CANDIDATES)

    def test_yang_ke_4(self):
        result = self._resolve("yang ke 4")

        self.assertEqual(result.type, ResolutionType.RANK)
        self.assertEqual(result.candidate["id"], 4)

    def test_ke_4_tanpa_yang(self):
        result = self._resolve("ke 4")

        self.assertEqual(result.type, ResolutionType.RANK)
        self.assertEqual(result.candidate["id"], 4)

    def test_keempat(self):
        result = self._resolve("keempat")

        self.assertEqual(result.type, ResolutionType.RANK)
        self.assertEqual(result.candidate["id"], 4)

    def test_angka_4(self):
        result = self._resolve("4")

        self.assertEqual(result.type, ResolutionType.RANK)
        self.assertEqual(result.candidate["id"], 4)

    def test_yg_keempat(self):
        result = self._resolve("yg keempat")

        self.assertEqual(result.type, ResolutionType.RANK)
        self.assertEqual(result.candidate["id"], 4)

    def test_nomor_4(self):
        result = self._resolve("nomor 4")

        self.assertEqual(result.type, ResolutionType.RANK)
        self.assertEqual(result.candidate["id"], 4)

    def test_yang_keempat(self):
        result = self._resolve("yang keempat")

        self.assertEqual(result.type, ResolutionType.RANK)
        self.assertEqual(result.candidate["id"], 4)

    def test_yg_ke_4(self):
        result = self._resolve("yg ke 4")

        self.assertEqual(result.type, ResolutionType.RANK)
        self.assertEqual(result.candidate["id"], 4)
