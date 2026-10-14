"""Fase C.1 — idempotency replay action endpoint (kontrak §5.1, prototype §8.4).

Aturan yang dikunci di sini:

  * key sama + request sama -> response pertama diputar ulang (200) + flag
    `duplicate-ignored: true` + header `X-Idempotent-Replay: true`, TANPA eksekusi ulang;
  * hanya response 200 yang di-cache (400/409 tidak);
  * `Idempotency-Key` opsional;
  * scope record = (resource, resource_id, action, request_hash) — bukan global;
  * record kedaluwarsa -> request baru.
"""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps_industry.garment.models import Bundle
from apps_industry.garment.tests.auth import authenticate
from apps_industry.garment.tests.factories import make_bundle
from core.idempotency.models import IdempotencyRecord

IDEMPOTENCY_HEADER = "Idempotency-Key"


class IdempotencyReplayTests(TestCase):
    """Bundle DRAFT; key sama dua kali harus mengembalikan response pertama."""

    @classmethod
    def setUpTestData(cls):
        cls.bundle = make_bundle(code="BND-IDEM-001")

    def setUp(self):
        self.client = APIClient()
        # FASE 4.1: ActionView kini `IsAuthenticated`.
        authenticate(self.client)

    def _post(self, action="BUNDLE_START", key=None, bundle=None, headers=None):
        bundle = bundle or self.bundle
        all_headers = dict(headers or {})
        if key is not None:
            all_headers[IDEMPOTENCY_HEADER] = key
        return self.client.post(
            f"/api/v1/garmen/bundles/{bundle.pk}/{action}/",
            {},
            format="json",
            headers=all_headers,
        )

    def test_key_sama_dua_kali_replay_tanpa_eksekusi_ulang(self):
        pertama = self._post(key="K1")
        setelah_pertama = Bundle.objects.get(pk=self.bundle.pk)

        kedua = self._post(key="K1")

        self.assertEqual(pertama.status_code, 200)
        self.assertEqual(kedua.status_code, 200)
        self.assertEqual(kedua["X-Idempotent-Replay"], "true")
        body = kedua.json()
        self.assertTrue(body["duplicate-ignored"])
        # Body selain flag identik dengan response pertama.
        self.assertEqual(
            {key: value for key, value in body.items() if key != "duplicate-ignored"},
            pertama.json(),
        )
        # Tidak dieksekusi ulang: state & version tidak bergerak.
        sesudah = Bundle.objects.get(pk=self.bundle.pk)
        self.assertEqual(sesudah.state, setelah_pertama.state)
        self.assertEqual(sesudah.version, setelah_pertama.version)

    def test_record_tersimpan_dengan_scope_dan_body(self):
        self._post(key="K-scope")

        record = IdempotencyRecord.objects.get(key="K-scope")
        self.assertEqual(record.resource, "bundles")
        self.assertEqual(record.resource_id, str(self.bundle.pk))
        self.assertEqual(record.action, "BUNDLE_START")
        self.assertEqual(record.response_status, 200)
        self.assertEqual(len(record.request_hash), 64)
        self.assertIsNotNone(record.created_at)
        self.assertIsNotNone(record.expires_at)
        self.assertTrue(record.response_body["ok"])

    def test_409_tidak_di_cache(self):
        response = self._post(
            action="BUNDLE_FINISH", key="K-409", headers={"X-Base-Version": "basi"}
        )

        self.assertEqual(response.status_code, 409)
        self.assertFalse(IdempotencyRecord.objects.filter(key="K-409").exists())

    def test_400_tidak_di_cache(self):
        response = self._post(action="BUNDLE_FINISH", key="K-400")  # FINISH dari QC saja

        self.assertEqual(response.status_code, 400)
        self.assertFalse(IdempotencyRecord.objects.filter(key="K-400").exists())

    def test_tanpa_key_tidak_ada_record(self):
        response = self._post()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(IdempotencyRecord.objects.count(), 0)

    def test_key_sama_untuk_request_beda_dianggap_request_baru(self):
        bundle_lain = make_bundle(code="BND-IDEM-002")

        pertama = self._post(key="K-scope2")
        lain = self._post(key="K-scope2", bundle=bundle_lain)

        self.assertEqual(pertama.status_code, 200)
        self.assertEqual(lain.status_code, 200)
        self.assertNotIn("duplicate-ignored", lain.json())
        self.assertEqual(
            IdempotencyRecord.objects.get(key="K-scope2").resource_id,
            str(bundle_lain.pk),
        )

    def test_record_kedaluwarsa_dieksekusi_sebagai_request_baru(self):
        IdempotencyRecord.objects.create(
            key="K-expired",
            resource="bundles",
            resource_id=str(self.bundle.pk),
            action="BUNDLE_START",
            request_hash="x" * 64,
            response_status=200,
            response_body={"ok": True, "versi": "lama"},
            expires_at=timezone.now() - timedelta(seconds=1),
        )

        response = self._post(key="K-expired")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertNotIn("duplicate-ignored", body)  # dieksekusi, bukan replay
        self.assertNotIn("versi", body)  # bukan body record lama
        # Record lama dihapus lalu diganti record baru (TTL baru).
        record = IdempotencyRecord.objects.get(key="K-expired")
        self.assertGreater(record.expires_at, timezone.now())
        self.assertNotIn("versi", record.response_body)