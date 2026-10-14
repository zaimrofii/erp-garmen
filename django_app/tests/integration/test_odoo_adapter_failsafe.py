"""Test Fail-Safe `OdooAdapter` — Odoo mati / salah URL / koneksi putus (Step 3).

Adapter **harus** menangkap exception dan mengembalikan ``ERPResponse(ok=False,
error=...)`` — tidak boleh melempar ke pemanggil (Django tidak crash).

Dua skenario:
  * **URL mati** (``http://127.0.0.1:9``) → client nyata gagal konek;
  * **exception dari client** (koneksi putus di tengah jalan) → client di-mock.

Jalankan:

    docker compose exec django python manage.py test tests.integration.test_odoo_adapter_failsafe
"""

from __future__ import annotations

from unittest.mock import MagicMock

from django.test import TestCase, override_settings

from integrations.erp_sync.adapters.base import ERPResponse
from integrations.erp_sync.adapters.odoo import OdooAdapter
from master.models import Product

PRODUCT_ODOO_ID = 100
PRODUCT_UOM_ID = 33

#: Kredensial palsu + URL ke port tanpa server -> koneksi ditolak.
DOWN = {
    "ODOO_URL": "http://127.0.0.1:9",
    "ODOO_DB": "garmen_db",
    "ODOO_USER": "x@example.com",
    "ODOO_API_KEY": "kunci-palsu",
    "ODOO_TIMEOUT": 5.0,
}

#: Lokasi (agar adapter sampai ke pemanggilan Odoo, bukan gagal di validasi lokasi).
LOCATIONS = {
    "ODOO_LOCATION_WIP_ID": 53,
    "ODOO_LOCATION_PRODUCTION_ID": 24,
    "ODOO_LOCATION_FG_ID": 54,
    "ODOO_LOCATION_SCRAP_ID": 26,
}

WO = {"qty": 1, "ref": "FS-0001", "uom_id": PRODUCT_UOM_ID}


@override_settings(**DOWN, **LOCATIONS)
class OdooAdapterFailSafeDownTests(TestCase):
    """Odoo mati / salah URL → semua push mengembalikan `ok=False` (tanpa crash)."""

    def setUp(self):
        self.product = Product.objects.create(
            code="KTS-EXPORT-L", name="Kaos Export L", odoo_id=PRODUCT_ODOO_ID
        )
        self.addCleanup(self.product.delete)

        self.adapter = OdooAdapter()  # client nyata menuju URL mati
        self.addCleanup(self.adapter.close)
        self.wo = {**WO, "product_id": self.product.pk}

    def _assert_fail_safe(self, response: ERPResponse) -> None:
        self.assertIsInstance(response, ERPResponse)
        self.assertFalse(response.ok)
        self.assertIsNotNone(response.error)
        self.assertIsNone(response.erp_id)

    def test_wip_ok_false_saat_odoo_mati(self):
        self._assert_fail_safe(self.adapter.push_wip_issue_wo(self.wo))

    def test_fg_ok_false_saat_odoo_mati(self):
        self._assert_fail_safe(self.adapter.push_fg_receipt_wo(self.wo))

    def test_scrap_ok_false_saat_odoo_mati(self):
        self._assert_fail_safe(self.adapter.push_scrap_wo(self.wo))

    def test_health_check_false_saat_odoo_mati(self):
        self.assertFalse(self.adapter.health_check())


@override_settings(**LOCATIONS)
class OdooAdapterFailSafeExceptionTests(TestCase):
    """Exception apa pun dari client (koneksi putus) → `ok=False`, bukan exception."""

    def setUp(self):
        self.product = Product.objects.create(
            code="KTS-EXPORT-L", name="Kaos Export L", odoo_id=PRODUCT_ODOO_ID
        )
        self.addCleanup(self.product.delete)

        self.client_mock = MagicMock()
        self.client_mock.execute_kw.side_effect = RuntimeError("connection reset by peer")
        self.adapter = OdooAdapter(client=self.client_mock)
        self.wo = {**WO, "product_id": self.product.pk}

    def test_wip_exception_client_jadi_ok_false(self):
        response = self.adapter.push_wip_issue_wo(self.wo)
        self.assertFalse(response.ok)
        self.assertIn("connection reset", response.error)

    def test_fg_exception_client_jadi_ok_false(self):
        response = self.adapter.push_fg_receipt_wo(self.wo)
        self.assertFalse(response.ok)
        self.assertIn("connection reset", response.error)

    def test_scrap_exception_client_jadi_ok_false(self):
        response = self.adapter.push_scrap_wo(self.wo)
        self.assertFalse(response.ok)
        self.assertIn("connection reset", response.error)
