"""Test ``BundleTagGenerator`` (Fase 5) memakai objek domain garmen sungguhan."""

from __future__ import annotations

from django.test import TestCase

from apps_industry.garment.tests.factories import (
    make_bundle,
    make_work_center,
    make_work_order,
)
from integrations.printing.bundle_tag import BundleTagGenerator


class BundleTagGeneratorTests(TestCase):
    """Layout tag: header, QR, kode, info, barcode, cut."""

    def setUp(self):
        self.work_center = make_work_center(code="SEWING-DEMO")
        self.bundle = make_bundle(
            code="BND-DEMO-1",
            size="L",
            sku_variant="KAOS-PUTIH",
            qty=12,
            current_work_center=self.work_center,
        )
        self.data = BundleTagGenerator(self.bundle).render()

    def test_render_menghasilkan_bytes_tidak_kosong(self):
        self.assertIsInstance(self.data, bytes)
        self.assertGreater(len(self.data), 100)

    def test_memuat_kode_bundle(self):
        self.assertIn(b"BND-DEMO-1", self.data)

    def test_memuat_perintah_qr_dan_barcode(self):
        self.assertIn(b"\x1d(k", self.data)  # QR (GS ( k)
        self.assertIn(b"\x1dk\x49", self.data)  # barcode CODE128 (GS k 73)

    def test_memuat_header_dan_info_bundle(self):
        self.assertIn(b"BUNDLE TAG", self.data)
        self.assertIn(b"Size: L | SKU: KAOS-PUTIH", self.data)
        self.assertIn(b"Qty: 12", self.data)
        self.assertIn(b"Dicetak: ", self.data)

    def test_memuat_work_order_dan_work_center(self):
        self.assertIn(
            f"Work Order: {self.bundle.work_order.code}".encode(), self.data
        )
        self.assertIn(b"WC: SEWING-DEMO", self.data)

    def test_work_order_bisa_di_override(self):
        work_order = make_work_order(code="WO-LAIN")

        data = BundleTagGenerator(self.bundle, work_order=work_order).render()

        self.assertIn(b"Work Order: WO-LAIN", data)

    def test_bundle_tanpa_work_center_tidak_error(self):
        bundle = make_bundle(code="BND-DEMO-2", size="M", qty=5)

        data = BundleTagGenerator(bundle).render()

        self.assertIn(b"BND-DEMO-2", data)
        self.assertNotIn(b"WC:", data)

    def test_diakhiri_feed_dua_baris_dan_cut(self):
        self.assertTrue(self.data.endswith(b"\x1bd\x02\x1dV\x00"))

    def test_render_ulang_tetap_valid(self):
        ulang = BundleTagGenerator(self.bundle).render()

        self.assertIn(b"BND-DEMO-1", ulang)
        self.assertTrue(ulang.endswith(b"\x1dV\x00"))
