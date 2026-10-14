"""Test endpoint reports on-time-delivery (F3A.1 / B20 & B20b).

* ``GET /api/v1/reports/on-time-delivery/``         -> per **work order** DONE (+ ``otd_pct``)
* ``GET /api/v1/reports/on-time-delivery/orders/``  -> agregat per **Order**

Catatan derivasi: `WorkOrder` tidak punya kolom ``finished_at`` → dipakai event
``BUNDLE_FINISH`` terakhir bundle WO tsb (fallback ``WorkOrder.updated_at``).

Jalankan (SERIAL):

    docker compose exec django python -m pytest tests/integration/test_reports_on_time_delivery.py -q
"""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps_industry.garment.models import BundleEvent
from apps_industry.garment.tests.factories import (
    make_bundle,
    make_order,
    make_order_line,
    make_work_order,
)
from core.auth.models import User

URL = "/api/v1/reports/on-time-delivery/"
URL_ORDERS = "/api/v1/reports/on-time-delivery/orders/"

TOP_KEYS = {"rows", "total_count", "has_more", "next_cursor", "otd_pct"}
ROW_KEYS = {"order_code", "deadline", "finished_at", "on_time", "delay_hours"}
ORDER_TOP_KEYS = {"rows", "total_count", "has_more", "next_cursor"}
ORDER_ROW_KEYS = {"order_code", "deadline", "last_wo_finished", "on_time", "wo_count"}


def _event(bundle, event_type, ts):
    """Buat `BundleEvent` lalu paksa `ts` (ts = auto_now_add)."""
    event = BundleEvent.objects.create(bundle=bundle, event_type=event_type, payload={})
    BundleEvent.objects.filter(pk=event.pk).update(ts=ts)
    return event


def _done_wo(order, code, finished_at):
    """WorkOrder ber-state DONE + 1 bundle dengan event FINISH pada ``finished_at``."""
    work_order = make_work_order(
        order_line=make_order_line(order=order), code=code, state="DONE"
    )
    bundle = make_bundle(work_order=work_order, code=f"B-{code}", state="DONE")
    _event(bundle, "BUNDLE_START", finished_at - timedelta(hours=1))
    _event(bundle, "BUNDLE_FINISH", finished_at)
    return work_order


class OnTimeDeliveryAuthTests(TestCase):
    def test_anonim_403(self):
        self.assertEqual(APIClient().get(URL).status_code, 403)

    def test_anonim_orders_403(self):
        self.assertEqual(APIClient().get(URL_ORDERS).status_code, 403)


class OnTimeDeliveryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="rep-otd", password="x")

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    @staticmethod
    def _seed_on_time_and_late():
        """Order tepat waktu (finish sebelum deadline) + 1 terlambat."""
        now = timezone.now()
        on_time_order = make_order(code="ORD-OT")
        on_time_order.deadline = now + timedelta(hours=1)
        on_time_order.save(update_fields=["deadline"])
        _done_wo(on_time_order, "WO-OT", now - timedelta(minutes=30))

        late_order = make_order(code="ORD-LATE")
        late_order.deadline = now - timedelta(hours=1)
        late_order.save(update_fields=["deadline"])
        _done_wo(late_order, "WO-LATE", now - timedelta(minutes=10))

    def test_shape_lengkap(self):
        body = self.api.get(URL).json()

        self.assertEqual(set(body), TOP_KEYS)
        self.assertEqual(body["rows"], [])
        self.assertEqual(body["otd_pct"], 0.0)

    def test_kosong(self):
        body = self.api.get(URL).json()

        self.assertEqual(body["total_count"], 0)
        self.assertFalse(body["has_more"])
        self.assertIsNone(body["next_cursor"])

    def test_satu_ontime_satu_late(self):
        self._seed_on_time_and_late()

        body = self.api.get(URL).json()

        self.assertEqual(body["total_count"], 2)
        self.assertEqual(set(body["rows"][0]), ROW_KEYS)
        per_order = {row["order_code"]: row for row in body["rows"]}
        self.assertTrue(per_order["ORD-OT"]["on_time"])
        self.assertEqual(per_order["ORD-OT"]["delay_hours"], 0.0)
        self.assertFalse(per_order["ORD-LATE"]["on_time"])
        self.assertGreater(per_order["ORD-LATE"]["delay_hours"], 0.0)

    def test_otd_pct_50_persen(self):
        self._seed_on_time_and_late()

        body = self.api.get(URL).json()

        self.assertEqual(body["otd_pct"], 50.0)

    def test_filter_on_time(self):
        self._seed_on_time_and_late()

        hanya_late = self.api.get(URL, {"on_time": "false"}).json()
        hanya_ontime = self.api.get(URL, {"on_time": "true"}).json()

        self.assertEqual([row["order_code"] for row in hanya_late["rows"]], ["ORD-LATE"])
class OnTimeDeliveryOrdersTests(TestCase):
    """B20b — OTD agregat per Order (bukan per work order)."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="rep-otd-ord", password="x")

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    @staticmethod
    def _seed_two_orders():
        """Order A tepat waktu (1 WO) + Order B terlambat (2 WO)."""
        now = timezone.now()
        order_a = make_order(code="ORD-A")
        order_a.deadline = now + timedelta(hours=2)
        order_a.save(update_fields=["deadline"])
        _done_wo(order_a, "WO-A1", now - timedelta(hours=1))

        order_b = make_order(code="ORD-B")
        order_b.deadline = now - timedelta(hours=2)
        order_b.save(update_fields=["deadline"])
        _done_wo(order_b, "WO-B1", now - timedelta(hours=1))
        _done_wo(order_b, "WO-B2", now - timedelta(minutes=20))

    def test_shape_order(self):
        self._seed_two_orders()

        body = self.api.get(URL_ORDERS).json()

        self.assertEqual(set(body), ORDER_TOP_KEYS)
        self.assertEqual(set(body["rows"][0]), ORDER_ROW_KEYS)

    def test_kosong(self):
        body = self.api.get(URL_ORDERS).json()

        self.assertEqual(body["rows"], [])
        self.assertEqual(body["total_count"], 0)
        self.assertIsNone(body["next_cursor"])

    def test_dua_order_wo_count_dan_last_finished(self):
        self._seed_two_orders()

        body = self.api.get(URL_ORDERS).json()

        self.assertEqual(body["total_count"], 2)
        per_order = {row["order_code"]: row for row in body["rows"]}
        self.assertEqual(per_order["ORD-A"]["wo_count"], 1)
        self.assertEqual(per_order["ORD-B"]["wo_count"], 2)
        self.assertIsNotNone(per_order["ORD-B"]["last_wo_finished"])
        self.assertFalse(per_order["ORD-B"]["on_time"])
        self.assertTrue(per_order["ORD-A"]["on_time"])

    def test_filter_on_time_orders(self):
        self._seed_two_orders()

        hanya_late = self.api.get(URL_ORDERS, {"on_time": "false"}).json()
        hanya_ontime = self.api.get(URL_ORDERS, {"on_time": "true"}).json()

        self.assertEqual([row["order_code"] for row in hanya_late["rows"]], ["ORD-B"])
        self.assertEqual([row["order_code"] for row in hanya_ontime["rows"]], ["ORD-A"])

