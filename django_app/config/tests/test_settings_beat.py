"""Test `CELERY_BEAT_SCHEDULE`: 9 task master sync harian (02:00 Asia/Jakarta)
+ 1 task poll sales order (I2, tiap 5 menit)
+ 1 task sync scrap (I4, per shift 06/14/22)
+ 1 task sync invoice (I5, tiap 15 menit)
+ 1 task recompute readiness (I3.4 + I6.3 dikonsolidasi di I7, harian 04:00)
+ 1 task rekonsiliasi stok (I7, mingguan Senin 03:00) = 14 entry.

Memastikan tiap entry menunjuk **persis** ke ``name=`` task di
``integrations/erp_sync/tasks_master.py`` / ``tasks_order.py`` / ``tasks_scrap.py``
/ ``tasks_invoice.py`` / ``tasks_vendor_bill.py`` / ``tasks_reconciliation.py``
(bukan dotted path modul) dan memakai crontab yang benar.
"""

from __future__ import annotations

from celery.schedules import crontab
from django.conf import settings
from django.test import SimpleTestCase

from integrations.erp_sync import (
    tasks_invoice,
    tasks_master,
    tasks_order,
    tasks_reconciliation,
    tasks_scrap,
    tasks_vendor_bill,
)

#: key schedule → objek task Celery (diambil dari tasks_master.py, bukan string).
EXPECTED = {
    "sync-master-products": tasks_master.sync_master_products,
    "sync-master-boms": tasks_master.sync_master_boms,
    "sync-master-partners": tasks_master.sync_master_partners,
    "sync-master-locations": tasks_master.sync_master_locations,
    "sync-master-taxes": tasks_master.sync_master_taxes,
    "sync-master-uoms": tasks_master.sync_master_uoms,
    "sync-master-warehouses": tasks_master.sync_master_warehouses,
    "sync-master-journals": tasks_master.sync_master_journals,
    "sync-master-currencies": tasks_master.sync_master_currencies,
}

BEAT = settings.CELERY_BEAT_SCHEDULE

#: Entry poll sales order (I2) — task diambil dari tasks_order.py (bukan string).
SO_KEY = "sync-sale-orders"
SO_TASK = tasks_order.sync_sale_orders

#: Entry sync scrap (I4) — task diambil dari tasks_scrap.py (bukan string).
SCRAP_KEY = "sync-scrap-accumulator"
SCRAP_TASK = tasks_scrap.sync_scrap_accumulator

#: Entry sync invoice (I5) — task diambil dari tasks_invoice.py (bukan string).
INV_KEY = "sync-invoice"
INV_TASK = tasks_invoice.sync_invoice

#: Entry recompute material readiness (I3.4 + I6.3 → I7) — task diambil dari
#: tasks_vendor_bill.py (nama task: ``erp_sync.recompute_readiness``).
READY_KEY = "recompute-readiness"
READY_TASK = tasks_vendor_bill.recompute_readiness

#: Entry rekonsiliasi stok (I7) — task diambil dari tasks_reconciliation.py.
RECON_KEY = "reconcile-stock"
RECON_TASK = tasks_reconciliation.reconcile_stock


class BeatScheduleKeysTests(SimpleTestCase):
    """9 entry master sync ada di ``CELERY_BEAT_SCHEDULE``."""

    def test_sembilan_key_ada(self):
        for key in EXPECTED:
            self.assertIn(key, BEAT)

    def test_jumlah_entry_master_sync_sembilan(self):
        master_keys = [key for key in BEAT if key.startswith("sync-master-")]

        self.assertEqual(len(master_keys), 9)


class BeatScheduleTaskPathTests(SimpleTestCase):
    """Tiap entry memakai ``name=`` task persis — bukan dotted path modul."""

    def test_task_path_sama_dengan_name_task(self):
        for key, task in EXPECTED.items():
            with self.subTest(key=key):
                self.assertEqual(BEAT[key]["task"], task.name)
                self.assertTrue(task.name.startswith("erp_sync.sync_master_"))

    def test_bukan_dotted_path_modul(self):
        for key in EXPECTED:
            with self.subTest(key=key):
                self.assertNotIn(".tasks_master.", BEAT[key]["task"])
                self.assertNotIn("integrations.", BEAT[key]["task"])


class BeatScheduleCrontabTests(SimpleTestCase):
    """Semua entry memakai ``crontab(hour=2, minute=0)``."""

    def test_crontab_jam_2_menit_0(self):
        for key in EXPECTED:
            with self.subTest(key=key):
                schedule = BEAT[key]["schedule"]
                self.assertIsInstance(schedule, crontab)
                self.assertEqual(schedule.hour, {2})
                self.assertEqual(schedule.minute, {0})


class BeatScheduleTimezoneTests(SimpleTestCase):
    """TZ global Celery = Asia/Jakarta (jadwal 02:00 = WIB)."""

    def test_celery_timezone_asia_jakarta(self):
        self.assertEqual(settings.CELERY_TIMEZONE, "Asia/Jakarta")


