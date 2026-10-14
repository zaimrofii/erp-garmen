"""E2E satu flow penuh (Fase H.1): aksi bundle → chatter → event WS → sync ERP.

Semuanya lewat **endpoint nyata** (APIClient), bukan pemanggilan fungsi internal:

  1. bundle DRAFT baru (factory) + aksi pertama dari metadata kontrak §3;
  2. ``POST /api/v1/garmen/bundles/<id>/<ACTION>/`` (Idempotency-Key + X-Base-Version) → 200;
  3. ``BundleEvent`` tertulis + tampil di endpoint chatter **dan** blok `chatter` metadata;
  4. event bus mengirim ``bundle_event`` ke group ``bundle.<id>`` — layer Channels
     disadap (brief H.1 mengizinkan "mock channel layer");
  5. ``POST /api/v1/sync/odoo/WIP/`` → 200 ``{"status": "queued"}`` + ``SyncRecord`` PENDING;
  6. task Celery dijalankan sinkron (``.apply``) dengan ``ERP_ADAPTER=null`` →
     ``SyncRecord`` berubah ``SENT`` (loop ERP tertutup tanpa jaringan).

Bukti real-time lewat socket sungguhan ada di harness live
(`frontend_app/tests/live/fase-ef-live.test.ts`, event < 1 detik dari aksi).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps_industry.garment.models import BundleEvent
from apps_industry.garment.tests.factories import make_bundle
from core.auth.models import User
from core.event_bus import websocket
from integrations.erp_sync.models import SyncRecord, SyncStatus
from integrations.erp_sync.tasks import push_wip_issue

SYNC_URL = "/api/v1/sync/odoo/WIP/"
DELAY_WIP = "integrations.erp_sync.api.push_wip_issue.delay"


class RecordedChannelLayer:
    """Layer Channels palsu: merekam `group_send` (bukti event WS dikirim)."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, dict]] = []

    async def group_send(self, group: str, message: dict) -> None:
        self.sent.append((group, message))


class E2EBundleFlowTests(TestCase):
    """Satu flow lengkap: aksi → chatter → WS → sync (Fase H.1)."""

    def setUp(self):
        websocket.reset_channel_layer_cache()
        self.addCleanup(websocket.reset_channel_layer_cache)

        self.client = APIClient()
        # Langkah terakhir flow ini menembak `/api/v1/sync/odoo/WIP/` yang
        # memakai IsAuthenticated sejak I8.5 → klien flow di-autentikasi.
        self.client.force_authenticate(
            user=User.objects.create_user(
                username="e2e-operator",
                password="rahasia",  # noqa: S106 - kredensial test
            )
        )
        self.bundle = make_bundle(code="BND-E2E-001", qty=7)

        metadata = self.client.get(f"/api/v1/metadata/bundles/?id={self.bundle.pk}").json()
        self.action_id = metadata["state_machine"]["allowed_actions"][0]["id"]
        self.version = metadata["resource"]["version"]

    def run_action(self):
        """Langkah 2 — kirim aksi pertama yang sah dari metadata."""
        return self.client.post(
            f"/api/v1/garmen/bundles/{self.bundle.pk}/{self.action_id}/",
            {},
            format="json",
            HTTP_IDEMPOTENCY_KEY=f"e2e-{self.bundle.pk}",
            HTTP_X_BASE_VERSION=self.version,
        )

    def test_flow_lengkap_aksi_chatter_ws_sync(self):
        layer = RecordedChannelLayer()

        with mock.patch("channels.layers.get_channel_layer", return_value=layer):
            response = self.run_action()

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["action"], self.action_id)
        self.assertEqual(body["id"], self.bundle.pk)
        self.assertEqual(body["expected_result"]["state"], body["state"])
        self.assertIn("fields", body["expected_result"])

        # 3a. jejak chatter tertulis
        self.bundle.refresh_from_db()
        events = BundleEvent.objects.filter(bundle=self.bundle)
        self.assertEqual(events.count(), 1)
        self.assertEqual(events.first().event_type, self.action_id)

        # 3b. chatter endpoint + blok chatter metadata memuat event itu
        chatter = self.client.get(f"/api/v1/chatter/bundles/{self.bundle.pk}?limit=20").json()
        self.assertEqual(chatter["total_count"], 1)
        self.assertEqual(chatter["preview"][0]["type"], self.action_id)
        self.assertEqual(chatter["preview"][0]["payload"]["state"], body["state"])

        metadata = self.client.get(f"/api/v1/metadata/bundles/?id={self.bundle.pk}").json()
        self.assertEqual(metadata["chatter"]["preview"][0]["type"], self.action_id)
        self.assertEqual(metadata["state_machine"]["current_state"], body["state"])

        # 4. event WS dikirim ke group bundle.<id> dengan bentuk chatter §8
        self.assertEqual(len(layer.sent), 1)
        group, message = layer.sent[0]
        self.assertEqual(group, f"bundle.{self.bundle.pk}")
        self.assertEqual(message["type"], "bundle_event")
        self.assertEqual(message["resource"], "bundles")
        self.assertEqual(message["event_name"], "BUNDLE_STATE_CHANGED")
        self.assertEqual(message["event"]["type"], self.action_id)
        self.assertEqual(
            set(message["event"]),
            {"id", "actor", "type", "summary", "payload", "created_at"},
        )

        # 5. sync WIP → 200 queued + SyncRecord PENDING (tanpa broker)
        sync_payload = {"product_ref": "SKU-E2E", "qty": 7, "ref": self.bundle.code}
        with mock.patch(DELAY_WIP, return_value=SimpleNamespace(id="e2e-task-1")) as delay:
            sync = self.client.post(
                SYNC_URL,
                {
                    "resource": "bundle",
                    "resource_id": str(self.bundle.pk),
                    "payload": sync_payload,
                },
                format="json",
                HTTP_IDEMPOTENCY_KEY=f"e2e-sync-{self.bundle.pk}",
            )

        self.assertEqual(sync.status_code, 200)
        sync_body = sync.json()
        self.assertTrue(sync_body["ok"])
        self.assertEqual(sync_body["status"], "queued")
        self.assertEqual(sync_body["stage"], "WIP")
        self.assertEqual(sync_body["resource"], "bundle")
        delay.assert_called_once()

        record = SyncRecord.objects.get(pk=sync_body["sync_record_id"])
        self.assertEqual(record.status, SyncStatus.PENDING)
        self.assertEqual(record.payload, sync_payload)

        # 6. task dijalankan sinkron dengan adapter `null` → SENT (ERP "menerima")
        with override_settings(ERP_ADAPTER="null"):
            hasil = push_wip_issue.apply(
                args=["bundle", str(self.bundle.pk), sync_payload, record.pk]
            )

        self.assertTrue(hasil.successful(), hasil.traceback)
        record.refresh_from_db()
        self.assertEqual(record.status, SyncStatus.SENT)
        self.assertTrue(str(record.erp_id).startswith("NULL-"))
        self.assertIsNotNone(record.sent_at)
        self.assertEqual(record.last_error, "")

    def test_sync_stage_ngawur_400_tidak_membuat_record(self):
        """Guard kontrak: stage selain WIP/FG ditolak sebelum menyentuh ERP."""
        response = self.client.post(
            "/api/v1/sync/odoo/NGARUT/",
            {"resource": "bundle", "resource_id": "1", "payload": {"qty": 1}},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("WIP", response.json()["detail"])
        self.assertEqual(SyncRecord.objects.count(), 0)
