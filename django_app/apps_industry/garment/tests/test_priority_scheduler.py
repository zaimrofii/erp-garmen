"""Test PriorityScheduler: bobot tag, bonus deadline, rule prioritas, next_to_process."""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps_industry.garment.models import Bundle
from apps_industry.garment.services import PriorityScheduler, PrioritySchedulerError
from apps_industry.garment.tests.factories import (
    make_bundle,
    make_order,
    make_order_line,
    make_priority_rule,
    make_work_center,
    make_work_order,
)


class PrioritySchedulerTests(TestCase):
    """Skor = base(rule/tag) + bonus deadline + order.priority."""

    def setUp(self):
        self.scheduler = PriorityScheduler()

    def _work_order(self, tag="FAST_TRACK", priority=0, deadline=None):
        order = make_order(priority=priority, deadline=deadline)
        order_line = make_order_line(order=order, tag=tag, qty=10)
        return make_work_order(order_line=order_line)

    # ------------------------------------------------------------------- score
    def test_default_weights_per_tag(self):
        self.assertEqual(
            self.scheduler.compute_priority(self._work_order(tag="FAST_TRACK")), 100
        )
        self.assertEqual(
            self.scheduler.compute_priority(self._work_order(tag="EXPORT")), 50
        )
        self.assertEqual(
            self.scheduler.compute_priority(self._work_order(tag="CUSTOM")), 10
        )
        self.assertEqual(
            self.scheduler.compute_priority(self._work_order(tag="TANPA_BOBOT")), 0
        )

    def test_default_weights_bisa_di_override(self):
        scheduler = PriorityScheduler(default_weights={"FAST_TRACK": 7})

        self.assertEqual(scheduler.compute_priority(self._work_order(tag="FAST_TRACK")), 7)

    def test_order_priority_ditambahkan(self):
        work_order = self._work_order(tag="EXPORT", priority=7)

        self.assertEqual(self.scheduler.compute_priority(work_order), 57)

    def test_deadline_bonus(self):
        work_order = self._work_order(
            tag="CUSTOM", deadline=timezone.now() + timedelta(days=5)
        )

        # max(0, 30 - 5) * 5 = 125
        self.assertEqual(
            self.scheduler.deadline_bonus(work_order.order_line.order.deadline), 125
        )
        self.assertEqual(self.scheduler.compute_priority(work_order), 10 + 125)

    def test_deadline_jauh_tidak_dapat_bonus_dan_none_aman(self):
        work_order = self._work_order(
            tag="CUSTOM", deadline=timezone.now() + timedelta(days=90)
        )

        self.assertEqual(self.scheduler.compute_priority(work_order), 10)
        self.assertEqual(self.scheduler.deadline_bonus(None), 0)

    def test_rule_priority_menimpa_bobot_tag(self):
        make_priority_rule("FAST_TRACK_OVERRIDE", value=250, tag="FAST_TRACK")
        work_order = self._work_order(tag="FAST_TRACK")

        self.assertEqual(self.scheduler.compute_priority(work_order), 250)

    def test_rule_priority_tidak_match_pakai_bobot_tag(self):
        make_priority_rule("LAIN", value=250, tag="EXPORT")
        work_order = self._work_order(tag="FAST_TRACK")

        self.assertEqual(self.scheduler.compute_priority(work_order), 100)

    # -------------------------------------------------------------------- rank
    def test_rank_work_orders_desc(self):
        rendah = self._work_order(tag="CUSTOM")
        tinggi = self._work_order(tag="FAST_TRACK")
        sedang = self._work_order(tag="EXPORT")

        ranked = self.scheduler.rank_work_orders([rendah, tinggi, sedang])

        self.assertEqual([item[0] for item in ranked], [tinggi, sedang, rendah])
        self.assertEqual([item[1] for item in ranked], [100, 50, 10])

    # --------------------------------------------------------- next_to_process
    def test_next_to_process_pilih_skor_tertinggi(self):
        wc = make_work_center(code="SEWING-1")
        rendah = self._work_order(tag="CUSTOM")
        tinggi = self._work_order(tag="FAST_TRACK")
        make_bundle(work_order=rendah, code="BND-R", current_work_center=wc)
        bundle_tinggi = make_bundle(
            work_order=tinggi, code="BND-T", current_work_center=wc
        )

        self.assertEqual(self.scheduler.next_to_process(wc), bundle_tinggi)

    def test_next_to_process_tie_break_updated_at_asc(self):
        wc = make_work_center(code="QC-1")
        work_order = self._work_order(tag="EXPORT")
        lebih_dulu = make_bundle(
            work_order=work_order, code="BND-1", current_work_center=wc
        )
        make_bundle(work_order=work_order, code="BND-2", current_work_center=wc)
        Bundle.objects.filter(pk=lebih_dulu.pk).update(
            updated_at=timezone.now() - timedelta(hours=1)
        )

        self.assertEqual(self.scheduler.next_to_process(wc), lebih_dulu)

    def test_next_to_process_queue_kosong(self):
        wc = make_work_center(code="KOSONG-1")

        self.assertIsNone(self.scheduler.next_to_process(wc))

    def test_input_none_raise(self):
        with self.assertRaises(PrioritySchedulerError):
            self.scheduler.compute_priority(None)
        with self.assertRaises(PrioritySchedulerError):
            self.scheduler.rank_work_orders(None)
        with self.assertRaises(PrioritySchedulerError):
            self.scheduler.next_to_process(None)
