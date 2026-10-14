"""Test endpoint quality rework (F1 / B6) — `GET /api/v1/quality/rework/`.

Read-only dari `CycleInstance` (definition code ``QC_REWORK``).
``IsAuthenticated`` → 403.

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_quality_rework.py -q
"""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.tests.factories import make_bundle
from core.auth.models import User
from core.cycle_handler.models import CycleDefinition, CycleInstance

REWORK_URL = "/api/v1/quality/rework/"
CYCLE_CODE = "QC_REWORK"

TOP_KEYS = {"rows", "total_count", "has_more", "next_cursor"}
ROW_KEYS = {
    "bundle_code",
    "from_step",
    "to_step",
    "iteration",
    "started_at",
    "closed_at",
    "is_open",
}


def _definition():
    """CycleDefinition QC_REWORK (dibuat ReworkLoopHandler saat runtime)."""
    return CycleDefinition.objects.get_or_create(
        code=CYCLE_CODE, defaults={"name": "QC Rework"}
    )[0]


class QualityReworkAuthTests(TestCase):
    def test_anonim_403(self):
        self.assertEqual(APIClient().get(REWORK_URL).status_code, 403)


class QualityReworkTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="rew-shape", password="x")

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def test_shape_listpage_lengkap(self):
        definition = _definition()
        bundle = make_bundle(code="B-001")
        CycleInstance.objects.create(
            definition=definition,
            ref_type="bundle",
            ref_id=str(bundle.pk),
            status="ACTIVE",
            iteration_count=1,
        )

        body = self.api.get(REWORK_URL).json()

        self.assertEqual(set(body), TOP_KEYS)
        self.assertEqual(body["total_count"], 1)
        self.assertFalse(body["has_more"])
        self.assertIsNone(body["next_cursor"])
        row = body["rows"][0]
        self.assertEqual(set(row), ROW_KEYS)
        self.assertEqual(row["bundle_code"], "B-001")
        self.assertEqual(row["iteration"], 1)  # field riil iteration_count
        self.assertIsNone(row["from_step"])
        self.assertIsNone(row["to_step"])
        self.assertIsNone(row["closed_at"])
        self.assertIs(row["is_open"], True)
        self.assertIn("T", row["started_at"])

    def test_db_kosong(self):
        body = self.api.get(REWORK_URL).json()

        self.assertEqual(body["rows"], [])
        self.assertEqual(body["total_count"], 0)
        self.assertFalse(body["has_more"])
        self.assertIsNone(body["next_cursor"])


class QualityReworkDataTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="rew-data", password="x")

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def test_terbuka_dan_tertutup(self):
        definition = _definition()
        bundle_open = make_bundle(code="B-OPEN")
        bundle_closed = make_bundle(code="B-CLOSED")
        CycleInstance.objects.create(
            definition=definition,
            ref_type="bundle",
            ref_id=str(bundle_open.pk),
            status="ACTIVE",
        )
        CycleInstance.objects.create(
            definition=definition,
            ref_type="bundle",
            ref_id=str(bundle_closed.pk),
            status="COMPLETED",
            iteration_count=2,
        )

        body = self.api.get(REWORK_URL).json()

        self.assertEqual(body["total_count"], 2)
        per_bundle = {row["bundle_code"]: row for row in body["rows"]}
        self.assertIs(per_bundle["B-OPEN"]["is_open"], True)
        self.assertIs(per_bundle["B-CLOSED"]["is_open"], False)
        self.assertEqual(per_bundle["B-CLOSED"]["iteration"], 2)

    def test_filter_open_true(self):
        definition = _definition()
        make_a = make_bundle(code="B-A")
        make_b = make_bundle(code="B-B")
        CycleInstance.objects.create(
            definition=definition, ref_type="bundle", ref_id=str(make_a.pk), status="ACTIVE"
        )
        CycleInstance.objects.create(
            definition=definition,
            ref_type="bundle",
            ref_id=str(make_b.pk),
            status="COMPLETED",
        )

        body = self.api.get(REWORK_URL, {"open": "true"}).json()

        self.assertEqual(body["total_count"], 1)
        self.assertEqual(body["rows"][0]["bundle_code"], "B-A")
        self.assertIs(body["rows"][0]["is_open"], True)

    def test_filter_open_false(self):
        definition = _definition()
        bundle_open = make_bundle(code="B-OPEN")
        bundle_closed = make_bundle(code="B-CLOSED")
        CycleInstance.objects.create(
            definition=definition,
            ref_type="bundle",
            ref_id=str(bundle_open.pk),
            status="ACTIVE",
        )
        CycleInstance.objects.create(
            definition=definition,
            ref_type="bundle",
            ref_id=str(bundle_closed.pk),
            status="COMPLETED",
        )

        body = self.api.get(REWORK_URL, {"open": "false"}).json()

        self.assertEqual(body["total_count"], 1)
        self.assertEqual(body["rows"][0]["bundle_code"], "B-CLOSED")

    def test_ref_type_bukan_bundle_kode_null(self):
        definition = _definition()
        CycleInstance.objects.create(
            definition=definition, ref_type="work_order", ref_id="12", status="ACTIVE"
        )

        row = self.api.get(REWORK_URL).json()["rows"][0]

        self.assertIsNone(row["bundle_code"])
        self.assertIs(row["is_open"], True)
