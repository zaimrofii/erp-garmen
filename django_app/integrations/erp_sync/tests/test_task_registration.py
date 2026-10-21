"""Regression PRA-0B.1 — task push `erp_sync` harus terdaftar di Celery.

Bug asli: ``ErpSyncConfig.ready()`` tidak mengimpor modul ``tasks_*_push``,
sehingga worker membuang pesan dengan "Received unregistered task" dan push
inventory adjustment tidak pernah dieksekusi.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from config.celery import app

PUSH_TASKS = [
    "erp_sync.push_customer_invoice",
    "erp_sync.push_inventory_adjustment",
    "erp_sync.push_journal_entry",
    "erp_sync.push_master_bom",
    "erp_sync.push_master_location",
    "erp_sync.push_master_partner",
    "erp_sync.push_master_product",
    "erp_sync.push_master_tax",
    "erp_sync.push_master_uom",
    "erp_sync.push_master_warehouse",
    "erp_sync.push_payment",
    "erp_sync.push_purchase_order",
    "erp_sync.push_sale_order",
    "erp_sync.push_stock_transfer",
    "erp_sync.push_vendor_bill",
]


class TaskRegistrationTests(SimpleTestCase):
    def test_semua_push_task_terdaftar(self):
        missing = [name for name in PUSH_TASKS if name not in app.tasks]

        self.assertEqual(missing, [], f"Task belum terdaftar: {missing}")

    def test_task_inventory_adjustment_terdaftar(self):
        self.assertIn("erp_sync.push_inventory_adjustment", app.tasks)
