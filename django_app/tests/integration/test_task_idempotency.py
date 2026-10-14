"""Test **idempotency di layer TASK** (`erp_sync.push_wip_issue`) — Odoo NYATA.

Adapter sengaja tetap stateless; idempotency ada di `tasks._push_stage` +
`SyncRecord`. Test ini memanggil task **dua kali** dengan SyncRecord/reference
yang **sama**:

  * call ke-1 → status ``sent``            (membuat **1** ``stock.move`` di Odoo);
  * call ke-2 → status ``duplicate-ignored`` (adapter **tidak** dipanggil).

Bukti: jumlah ``stock.move`` dengan ``reference`` tsb tetap **1** (tidak bertambah).

Butuh kredensial Odoo dengan hak DELETE pada ``stock.move`` (mis. akun master)
untuk membersihkan move hasil test.

Jalankan:

    docker compose exec django python manage.py test tests.integration.test_task_idempotency
"""

from __future__ import annotations

from django.test import TestCase, override_settings

from integrations.erp_sync.adapters.odoo import OdooAdapter
from integrations.erp_sync.idempotency import STAGE_WIP, SyncIdempotency
from integrations.erp_sync.tasks import push_wip_issue
from master.models import Product

PRODUCT_CODE = "KTS-EXPORT-L"
PRODUCT_ODOO_ID = 100
REF = "WO-IDEM-STEP3-0001"

LOCATIONS = {
    "ODOO_LOCATION_WIP_ID": 53,
    "ODOO_LOCATION_PRODUCTION_ID": 24,
    "ODOO_LOCATION_FG_ID": 54,
    "ODOO_LOCATION_SCRAP_ID": 26,
}


@override_settings(**LOCATIONS)
class TaskPushWipIssueIdempotencyTests(TestCase):
    """`push_wip_issue` 2x dengan SyncRecord/reference sama → hanya 1 stock.move di Odoo."""

    def setUp(self):
        self.product = Product.objects.create(
            code=PRODUCT_CODE, name="Kaos Export L", odoo_id=PRODUCT_ODOO_ID
        )
        self.addCleanup(self.product.delete)

        self.payload = {"product_ref": PRODUCT_CODE, "qty": 5, "ref": REF}
        self.record = SyncIdempotency().get_or_create_sync_record(
            "work_order", REF, STAGE_WIP, self.payload
        )

        self.odoo = OdooAdapter()  # client nyata (untuk hitung & cleanup)
        self.addCleanup(self.odoo.close)
        self.addCleanup(self._cleanup_moves)

    # ------------------------------------------------------------------ helper
    def _count_moves(self) -> int:
        """Jumlah `stock.move` di Odoo dengan reference test ini (bukti tidak bertambah)."""
        return self.odoo.client.execute_kw(
            "stock.move", "search_count", [[["reference", "=", REF]]]
        )

    def _cleanup_moves(self) -> None:
        """Cleanup manual: hapus `stock.move` yang dibuat test (butuh hak delete)."""
        ids = self.odoo.client.execute_kw("stock.move", "search", [[["reference", "=", REF]]])
        if ids:
            self.odoo.client.execute_kw("stock.move", "unlink", [ids])

    # -------------------------------------------------------------------- test
    def test_push_dua_kali_hanya_satu_move_di_odoo(self):
        args = ["work_order", REF, self.payload, self.record.pk]

        # Call ke-1: benar-benar dikirim ke Odoo -> 1 stock.move.
        first = push_wip_issue.apply(args=args).get()
        self.assertEqual(first["status"], "sent")
        after_first = self._count_moves()
        self.assertEqual(after_first, 1)

        # Call ke-2 (SyncRecord/reference SAMA): duplicate-ignored, tanpa move baru.
        second = push_wip_issue.apply(args=args).get()
        self.assertEqual(second["status"], "duplicate-ignored")
        self.assertEqual(second["erp_id"], first["erp_id"])

        self.assertEqual(self._count_moves(), after_first)  # TIDAK bertambah
