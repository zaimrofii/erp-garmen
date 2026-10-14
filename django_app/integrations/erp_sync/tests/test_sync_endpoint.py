"""Test endpoint sync manual: `POST /api/v1/sync/odoo/<stage>/` (Fase 4.2).

``.delay`` task Celery di-patch supaya test tidak butuh broker/worker dan
**tidak pernah** memanggil Odoo.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from integrations.erp_sync.idempotency import STAGE_FG, STAGE_WIP
from integrations.erp_sync.models import SyncRecord, SyncStatus
from core.auth.models import User

URL_WIP = "/api/v1/sync/odoo/WIP/"
URL_FG = "/api/v1/sync/odoo/FG/"
DELAY_WIP = "integrations.erp_sync.api.push_wip_issue.delay"
DELAY_FG = "integrations.erp_sync.api.push_fg_receipt.delay"
PAYLOAD = {"product_ref": "PROD-1", "qty": 10, "ref": "WO-DEMO-1"}
BODY = {"resource": "work_order", "resource_id": "WO-DEMO-1", "payload": PAYLOAD}


class SyncOdooViewTests(TestCase):
    """View sync: validasi, enqueue async, idempotency, duplicate-ignored."""

    def setUp(self):
        # Endpoint ini ``IsAuthenticated`` (I8.5) → test mengirim user lewat
        # ``force_authenticate``; request anonim diuji di test terpisah.
        self.api = APIClient()
        self.user = User.objects.create_user(
            username="admin-sync", password="rahasia"  # noqa: S106 - kredensial test
        )
        self.api.force_authenticate(user=self.user)

    def post(self, url: str = URL_WIP, body: dict | None = None, **headers):
        return self.api.post(url, body if body is not None else BODY, format="json", **headers)

    # ------------------------------------------------------------------ sukses
    def test_post_wip_mengembalikan_task_id(self):
        with patch(DELAY_WIP, return_value=SimpleNamespace(id="task-123")) as delay:
            response = self.post()

        data = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["status"], "queued")
        self.assertEqual(data["task_id"], "task-123")
        self.assertEqual(data["stage"], STAGE_WIP)
        self.assertEqual(data["resource"], "work_order")
        record = SyncRecord.objects.get(pk=data["sync_record_id"])
        self.assertEqual(record.status, SyncStatus.PENDING)
        self.assertEqual(record.payload, PAYLOAD)
        delay.assert_called_once_with("work_order", "WO-DEMO-1", PAYLOAD, record.pk)

    def test_post_fg_memakai_task_fg(self):
        with patch(DELAY_WIP) as delay_wip, patch(
            DELAY_FG, return_value=SimpleNamespace(id="task-fg")
        ) as delay_fg:
            response = self.post(URL_FG)

        data = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["status"], "queued")
        self.assertEqual(data["stage"], STAGE_FG)
        delay_fg.assert_called_once()
        delay_wip.assert_not_called()
        self.assertEqual(
            SyncRecord.objects.get(pk=data["sync_record_id"]).stage, STAGE_FG
        )

    def test_stage_case_insensitive(self):
        with patch(DELAY_WIP, return_value=SimpleNamespace(id="task-123")):
            response = self.post("/api/v1/sync/odoo/wip/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["stage"], STAGE_WIP)

    def test_tanpa_idempotency_key_tetap_diproses(self):
        with patch(DELAY_WIP, return_value=SimpleNamespace(id="task-123")):
            response = self.post()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "queued")

    # -------------------------------------------------------- idempotency & dup
    def test_idempotency_key_sama_dua_kali_jadi_replay(self):
        with patch(DELAY_WIP, return_value=SimpleNamespace(id="task-456")) as delay:
            first = self.post(**{"HTTP_IDEMPOTENCY_KEY": "sync-key-1"})
            second = self.post(**{"HTTP_IDEMPOTENCY_KEY": "sync-key-1"})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second["X-Idempotent-Replay"], "true")
        self.assertTrue(second.json()["duplicate-ignored"])
        self.assertEqual(second.json()["task_id"], first.json()["task_id"])
        self.assertEqual(second.json()["sync_record_id"], first.json()["sync_record_id"])
        self.assertEqual(delay.call_count, 1)
        self.assertEqual(SyncRecord.objects.count(), 1)

    def test_record_sudah_sent_dibalas_duplicate_ignored(self):
        SyncRecord.objects.create(
            resource="work_order",
            resource_id="WO-DEMO-1",
            stage=STAGE_WIP,
            status=SyncStatus.SENT,
            erp_id="MOVE-777",
            payload=PAYLOAD,
        )

        with patch(DELAY_WIP) as delay:
            response = self.post()

        data = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["status"], "duplicate-ignored")
        self.assertTrue(data["duplicate-ignored"])
        self.assertEqual(data["erp_id"], "MOVE-777")
        delay.assert_not_called()

    # ------------------------------------------------------------- validasi 400
    def test_stage_tidak_valid_400(self):
        response = self.post("/api/v1/sync/odoo/QC/")

        self.assertEqual(response.status_code, 400)
        self.assertIn("tidak dikenal", response.json()["detail"])

    def test_resource_tidak_valid_400(self):
        response = self.post(body={**BODY, "resource": "qc"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("resource", response.json()["detail"])

    def test_resource_scrap_accumulator_diarahkan_ke_endpoint_scrap(self):
        """``scrap_accumulator`` bukan jalur two-stage → 400 + petunjuk (I8.3)."""
        with patch(DELAY_WIP) as delay:
            response = self.post(body={**BODY, "resource": "scrap_accumulator"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("/api/v1/sync/scrap/", response.json()["detail"])
        delay.assert_not_called()
        self.assertEqual(SyncRecord.objects.count(), 0)

    def test_resource_order_diarahkan_ke_listener_invoice(self):
        """``order`` dibuat event-driven (listener WO selesai), bukan di sini."""
        response = self.post(body={**BODY, "resource": "order"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("WORK_ORDER_STATE_CHANGED", response.json()["detail"])

    def test_resource_bundle_tetap_diterima(self):
        """Whitelist TIDAK mempersempit resource yang memang jalur two-stage."""
        with patch(DELAY_WIP, return_value=SimpleNamespace(id="task-bnd")):
            response = self.post(body={**BODY, "resource": "bundle"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["resource"], "bundle")

    def test_resource_id_kosong_400(self):
        response = self.post(body={"resource": "work_order", "payload": PAYLOAD})

        self.assertEqual(response.status_code, 400)
        self.assertIn("resource_id", response.json()["detail"])

    def test_payload_hilang_400(self):
        response = self.post(body={"resource": "bundle", "resource_id": "1"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("payload", response.json()["detail"])

    def test_payload_kosong_400(self):
        response = self.post(body={**BODY, "payload": {}})

        self.assertEqual(response.status_code, 400)
        self.assertIn("payload", response.json()["detail"])

    def test_payload_bukan_object_400(self):
        response = self.post(body={**BODY, "payload": "bukan object"})

        self.assertEqual(response.status_code, 400)

    def test_request_tidak_valid_tidak_menulis_apa_pun(self):
        with patch(DELAY_WIP) as delay:
            self.post("/api/v1/sync/odoo/QC/")

        delay.assert_not_called()
        self.assertEqual(SyncRecord.objects.count(), 0)

    def test_trailing_slash_wajib(self):
        """Tanpa trailing slash, Django APPEND_SLASH me-redirect (301)."""
        response = self.api.post("/api/v1/sync/odoo/WIP", BODY, format="json")

        self.assertEqual(response.status_code, 301)
        self.assertTrue(response["Location"].endswith("/api/v1/sync/odoo/WIP/"))

    # ---------------------------------------------------------------- permission
    def test_anonim_403(self):
        """Permission ``IsAuthenticated`` (I8.5) — dulu ``AllowAny``."""
        with patch(DELAY_WIP) as delay:
            response = APIClient().post(URL_WIP, BODY, format="json")

        self.assertEqual(response.status_code, 403)
        delay.assert_not_called()
        self.assertEqual(SyncRecord.objects.count(), 0)

