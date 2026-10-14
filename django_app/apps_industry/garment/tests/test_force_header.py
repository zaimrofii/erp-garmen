"""Fase C.4 — `X-Force: true` (prototype §8.4: "`X-Force: true` → timpa version").

Prioritas header: `X-Force` > `X-Conflict-Policy` > default `manual`.
`X-Force` HANYA melewati cek konflik — bukan validasi transisi/resource.
"""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.models import Bundle
from apps_industry.garment.tests.auth import authenticate
from apps_industry.garment.tests.factories import make_bundle

FORCE_HEADER = "X-Force"


class ForceHeaderTests(TestCase):
    """Bundle DRAFT; `X-Force` setara `last_write_wins`."""

    @classmethod
    def setUpTestData(cls):
        cls.bundle = make_bundle(code="BND-FRC-001")

    def setUp(self):
        self.client = APIClient()
        # FASE 4.1: ActionView kini `IsAuthenticated`.
        authenticate(self.client)

    def _post(
        self, action="BUNDLE_START", base_version=None, policy=None, force=None, bundle=None
    ):
        headers = {}
        if base_version is not None:
            headers["X-Base-Version"] = base_version
        if policy is not None:
            headers["X-Conflict-Policy"] = policy
        if force is not None:
            headers[FORCE_HEADER] = force
        bundle = bundle or self.bundle
        return self.client.post(
            f"/api/v1/garmen/bundles/{bundle.pk}/{action}/",
            {},
            format="json",
            headers=headers,
        )

    def test_force_true_basi_200_dan_menimpa_version(self):
        versi_lama = Bundle.objects.get(pk=self.bundle.pk).version

        response = self._post(base_version="versi-basi", force="true")

        self.assertEqual(response.status_code, 200)
        setelah = Bundle.objects.get(pk=self.bundle.pk)
        self.assertEqual(setelah.state, "CUTTING")
        self.assertNotEqual(setelah.version, versi_lama)
        self.assertEqual(response.json()["version"], setelah.version)

    def test_force_menang_atas_policy_manual_dan_server_wins(self):
        for policy in ("manual", "server_wins"):
            with self.subTest(policy=policy):
                bundle = make_bundle(code=f"BND-FRC-P-{policy}")

                response = self._post(
                    bundle=bundle, base_version="versi-basi", policy=policy, force="true"
                )

                self.assertEqual(response.status_code, 200)

    def test_force_variasi_nilai_true(self):
        for force in ("true", "TRUE", "1", "yes", "on"):
            with self.subTest(force=force):
                bundle = make_bundle(code=f"BND-FRC-T-{force}")

                response = self._post(bundle=bundle, base_version="versi-basi", force=force)

                self.assertEqual(response.status_code, 200)

    def test_force_nilai_lain_tidak_aktif(self):
        for force in ("false", "0", "ngawur"):
            with self.subTest(force=force):
                bundle = make_bundle(code=f"BND-FRC-F-{force}")

                response = self._post(bundle=bundle, base_version="versi-basi", force=force)

                self.assertEqual(response.status_code, 409)

    def test_force_tidak_melewati_validasi_transisi(self):
        response = self._post(action="BUNDLE_FINISH", base_version="versi-basi", force="true")

        self.assertEqual(response.status_code, 400)

    def test_force_tidak_melewati_resource_tak_dikenal(self):
        # H2.1: `/garmen/orders/` kini endpoint nyata ⇒ placeholder diganti.
        response = self.client.post(
            "/api/v1/garmen/tidak-ada/1/BUNDLE_START/",
            {},
            format="json",
            headers={FORCE_HEADER: "true"},
        )

        self.assertEqual(response.status_code, 404)

    def test_force_tanpa_base_version_tetap_200(self):
        response = self._post(force="true")

        self.assertEqual(response.status_code, 200)