"""Test FASE 4.3: `fields` dari body aksi tersimpan di jejak `BundleEvent`.

Konteks: `POST /garmen/bundles/<id>/BUNDLE_SCRAP/` body
``{"fields": {"scrap_qty": 3, "reason": "stitch"}}`` dulu HANYA mengubah
`state`/`version` — body-nya dibuang sehingga jejak scrap hilang. Sekarang
`fields` di-merge ke ``BundleEvent.payload`` (JSONField milik `BundleEvent`),
yang juga diekspos `chatter_event_payload()` → muncul di chatter & WebSocket.
"""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.models import BundleEvent
from apps_industry.garment.tests.auth import authenticate
from apps_industry.garment.tests.factories import make_bundle


class ActionFieldsEventPayloadTests(TestCase):
    """`fields` body aksi → `BundleEvent.payload`."""

    def setUp(self):
        # FASE 4.1: ActionView butuh auth.
        self.client = APIClient()
        authenticate(self.client)
        self.bundle = make_bundle(code="BND-FIELDS-001")  # state DRAFT

    def _post(self, action: str, body: dict):
        return self.client.post(
            f"/api/v1/garmen/bundles/{self.bundle.pk}/{action}/", body, format="json"
        )

    def _latest_event(self) -> BundleEvent:
        return BundleEvent.objects.filter(bundle=self.bundle).order_by("-ts").first()

    def test_fields_scrap_tersimpan_di_event(self):
        response = self._post(
            "BUNDLE_SCRAP", {"fields": {"scrap_qty": 3, "reason": "stitch"}}
        )

        self.assertEqual(response.status_code, 200)
        event = self._latest_event()
        self.assertEqual(event.event_type, "BUNDLE_SCRAP")
        self.assertEqual(event.payload["scrap_qty"], 3)
        self.assertEqual(event.payload["reason"], "stitch")
        # state tetap ikut tercatat (perilaku lama tidak hilang)
        self.assertEqual(event.payload["state"], "DONE")

    def test_tanpa_fields_payload_hanya_state(self):
        response = self._post("BUNDLE_START", {})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._latest_event().payload, {"state": "CUTTING"})

    def test_fields_bukan_objek_diabaikan(self):
        response = self._post("BUNDLE_START", {"fields": "bukan-objek"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._latest_event().payload, {"state": "CUTTING"})

    def test_fields_ikut_terkirim_melalui_chatter(self):
        self._post("BUNDLE_SCRAP", {"fields": {"scrap_qty": 2, "reason": "fabric"}})

        response = self.client.get(f"/api/v1/chatter/bundles/{self.bundle.pk}/")

        self.assertEqual(response.status_code, 200)
        preview = response.json()["preview"]
        self.assertEqual(preview[0]["type"], "BUNDLE_SCRAP")
        self.assertEqual(preview[0]["payload"]["scrap_qty"], 2)
        self.assertEqual(preview[0]["payload"]["reason"], "fabric")

    def test_event_lama_tanpa_fields_tetap_terbaca(self):
        """Event lama (FASE 3.x) hanya punya `{"state": ...}` → tetap valid."""
        BundleEvent.objects.create(
            bundle=self.bundle,
            event_type="BUNDLE_START",
            text="BUNDLE_START → CUTTING",
            payload={"state": "CUTTING"},
        )

        response = self.client.get(f"/api/v1/chatter/bundles/{self.bundle.pk}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["preview"][0]["payload"], {"state": "CUTTING"})
