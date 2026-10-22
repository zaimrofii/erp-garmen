"""Regresi Fase 4.1 — filter produk, agregat harga, dan bundle tanpa event."""

from __future__ import annotations

from django.test import TestCase

from apps_industry.garment.models import Bundle, Order, OrderLine, WorkOrder
from core.auth.models import Role, User
from integrations.ai_agent.orchestrator.context_builder import build_context
from master.models import Product


class Fase41FixTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.products = {}
        for code, name, price, category in (
            ("F41-ZERO", "Zero Product", 0, ""),
            ("F41-LOW", "Low Product", 25000, "Kaos"),
            ("F41-MID", "Mid Product", 50000, "Kaos"),
            ("F41-HIGH", "High Product", 100000, "Jaket"),
            ("F41-TOP", "Top Product", 250000, "Jaket"),
        ):
            cls.products[code] = Product.objects.create(
                code=code,
                name=name,
                sale_price=price,
                cost_price=price,
                category=category,
            )
        order = Order.objects.create(code="F41-ORD")
        line = OrderLine.objects.create(
            order=order,
            product=cls.products["F41-MID"],
            qty=20,
            price_unit=50000,
        )
        wo = WorkOrder.objects.create(
            code="F41-WO", order_line=line, qty_planned=20
        )
        cls.bundle = Bundle.objects.create(
            code="F41-BND-NOEVENT",
            work_order=wo,
            qty=20,
            qty_done=20,
            state="DONE",
        )
        cls.owner = User.objects.filter(role__code="OWNER").first() or User.objects.create_user(
            username="f41-owner",
            password="x",
            role=Role.objects.get(code=Role.Code.OWNER),
        )

    def context(self, message: str) -> dict:
        return build_context(
            "DATA_LOOKUP", ["mcp-postgres-query"], message, {}, user=self.owner
        )

    def test_produk_harga_0_filter(self):
        data = self.context("produk harga 0?")
        self.assertEqual(data["product_filter_label"], "harga 0")
        self.assertEqual(
            [row["name"] for row in data["products"]], ["Zero Product"]
        )

    def test_produk_tanpa_kategori_filter(self):
        data = self.context("produk tanpa kategori?")
        self.assertEqual(data["product_filter_label"], "tanpa kategori")
        self.assertEqual(
            [row["name"] for row in data["products"]], ["Zero Product"]
        )

    def test_produk_di_atas_100rb_filter(self):
        data = self.context("produk di atas 100rb?")
        self.assertEqual(
            [row["name"] for row in data["products"]], ["Top Product"]
        )

    def test_produk_di_bawah_50rb_filter(self):
        data = self.context("produk di bawah 50rb?")
        self.assertEqual(
            sorted(row["name"] for row in data["products"]),
            ["Low Product", "Zero Product"],
        )

    def test_rata_rata_harga(self):
        data = self.context("rata-rata harga produk?")
        self.assertEqual(data["price_aggregate"]["value"], 85000.0)

    def test_harga_tertinggi(self):
        data = self.context("harga tertinggi produk?")
        self.assertEqual(data["price_aggregate"]["value"], 250000.0)

    def test_total_nilai_produk(self):
        data = self.context("total nilai semua produk?")
        self.assertEqual(data["price_aggregate"]["value"], 425000.0)

    def test_bundle_tanpa_event(self):
        data = self.context("bundle tanpa event?")
        self.assertEqual(
            [row["code"] for row in data["bundles"]], ["F41-BND-NOEVENT"]
        )
