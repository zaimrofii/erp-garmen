"""Test endpoint buffer queue (F1 / B2) — `GET /api/v1/production/buffer-queue/`.

Read-only, agregat DB murni (reuse `WCQueue`). ``IsAuthenticated`` → anonim 403.

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_buffer_queue.py -q
"""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps_industry.garment.models import Bundle, WorkCenter
from apps_industry.garment.tests.factories import (
    make_bundle,
    make_routing,
    make_step,
    make_work_center,
    make_work_order,
)
from core.auth.models import User

BUFFER_URL = "/api/v1/production/buffer-queue/"

TOP_KEYS = {"rows", "generated_at"}
ROW_KEYS = {"wc_code", "wc_name", "queue_depth", "avg_wait_min", "bundles"}
BUNDLE_KEYS = {"code", "qty", "waited_min", "state", "from_wc", "to_wc", "status"}


class BufferQueueAuthTests(TestCase):
    def test_anonim_403(self):
        self.assertEqual(APIClient().get(BUFFER_URL).status_code, 403)


class BufferQueueTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="buf-queue", password="x")

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def test_shape_lengkap(self):
        work_center = make_work_center(code="SEW-01")
        work_order = make_work_order()
        make_bundle(
            work_order=work_order,
            code="B-001",
            state="SEWING",
            current_work_center=work_center,
        )

        body = self.api.get(BUFFER_URL).json()

        self.assertEqual(set(body), TOP_KEYS)
        self.assertIn("T", body["generated_at"])
        self.assertEqual(len(body["rows"]), 1)
        row = body["rows"][0]
        self.assertEqual(set(row), ROW_KEYS)
        self.assertEqual(set(row["bundles"][0]), BUNDLE_KEYS)

    def test_db_kosong(self):
        body = self.api.get(BUFFER_URL).json()

        self.assertEqual(body["rows"], [])
        self.assertIn("T", body["generated_at"])

    def test_queue_depth_dan_avg_wait(self):
        work_center = WorkCenter.objects.create(code="SEW-01", name="Sewing Line 1")
        work_order = make_work_order()
        bundles = [
            make_bundle(
                work_order=work_order,
                code=f"B-{index}",
                state="SEWING",
                current_work_center=work_center,
            )
            for index in range(3)
        ]
        now = timezone.now()
        for bundle, umur_menit in zip(bundles, (30, 60, 90)):
            Bundle.objects.filter(pk=bundle.pk).update(
                updated_at=now - timedelta(minutes=umur_menit)
            )

        body = self.api.get(BUFFER_URL).json()

        row = next(r for r in body["rows"] if r["wc_code"] == "SEW-01")
        self.assertEqual(row["wc_name"], "Sewing Line 1")
        self.assertEqual(row["queue_depth"], 3)
        self.assertAlmostEqual(row["avg_wait_min"], 60.0, delta=2.0)
        # bundles urut waited_min DESC -> yang paling lama (90 menit) di depan.
        self.assertEqual(row["bundles"][0]["code"], "B-2")
        self.assertAlmostEqual(row["bundles"][0]["waited_min"], 90.0, delta=2.0)

    def test_bundle_done_tidak_masuk_hitungan(self):
        work_center = make_work_center(code="SEW-02")
        work_order = make_work_order()
        make_bundle(
            work_order=work_order,
            code="B-ACTIVE",
            state="SEWING",
            current_work_center=work_center,
        )
        make_bundle(
            work_order=work_order,
            code="B-DONE",
            state="DONE",
            current_work_center=work_center,
        )
        # WC lain yang HANYA punya bundle DONE -> tidak boleh muncul sama sekali.
        wc_selesai = make_work_center(code="SEW-03")
        make_bundle(
            work_order=work_order,
            code="B-DONE-2",
            state="DONE",
            current_work_center=wc_selesai,
        )

        body = self.api.get(BUFFER_URL).json()

        kodes = [r["wc_code"] for r in body["rows"]]
        self.assertNotIn("SEW-03", kodes)
        row = next(r for r in body["rows"] if r["wc_code"] == "SEW-02")
        self.assertEqual(row["queue_depth"], 1)
        self.assertEqual([b["code"] for b in row["bundles"]], ["B-ACTIVE"])


class BufferQueueGapTests(TestCase):
    """G2 (aditif) — `from_wc` / `to_wc` / `status` per bundle."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="buf-gap", password="x")

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    @staticmethod
    def _linear_routing():
        wc_cut = make_work_center(code="CUT-1")
        wc_sew = make_work_center(code="SEW-1")
        wc_pack = make_work_center(code="PACK-1")
        routing = make_routing(code="R-BUF")
        step1 = make_step(routing, "CUT", 1, is_initial=True, work_center=wc_cut)
        step2 = make_step(routing, "SEW", 2, work_center=wc_sew)
        step3 = make_step(routing, "PACK", 3, is_terminal=True, work_center=wc_pack)
        step1.allowed_next_steps.add(step2)
        step2.allowed_next_steps.add(step3)
        return wc_cut, wc_sew, wc_pack

    def _bundle_item(self, wc_code):
        body = self.api.get(BUFFER_URL).json()
        row = next(r for r in body["rows"] if r["wc_code"] == wc_code)
        return row["bundles"][0]

    def test_field_baru_ada(self):
        _wc_cut, wc_sew, _wc_pack = self._linear_routing()
        work_order = make_work_order()
        make_bundle(
            work_order=work_order,
            code="B-SEW",
            state="SEWING",
            current_work_center=wc_sew,
        )

        item = self._bundle_item("SEW-1")

        self.assertEqual(set(item), BUNDLE_KEYS)
        self.assertEqual(item["status"], "SEWING")
        self.assertEqual(item["to_wc"], "PACK-1")
        self.assertEqual(item["from_wc"], "CUT-1")  # step sebelumnya (dari routing)

    def test_to_wc_null_di_terminal(self):
        _wc_cut, _wc_sew, wc_pack = self._linear_routing()
        work_order = make_work_order()
        make_bundle(
            work_order=work_order,
            code="B-PACK",
            state="QC",
            current_work_center=wc_pack,
        )

        self.assertIsNone(self._bundle_item("PACK-1")["to_wc"])

    def test_from_wc_null_bundle_pertama(self):
        wc_cut, _wc_sew, _wc_pack = self._linear_routing()
        work_order = make_work_order()
        make_bundle(
            work_order=work_order,
            code="B-FIRST",
            state="CUTTING",
            current_work_center=wc_cut,
        )

        self.assertIsNone(self._bundle_item("CUT-1")["from_wc"])

    def test_from_wc_dari_rework_target(self):
        wc_sew = make_work_center(code="SEW-1")
        wc_qc = make_work_center(code="QC-1")
        routing = make_routing(code="R-RW")
        step_sew = make_step(routing, "SEW", 1, is_initial=True, work_center=wc_sew)
        step_qc = make_step(routing, "QC", 2, is_terminal=True, work_center=wc_qc)
        step_sew.allowed_next_steps.add(step_qc)
        step_qc.rework_target_step = step_sew
        step_qc.save(update_fields=["rework_target_step"])

        work_order = make_work_order()
        make_bundle(
            work_order=work_order,
            code="B-RW",
            state="QC",
            current_work_center=wc_qc,
        )

        item = self._bundle_item("QC-1")

        # Step QC punya rework_target_step (SEW) -> from_wc = WC target rework.
        self.assertEqual(item["from_wc"], "SEW-1")


