"""Test TX-SCRAP (`OdooAdapter.push_scrap_wo`) — Django TestCase.

Model Odoo 17 = **`stock.scrap`** (BUKAN `stock.move.line` + `is_scrap`; field itu
tidak ada di build ini). ``wo`` = dict minimal ``{product_id, qty, ref, uom_id}``.

Isi: 2 test **unit** (client di-mock → tanpa jejak di Odoo) + 1 test **integrasi**
(Odoo nyata, dan tidak meninggalkan sisa).

⚠️ Catatan: `action_validate` yang sukses membuat `stock.move` **permanen** (done
moves tak bisa dihapus) dan scrap `done` tak bisa di-unlink. Karena itu jalur
"validasi sukses" diuji dengan mock; bukti E2E nyata dicatat di CONTRACT.md.

Jalankan:

    docker compose exec django python manage.py test tests.integration.test_odoo_adapter_scrap
"""

from __future__ import annotations

from unittest.mock import MagicMock

from django.test import TestCase, override_settings

from integrations.erp_sync.adapters.base import ERPResponse
from integrations.erp_sync.adapters.odoo import STAGE_SCRAP, OdooAdapter
from master.models import Product

#: Produk = "Kaos Export L" (Odoo id 100), UoM PCS (Odoo id 33).
PRODUCT_ODOO_ID = 100
PRODUCT_UOM_ID = 33
SCRAP_REF = "SCRAP-STEP9-0001"

#: Lokasi Odoo nyata: WH/WIP (asal, 53) & Virtual Locations/Scrap (tujuan, 26).
LOCATIONS = {"ODOO_LOCATION_WIP_ID": 53, "ODOO_LOCATION_SCRAP_ID": 26}

WO = {"qty": 1, "ref": SCRAP_REF, "uom_id": PRODUCT_UOM_ID}


