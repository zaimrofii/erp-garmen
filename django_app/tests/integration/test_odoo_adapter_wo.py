"""Test integrasi `OdooAdapter.push_wip_issue_wo` (Step 7) — Django TestCase.

Menguji method **baru** ``push_wip_issue_wo(wo)`` (method lama
``push_wip_issue(payload)`` tidak disentuh). ``wo`` = dict minimal
``{product_id, qty, ref, uom_id?}``.

Test ini **memanggil Odoo sungguhan**: ``stock.move`` benar-benar dibuat lalu
dihapus lagi di cleanup (``unlink``). Karena itu dibutuhkan:

* kredensial Odoo valid di settings (``ODOO_URL/DB/USER/API_KEY``) **dengan hak
  DELETE pada ``stock.move``** (mis. akun admin) — api_bot saja tidak cukup;
* ``ODOO_LOCATION_WIP_ID`` & ``ODOO_LOCATION_PRODUCTION_ID`` (di sini di-override
  ke id lokasi nyata di Odoo: ``WH/WIP``=53 dan
  ``Virtual Locations/Production``=24 — produksi = **virtual location**,
  konsumsi benar-benar keluar persediaan).

Jalankan:

    docker compose exec django python manage.py test tests.integration.test_odoo_adapter_wo
"""

from __future__ import annotations

from django.test import TestCase, override_settings

from integrations.erp_sync.adapters.base import STAGE_WIP
from integrations.erp_sync.adapters.odoo import OdooAdapter
from master.models import Product

#: Produk yang dipakai = "Kaos Export L" (Odoo id 100), UoM PCS (Odoo id 33).
PRODUCT_ODOO_ID = 100
PRODUCT_UOM_ID = 33

#: Lokasi Odoo nyata: WH/WIP (sumber, 53) -> Virtual Locations/Production (tujuan, 24).
LOCATIONS = {"ODOO_LOCATION_WIP_ID": 53, "ODOO_LOCATION_PRODUCTION_ID": 24}

#: Payload WO contoh (product_id diisi pk Product Django di dalam test).
WO = {"qty": 12, "ref": "WO-STEP7-0001", "uom_id": PRODUCT_UOM_ID}


@override_settings(**LOCATIONS)
class OdooAdapterPushWipIssueWoTests(TestCase):
    """2 test: happy path (Odoo nyata + cleanup `unlink`) & payload kurang field."""

    def setUp(self):
        self.product = Product.objects.create(
            code="KTS-EXPORT-L", name="Kaos Export L", odoo_id=PRODUCT_ODOO_ID
        )
        self.addCleanup(self.product.delete)

        self.adapter = OdooAdapter()  # client nyata dari settings (ODOO_*)
        self.addCleanup(self.adapter.close)

    # --------------------------------------------------------------- happy path
    def test_push_wip_issue_wo_sukses(self):
        response = self.adapter.push_wip_issue_wo({**WO, "product_id": self.product.pk})

        # Cleanup manual: hapus stock.move yang baru dibuat di Odoo (butuh hak delete).
        if response.erp_id:
            self.addCleanup(self._unlink_stock_move, int(response.erp_id))

        self.assertTrue(response.ok, response.error)
        self.assertEqual(response.stage, STAGE_WIP)
        self.assertEqual(response.ref, "WO-STEP7-0001")
        self.assertIsNotNone(response.erp_id)

        values = response.raw["values"]
        self.assertEqual(values["product_id"], PRODUCT_ODOO_ID)  # Product.odoo_id
        self.assertEqual(values["product_uom_qty"], 12.0)
        self.assertEqual(values["location_id"], LOCATIONS["ODOO_LOCATION_WIP_ID"])
        self.assertEqual(values["location_dest_id"], LOCATIONS["ODOO_LOCATION_PRODUCTION_ID"])
        # Kontrak baru (Fase I7), dipatok LITERAL supaya tidak ikut berubah kalau
        # dict override di atas keliru: WIP `WH/WIP`(53) → virtual
        # `Virtual Locations/Production`(24) — konsumsi keluar persediaan.
        self.assertEqual(values["location_id"], 53)
        self.assertEqual(values["location_dest_id"], 24)
        self.assertEqual(values["product_uom"], PRODUCT_UOM_ID)
        self.assertEqual(values["name"], "WO-STEP7-0001")

    def _unlink_stock_move(self, move_id: int) -> None:
        """Cleanup manual via Odoo `unlink` (butuh hak DELETE pada stock.move)."""
        self.adapter.client.execute_kw("stock.move", "unlink", [[move_id]])

    # ------------------------------------------------------------- negative path
    def test_push_wip_issue_wo_payload_kurang_field(self):
        response = self.adapter.push_wip_issue_wo({"ref": "WO-STEP7-0001"})

        self.assertFalse(response.ok)
        self.assertIn("tidak lengkap", response.error)
        self.assertIn("product_id", response.error)
        self.assertIn("qty", response.error)
        self.assertEqual(response.stage, STAGE_WIP)
        self.assertIsNone(response.erp_id)
