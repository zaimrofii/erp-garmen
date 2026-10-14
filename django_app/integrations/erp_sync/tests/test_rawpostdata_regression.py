"""Regresi: `SyncOdooView` tidak boleh menyentuh `request.body`.

**Kenapa ada:** di server ASGI live (daphne) stream body sudah dikonsumsi
sebelum view jalan, sehingga `request.body` melempar `RawPostDataException` →
500 padahal body VALID. Test lama (APIClient materialisasi body + CSRF
di-bypass `force_authenticate`) tidak mereproduksi ini.

**Cara menangkap deterministik:** `request.body` di-patch agar MELEMPAR saat
diakses (mensimulasikan kondisi ASGI). Endpoint dengan body VALID harus tetap
merespons normal (200) dan `request.body` **tidak pernah** diakses.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import PropertyMock, patch

from django.http import HttpRequest, RawPostDataException
from django.test import TestCase
from rest_framework.test import APIClient

from core.auth.models import User
from integrations.erp_sync.idempotency import STAGE_WIP

URL_WIP = "/api/v1/sync/odoo/WIP/"
BODY = {"resource": "work_order", "resource_id": "WO-REG-1", "payload": {"qty": 1}}
DELAY_WIP = "integrations.erp_sync.api.push_wip_issue.delay"


class SyncOdooViewRawPostDataRegressionTests(TestCase):
    """Pastikan endpoint tidak pernah membaca `request.body` (anti-500 ASGI)."""

    def setUp(self):
        self.api = APIClient()
        self.user = User.objects.create_user(
            username="reg-sync", password="rahasia"  # noqa: S106 - kredensial test
        )
        self.api.force_authenticate(user=self.user)

    def test_body_valid_tidak_500_dan_body_tak_disentuh(self):
        with patch.object(
            HttpRequest,
            "body",
            new_callable=PropertyMock,
            side_effect=RawPostDataException("stream sudah dikonsumsi (simulasi ASGI)"),
        ) as body_prop:
            with patch(DELAY_WIP, return_value=SimpleNamespace(id="task-reg")):
                response = self.api.post(URL_WIP, BODY, format="json")

        self.assertNotEqual(response.status_code, 500)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["stage"], STAGE_WIP)
        self.assertEqual(response.json()["status"], "queued")
        body_prop.assert_not_called()
