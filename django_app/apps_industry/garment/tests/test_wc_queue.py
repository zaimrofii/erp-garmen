"""Test WCQueue: enqueue, dequeue, count, position, dan urutan queue virtual."""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps_industry.garment.models import Bundle
from apps_industry.garment.services import WCQueue, WCQueueError
from apps_industry.garment.tests.factories import make_bundle, make_work_center, make_work_order


class WCQueueTests(TestCase):
    """Queue = query (virtual), bukan tabel tersendiri."""

    @classmethod
    def setUpTestData(cls):
        cls.wc_sewing = make_work_center(code="SEWING-1")
        cls.wc_qc = make_work_center(code="QC-1")
        cls.work_order = make_work_order()
        cls.bundle_a = make_bundle(work_order=cls.work_order, code="BND-A")
        cls.bundle_b = make_bundle(work_order=cls.work_order, code="BND-B")

    def setUp(self):
        self.queue = WCQueue()

    def test_enqueue_set_work_center_dan_version_berubah(self):
        version_awal = Bundle.objects.get(pk=self.bundle_a.pk).version

        hasil = self.queue.enqueue(self.bundle_a, self.wc_sewing)

        self.assertEqual(hasil.current_work_center, self.wc_sewing)
        self.assertNotEqual(hasil.version, version_awal)
        self.assertEqual(self.queue.count(self.wc_sewing), 1)

    def test_dequeue_mengosongkan_work_center(self):
        self.queue.enqueue(self.bundle_a, self.wc_sewing)
        version_sebelum = Bundle.objects.get(pk=self.bundle_a.pk).version

        hasil = self.queue.dequeue(self.bundle_a)

        self.assertIsNone(hasil.current_work_center)
        self.assertNotEqual(hasil.version, version_sebelum)
        self.assertEqual(self.queue.count(self.wc_sewing), 0)

    def test_count_mengabaikan_state_done_dan_cancelled(self):
        self.queue.enqueue(self.bundle_a, self.wc_sewing)
        self.queue.enqueue(self.bundle_b, self.wc_sewing)
        self.assertEqual(self.queue.count(self.wc_sewing), 2)

        self.bundle_b.state = "DONE"
        self.bundle_b.save()
        self.assertEqual(self.queue.count(self.wc_sewing), 1)

        self.bundle_a.state = "CANCELLED"
        self.bundle_a.save()
        self.assertEqual(self.queue.count(self.wc_sewing), 0)

    def test_position_1_based(self):
        self.queue.enqueue(self.bundle_a, self.wc_sewing)
        self.queue.enqueue(self.bundle_b, self.wc_sewing)

        self.assertEqual(self.queue.position(self.bundle_a), 1)
        self.assertEqual(self.queue.position(self.bundle_b), 2)

    def test_position_none_kalau_tidak_di_queue(self):
        bundle_lain = make_bundle(code="BND-C")  # belum punya work center

        self.assertIsNone(self.queue.position(bundle_lain))

    def test_position_none_kalau_state_sudah_selesai(self):
        self.queue.enqueue(self.bundle_a, self.wc_sewing)
        self.bundle_a.state = "DONE"
        self.bundle_a.save()

        self.assertIsNone(self.queue.position(self.bundle_a))

    def test_queue_hanya_berisi_work_center_yang_diminta(self):
        self.queue.enqueue(self.bundle_a, self.wc_sewing)
        self.queue.enqueue(self.bundle_b, self.wc_qc)

        self.assertEqual(
            list(self.queue.get_queue(self.wc_sewing).values_list("code", flat=True)),
            ["BND-A"],
        )
        self.assertEqual(self.queue.count(self.wc_qc), 1)

    def test_urutan_queue_paling_lama_di_update_lebih_dulu(self):
        self.queue.enqueue(self.bundle_b, self.wc_sewing)
        Bundle.objects.filter(pk=self.bundle_b.pk).update(
            updated_at=timezone.now() - timedelta(hours=1)
        )
        self.queue.enqueue(self.bundle_a, self.wc_sewing)

        ids = list(self.queue.get_queue(self.wc_sewing).values_list("pk", flat=True))

        self.assertEqual(ids, [self.bundle_b.pk, self.bundle_a.pk])

    def test_input_none_raise(self):
        with self.assertRaises(WCQueueError):
            self.queue.get_queue(None)
        with self.assertRaises(WCQueueError):
            self.queue.enqueue(self.bundle_a, None)
        with self.assertRaises(WCQueueError):
            self.queue.dequeue(None)
        with self.assertRaises(WCQueueError):
            self.queue.position(None)
