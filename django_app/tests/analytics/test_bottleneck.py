"""Test metrik `garment.bottleneck` (R.4)."""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps_industry.garment.models import Bundle
from apps_industry.garment.tests.factories import make_bundle, make_work_center
from integrations.analytics.plugins.garment.metrics import bottleneck


class BottleneckTests(TestCase):
    def _active(self, work_center, hours_ago: float, state="SEWING"):
        bundle = make_bundle(state=state, current_work_center=work_center)
        Bundle.objects.filter(pk=bundle.pk).update(
            updated_at=timezone.now() - timedelta(hours=hours_ago)
        )
        return bundle

    def test_wc_paling_sibuk_punya_skor_tertinggi(self):
        busy, medium, quiet = (make_work_center(code=f"WC-{i}") for i in range(3))
        for _ in range(3):
            self._active(busy, 2)
        for _ in range(2):
            self._active(medium, 2)
        self._active(quiet, 2)

        rows = bottleneck._compute_bottleneck({})

        self.assertEqual(rows[0]["key"], busy.code)
        self.assertEqual(rows[0]["buffer_length"], 3)
        self.assertGreater(rows[0]["value"], rows[1]["value"])

    def test_avg_wait_dihitung_benar(self):
        work_center = make_work_center()
        self._active(work_center, 4)

        rows = bottleneck._compute_bottleneck({})

        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["avg_wait_hours"], 4.0, delta=0.2)
        self.assertAlmostEqual(rows[0]["value"], 4.0, delta=0.8)

    def test_tanpa_bundle_aktif_kosong(self):
        work_center = make_work_center()
        make_bundle(state="DONE", current_work_center=work_center)
        make_bundle(state="CANCELLED", current_work_center=work_center)

        self.assertEqual(bottleneck._compute_bottleneck({}), [])

    def test_filter_work_center_menghasilkan_satu_baris(self):
        first = make_work_center(code="WC-FIRST")
        second = make_work_center(code="WC-SECOND")
        self._active(first, 1)
        self._active(second, 3)

        rows = bottleneck._compute_bottleneck({"work_center_id": first.pk})

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["key"], "WC-FIRST")

    def test_compute_set_based_satu_query(self):
        work_center = make_work_center()
        self._active(work_center, 1)
        self._active(work_center, 2)

        with self.assertNumQueries(1):
            rows = bottleneck._compute_bottleneck({})

        self.assertEqual(rows[0]["buffer_length"], 2)
