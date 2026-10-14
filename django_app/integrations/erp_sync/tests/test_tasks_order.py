"""Test task `erp_sync.sync_sale_orders` (I2) — service di-mock, tanpa Odoo.

Cakupan: happy path (return counter dari service), `since` diteruskan, dan
retry hanya terpicu untuk error transport (``httpx.HTTPError``/``ConnectionError``).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
from django.test import SimpleTestCase

from integrations.erp_sync.tasks_order import sync_sale_orders

SERVICE = "integrations.erp_sync.tasks_order.SaleOrderSyncService"
RESULT = {"created": 3, "updated": 0, "skipped": 0}


class SyncSaleOrdersTaskTests(SimpleTestCase):
    """Task delegasi ke ``SaleOrderSyncService.sync``."""

    def test_happy_path_mengembalikan_counter_service(self):
        service = MagicMock()
        service.sync.return_value = RESULT

        with patch(SERVICE, return_value=service):
            result = sync_sale_orders.apply(kwargs={"since": None}).get()

        self.assertEqual(result, RESULT)
        service.sync.assert_called_once_with(since=None)

    def test_since_diteruskan_ke_service(self):
        service = MagicMock()
        service.sync.return_value = RESULT
        since = "2026-10-06 00:00:00"

        with patch(SERVICE, return_value=service):
            sync_sale_orders.apply(kwargs={"since": since}).get()

        service.sync.assert_called_once_with(since=since)

    def test_error_transport_memicu_retry(self):
        # Konfigurasi retry: HANYA error transport/jaringan.
        self.assertIn(httpx.HTTPError, sync_sale_orders.autoretry_for)
        self.assertIn(ConnectionError, sync_sale_orders.autoretry_for)
        self.assertEqual(sync_sale_orders.max_retries, 3)

        service = MagicMock()
        service.sync.side_effect = httpx.ConnectError("odoo mati")

        with patch(SERVICE, return_value=service):
            with self.assertRaises(httpx.HTTPError):
                sync_sale_orders.apply(kwargs={"since": None}).get()
