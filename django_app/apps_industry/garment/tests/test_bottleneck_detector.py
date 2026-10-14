"""Test BottleneckDetector: ambang queue, ambang waktu tunggu, dan top_n."""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps_industry.garment.models import Bundle
from apps_industry.garment.services import (
    BottleneckDetector,
    BottleneckDetectorError,
    BottleneckReport,
)
from apps_industry.garment.tests.factories import (
    make_bundle,
    make_work_center,
    make_work_order,
)


class BottleneckDetectorTests(TestCase):
    """Threshold default: 10 bundle / 60 menit."""

    @classmethod
    def setUpTestData(cls):
        cls.wc_ramai = make_work_center(code="SEWING-1")
        cls.wc_lama = make_work_center(code="QC-1")
        cls.wc_sepi = make_work_center(code="PACKING-1")
        cls.work_order = make_work_order()

    def _isi_queue(self, work_center, jumlah, umur_menit=0):
        """Isi queue WC dengan `jumlah` bundle (opsional dibuat berumur)."""
        bundles = [
            make_bundle(
                work_order=self.work_order,
                code=f"{work_center.code}-B{index}",
                current_work_center=work_center,
            )
            for index in range(jumlah)
        ]
        if umur_menit:
            Bundle.objects.filter(pk__in=[bundle.pk for bundle in bundles]).update(
                updated_at=timezone.now() - timedelta(minutes=umur_menit)
            )
        return bundles

    def test_bukan_bottleneck_kalau_queue_kecil_dan_baru(self):
        self._isi_queue(self.wc_sepi, 2)

        report = BottleneckDetector().detect(self.wc_sepi)

        self.assertIsInstance(report, BottleneckReport)
        self.assertEqual(report.queue_depth, 2)
        self.assertFalse(report.is_bottleneck)
        self.assertEqual(report.reason, "normal")

    def test_bottleneck_karena_queue_tinggi(self):
        self._isi_queue(self.wc_ramai, 11)  # ambang 10

        report = BottleneckDetector().detect(self.wc_ramai)

        self.assertTrue(report.is_bottleneck)
        self.assertIn("queue 11", report.reason)

    def test_bottleneck_karena_waktu_tunggu_tinggi(self):
        self._isi_queue(self.wc_lama, 2, umur_menit=120)  # ambang 60 menit

        report = BottleneckDetector().detect(self.wc_lama)

        self.assertTrue(report.is_bottleneck)
        self.assertGreater(report.avg_wait_minutes, 100)
        self.assertIn("rata-rata tunggu", report.reason)

    def test_avg_wait_nol_kalau_queue_kosong(self):
        report = BottleneckDetector().detect(self.wc_sepi)

        self.assertEqual(report.queue_depth, 0)
        self.assertEqual(report.avg_wait_minutes, 0.0)
        self.assertFalse(report.is_bottleneck)

    def test_detect_all_semua_work_center_aktif(self):
        reports = BottleneckDetector().detect_all()

        self.assertEqual(
            [report.work_center.code for report in reports],
            ["PACKING-1", "QC-1", "SEWING-1"],
        )

    def test_top_n_urut_queue_depth_desc(self):
        self._isi_queue(self.wc_ramai, 12)
        self._isi_queue(self.wc_lama, 11)

        top = BottleneckDetector().top_n(n=5)

        self.assertEqual(
            [report.work_center.code for report in top], ["SEWING-1", "QC-1"]
        )

    def test_top_n_hanya_work_center_bottleneck(self):
        self._isi_queue(self.wc_sepi, 1)

        self.assertEqual(BottleneckDetector().top_n(n=5), [])

    def test_threshold_bisa_di_override(self):
        self._isi_queue(self.wc_sepi, 3)

        report = BottleneckDetector(queue_depth_threshold=2).detect(self.wc_sepi)

        self.assertTrue(report.is_bottleneck)

    def test_queue_hanya_menghitung_wc_tersebut(self):
        self._isi_queue(self.wc_ramai, 3)
        self._isi_queue(self.wc_sepi, 1)

        self.assertEqual(BottleneckDetector().detect(self.wc_ramai).queue_depth, 3)

    def test_input_tidak_valid_raise(self):
        with self.assertRaises(BottleneckDetectorError):
            BottleneckDetector().detect(None)
        with self.assertRaises(BottleneckDetectorError):
            BottleneckDetector().top_n(n=0)
        with self.assertRaises(BottleneckDetectorError):
            BottleneckDetector().top_n(n="lima")
