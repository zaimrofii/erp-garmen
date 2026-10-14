"""Fase C.2 — conflict check `X-Base-Version` vs `Bundle.version` (kontrak §5.2/§8.4).

409 body yang dibaca frontend (`api-client.ts` -> `readConflictCurrent()`):
`body['current'] = {version, state, current_work_center}` — dan prototipe §8.4
menulis hal yang sama. Alias bersarang `conflict.current` berisi isi identik.
"""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.models import Bundle
from apps_industry.garment.tests.auth import authenticate
from apps_industry.garment.tests.factories import make_bundle, make_work_center

BASE_VERSION_HEADER = "X-Base-Version"


class ConflictResponseTests(TestCase):
    """Bundle DRAFT di work center SEWING-1."""

    @classmethod
    def setUpTestData(cls):
        cls.work_center = make_work_center(code="SEWING-1")
        cls.bundle = make_bundle(code="BND-CF-001", current_work_center=cls.work_center)

    def setUp(self):
        self.client = APIClient()
        # FASE 4.1: ActionView kini `IsAuthenticated`.
        authenticate(self.client)

    def _post(self, action="BUNDLE_START", base_version=None, bundle=None, headers=None):
        bundle = bundle or self.bundle
        all_headers = dict(headers or {})
        if base_version is not None:
            all_headers[BASE_VERSION_HEADER] = base_version
        return self.client.post(
            f"/api/v1/garmen/bundles/{bundle.pk}/{action}/",
            {},
            format="json",
            headers=all_headers,
        )

    def test_version_basi_409_dengan_current_lengkap(self):
        bundle_db = Bundle.objects.get(pk=self.bundle.pk)

        response = self._post(base_version="versi-basi")
        body = response.json()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(body["status"], "conflict")
        current = body["current"]
        self.assertEqual(current["version"], bundle_db.version)
        self.assertEqual(current["state"], "DRAFT")
        self.assertEqual(current["current_work_center"], "SEWING-1")
        # Alias bersarang (Fase C) = isi identik.
        self.assertEqual(body["conflict"]["current"], current)

    def test_current_work_center_null_kalau_belum_di_wc(self):
        bundle = make_bundle(code="BND-CF-002")

        response = self._post(bundle=bundle, base_version="versi-basi")

        self.assertEqual(response.status_code, 409)
        self.assertIsNone(response.json()["current"]["current_work_center"])

    def test_version_benar_200_bukan_409(self):
        versi = Bundle.objects.get(pk=self.bundle.pk).version

        response = self._post(base_version=versi)

        self.assertEqual(response.status_code, 200)

    def test_tanpa_header_base_version_tidak_cek_konflik(self):
        response = self._post()

        self.assertEqual(response.status_code, 200)

    def test_base_version_kosong_dianggap_tidak_ada(self):
        response = self._post(headers={BASE_VERSION_HEADER: ""})

        self.assertEqual(response.status_code, 200)

    def test_409_tidak_mengubah_state_dan_version(self):
        sebelum = Bundle.objects.get(pk=self.bundle.pk)

        response = self._post(base_version="versi-basi")

        sesudah = Bundle.objects.get(pk=self.bundle.pk)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(sesudah.state, sebelum.state)
        self.assertEqual(sesudah.version, sebelum.version)

    def test_409_membawa_version_terbaru_bukan_version_klien(self):
        """Skenario nyata: UI pegang version lama, operator lain sudah maju."""
        versi_lama = Bundle.objects.get(pk=self.bundle.pk).version
        self._post(action="BUNDLE_START", base_version=versi_lama)  # maju ke CUTTING
        versi_baru = Bundle.objects.get(pk=self.bundle.pk).version

        response = self._post(action="BUNDLE_QC", base_version=versi_lama)

        body = response.json()
        self.assertEqual(response.status_code, 409)
        self.assertNotEqual(versi_lama, versi_baru)
        self.assertEqual(body["current"]["version"], versi_baru)
        self.assertEqual(body["current"]["state"], "CUTTING")

    def test_409_dicatat_di_audit_sebagai_conflict(self):
        from core.audit.models import AuditLog

        self._post(base_version="versi-basi")

        log = AuditLog.objects.filter(result=AuditLog.Result.CONFLICT).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.action, "BUNDLE_START")