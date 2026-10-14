"""Test ``CouponGenerator`` (kupon piece-rate) — Fase 5."""

from __future__ import annotations

from django.test import TestCase

from apps_industry.garment.tests.factories import make_order, make_order_line
from integrations.printing.coupon import CouponError, CouponGenerator


class CouponGeneratorTests(TestCase):
    """Layout kupon + penolakan kupon tanpa kode."""

    def setUp(self):
        self.order = make_order(code="SO-DEMO-1")
        self.order_line = make_order_line(
            order=self.order,
            ticket_code="TKT-0001",
            tag="FAST_TRACK",
            qty=25,
        )

    def test_render_memuat_header_dan_kode_kupon(self):
        data = CouponGenerator(self.order_line).render()

        self.assertIn(b"KUPON", data)
        self.assertIn(b"TKT-0001", data)

    def test_render_memuat_tag_qty_dan_order(self):
        data = CouponGenerator(self.order_line).render()

        self.assertIn(b"Tag: FAST_TRACK", data)
        self.assertIn(b"Qty: 25", data)
        self.assertIn(b"Order: SO-DEMO-1", data)

    def test_render_diakhiri_feed_dan_cut(self):
        data = CouponGenerator(self.order_line).render()

        self.assertTrue(data.endswith(b"\x1bd\x02\x1dV\x00"))

    def test_ticket_code_kosong_raise_coupon_error(self):
        line = make_order_line(order=self.order, tag="EXPORT", qty=5)

        with self.assertRaisesMessage(CouponError, "ticket_code"):
            CouponGenerator(line).render()

    def test_ticket_code_hanya_spasi_raise_coupon_error(self):
        line = make_order_line(order=self.order, ticket_code="   ", tag="EXPORT", qty=5)

        with self.assertRaises(CouponError):
            CouponGenerator(line).render()

    def test_coupon_error_adalah_value_error(self):
        self.assertTrue(issubclass(CouponError, ValueError))

    def test_tag_kosong_ditampilkan_sebagai_strip(self):
        line = make_order_line(order=self.order, ticket_code="TKT-0002", tag="", qty=3)

        data = CouponGenerator(line).render()

        self.assertIn(b"Tag: -", data)
