"""Test task `erp_sync.sync_scrap_accumulator` (I4) — service di-mock, tanpa Odoo.

Cakupan: happy path (return counter ``sync_batch``), registrasi nama task, dan
retry yang hanya terpicu error transport (``httpx.HTTPError``/``ConnectionError``).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
from django.test import SimpleTestCase

from integrations.erp_sync import tasks_scrap
from integrations.erp_sync.tasks_scrap import sync_scrap_accumulator

SERVICE = "integrations.erp_sync.tasks_scrap.ScrapSyncService"
RESULT = {"sent": 2, "failed": 0, "skipped": 1}


class SyncScrapAccumulatorTaskTests(SimpleTestCase):
    """Task delegasi ke ``ScrapSyncService.sync_batch``."""

    def test_happy_path_mengembalikan_counter_service(self):
        service = MagicMock()
        service.sync_batch.return_value = RESULT

        with patch(SERVICE, return_value=service):
            result = sync_scrap_accumulator.apply().get()

        self.assertEqual(result, RESULT)
        service.sync_batch.assert_called_once_with()

    def test_registrasi_nama_task(self):
        self.assertEqual(sync_scrap_accumulator.name, "erp_sync.sync_scrap_accumulator")
        self.assertIn("sync_scrap_accumulator", tasks_scrap.__all__)

    def test_error_transport_memicu_retry(self):
        # Konfigurasi retry: HANYA error transport/jaringan (impor dari tasks_master).
        self.assertIn(httpx.HTTPError, sync_scrap_accumulator.autoretry_for)
        self.assertIn(ConnectionError, sync_scrap_accumulator.autoretry_for)
        self.assertEqual(sync_scrap_accumulator.max_retries, 3)

        service = MagicMock()
        service.sync_batch.side_effect = httpx.ConnectError("odoo mati")

        with patch(SERVICE, return_value=service):
            with self.assertRaises(httpx.HTTPError):
                sync_scrap_accumulator.apply().get()
