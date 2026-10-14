"""Test OdooAdapter implementasi penuh (Fase 4.2) — client di-mock, tanpa jaringan.

Product diambil dari ``master.Product`` (test DB); lokasi Odoo dari settings.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from django.test import TestCase, override_settings

from integrations.erp_sync.adapters.base import STAGE_FG, STAGE_WIP
from integrations.erp_sync.adapters.odoo import OdooAdapter
from master.models import Product

PAYLOAD = {"product_ref": "PROD-1", "qty": 10, "ref": "WO-DEMO-1"}
LOCATIONS = {
    "ODOO_LOCATION_WIP_ID": 11,
    "ODOO_LOCATION_PRODUCTION_ID": 22,
    "ODOO_LOCATION_FG_ID": 33,
}


@override_settings(**LOCATIONS)
class OdooAdapterPushTests(TestCase):
    """Pemetaan payload garmen -> `stock.move` Odoo."""

    def setUp(self):
        self.product = Product.objects.create(code="PROD-1", name="Kaos Putih", odoo_id=501)
        self.client_mock = MagicMock()
        self.client_mock.execute_kw.return_value = [123]
        self.adapter = OdooAdapter(client=self.client_mock)

    def test_push_wip_issue_sukses(self):
        response = self.adapter.push_wip_issue(PAYLOAD)

        self.assertTrue(response.ok)
        self.assertEqual(response.erp_id, "123")
        self.assertEqual(response.stage, "WIP")
        self.assertEqual(response.ref, "WO-DEMO-1")
        self.assertIsNone(response.error)
        self.assertEqual(response.raw["move_id"], 123)

        args = self.client_mock.execute_kw.call_args.args
        self.assertEqual(args[0], "stock.move")
        self.assertEqual(args[1], "create")
        values = args[2][0][0]
        self.assertEqual(values["product_id"], 501)
        self.assertEqual(values["product_uom_qty"], 10.0)
        self.assertEqual(values["location_id"], 11)  # gudang bahan
        self.assertEqual(values["location_dest_id"], 22)  # lokasi produksi (WIP)
        self.assertEqual(values["reference"], "WO-DEMO-1")
        self.assertEqual(values["name"], "WO-DEMO-1")

    def test_push_fg_receipt_sukses(self):
        response = self.adapter.push_fg_receipt({**PAYLOAD, "qty": 8})

        values = self.client_mock.execute_kw.call_args.args[2][0][0]
        self.assertTrue(response.ok)
        self.assertEqual(response.stage, "FG")
        self.assertEqual(values["location_id"], 22)  # dari produksi
        self.assertEqual(values["location_dest_id"], 33)  # ke gudang FG
        self.assertEqual(values["product_uom_qty"], 8.0)

    def test_erp_id_dari_int_bukan_list(self):
        self.client_mock.execute_kw.return_value = 777

        response = self.adapter.push_wip_issue(PAYLOAD)

        self.assertTrue(response.ok)
        self.assertEqual(response.erp_id, "777")

    def test_push_wip_issue_product_tidak_ditemukan(self):
        response = self.adapter.push_wip_issue({**PAYLOAD, "product_ref": "TIDAK-ADA"})

        self.assertFalse(response.ok)
        self.assertIn("Product tidak ditemukan: TIDAK-ADA", response.error)
        self.assertEqual(response.stage, STAGE_WIP)
        self.assertIsNone(response.erp_id)
        self.client_mock.execute_kw.assert_not_called()

    def test_push_wip_issue_product_tanpa_odoo_id(self):
        self.product.odoo_id = None
        self.product.save(update_fields=["odoo_id"])

        response = self.adapter.push_wip_issue(PAYLOAD)

        self.assertFalse(response.ok)
        self.assertIn("belum punya odoo_id", response.error)
        self.client_mock.execute_kw.assert_not_called()

    @override_settings(ODOO_LOCATION_WIP_ID=None, ODOO_LOCATION_PRODUCTION_ID=None)
    def test_push_wip_issue_lokasi_belum_dikonfigurasi(self):
        # Lokasi dibaca saat __init__ -> adapter dibuat SETELAH override settings.
        adapter = OdooAdapter(client=self.client_mock)

        response = adapter.push_wip_issue(PAYLOAD)

        self.assertFalse(response.ok)
        self.assertEqual(
            response.error,
            "Location WIP/PRODUCTION belum dikonfigurasi (ODOO_LOCATION_*).",
        )
        self.client_mock.execute_kw.assert_not_called()

    @override_settings(ODOO_LOCATION_FG_ID=None)
    def test_push_fg_receipt_lokasi_fg_belum_dikonfigurasi(self):
        adapter = OdooAdapter(client=self.client_mock)

        response = adapter.push_fg_receipt(PAYLOAD)

        self.assertFalse(response.ok)
        self.assertIn("Location PRODUCTION/FG belum dikonfigurasi", response.error)
        self.client_mock.execute_kw.assert_not_called()

    def test_push_payload_kurang_field_wajib(self):
        response = self.adapter.push_wip_issue({"ref": "WO-1"})

        self.assertFalse(response.ok)
        self.assertIn("Payload tidak lengkap", response.error)
        self.assertIn("product_ref", response.error)
        self.assertIn("qty", response.error)
        self.client_mock.execute_kw.assert_not_called()

    def test_push_qty_tidak_valid(self):
        response = self.adapter.push_wip_issue({**PAYLOAD, "qty": "banyak"})

        self.assertFalse(response.ok)
        self.assertIn("Qty tidak valid", response.error)

    def test_push_client_raise_jadi_ok_false(self):
        self.client_mock.execute_kw.side_effect = RuntimeError("JSON-RPC gagal")

        response = self.adapter.push_wip_issue(PAYLOAD)

        self.assertFalse(response.ok)
        self.assertIn("JSON-RPC gagal", response.error)
        self.assertEqual(response.stage, STAGE_WIP)
        self.assertEqual(response.ref, "WO-DEMO-1")

    def test_push_odoo_tidak_mengembalikan_id(self):
        self.client_mock.execute_kw.return_value = None

        response = self.adapter.push_wip_issue(PAYLOAD)

        self.assertFalse(response.ok)
        self.assertIn("tidak mengembalikan id", response.error)


@override_settings(ODOO_URL="", ODOO_DB="", ODOO_USER="", ODOO_API_KEY="", **LOCATIONS)
class OdooAdapterTanpaKredensialTests(TestCase):
    """Kredensial ODOO_* kosong -> client None & push ditolak (tanpa jaringan)."""

    def test_client_none_dan_health_check_false(self):
        adapter = OdooAdapter()

        self.assertIsNone(adapter.client)
        self.assertFalse(adapter.health_check())

    def test_push_ditolak_tanpa_client(self):
        response = OdooAdapter().push_wip_issue(PAYLOAD)

        self.assertFalse(response.ok)
        self.assertIn("Odoo client belum siap", response.error)


@override_settings(**LOCATIONS)
class OdooAdapterHealthAndCloseTests(TestCase):
    """health_check & close memakai client yang di-inject (mock)."""

    def test_health_check_true_kalau_ping_true(self):
        client = MagicMock()
        client.ping.return_value = True

        self.assertTrue(OdooAdapter(client=client).health_check())
        client.ping.assert_called_once_with()

    def test_health_check_false_kalau_ping_error(self):
        client = MagicMock()
        client.ping.side_effect = RuntimeError("koneksi putus")

        self.assertFalse(OdooAdapter(client=client).health_check())

    def test_close_menutup_client(self):
        client = MagicMock()

        OdooAdapter(client=client).close()

        client.close.assert_called_once_with()

