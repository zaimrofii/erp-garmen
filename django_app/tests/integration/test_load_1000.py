"""I8.12 — load test 1000 stock move: bukti idempotency (tanpa duplikasi).

**Dilewati** kecuali ``LOAD_TEST=1`` (membuat 1000 WorkOrder + Bundle dan
menjalankan task push sebanyak itu → beberapa detik sampai puluhan detik):

    LOAD_TEST=1 docker compose exec -T django python -m pytest \
        tests/integration/test_load_1000.py -q

Adapter disetel ``null`` (``ERP_ADAPTER="null"`` — **bukan** Odoo nyata).
Yang dibuktikan:

* 1000 push pertama → ``SyncRecord`` tetap **1000** (bukan 2000+);
* re-run untuk 1000 item yang sama → semuanya ``duplicate-ignored`` dan
  ``SyncRecord`` **masih 1000** — yaitu unique constraint
  ``(resource, resource_id, stage)`` benar-benar menahan duplikasi saat volume
  tinggi;
* jejak audit (I8.11) ikut terbukti: 1000 baris ``AuditLog`` pada fase pertama,
  tidak bertambah setelah re-run (percobaan yang dilewati tidak diaudit).
"""

from __future__ import annotations

import os
import unittest

from django.test import TestCase, override_settings

from apps_industry.garment.models import Bundle, WorkOrder
from apps_industry.garment.tests.factories import make_order, make_order_line
from core.audit.models import AuditLog
from integrations.erp_sync.audit import ACTION_WIP
from integrations.erp_sync.idempotency import SyncIdempotency
from integrations.erp_sync.models import SyncRecord, SyncStage
from integrations.erp_sync.tasks import push_wip_issue

#: Jumlah stock move pada load test (bisa diperkecil saat debug).
TOTAL = int(os.environ.get("LOAD_TOTAL", "1000"))


@unittest.skipUnless(
    os.environ.get("LOAD_TEST") == "1",
    "load test 1000 stock move — jalankan dengan LOAD_TEST=1",
)
@override_settings(ERP_ADAPTER="null")
class LoadThousandPushTests(TestCase):
    """1000 WorkOrder + Bundle → push WIP berulang tanpa duplikasi."""

    @classmethod
    def setUpTestData(cls):
        order = make_order(code="ORD-LOAD-1")
        line = make_order_line(order=order, qty=TOTAL)
        cls.product = line.product

        # bulk_create supaya penyiapan data cepat (Bundle.save() tak dijalankan —
        # load test ini menguji idempotensi push, bukan versioning bundle).
        work_orders = WorkOrder.objects.bulk_create(
            [
                WorkOrder(code=f"WO-LOAD-{i:04d}", order_line=line, qty_planned=1)
                for i in range(TOTAL)
            ]
        )
        Bundle.objects.bulk_create(
            [
                Bundle(code=f"BND-LOAD-{i:04d}", work_order=work_order, qty=1)
                for i, work_order in enumerate(work_orders)
            ]
        )
        cls.work_orders = work_orders

    def push_all(self):
        """Push WIP untuk semua WO; return counter status."""
        sync = SyncIdempotency()
        counters = {"sent": 0, "duplicate-ignored": 0, "lain": 0}

        for work_order in self.work_orders:
            payload = {"ref": work_order.code, "qty": 1}
            record = sync.get_or_create_sync_record(
                "work_order", str(work_order.pk), SyncStage.WIP, payload
            )
            result = push_wip_issue.apply(
                args=("work_order", str(work_order.pk), payload, record.pk)
            ).get()
            counters[result["status"]] = counters.get(result["status"], 0) + 1
        return counters

    def test_seribu_push_tidak_duplikat_dan_rerun_aman(self):
        # Fase 1 — 1000 kiriman pertama: semuanya terkirim.
        first = self.push_all()

        self.assertEqual(first["sent"], TOTAL)
        self.assertEqual(SyncRecord.objects.count(), TOTAL)  # bukan 2000
        self.assertEqual(AuditLog.objects.filter(action=ACTION_WIP).count(), TOTAL)

        # Fase 2 — re-run item yang sama: tidak ada record baru (idempotent).
        second = self.push_all()

        self.assertEqual(second["duplicate-ignored"], TOTAL)
        self.assertEqual(second["sent"], 0)
        self.assertEqual(SyncRecord.objects.count(), TOTAL)
        self.assertEqual(AuditLog.objects.filter(action=ACTION_WIP).count(), TOTAL)
