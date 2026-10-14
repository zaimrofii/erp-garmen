"""Test integrasi audit log di action endpoint & sync endpoint (Fase 6).

Read-only endpoint (list/detail/schema/chatter) sengaja TIDAK diaudit — itu
diuji lewat tidak adanya baris audit setelah GET.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.tests.auth import authenticate
from apps_industry.garment.tests.factories import make_bundle
from core.audit.models import AuditLog
from core.auth.models import User
from integrations.erp_sync.models import SyncStatus

SYNC_URL = "/api/v1/sync/odoo/WIP/"
DELAY_WIP = "integrations.erp_sync.api.push_wip_issue.delay"
SYNC_BODY = {
    "resource": "work_order",
    "resource_id": "WO-AUDIT-1",
    "payload": {"product_ref": "PROD-1", "qty": 5, "ref": "WO-AUDIT-1"},
}


class ActionAuditTests(TestCase):
    """Aksi operator harus meninggalkan jejak audit."""

    def setUp(self):
        self.api = APIClient()
        # FASE 4.1: ActionView kini `IsAuthenticated` (dulu AllowAny).
        authenticate(self.api)
        self.bundle = make_bundle(code="BND-AUDIT-1")

    def url(self, action: str = "BUNDLE_START") -> str:
        return f"/api/v1/garmen/bundles/{self.bundle.pk}/{action}/"

    def post(self, action: str = "BUNDLE_START", **headers):
        return self.api.post(self.url(action), {}, format="json", **headers)

    def test_aksi_sukses_tercatat_ok(self):
        response = self.post(**{"HTTP_IDEMPOTENCY_KEY": "audit-key-1"})

        self.assertEqual(response.status_code, 200)
        log = AuditLog.objects.get(action="BUNDLE_START")
        self.assertEqual(log.resource, "bundles")
        self.assertEqual(log.resource_id, str(self.bundle.pk))
        self.assertEqual(log.result, AuditLog.Result.OK)
        self.assertEqual(log.payload["status"], 200)
        self.assertEqual(log.ip_address, "127.0.0.1")
        self.assertTrue(log.request_id)  # dari RequestIDMiddleware

    def test_aksi_tidak_dikenal_tercatat_denied(self):
        response = self.post(action="BUNDLE_NGACO")

        self.assertEqual(response.status_code, 400)
        log = AuditLog.objects.get(action="BUNDLE_NGACO")
        self.assertEqual(log.result, AuditLog.Result.DENIED)

    def test_konflik_versi_tercatat_conflict(self):
        response = self.post(**{"HTTP_X_BASE_VERSION": "versi-basi"})

        self.assertEqual(response.status_code, 409)
        log = AuditLog.objects.get(action="BUNDLE_START")
        self.assertEqual(log.result, AuditLog.Result.CONFLICT)

    def test_replay_idempoten_tidak_menambah_audit(self):
        headers = {"HTTP_IDEMPOTENCY_KEY": "audit-key-2"}

        self.post(**headers)
        self.post(**headers)  # replay: tidak mengeksekusi apa pun

        self.assertEqual(AuditLog.objects.filter(action="BUNDLE_START").count(), 1)

    def test_request_id_dan_user_agent_dari_header_klien(self):
        self.post(**{"HTTP_X_REQUEST_ID": "rid-kiosk", "HTTP_USER_AGENT": "kiosk-lini-1"})

        log = AuditLog.objects.latest("id")
        self.assertEqual(log.request_id, "rid-kiosk")
        self.assertEqual(log.user_agent, "kiosk-lini-1")

    def test_endpoint_read_only_tidak_diaudit(self):
        self.api.get("/api/v1/garmen/bundles/?limit=1")
        self.api.get("/api/v1/garmen/bundles/1/")
        self.api.get("/api/v1/chatter/bundles/1?limit=2")

        self.assertEqual(AuditLog.objects.count(), 0)


class SyncAuditTests(TestCase):
    """Permintaan sync ERP juga meninggalkan jejak audit."""

    def setUp(self):
        # `/api/v1/sync/odoo/<stage>/` memakai IsAuthenticated sejak I8.5
        # (sebelumnya AllowAny, jadi request anonim pun tercatat) → klien
        # di-autentikasi agar tetap menguji jalur sukses & duplicate-ignored.
        self.api = APIClient()
        self.api.force_authenticate(
            user=User.objects.create_user(
                username="auditor-sync",
                password="rahasia",  # noqa: S106 - kredensial test
            )
        )

    def test_sync_masuk_queue_tercatat_ok(self):
        with patch(DELAY_WIP, return_value=SimpleNamespace(id="task-audit")):
            response = self.api.post(SYNC_URL, SYNC_BODY, format="json")

        self.assertEqual(response.status_code, 200)
        log = AuditLog.objects.get(action="SYNC_WIP")
        self.assertEqual(log.resource, "work_order")
        self.assertEqual(log.resource_id, "WO-AUDIT-1")
        self.assertEqual(log.result, AuditLog.Result.OK)
        self.assertEqual(log.metadata["status"], "queued")
        self.assertEqual(log.metadata["task_id"], "task-audit")
        self.assertEqual(log.payload["qty"], 5)

    def test_sync_duplicate_ignored_tercatat_dengan_erp_id(self):
        from integrations.erp_sync.models import SyncRecord

        SyncRecord.objects.create(
            resource="work_order",
            resource_id="WO-AUDIT-1",
            stage="WIP",
            status=SyncStatus.SENT,
            erp_id="MOVE-9",
            payload=SYNC_BODY["payload"],
        )

        with patch(DELAY_WIP) as delay:
            response = self.api.post(SYNC_URL, SYNC_BODY, format="json")

        self.assertEqual(response.status_code, 200)
        delay.assert_not_called()
        log = AuditLog.objects.get(action="SYNC_WIP")
        self.assertEqual(log.metadata["status"], "duplicate-ignored")
        self.assertEqual(log.metadata["erp_id"], "MOVE-9")
