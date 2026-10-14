"""Test bentuk response action endpoint (Fase B.2) — kontrak §2/§5.

Frontend membaca:
  * `expected_result` + `version` (optimistic UI & mismatch detection), dan
  * `state` di **top level** body (`offline-queue.checkExpectedResult()`
    membandingkan `data['state']`).
"""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.models import Bundle
from apps_industry.garment.tests.auth import authenticate
from apps_industry.garment.tests.factories import make_bundle


class ActionResponseShapeTests(TestCase):
    """Bundle DRAFT; aksi dijalankan lewat state machine `garment.bundle`."""

    @classmethod
    def setUpTestData(cls):
        cls.bundle = make_bundle(code="BND-001")  # state DRAFT

    def setUp(self):
        self.client = APIClient()
        # FASE 4.1: ActionView kini `IsAuthenticated`.
        authenticate(self.client)

    def _post(self, action: str = "BUNDLE_START", bundle=None, body=None):
        bundle = bundle or self.bundle
        return self.client.post(
            f"/api/v1/garmen/bundles/{bundle.pk}/{action}/", body or {}, format="json"
        )

    def test_200_punya_ok_version_dan_expected_result(self):
        response = self._post()

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(len(body["version"]), 64)
        self.assertEqual(body["expected_result"]["state"], "CUTTING")
        self.assertTrue(body["expected_result"]["fields"]["state"])

    def test_state_top_level_untuk_check_expected_result_frontend(self):
        body = self._post().json()

        self.assertEqual(body["state"], "CUTTING")
        self.assertEqual(body["state"], body["expected_result"]["state"])

    def test_version_cocok_dengan_bundle_di_db(self):
        body = self._post().json()

        self.assertEqual(body["version"], Bundle.objects.get(pk=self.bundle.pk).version)

    def test_field_kritis_diangkat_ke_top_level(self):
        body = self._post(action="BUNDLE_SCRAP").json()

        self.assertEqual(body["expected_result"]["state"], "DONE")
        self.assertTrue(body["expected_result"]["fields"]["scrap"])
        # `checkExpectedResult()` membandingkan `data[key]` untuk tiap
        # `expected.fields[key]` → field kritis harus ada di top level.
        self.assertTrue(body["scrap"])

    def test_action_id_apa_adanya_bukan_slug(self):
        response = self._post(action="BUNDLE_START")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["action"], "BUNDLE_START")

    def test_slug_bukan_action_id_ditolak(self):
        """Backend TIDAK menebak slug: `start` bukan `BUNDLE_START` → 400."""
        response = self._post(action="start")

        self.assertEqual(response.status_code, 400)

    def test_error_409_tetap_bentuk_kontrak(self):
        response = self.client.post(
            f"/api/v1/garmen/bundles/{self.bundle.pk}/BUNDLE_START/",
            {},
            format="json",
            headers={"X-Base-Version": "versi-palsu"},
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["status"], "conflict")
        self.assertIn("current", response.json())
        self.bundle.refresh_from_db()
        self.assertEqual(self.bundle.state, "DRAFT")  # tidak berubah

    def test_error_400_tetap_punya_detail(self):
        response = self._post(action="BUNDLE_FINISH")  # FINISH hanya dari QC

        self.assertEqual(response.status_code, 400)
        self.assertIn("BUNDLE_FINISH", response.json()["detail"])