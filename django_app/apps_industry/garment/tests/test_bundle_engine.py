"""Test BundleEngine: pembagian per size, sisa, validasi, dan preview."""

from __future__ import annotations

import re

from django.test import TestCase

from apps_industry.garment.models import Bundle
from apps_industry.garment.services import BundleEngine, BundleEngineError
from apps_industry.garment.tests.factories import make_order_line, make_work_order

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class BundleEngineTests(TestCase):
    """Pembentukan bundle dari matriks ukuran."""

    @classmethod
    def setUpTestData(cls):
        cls.order_line = make_order_line(tag="FAST_TRACK", qty=10)
        cls.work_order = make_work_order(order_line=cls.order_line)

    def test_bagi_rata_per_size(self):
        bundles = BundleEngine.create_bundles(self.order_line, {"L": 10}, 5)

        self.assertEqual([bundle.qty for bundle in bundles], [5, 5])
        self.assertEqual(
            [bundle.code for bundle in bundles],
            [f"{self.order_line.id}-L-001", f"{self.order_line.id}-L-002"],
        )
        self.assertEqual(Bundle.objects.count(), 2)

    def test_bagi_dengan_sisa(self):
        bundles = BundleEngine.create_bundles(self.order_line, {"M": 7}, 5)

        self.assertEqual([bundle.qty for bundle in bundles], [5, 2])
        self.assertTrue(all(bundle.size == "M" for bundle in bundles))

    def test_seq_reset_per_size_dan_urutan_deterministik(self):
        bundles = BundleEngine.create_bundles(self.order_line, {"L": 5, "M": 3}, 5)

        self.assertEqual(
            [bundle.code for bundle in bundles],
            [f"{self.order_line.id}-L-001", f"{self.order_line.id}-M-001"],
        )
        self.assertEqual([bundle.qty for bundle in bundles], [5, 3])

    def test_size_dinormalkan_ke_huruf_besar_dan_digabung(self):
        bundles = BundleEngine.create_bundles(self.order_line, {"l": 3, "L": 2}, 5)

        self.assertEqual(len(bundles), 1)
        self.assertEqual(bundles[0].size, "L")
        self.assertEqual(bundles[0].qty, 5)

    def test_version_terisi_walau_bulk_create(self):
        bundles = BundleEngine.create_bundles(self.order_line, {"L": 4}, 5)

        self.assertEqual(len(bundles), 1)
        self.assertIsNotNone(bundles[0].pk)  # sudah tersimpan
        self.assertTrue(SHA256_RE.match(bundles[0].version))
        self.assertEqual(bundles[0].state, "DRAFT")
        self.assertEqual(bundles[0].work_order, self.work_order)

    def test_validasi_bundle_size_tidak_valid(self):
        with self.assertRaises(BundleEngineError):
            BundleEngine.create_bundles(self.order_line, {"L": 5}, 0)
        with self.assertRaises(BundleEngineError):
            BundleEngine.create_bundles(self.order_line, {"L": 5}, "lima")

    def test_validasi_size_matrix_kosong(self):
        with self.assertRaises(BundleEngineError):
            BundleEngine.create_bundles(self.order_line, {}, 5)

    def test_validasi_qty_tidak_valid(self):
        with self.assertRaises(BundleEngineError):
            BundleEngine.create_bundles(self.order_line, {"L": -1}, 5)
        with self.assertRaises(BundleEngineError):
            BundleEngine.create_bundles(self.order_line, {"L": "banyak"}, 5)

    def test_validasi_total_qty_nol(self):
        with self.assertRaises(BundleEngineError):
            BundleEngine.create_bundles(self.order_line, {"L": 0}, 5)

    def test_error_kalau_work_order_belum_ada(self):
        order_line_tanpa_wo = make_order_line(tag="EXPORT", qty=3)

        with self.assertRaises(BundleEngineError):
            BundleEngine.create_bundles(order_line_tanpa_wo, {"L": 3}, 5)

    def test_preview_tidak_menyimpan_apa_pun(self):
        plan = BundleEngine.preview_bundles(self.order_line, {"l": 7}, 5)

        self.assertEqual(
            plan,
            [
                {
                    "code": f"{self.order_line.id}-L-001",
                    "size": "L",
                    "sku_variant": "",
                    "qty": 5,
                },
                {
                    "code": f"{self.order_line.id}-L-002",
                    "size": "L",
                    "sku_variant": "",
                    "qty": 2,
                },
            ],
        )
        self.assertEqual(Bundle.objects.count(), 0)
