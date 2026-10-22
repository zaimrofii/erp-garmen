"""Test Fase Berat-Lite — korelasi kualitas via SQL (TEMPORARY)."""

from __future__ import annotations

from datetime import datetime

from django.test import TestCase
from django.utils import timezone

from apps_industry.garment.models import BundleEvent, ScrapAccumulator
from apps_industry.garment.tests.factories import (
    make_bundle,
    make_scrap_accumulator,
    make_work_center,
)
from core.auth.models import Role, User
from integrations.ai_agent.data_access.metrics import MetricsRepository

DAY = timezone.make_aware(datetime(2026, 10, 10, 9, 0))


class QualityTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        role = Role.objects.get(code=Role.Code.OPERATOR)
        cls.op1 = User.objects.create_user(username="q-op1", password="x", role=role)
        cls.op2 = User.objects.create_user(username="q-op2", password="x", role=role)

    def setUp(self):
        self.repo = MetricsRepository()
        self.wc1 = make_work_center("SEWING-1")
        self.wc2 = make_work_center("QC-1")
        self.bundle = make_bundle(qty=100, current_work_center=self.wc1)

    def _event(self, actor, event_type):
        BundleEvent.objects.create(
            bundle=self.bundle, event_type=event_type, actor=actor
        )


class QualityByOperatorTests(QualityTestBase):
    def test_scrap_dan_rework_per_operator(self):
        self._event(self.op1, "SCRAP")
        self._event(self.op1, "SCRAP")
        self._event(self.op1, "REWORK")
        self._event(self.op2, "REWORK")

        rows = {row["operator"]: row for row in self.repo.quality_by_operator()}

        self.assertEqual(rows["q-op1"]["scrap_events"], 2)
        self.assertEqual(rows["q-op1"]["rework_events"], 1)
        self.assertEqual(rows["q-op2"]["rework_events"], 1)

    def test_event_non_quality_tidak_dihitung(self):
        self._event(self.op1, "BUNDLE_START")

        self.assertEqual(self.repo.quality_by_operator(), [])


class QualityByShiftTests(QualityTestBase):
    def test_shift_1_dan_2_dipisah(self):
        morning = make_scrap_accumulator(
            bundle=self.bundle, work_center=self.wc1, qty=2, rework_qty=1
        )
        evening = make_scrap_accumulator(
            bundle=self.bundle, work_center=self.wc2, qty=5, rework_qty=0
        )
        ScrapAccumulator.objects.filter(pk=morning.pk).update(
            created_at=timezone.make_aware(datetime(2026, 10, 10, 10, 0))
        )
        ScrapAccumulator.objects.filter(pk=evening.pk).update(
            created_at=timezone.make_aware(datetime(2026, 10, 10, 16, 0))
        )

        rows = {row["shift"]: row for row in self.repo.quality_by_shift()}

        self.assertEqual(rows[1]["scrap_qty"], 2.0)
        self.assertEqual(rows[2]["scrap_qty"], 5.0)


class QualityByWcTests(QualityTestBase):
    def test_scrap_per_wc(self):
        make_scrap_accumulator(
            bundle=self.bundle, work_center=self.wc1, qty=3, rework_qty=2
        )

        rows = self.repo.quality_by_wc()
        row = next(item for item in rows if item["work_center"] == "SEWING-1")

        self.assertEqual(row["scrap_qty"], 3.0)
        self.assertEqual(row["rework_qty"], 2.0)


class CorrelationTests(QualityTestBase):
    def test_korelasi_negatif_kuat(self):
        for _index in range(3):
            self._event(self.op1, "SCRAP")
        for _index in range(3):
            self._event(self.op2, "REWORK")

        result = self.repo.quality_correlation()

        self.assertEqual(result["n"], 2)
        self.assertLess(result["r"], 0)
        self.assertIn("negatif", result["interpretation"])

    def test_korelasi_data_kurang(self):
        self._event(self.op1, "SCRAP")

        result = self.repo.quality_correlation()

        self.assertIsNone(result["r"])
        self.assertEqual(result["interpretation"], "data belum cukup")

    def test_snapshot_berisi_semua_bagian(self):
        snapshot = self.repo.anomaly_snapshot()

        self.assertEqual(
            set(snapshot),
            {"by_operator", "by_shift", "by_wc", "correlation"},
        )
