"""Test endpoint schema bundle + chatter preview (Kontrak §1 & §8)."""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.models import Bundle, BundleEvent
from apps_industry.garment.tests.factories import make_bundle, make_work_center


class BundleSchemaTests(TestCase):
    """Bundle di state SEWING dengan work center + chatter."""

    @classmethod
    def setUpTestData(cls):
        cls.work_center = make_work_center(code="SEWING-1")
        cls.bundle = make_bundle(
            code="BND-001",
            size="L",
            qty=5,
            qty_done=2,
            state="SEWING",
            current_work_center=cls.work_center,
        )

    def setUp(self):
        self.client = APIClient()

    def _get(self, bundle=None):
        bundle = bundle or self.bundle
        return self.client.get(f"/api/v1/garmen/bundles/{bundle.pk}/schema/")

    def test_status_dan_metadata_dasar(self):
        response = self._get()

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            body["resource"],
            {
                "name": "bundles",
                "label": "Bundle",
                "id": str(self.bundle.pk),
                "version": Bundle.objects.get(pk=self.bundle.pk).version,
            },
        )
        self.assertEqual(body["industry"], "garmen")
        self.assertEqual(body["view_type"], "form")
        self.assertEqual(body["schema_version"], "1.0")
        self.assertEqual(body["title"], "Bundle #BND-001")
        self.assertEqual(body["device_hint"], "SCANNER_USB")
        self.assertEqual(response["X-Schema-Version"], "1.0")

    def test_version_sama_dengan_bundle_version(self):
        body = self._get().json()
        version = Bundle.objects.get(pk=self.bundle.pk).version

        self.assertEqual(body["version"], version)
        # Fase B.1.1: versi juga di dalam objek `resource`.
        self.assertEqual(body["resource"]["version"], version)

    def test_version_berubah_kalau_state_berubah(self):
        versi_awal = self._get().json()["version"]

        self.bundle.state = "QC"
        self.bundle.save()

        self.assertNotEqual(self._get().json()["version"], versi_awal)

    def test_state_machine_allowed_actions_dari_sewing(self):
        machine = self._get().json()["state_machine"]

        self.assertEqual(machine["current_state"], "SEWING")
        self.assertEqual(
            [state["id"] for state in machine["possible_states"]],
            ["DRAFT", "CUTTING", "SEWING", "QC", "DONE"],
        )
        # Fase B.1.2: `kind` diturunkan dari POSISI current_state.
        self.assertEqual(
            [state["kind"] for state in machine["possible_states"]],
            ["past", "past", "current", "future", "future"],
        )
        self.assertEqual(
            [action["id"] for action in machine["allowed_actions"]],
            ["BUNDLE_QC", "BUNDLE_SCRAP"],
        )
        self.assertEqual(machine["allowed_actions"][0]["mode"], "optimistic")
        self.assertEqual(machine["allowed_actions"][1]["mode"], "pessimistic")
        # Fase B.1.5: endpoint siap pakai (action_id apa adanya, bukan slug).
        self.assertEqual(
            [action["endpoint"] for action in machine["allowed_actions"]],
            [
                f"/garmen/bundles/{self.bundle.pk}/BUNDLE_QC/",
                f"/garmen/bundles/{self.bundle.pk}/BUNDLE_SCRAP/",
            ],
        )

    def test_layout_sections_dan_widget_qr_bundle(self):
        layout = self._get().json()["layout"]

        # Fase B.1.3: layout = {sections: [{id, label, fields}]}
        self.assertEqual(set(layout), {"sections"})
        section = layout["sections"][0]
        self.assertEqual(section["id"], "info-bundle")
        self.assertEqual(section["label"], "Info Bundle")
        fields = section["fields"]
        self.assertEqual(
            [field["name"] for field in fields],
            ["code", "size", "qty", "qty_done", "current_work_center", "qr_scan"],
        )
        self.assertEqual(fields[4]["value"], "SEWING-1")
        # Fase B.1.4: `type` enum kontrak + nama widget dipisah ke `widget`.
        self.assertEqual(fields[-1]["type"], "string")
        self.assertEqual(fields[-1]["widget"], "garmen-qr-bundle")
        self.assertEqual(fields[-1]["value"], "BND-001")

    def test_chatter_preview_5_plus_cursor_dan_total(self):
        for index in range(7):
            BundleEvent.objects.create(
                bundle=self.bundle, event_type=f"EVENT_{index}", text=f"e{index}"
            )

        chatter = self._get().json()["chatter"]

        self.assertEqual(len(chatter["preview"]), 5)
        self.assertEqual(chatter["total_count"], 7)
        self.assertTrue(chatter["has_more"])
        self.assertIsNotNone(chatter["next_cursor"])
        # Fase B.1: preview metadata memakai bentuk kontrak §8 (endpoint chatter
        # sendiri masih bentuk lama sampai Fase B.2).
        self.assertEqual(chatter["preview"][0]["type"], "EVENT_6")
        self.assertEqual(chatter["preview"][0]["summary"], "e6")
        self.assertEqual(chatter["preview"][0]["actor"]["id"], "system")

    def test_chatter_kurang_dari_limit(self):
        BundleEvent.objects.create(bundle=self.bundle, event_type="BUNDLE_START")

        chatter = self._get().json()["chatter"]

        self.assertEqual(len(chatter["preview"]), 1)
        self.assertEqual(chatter["total_count"], 1)
        self.assertFalse(chatter["has_more"])
        self.assertIsNone(chatter["next_cursor"])

    def test_bundle_tanpa_event_chatter_kosong(self):
        bundle_lain = make_bundle(code="BND-002")

        chatter = self._get(bundle_lain).json()["chatter"]

        self.assertEqual(chatter["preview"], [])
        self.assertEqual(chatter["total_count"], 0)
        self.assertFalse(chatter["has_more"])
