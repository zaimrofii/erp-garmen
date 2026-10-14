"""Test endpoint quality defects (F1 / B4) — `GET /api/v1/quality/defects/`.

Read-only dari `BundleEvent` (aksi scrap). ``IsAuthenticated`` → 403.
`BundleEvent` tidak punya ``wc_id`` → ``wc_code`` dari ``bundle.current_work_center``.

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_quality_defects.py -q
"""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.models import BundleEvent, WorkCenter
from apps_industry.garment.tests.factories import make_bundle, make_work_center
from core.auth.models import User

DEFECTS_URL = "/api/v1/quality/defects/"

TOP_KEYS = {"rows", "total_count", "has_more", "next_cursor"}
ROW_KEYS = {"bundle_code", "wc_code", "defect_type", "qty", "reason", "recorded_at", "location", "action", "defect_entries"}


def _event(bundle, event_type="BUNDLE_SCRAP", payload=None):
    """Buat `BundleEvent` (ts otomatis)."""
    return BundleEvent.objects.create(
        bundle=bundle, event_type=event_type, payload=payload or {}
    )


class QualityDefectsAuthTests(TestCase):
    def test_anonim_403(self):
        self.assertEqual(APIClient().get(DEFECTS_URL).status_code, 403)


class QualityDefectsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="quality-def", password="x")

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def test_shape_listpage_lengkap(self):
        work_center = make_work_center(code="SEW-01")
        bundle = make_bundle(code="B-001", state="SEWING", current_work_center=work_center)
        _event(
            bundle,
            "BUNDLE_SCRAP",
            {"defect_type": "stitch", "scrap_qty": 3, "reason": "jahitan loncat"},
        )

        body = self.api.get(DEFECTS_URL).json()

        self.assertEqual(set(body), TOP_KEYS)
        self.assertEqual(body["total_count"], 1)
        self.assertFalse(body["has_more"])
        self.assertIsNone(body["next_cursor"])
        row = body["rows"][0]
        self.assertEqual(set(row), ROW_KEYS)
        self.assertEqual(row["bundle_code"], "B-001")
        self.assertEqual(row["wc_code"], "SEW-01")
        self.assertEqual(row["defect_type"], "stitch")
        self.assertEqual(row["qty"], 3)
        self.assertEqual(row["reason"], "jahitan loncat")
        self.assertIn("T", row["recorded_at"])

    def test_db_kosong(self):
        body = self.api.get(DEFECTS_URL).json()

        self.assertEqual(body["rows"], [])
        self.assertEqual(body["total_count"], 0)
        self.assertFalse(body["has_more"])
        self.assertIsNone(body["next_cursor"])


class QualityDefectsDataTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="quality-def-data", password="x")

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def _create_event(self, code, wc_code, event_type, payload):
        work_center, _ = WorkCenter.objects.get_or_create(
            code=wc_code, defaults={"name": wc_code}
        )
        bundle = make_bundle(code=code, state="SEWING", current_work_center=work_center)
        return _event(bundle, event_type, payload)

    def test_dua_event_scrap_dua_baris(self):
        self._create_event(
            "B-1", "SEW-02", "SCRAP",
            {"defect_type": "kain_rusak", "scrap_qty": 4, "reason": "pocket"},
        )
        self._create_event(
            "B-2", "SEW-02", "SCRAP",
            {"defect_type": "jahitan_loncat", "scrap_qty": 1, "reason": "hem"},
        )

        body = self.api.get(DEFECTS_URL).json()

        self.assertEqual(body["total_count"], 2)
        self.assertEqual(len(body["rows"]), 2)
        per_bundle = {row["bundle_code"]: row for row in body["rows"]}
        self.assertEqual(per_bundle["B-1"]["defect_type"], "kain_rusak")
        self.assertEqual(per_bundle["B-1"]["qty"], 4)
        self.assertEqual(per_bundle["B-1"]["reason"], "pocket")
        self.assertEqual(per_bundle["B-2"]["defect_type"], "jahitan_loncat")
        self.assertEqual(per_bundle["B-2"]["qty"], 1)

    def test_event_bundle_scrap_aksi_nyata_ikut_terhitung(self):
        # `event_type` aksi scrap nyata di repo = `BUNDLE_SCRAP` (Fase 4.3).
        self._create_event(
            "B-REAL", "SEW-04", "BUNDLE_SCRAP",
            {"defect_type": "stitch", "scrap_qty": 2, "reason": "loncat"},
        )

        body = self.api.get(DEFECTS_URL).json()

        self.assertEqual(body["total_count"], 1)
        self.assertEqual(body["rows"][0]["defect_type"], "stitch")

    def test_filter_wc(self):
        self._create_event("B-1", "SEW-01", "BUNDLE_SCRAP", {"defect_type": "a", "scrap_qty": 1})
        self._create_event("B-2", "SEW-02", "BUNDLE_SCRAP", {"defect_type": "b", "scrap_qty": 2})

        body = self.api.get(DEFECTS_URL, {"wc": "SEW-01"}).json()

        self.assertEqual(body["total_count"], 1)
        self.assertEqual(len(body["rows"]), 1)
        self.assertEqual(body["rows"][0]["wc_code"], "SEW-01")
        self.assertEqual(body["rows"][0]["bundle_code"], "B-1")

    def test_payload_tanpa_key_pakai_default(self):
        self._create_event("B-DEF", "SEW-05", "BUNDLE_SCRAP", {"state": "DONE"})

        row = self.api.get(DEFECTS_URL).json()["rows"][0]

        self.assertEqual(row["defect_type"], "unknown")
        self.assertEqual(row["qty"], 0)
        self.assertEqual(row["reason"], "")

    def test_event_non_defect_dikecualikan(self):
        self._create_event("B-OK", "SEW-06", "BUNDLE_START", {"state": "CUTTING"})

        body = self.api.get(DEFECTS_URL).json()

        self.assertEqual(body["total_count"], 0)
        self.assertEqual(body["rows"], [])

    def test_kosong_dan_limit_param_salah_400(self):
        self.assertEqual(self.api.get(DEFECTS_URL, {"limit": 0}).status_code, 400)


class QualityDefectsGapTests(TestCase):
    """G3 (aditif) — defect_entries / action / location."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="qc-gap", password="x")

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def _row(self, payload, event_type="BUNDLE_SCRAP"):
        work_center, _ = WorkCenter.objects.get_or_create(
            code="SEW-G3", defaults={"name": "SEW-G3"}
        )
        bundle = make_bundle(code="B-G3", state="SEWING", current_work_center=work_center)
        _event(bundle, event_type, payload)
        return self.api.get(DEFECTS_URL).json()["rows"][0]

    def test_defect_entries_array_min_1(self):
        row = self._row(
            {"defect_type": "stitch", "scrap_qty": 3, "reason": "jahitan loncat"}
        )

        self.assertIsInstance(row["defect_entries"], list)
        self.assertGreaterEqual(len(row["defect_entries"]), 1)
        entry = row["defect_entries"][0]
        self.assertEqual(entry["type"], "stitch")
        self.assertEqual(entry["qty"], 3)
        self.assertEqual(entry["note"], "jahitan loncat")

    def test_action_dari_payload(self):
        row = self._row({"action": "rework", "defect_type": "x", "scrap_qty": 1})

        self.assertEqual(row["action"], "rework")

    def test_action_derive_dari_event_type(self):
        row = self._row({"defect_type": "x", "scrap_qty": 1}, event_type="BUNDLE_SCRAP")

        self.assertEqual(row["action"], "scrap")

    def test_fallback_defect_entries_dari_field_flat(self):
        row = self._row(
            {
                "defect_type": "kain_rusak",
                "scrap_qty": 2,
                "reason": "rusak",
                "location": "seam-1",
            }
        )

        self.assertEqual(len(row["defect_entries"]), 1)
        self.assertEqual(row["defect_entries"][0]["type"], "kain_rusak")
        self.assertEqual(row["defect_entries"][0]["location"], "seam-1")
        self.assertEqual(row["location"], "seam-1")