class OdooAdapterPushScrapWoMockTests(TestCase):
    """Unit (mock client): payload `stock.scrap.create` + urutan `action_validate`."""

    def setUp(self):
        self.product = Product.objects.create(
            code="KTS-EXPORT-L", name="Kaos Export L", odoo_id=PRODUCT_ODOO_ID
        )
        self.addCleanup(self.product.delete)

        self.client_mock = MagicMock()
        self.client_mock.execute_kw.side_effect = [
            [555],                            # stock.scrap.create
            True,                             # stock.scrap.action_validate
            [{"id": 555, "state": "done"}],   # stock.scrap.read
        ]
        self.adapter = OdooAdapter(client=self.client_mock)

    @override_settings(**LOCATIONS)
    def test_push_scrap_wo_sukses(self):
        response = self.adapter.push_scrap_wo({**WO, "product_id": self.product.pk})

        self.assertTrue(response.ok, response.error)
        self.assertEqual(response.erp_id, "555")
        self.assertEqual(response.stage, STAGE_SCRAP)
        self.assertEqual(response.ref, SCRAP_REF)
        self.assertEqual(response.raw["state"], "done")

        calls = self.client_mock.execute_kw.call_args_list
        # 1) create stock.scrap dengan 5 field wajib + name/origin.
        self.assertEqual(calls[0].args[0], "stock.scrap")
        self.assertEqual(calls[0].args[1], "create")
        values = calls[0].args[2][0][0]
        self.assertEqual(values["product_id"], PRODUCT_ODOO_ID)  # Product.odoo_id
        self.assertEqual(values["scrap_qty"], 1.0)
        self.assertEqual(values["product_uom_id"], PRODUCT_UOM_ID)
        self.assertEqual(values["location_id"], LOCATIONS["ODOO_LOCATION_WIP_ID"])
        self.assertEqual(values["scrap_location_id"], LOCATIONS["ODOO_LOCATION_SCRAP_ID"])
        self.assertEqual(values["name"], SCRAP_REF)
        self.assertEqual(values["origin"], SCRAP_REF)
        # 2) action_validate pada id scrap tsb.
        self.assertEqual(calls[1].args[0], "stock.scrap")
        self.assertEqual(calls[1].args[1], "action_validate")
        self.assertEqual(calls[1].args[2], [[555]])

    @override_settings(**LOCATIONS)
    def test_push_scrap_wo_payload_kurang_field(self):
        response = self.adapter.push_scrap_wo({"ref": SCRAP_REF})

        self.assertFalse(response.ok)
        self.assertIn("tidak lengkap", response.error)
        for field in ("product_id", "qty", "uom_id"):
            self.assertIn(field, response.error)
        self.assertEqual(response.stage, STAGE_SCRAP)
        self.assertIsNone(response.erp_id)
        self.client_mock.execute_kw.assert_not_called()

    @override_settings(**LOCATIONS)
    def test_push_scrap_wo_tidak_tervalidasi_unlink_draft(self):
        # Odoo membalas wizard (stok kurang) → `action_validate` tidak mengubah
        # state → adapter WAJIB membuang draft-nya (best-effort unlink).
        self.client_mock.execute_kw.side_effect = [
            [556],                                                 # stock.scrap.create
            {"res_model": "stock.warn.insufficient.qty.scrap"},    # action_validate (wizard)
            [{"id": 556, "state": "draft"}],                       # stock.scrap.read
            True,                                                  # stock.scrap.unlink
        ]

        response = self.adapter.push_scrap_wo({**WO, "product_id": self.product.pk})

        self.assertFalse(response.ok)
        self.assertIsNone(response.erp_id)
        self.assertIn("tidak tervalidasi", response.error)
        self.assertIn("state=draft", response.error)

        calls = self.client_mock.execute_kw.call_args_list
        self.assertEqual(len(calls), 4)                      # create, validate, read, unlink
        self.assertEqual(calls[2].args[1], "read")
        self.assertEqual(calls[3].args[0], "stock.scrap")
        self.assertEqual(calls[3].args[1], "unlink")
        self.assertEqual(calls[3].args[2], [[556]])

    @override_settings(**LOCATIONS)
    def test_push_scrap_wo_validate_raise_unlink_draft(self):
        # `action_validate` melempar (mis. UserError) → draft tetap dibuang,
        # tidak ada record menggantung di Odoo.
        self.client_mock.execute_kw.side_effect = [
            [557],                                        # stock.scrap.create
            RuntimeError("UserError: cannot validate"),   # action_validate (raise)
            True,                                         # stock.scrap.unlink
        ]

        response = self.adapter.push_scrap_wo({**WO, "product_id": self.product.pk})

        self.assertFalse(response.ok)
        self.assertIsNone(response.erp_id)
        self.assertIn("cannot validate", response.error)

        calls = self.client_mock.execute_kw.call_args_list
        self.assertEqual(len(calls), 3)                   # create, validate (raise), unlink
        self.assertEqual(calls[2].args[1], "unlink")
        self.assertEqual(calls[2].args[2], [[557]])


@override_settings(**LOCATIONS)
class OdooAdapterPushScrapWoNyataTests(TestCase):
    """Integrasi (Odoo nyata): adapter menulis ke `stock.scrap` & tidak menyisakan record."""

    def setUp(self):
        self.product = Product.objects.create(
            code="KTS-EXPORT-L", name="Kaos Export L", odoo_id=PRODUCT_ODOO_ID
        )
        self.addCleanup(self.product.delete)

        self.adapter = OdooAdapter()  # client nyata dari settings (ODOO_*)
        self.addCleanup(self.adapter.close)

    def test_push_scrap_wo_odoo_nyata(self):
        response = self.adapter.push_scrap_wo({**WO, "product_id": self.product.pk})

        # Kalau tervalidasi (done), scrap tak bisa langsung dihapus Odoo -> bersihkan paksa.
        if response.erp_id:
            self.addCleanup(self._force_unlink_scrap, int(response.erp_id))

        self.assertIsInstance(response, ERPResponse)
        self.assertEqual(response.stage, STAGE_SCRAP)

        leftovers = self.adapter.client.execute_kw(
            "stock.scrap", "search", [[["name", "=", SCRAP_REF]]]
        )
        if response.ok:
            self.assertTrue(leftovers)        # ada -> dibersihkan oleh addCleanup
        else:
            self.assertEqual(leftovers, [])   # adapter sudah rollback draft-nya

    def _force_unlink_scrap(self, scrap_id: int) -> None:
        """Cleanup: kembalikan ke `draft` lalu `unlink` (scrap `done` tak bisa langsung dihapus)."""
        client = self.adapter.client
        client.execute_kw("stock.scrap", "write", [[scrap_id], {"state": "draft"}])
        client.execute_kw("stock.scrap", "unlink", [[scrap_id]])
