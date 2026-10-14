"""Test endpoint sync scrap manual (`POST /api/v1/sync/scrap/`) — DRF, tanpa Odoo.

Cakupan: happy path (service di-mock → 200 + counter), anonim → 403
(permission ``IsAuthenticated``), dan ``GET`` → 405 (``get()`` tidak ada).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.test import TestCase
from rest_framework.test import APIClient

from core.auth.models import User

URL = "/api/v1/sync/scrap/"
#: Service di-import di api.py → patch nama di modul itu.
SERVICE = "integrations.erp_sync.api.ScrapSyncService"
RESULT = {"sent": 2, "failed": 0, "skipped": 1}


class SyncScrapViewTests(TestCase):
    """``POST /api/v1/sync/scrap/`` — trigger sync scrap (sinkron)."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="supervisor-scrap", password="rahasia"  # noqa: S106 - kredensial test
        )
        self.api = APIClient()
        self.api.force_authenticate(user=self.user)

    def test_post_happy_path_counter(self):
        service = MagicMock()
        service.sync_batch.return_value = RESULT

        with patch(SERVICE, return_value=service):
            response = self.api.post(URL)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), RESULT)
        service.sync_batch.assert_called_once_with()

    def test_post_tanpa_auth_403(self):
        response = APIClient().post(URL)

        self.assertEqual(response.status_code, 403)

    def test_get_405(self):
        response = self.api.get(URL)

        self.assertEqual(response.status_code, 405)
