"""E2E (Step 5): jejak satu trace melewati aksi produksi + sinkronisasi ERP.

Satu trace = dua permintaan dengan **X-Request-ID yang sama**:

  1. **aksi bundle** (endpoint aksi state machine) — jejak aksi produksi;
  2. **two-stage ERP sync** (``/api/v1/sync/odoo/WIP/``) — span ``erp_sync``.

Catatan penting: aksi bundle **sendiri tidak menyentuh erp_sync** di codebase
ini (hanya menerbitkan ``BUNDLE_STATE_CHANGED`` yang tak punya listener), jadi
span ``erp_sync`` di trace ini berasal dari two-stage sync yang dijalankan
dengan request id sama. ``ERP_ADAPTER=null`` + Celery eager -> tanpa jaringan
(Odoo/broker) sama sekali.

Jalankan:
    python manage.py test tests.integration.test_trace_bridge_e2e -v 2
"""

from __future__ import annotations

import uuid
from pathlib import Path

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps_industry.garment.tests.factories import make_bundle
from config.celery import app as celery_app
from core.auth.models import User
from trace_bridge.normalize import to_spans
from trace_bridge.reader import read_trace


@override_settings(ERP_ADAPTER="null", ODOO_UOM_ID=33)
class TraceBridgeE2ETests(TestCase):
    """Aksi bundle + two-stage sync pada satu trace id → span bisa ditelusuri."""

    def setUp(self):
        super().setUp()
        self._task_always_eager = celery_app.conf.task_always_eager
        celery_app.conf.task_always_eager = True
        self.api = APIClient()
        self.api.force_authenticate(
            user=User.objects.create_user(username="tr-operator", password="rahasia")
        )

    def tearDown(self):
        celery_app.conf.task_always_eager = self._task_always_eager
        super().tearDown()

    def test_bundle_action_produces_traceable_span(self):
        bundle = make_bundle(code="BND-TR-1", qty=1)
        trace_id = f"trace-bundle-e2e-{uuid.uuid4().hex[:8]}"

        # 1) Aksi bundle (state machine) → jejak aksi produksi.
        metadata = self.api.get(f"/api/v1/metadata/bundles/?id={bundle.pk}").json()
        action_id = metadata["state_machine"]["allowed_actions"][0]["id"]
        version = metadata["resource"]["version"]
        action = self.api.post(
            f"/api/v1/garmen/bundles/{bundle.pk}/{action_id}/",
            {},
            format="json",
            HTTP_IDEMPOTENCY_KEY=f"tr-action-{bundle.pk}",
            HTTP_X_BASE_VERSION=version,
            HTTP_X_REQUEST_ID=trace_id,
        )
        self.assertEqual(action.status_code, 200)
        # X-Request-ID diambil dari header response (middleware mengembalikannya).
        self.assertEqual(action.headers.get("X-Request-ID"), trace_id)

        # 2) Two-stage ERP sync pada trace id yang sama → span integrations.erp_sync.*
        sync = self.api.post(
            "/api/v1/sync/odoo/WIP/",
            {
                "resource": "bundle",
                "resource_id": str(bundle.pk),
                "payload": {"ref": f"WO-{bundle.pk}", "qty": 1},
            },
            format="json",
            HTTP_IDEMPOTENCY_KEY=f"tr-sync-{bundle.pk}",
            HTTP_X_REQUEST_ID=trace_id,
        )
        self.assertEqual(sync.status_code, 200)

        rows = read_trace(trace_id, Path("logs"))

        self.assertGreaterEqual(len(rows), 2)
        self.assertTrue(
            any("erp_sync" in str(row.get("logger", "")) for row in rows),
            "harus ada span dari logger integrations.erp_sync.*",
        )
        self.assertEqual(to_spans(rows, trace_id)["trace_id"], trace_id)
