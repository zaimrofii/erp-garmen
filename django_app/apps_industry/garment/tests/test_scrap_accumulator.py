"""Test ScrapAccumulatorService: akumulasi scrap/rework/end-loss + ringkasan."""

from __future__ import annotations

from django.test import TestCase

from apps_industry.garment.models import ScrapAccumulator
from apps_industry.garment.services import (
    ScrapAccumulatorError,
    ScrapAccumulatorService,
)
from apps_industry.garment.tests.factories import make_bundle, make_work_center


class ScrapAccumulatorServiceTests(TestCase):
    """Akumulasi per (work_center, bundle)."""

    @classmethod
    def setUpTestData(cls):
        cls.wc_sewing = make_work_center(code="SEWING-1")
        cls.wc_qc = make_work_center(code="QC-1")
        cls.bundle = make_bundle(code="BND-001")
        cls.bundle_lain = make_bundle(code="BND-002")

    def setUp(self):
        self.service = ScrapAccumulatorService()

    def test_record_scrap_membuat_baris_baru(self):
        row = self.service.record_scrap(
            self.bundle, self.wc_sewing, 3, reason="kain sobek"
        )

        self.assertEqual(row.qty, 3)
        self.assertEqual(row.rework_qty, 0)
        self.assertEqual(row.end_loss_qty, 0)
        self.assertEqual(row.reason, "kain sobek")
        self.assertEqual(ScrapAccumulator.objects.count(), 1)

    def test_record_scrap_mengakumulasi_baris_yang_sama(self):
        self.service.record_scrap(self.bundle, self.wc_sewing, 3)

        row = self.service.record_scrap(self.bundle, self.wc_sewing, 2)

        self.assertEqual(row.qty, 5)
        self.assertEqual(ScrapAccumulator.objects.count(), 1)

    def test_record_rework_dan_end_loss_terpisah_per_field(self):
        self.service.record_rework(self.bundle, self.wc_sewing, 4)

        row = self.service.record_end_loss(
            self.bundle, self.wc_sewing, 2, reason="sisa potongan"
        )

        self.assertEqual(row.qty, 0)
        self.assertEqual(row.rework_qty, 4)
        self.assertEqual(row.end_loss_qty, 2)
        self.assertEqual(row.reason, "sisa potongan")
        self.assertEqual(ScrapAccumulator.objects.count(), 1)

    def test_work_center_berbeda_membuat_baris_terpisah(self):
        self.service.record_scrap(self.bundle, self.wc_sewing, 3)
        self.service.record_scrap(self.bundle, self.wc_qc, 2)

        self.assertEqual(ScrapAccumulator.objects.count(), 2)

    def test_get_bundle_scrap(self):
        self.assertIsNone(self.service.get_bundle_scrap(self.bundle))

        self.service.record_scrap(self.bundle, self.wc_sewing, 1)

        self.assertEqual(self.service.get_bundle_scrap(self.bundle).qty, 1)

    def test_get_summary(self):
        self.service.record_scrap(self.bundle, self.wc_sewing, 3)
        self.service.record_scrap(self.bundle_lain, self.wc_sewing, 2)
        self.service.record_rework(self.bundle, self.wc_sewing, 1)
        self.service.record_end_loss(self.bundle_lain, self.wc_sewing, 1)

        summary = self.service.get_summary(self.wc_sewing)

        self.assertEqual(summary["work_center"], "SEWING-1")
        self.assertEqual(summary["total_qty"], 5)
        self.assertEqual(summary["total_rework_qty"], 1)
        self.assertEqual(summary["total_end_loss_qty"], 1)
        self.assertEqual(summary["bundle_count"], 2)
        self.assertEqual(summary["entries"], 2)

    def test_get_summary_tanpa_data(self):
        summary = self.service.get_summary(self.wc_qc)

        self.assertEqual(summary["total_qty"], 0)
        self.assertEqual(summary["total_rework_qty"], 0)
        self.assertEqual(summary["bundle_count"], 0)
        self.assertEqual(summary["entries"], 0)

    def test_get_top_scrap_work_centers(self):
        self.service.record_scrap(self.bundle, self.wc_sewing, 5)
        self.service.record_scrap(self.bundle, self.wc_qc, 9)

        top = self.service.get_top_scrap_work_centers(limit=1)

        self.assertEqual(len(top), 1)
        self.assertEqual(top[0]["work_center"], "QC-1")
        self.assertEqual(top[0]["total_qty"], 9)
        self.assertEqual(top[0]["entries"], 1)

    def test_validasi_input(self):
        with self.assertRaises(ScrapAccumulatorError):
            self.service.record_scrap(self.bundle, self.wc_sewing, 0)
        with self.assertRaises(ScrapAccumulatorError):
            self.service.record_scrap(self.bundle, self.wc_sewing, -1)
        with self.assertRaises(ScrapAccumulatorError):
            self.service.record_scrap(self.bundle, self.wc_sewing, "dua")
        with self.assertRaises(ScrapAccumulatorError):
            self.service.record_scrap(None, self.wc_sewing, 1)
        with self.assertRaises(ScrapAccumulatorError):
            self.service.record_scrap(self.bundle, None, 1)
        with self.assertRaises(ScrapAccumulatorError):
            self.service.get_summary(None)
        with self.assertRaises(ScrapAccumulatorError):
            self.service.get_top_scrap_work_centers(limit=0)
