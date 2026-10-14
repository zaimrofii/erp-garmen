"""Test endpoint aksi POST: sukses, expected_result, konflik, idempotency replay."""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.models import Bundle
from apps_industry.garment.tests.auth import authenticate
from apps_industry.garment.tests.factories import make_bundle


class ActionEndpointTests(TestCase):
    """Bundle DRAFT; aksi dijalankan lewat state machine `garment.bundle`."""

    @classmethod
    def setUpTestData(cls):
        cls.bundle = make_bundle(code="BND-001")  # state DRAFT

    def setUp(self):
        self.client = APIClient()
        # FASE 4.1: ActionView kini `IsAuthenticated` (dulu AllowAny).
        authenticate(self.client)

    def _url(self, bundle, action: str) -> str:
        return f"/api/v1/garmen/bundles/{bundle.pk}/{action}/"

    def _post(
        self,
        action: str = "BUNDLE_START",
        bundle=None,
        key: str | None = "key-1",
        base_version: str | None = None,
        policy: str | None = None,
        force: bool = False,
    ):
        bundle = bundle or self.bundle
        headers = {}
        if key:
            headers["Idempotency-Key"] = key
        if base_version:
            headers["X-Base-Version"] = base_version
        if policy:
            headers["X-Conflict-Policy"] = policy
        if force:
            headers["X-Force"] = "true"
        return self.client.post(self._url(bundle, action), {}, format="json", headers=headers)

    def _version(self, bundle) -> str:
        return Bundle.objects.get(pk=bundle.pk).version

    # ------------------------------------------------------------------- sukses
    def test_bundle_start_sukses_dan_expected_result(self):
        version_awal = self._version(self.bundle)

        response = self._post(base_version=version_awal)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["resource"], "bundles")
        self.assertEqual(body["action"], "BUNDLE_START")
        self.assertEqual(
            body["expected_result"], {"state": "CUTTING", "fields": {"state": "CUTTING"}}
        )
        self.assertNotEqual(body["version"], version_awal)
        self.assertEqual(self._version(self.bundle), body["version"])
        self.bundle.refresh_from_db()
        self.assertEqual(self.bundle.state, "CUTTING")

    def test_bundle_scrap_sukses_dengan_field_scrap(self):
        response = self._post(action="BUNDLE_SCRAP")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["expected_result"],
            {"state": "DONE", "fields": {"state": "DONE", "scrap": True}},
        )

    def test_tanpa_idempotency_key_tetap_diproses(self):
        response = self._post(key=None)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["expected_result"]["state"], "CUTTING")

    # -------------------------------------------------------------------- error
    def test_transisi_tidak_sah_400(self):
        response = self._post(action="BUNDLE_FINISH")  # FINISH hanya dari QC

        self.assertEqual(response.status_code, 400)
        self.assertIn("BUNDLE_FINISH", response.json()["detail"])

    def test_aksi_tidak_dikenal_400(self):
        response = self._post(action="NGAWUR")

        self.assertEqual(response.status_code, 400)

    def test_resource_tidak_dikenal_404(self):
        # H2.1 mendaftarkan `/garmen/orders/...` sebagai endpoint NYATA ⇒ nama
        # resource placeholder uji diganti yang benar-benar tak dikenal.
        response = self.client.post("/api/v1/garmen/tidak-ada/1/BUNDLE_START/", {})

        self.assertEqual(response.status_code, 404)

    # ------------------------------------------------------------------ konflik
    def test_conflict_409_kalau_base_version_beda(self):
        response = self._post(base_version="versi-palsu")

        self.assertEqual(response.status_code, 409)
        body = response.json()
        self.assertEqual(body["status"], "conflict")
        self.assertEqual(body["current"]["state"], "DRAFT")
        self.assertEqual(body["current"]["version"], self._version(self.bundle))
        self.bundle.refresh_from_db()
        self.assertEqual(self.bundle.state, "DRAFT")  # tidak berubah

    def test_server_wins_menolak_dengan_409(self):
        response = self._post(base_version="versi-palsu", policy="server_wins")

        self.assertEqual(response.status_code, 409)

    def test_last_write_wins_menimpa(self):
        response = self._post(base_version="versi-palsu", policy="last_write_wins")

        self.assertEqual(response.status_code, 200)
        self.bundle.refresh_from_db()
        self.assertEqual(self.bundle.state, "CUTTING")

    # -------------------------------------------------------------- idempotency
    def test_replay_idempotency_key_sama_mengembalikan_response_pertama(self):
        pertama = self._post(key="key-replay")
        version_setelah_pertama = self._version(self.bundle)

        kedua = self._post(key="key-replay")

        self.assertEqual(pertama.status_code, 200)
        self.assertEqual(kedua.status_code, 200)
        self.assertEqual(kedua["X-Idempotent-Replay"], "true")
        body_kedua = kedua.json()
        self.assertTrue(body_kedua["duplicate-ignored"])
        self.assertEqual(
            {k: v for k, v in body_kedua.items() if k != "duplicate-ignored"},
            pertama.json(),
        )
        # Aksi TIDAK dieksekusi dua kali (kalau dieksekusi, state CUTTING->lagi
        # akan jadi 400 dan version berubah).
        self.assertEqual(self._version(self.bundle), version_setelah_pertama)


class ActionViewAuthTests(TestCase):
    """FASE 4.1 (hardening): ActionView kini `IsAuthenticated` (dulu AllowAny)."""

    @classmethod
    def setUpTestData(cls):
        cls.bundle = make_bundle(code="BND-AUTH-001")  # state DRAFT

    def setUp(self):
        self.client = APIClient()
        self.url = f"/api/v1/garmen/bundles/{self.bundle.pk}/BUNDLE_START/"

    def test_anonim_403_dan_state_tidak_berubah(self):
        response = self.client.post(self.url, {}, format="json")

        self.assertEqual(response.status_code, 403)
        self.bundle.refresh_from_db()
        self.assertEqual(self.bundle.state, "DRAFT")

    def test_terautentikasi_200(self):
        authenticate(self.client)

        response = self.client.post(self.url, {}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.bundle.refresh_from_db()
        self.assertEqual(self.bundle.state, "CUTTING")