class BeatScheduleSaleOrdersTests(SimpleTestCase):
    """Entry ``sync-sale-orders`` (I2): poll sales order tiap 5 menit."""

    def test_key_sync_sale_orders_ada(self):
        self.assertIn(SO_KEY, BEAT)

    def test_task_path_sama_dengan_name_task(self):
        self.assertEqual(BEAT[SO_KEY]["task"], SO_TASK.name)

    def test_bukan_dotted_path_modul(self):
        self.assertNotIn(".tasks_order.", BEAT[SO_KEY]["task"])
        self.assertNotIn("integrations.", BEAT[SO_KEY]["task"])

    def test_crontab_interval_5_menit(self):
        schedule = BEAT[SO_KEY]["schedule"]

        self.assertIsInstance(schedule, crontab)
        # `crontab(minute="*/5")` → {0, 5, 10, ..., 55}
        self.assertEqual(schedule.minute, set(range(0, 60, 5)))
        self.assertEqual(
            schedule.minute, {0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}
        )


class BeatScheduleScrapTests(SimpleTestCase):
    """Entry ``sync-scrap-accumulator`` (I4): per shift 06:00/14:00/22:00 WIB."""

    def test_key_sync_scrap_accumulator_ada(self):
        self.assertIn(SCRAP_KEY, BEAT)

    def test_task_path_sama_dengan_name_task(self):
        self.assertEqual(BEAT[SCRAP_KEY]["task"], SCRAP_TASK.name)

    def test_bukan_dotted_path_modul(self):
        self.assertNotIn(".tasks_scrap.", BEAT[SCRAP_KEY]["task"])
        self.assertNotIn("integrations.", BEAT[SCRAP_KEY]["task"])

    def test_crontab_tiga_shift_jam_6_14_22(self):
        schedule = BEAT[SCRAP_KEY]["schedule"]

        self.assertIsInstance(schedule, crontab)
        # `crontab(hour="6,14,22", minute=0)` → pagi/siang/malam, tepat di menit 0.
        self.assertEqual(schedule.hour, {6, 14, 22})
        self.assertEqual(schedule.minute, {0})


class BeatScheduleInvoiceTests(SimpleTestCase):
    """Entry ``sync-invoice`` (I5): tiap 15 menit (menit 0/15/30/45)."""

    def test_key_sync_invoice_ada(self):
        self.assertIn(INV_KEY, BEAT)

    def test_task_path_sama_dengan_name_task(self):
        self.assertEqual(BEAT[INV_KEY]["task"], INV_TASK.name)

    def test_bukan_dotted_path_modul(self):
        self.assertNotIn(".tasks_invoice.", BEAT[INV_KEY]["task"])
        self.assertNotIn("integrations.", BEAT[INV_KEY]["task"])

    def test_crontab_interval_15_menit(self):
        schedule = BEAT[INV_KEY]["schedule"]

        self.assertIsInstance(schedule, crontab)
        # `crontab(minute="*/15")` → {0, 15, 30, 45}
        self.assertEqual(schedule.minute, set(range(0, 60, 15)))
        self.assertEqual(schedule.minute, {0, 15, 30, 45})


class BeatScheduleRecomputeReadinessTests(SimpleTestCase):
    """Entry ``recompute-readiness`` (konsolidasi I3.4+I6.3 → I7): harian 04:00 WIB."""

    def test_key_recompute_readiness_ada(self):
        self.assertIn(READY_KEY, BEAT)

    def test_entry_lama_sync_vendor_bills_sudah_dihapus(self):
        self.assertNotIn("sync-vendor-bills", BEAT)

    def test_task_path_sama_dengan_name_task(self):
        self.assertEqual(BEAT[READY_KEY]["task"], READY_TASK.name)

    def test_bukan_dotted_path_modul(self):
        self.assertNotIn(".tasks_vendor_bill.", BEAT[READY_KEY]["task"])
        self.assertNotIn("integrations.", BEAT[READY_KEY]["task"])

    def test_crontab_harian_jam_4(self):
        schedule = BEAT[READY_KEY]["schedule"]

        self.assertIsInstance(schedule, crontab)
        # `crontab(hour=4, minute=0)` → sekali sehari, 04:00 WIB.
        self.assertEqual(schedule.hour, {4})
        self.assertEqual(schedule.minute, {0})


class BeatScheduleReconciliationTests(SimpleTestCase):
    """Entry ``reconcile-stock`` (I7): mingguan Senin 03:00 WIB."""

    def test_key_reconcile_stock_ada(self):
        self.assertIn(RECON_KEY, BEAT)

    def test_task_path_sama_dengan_name_task(self):
        self.assertEqual(BEAT[RECON_KEY]["task"], RECON_TASK.name)

    def test_bukan_dotted_path_modul(self):
        self.assertNotIn(".tasks_reconciliation.", BEAT[RECON_KEY]["task"])
        self.assertNotIn("integrations.", BEAT[RECON_KEY]["task"])

    def test_crontab_mingguan_senin_jam_3(self):
        schedule = BEAT[RECON_KEY]["schedule"]

        self.assertIsInstance(schedule, crontab)
        # `crontab(day_of_week=1, hour=3, minute=0)` → Senin 03:00 WIB.
        self.assertEqual(schedule.day_of_week, {1})
        self.assertEqual(schedule.hour, {3})
        self.assertEqual(schedule.minute, {0})


class BeatScheduleTotalTests(SimpleTestCase):
    """9 master + 1 SO + 1 scrap + 1 invoice + 1 recompute readiness + 1 rekonsiliasi = 14."""

    def test_jumlah_entry_total_empat_belas(self):
        self.assertEqual(len(BEAT), 14)

    def test_sembilan_entry_master_tetap_utuh(self):
        master_keys = [key for key in BEAT if key.startswith("sync-master-")]

        self.assertEqual(len(master_keys), 9)
        self.assertEqual(set(master_keys), set(EXPECTED))
