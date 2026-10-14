"""Test factory `get_adapter()` (Fase 4.1): mapping vendor + fail-safe ke NullAdapter."""

from __future__ import annotations

from django.test import SimpleTestCase, override_settings

from integrations.erp_sync.adapters.accurate import AccurateAdapter
from integrations.erp_sync.adapters.factory import ADAPTERS, get_adapter
from integrations.erp_sync.adapters.null import NullAdapter
from integrations.erp_sync.adapters.odoo import OdooAdapter
from integrations.erp_sync.adapters.sap import SapAdapter

FACTORY_LOGGER = "integrations.erp_sync.adapters.factory"


class GetAdapterTests(SimpleTestCase):
    """Pemilihan adapter murni dari settings.ERP_ADAPTER."""

    def test_mapping_vendor_lengkap(self):
        self.assertEqual(
            ADAPTERS,
            {
                "null": NullAdapter,
                "odoo": OdooAdapter,
                "accurate": AccurateAdapter,
                "sap": SapAdapter,
            },
        )

    @override_settings(ERP_ADAPTER="null")
    def test_adapter_null(self):
        self.assertIsInstance(get_adapter(), NullAdapter)

    @override_settings(ERP_ADAPTER="odoo")
    def test_adapter_odoo(self):
        self.assertIsInstance(get_adapter(), OdooAdapter)

    @override_settings(ERP_ADAPTER="ODoo")
    def test_adapter_case_insensitive(self):
        self.assertIsInstance(get_adapter(), OdooAdapter)

    @override_settings(ERP_ADAPTER="accurate")
    def test_adapter_accurate(self):
        self.assertIsInstance(get_adapter(), AccurateAdapter)

    @override_settings(ERP_ADAPTER="sap")
    def test_adapter_sap(self):
        self.assertIsInstance(get_adapter(), SapAdapter)

    @override_settings(ERP_ADAPTER="vendor-baru")
    def test_adapter_tidak_dikenal_fallback_null(self):
        with self.assertLogs(FACTORY_LOGGER, level="WARNING") as logs:
            adapter = get_adapter()

        self.assertIsInstance(adapter, NullAdapter)
        self.assertIn("tidak dikenal", logs.output[0])

    @override_settings(ERP_ADAPTER="")
    def test_adapter_kosong_fallback_null(self):
        with self.assertLogs(FACTORY_LOGGER, level="WARNING"):
            adapter = get_adapter()

        self.assertIsInstance(adapter, NullAdapter)

    @override_settings(ERP_ADAPTER="odoo")
    def test_parameter_name_menimpa_settings(self):
        self.assertIsInstance(get_adapter("null"), NullAdapter)

    @override_settings(
        ERP_ADAPTER="odoo", ODOO_URL="", ODOO_DB="", ODOO_USER="", ODOO_API_KEY=""
    )
    def test_adapter_odoo_tanpa_kredensial_tidak_crash(self):
        """ERP_ADAPTER=odoo tanpa kredensial -> push ditolak ok=False (bukan crash)."""
        response = get_adapter().push_wip_issue(
            {"product_ref": "PROD-1", "qty": 1, "ref": "WO-1"}
        )

        self.assertFalse(response.ok)
        self.assertIn("Odoo client belum siap", response.error)

    @override_settings(ERP_ADAPTER="null")
    def test_adapter_null_langsung_bisa_dipakai(self):
        response = get_adapter().push_fg_receipt({"qty": 2, "ref": "WO-2"})

        self.assertTrue(response.ok)
        self.assertEqual(response.stage, "FG")
