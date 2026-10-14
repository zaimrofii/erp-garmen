"""Test task `erp_sync.sync_invoice` (I5) — service di-mock, tanpa Odoo.

Cakupan: happy path (return counter ``sync_pending``), registrasi nama task, dan
retry yang hanya terpicu error transport (``httpx.HTTPError``/``ConnectionError``).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
from django.test import SimpleTestCase

from integrations.erp_sync import tasks_invoice
from integrations.erp_sync.tasks_invoice import sync_invoice

SERVICE = "integrations.erp_sync.tasks_invoice.InvoiceSyncService"
RESULT = {"sent": 3, "failed": 1, "skipped": 0}


class SyncInvoiceTaskTests(SimpleTestCase):
    """Task delegasi ke ``InvoiceSyncService.sync_pending``."""

    def test_happy_path_mengembalikan_counter_service(self):
        service = MagicMock()
        service.sync_pending.return_value = RESULT

        with patch(SERVICE, return_value=service):
            result = sync_invoice.apply().get()

        self.assertEqual(result, RESULT)
        service.sync_pending.assert_called_once_with()

    def test_registrasi_nama_task(self):
        self.assertEqual(sync_invoice.name, "erp_sync.sync_invoice")
        self.assertIn("sync_invoice", tasks_invoice.__all__)

    def test_error_transport_memicu_retry(self):
        # Konfigurasi retry: HANYA error transport/jaringan (impor dari tasks_master).
        self.assertIn(httpx.HTTPError, sync_invoice.autoretry_for)
        self.assertIn(ConnectionError, sync_invoice.autoretry_for)
        self.assertEqual(sync_invoice.max_retries, 3)

        service = MagicMock()
        service.sync_pending.side_effect = httpx.ConnectError("odoo mati")

        with patch(SERVICE, return_value=service):
            with self.assertRaises(httpx.HTTPError):
                sync_invoice.apply().get()
