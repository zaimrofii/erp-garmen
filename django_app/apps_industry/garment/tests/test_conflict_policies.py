"""Fase C.3 — `X-Conflict-Policy` (kontrak §8.2).

`last_write_wins` = lewati cek konflik & timpa version; `server_wins`/`manual`
(default) = 409 tanpa eksekusi. Policy tak dikenal -> fail-closed ke `manual`.
"""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.api.actions.executor import (
    DEFAULT_CONFLICT_POLICY,
    POLICY_LAST_WRITE_WINS,
    POLICY_MANUAL,
    POLICY_SERVER_WINS,
    is_force_requested,
    normalize_conflict_policy,
    resolve_conflict_policy,
)
from apps_industry.garment.models import Bundle
from apps_industry.garment.tests.auth import authenticate
from apps_industry.garment.tests.factories import make_bundle

POLICY_HEADER = "X-Conflict-Policy"


class ConflictPolicyPureTests(TestCase):
    """Helper murni: normalisasi policy & prioritas header."""

    def test_normalize_kosong_atau_tak_dikenal_jadi_manual(self):
        for value in (None, "", "   ", "ngawur", "last_write_wins_banget"):
            with self.subTest(value=value):
                self.assertEqual(normalize_conflict_policy(value), POLICY_MANUAL)

    def test_normalize_case_insensitive_dan_trim(self):
        self.assertEqual(
            normalize_conflict_policy(" Last_Write_Wins "), POLICY_LAST_WRITE_WINS
        )
        self.assertEqual(normalize_conflict_policy("SERVER_WINS"), POLICY_SERVER_WINS)

    def test_prioritas_force_di_atas_policy(self):
        self.assertEqual(
            resolve_conflict_policy(POLICY_SERVER_WINS, "true"), POLICY_LAST_WRITE_WINS
        )
        self.assertEqual(
            resolve_conflict_policy(POLICY_MANUAL, "1"), POLICY_LAST_WRITE_WINS
        )
        self.assertEqual(resolve_conflict_policy(POLICY_MANUAL, "false"), POLICY_MANUAL)
        self.assertEqual(resolve_conflict_policy(None, None), DEFAULT_CONFLICT_POLICY)

    def test_is_force_requested(self):
        for value in ("true", "TRUE", " true ", "1", "yes", "on"):
            with self.subTest(value=value):
                self.assertTrue(is_force_requested(value))
        for value in (None, "", "0", "false", "ngawur"):
            with self.subTest(value=value):
                self.assertFalse(is_force_requested(value))


class ConflictPolicyHttpTests(TestCase):
    """Policy lewat HTTP pada bundle DRAFT."""

    @classmethod
    def setUpTestData(cls):
        cls.bundle = make_bundle(code="BND-POL-001")

    def setUp(self):
        self.client = APIClient()
        # FASE 4.1: ActionView kini `IsAuthenticated`.
        authenticate(self.client)

    def _post(self, action="BUNDLE_START", base_version=None, policy=None):
        headers = {}
        if base_version is not None:
            headers["X-Base-Version"] = base_version
        if policy is not None:
            headers[POLICY_HEADER] = policy
        return self.client.post(
            f"/api/v1/garmen/bundles/{self.bundle.pk}/{action}/",
            {},
            format="json",
            headers=headers,
        )

    def test_last_write_wins_basi_200_dan_menimpa(self):
        versi_lama = Bundle.objects.get(pk=self.bundle.pk).version

        response = self._post(
            base_version=f"{versi_lama}-basi", policy="last_write_wins"
        )

        self.assertEqual(response.status_code, 200)
        setelah = Bundle.objects.get(pk=self.bundle.pk)
        self.assertEqual(setelah.state, "CUTTING")
        self.assertNotEqual(setelah.version, versi_lama)
        self.assertEqual(response.json()["version"], setelah.version)

    def test_server_wins_basi_409_tanpa_eksekusi(self):
        versi = Bundle.objects.get(pk=self.bundle.pk).version

        response = self._post(base_version=f"{versi}-basi", policy="server_wins")

        self.assertEqual(response.status_code, 409)
        setelah = Bundle.objects.get(pk=self.bundle.pk)
        self.assertEqual(setelah.state, "DRAFT")
        self.assertEqual(setelah.version, versi)

    def test_manual_basi_409(self):
        response = self._post(base_version="basi", policy="manual")

        self.assertEqual(response.status_code, 409)

    def test_default_manual_kalau_header_tidak_ada(self):
        response = self._post(base_version="basi")

        self.assertEqual(response.status_code, 409)

    def test_policy_tak_dikenal_fail_closed_409(self):
        response = self._post(base_version="basi", policy="ngawur")

        self.assertEqual(response.status_code, 409)

    def test_policy_case_insensitive(self):
        response = self._post(base_version="basi", policy="LAST_WRITE_WINS")

        self.assertEqual(response.status_code, 200)

    def test_last_write_wins_tanpa_base_version_tetap_200(self):
        response = self._post(policy="last_write_wins")

        self.assertEqual(response.status_code, 200)