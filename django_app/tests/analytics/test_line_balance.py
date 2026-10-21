"""Test metrik `garment.line_balance` (R.4)."""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps_industry.garment.models import Bundle
from apps_industry.garment.tests.factories import (
    make_bundle,
    make_line,
    make_work_center,
)
from integrations.analytics.plugins.garment.metrics import line_balance


class LineBalanceTests(TestCase):
    def _done(self, line, work_center, qty_done: int):
        return make_bundle(
            qty_done=qty_done,
            state="DONE",
            production_line=line,
            current_work_center=work_center,
        )

    def test_line_paling_tidak_seimbang_punya_skor_terendah(self):
        wc_a, wc_b, wc_c = (make_work_center() for _ in range(3))
        line_1 = make_line(code="LINE-1")
        line_2 = make_line(code="LINE-2")
        line_3 = make_line(code="LINE-3")

        self._done(line_1, wc_a, 10)
        self._done(line_1, wc_b, 10)
        self._done(line_2, wc_a, 10)
        self._done(line_2, wc_b, 2)
        self._done(line_3, wc_a, 10)
        self._done(line_3, wc_b, 4)

        rows = line_balance._compute_line_balance({"group_by": "line"})

        self.assertEqual(rows[0]["key"], "LINE-2")
        self.assertEqual(rows[0]["value"], 0.33)
        self.assertEqual(rows[0]["total_done"], 12.0)

    def test_satu_work_center_balance_sempurna(self):
        line = make_line(code="LINE-SOLO")
        self._done(line, make_work_center(), 7)

        rows = line_balance._compute_line_balance({"group_by": "line"})

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["value"], 1.0)
        self.assertEqual(rows[0]["work_center_count"], 1)

    def test_tanpa_bundle_done_kosong(self):
        bundle = make_bundle(
            state="SEWING",
            production_line=make_line(),
            current_work_center=make_work_center(),
        )

        rows = line_balance._compute_line_balance({"group_by": "line"})

        self.assertEqual(rows, [])
        self.assertNotEqual(bundle.state, "DONE")

    def test_filter_period_hanya_menghitung_bundle_dalam_rentang(self):
        wc = make_work_center()
        recent_line = make_line(code="LINE-R")
        old_line = make_line(code="LINE-O")
        self._done(recent_line, wc, 10)
        old = self._done(old_line, wc, 10)
        Bundle.objects.filter(pk=old.pk).update(
            updated_at=timezone.now() - timedelta(days=30)
        )

        rows = line_balance._compute_line_balance(
            {
                "group_by": "line",
                "date_from": timezone.now() - timedelta(days=1),
            }
        )

        self.assertEqual([row["key"] for row in rows], ["LINE-R"])

    def test_compute_set_based_satu_query(self):
        line = make_line(code="LINE-Q")
        self._done(line, make_work_center(), 10)
        self._done(line, make_work_center(), 4)

        with self.assertNumQueries(1):
            rows = line_balance._compute_line_balance({"group_by": "line"})

        self.assertEqual(len(rows), 1)
