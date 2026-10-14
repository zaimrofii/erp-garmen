"""Test task `erp_sync.reconcile_stock` (I7) — service & gateway WA di-mock.

Cakupan: tanpa selisih → WA tidak dipanggil; ada selisih → WA dikirim ke semua
nomor tujuan (isi pesan benar); WA error (exception **atau** ``ok=False``) tidak
menggagalkan task; ``RECONCILIATION_ALERT_WA_TO`` kosong → WA dilewati; registrasi
nama task; dan retry hanya untuk error transport (``httpx.HTTPError``/
``ConnectionError``, di-import dari ``tasks_master``).

Catatan: ``TestCase`` (bukan ``SimpleTestCase``) supaya aman kalau service benar-
benar menyentuh DB — di test ini service di-mock, jadi tidak ada Odoo/DB.
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import httpx
from django.test import TestCase, override_settings

from integrations.erp_sync import tasks_reconciliation
from integrations.erp_sync.tasks_reconciliation import (
    format_reconciliation_alert,
    reconcile_stock,
)
from integrations.wa_bot.services import WAResponse

SERVICE = "integrations.erp_sync.tasks_reconciliation.ReconciliationService"
GATEWAY = "integrations.erp_sync.tasks_reconciliation.get_wa_gateway"

#: Hasil `compare()` tanpa selisih.
NO_ALERT = {"total_products": 3, "alert_count": 0, "alerts": []}
#: Hasil `compare()` dengan 2 produk selisih (top 5 ada 2).
ALERT = {
    "total_products": 3,
    "alert_count": 2,
    "alerts": [
        {
            "product_odoo_id": 501,
            "product_code": "FG-001",
            "mes_qty": 10.0,
            "odoo_qty": 4.0,
            "diff": 6.0,
        },
        {
            "product_odoo_id": 502,
            "product_code": "FG-002",
            "mes_qty": 1000.0,
            "odoo_qty": 985.0,
            "diff": 15.0,
        },
    ],
}
#: Nomor WA penerima alert (dari settings.RECONCILIATION_ALERT_WA_TO).
RECIPIENTS = ["628111", "628222"]


class ReconcileStockTaskTests(TestCase):
    """Task ``erp_sync.reconcile_stock`` — delegasi + alert WA best-effort."""

    def run_task(self, service_result, gateway=None):
        """Jalankan task dengan service & gateway di-patch; return (hasil, mocks)."""
        service = MagicMock()
        service.compare.return_value = service_result
        if gateway is None:
            gateway = MagicMock()
            gateway.send_message.return_value = WAResponse(ok=True, message_id="MOCK-1")
        with patch(SERVICE, return_value=service), patch(GATEWAY, return_value=gateway):
            result = reconcile_stock.apply().get()
        return result, service, gateway

    # ------------------------------------------------------------------ tests
    @override_settings(RECONCILIATION_ALERT_WA_TO=RECIPIENTS)
    def test_tanpa_selisih_wa_tidak_dipanggil(self):
        result, service, gateway = self.run_task(NO_ALERT)

        self.assertEqual(result, NO_ALERT)
        service.compare.assert_called_once_with()
        gateway.send_message.assert_not_called()

    @override_settings(RECONCILIATION_ALERT_WA_TO=RECIPIENTS)
    def test_ada_selisih_mengirim_wa_ke_semua_nomor(self):
        result, _, gateway = self.run_task(ALERT)

        self.assertEqual(result, ALERT)
        self.assertEqual(gateway.send_message.call_count, len(RECIPIENTS))
        recipients = [args.args[0] for args in gateway.send_message.call_args_list]
        self.assertEqual(recipients, RECIPIENTS)

        body = gateway.send_message.call_args_list[0].args[1]
        self.assertEqual(
            body.splitlines()[0], "Rekonsiliasi stok: 2 produk selisih."
        )
        self.assertIn("Top 5:", body)
        self.assertIn("- FG-001: MES=10, Odoo=4, diff=6", body)
        self.assertIn("- FG-002: MES=1000, Odoo=985, diff=15", body)
        self.assertEqual(
            gateway.send_message.call_args_list,
            [call(RECIPIENTS[0], body), call(RECIPIENTS[1], body)],
        )

    @override_settings(RECONCILIATION_ALERT_WA_TO=RECIPIENTS)
    def test_wa_error_tidak_menggagalkan_task(self):
        gateway = MagicMock()
        gateway.send_message.side_effect = RuntimeError("wa mati")

        result, _, _ = self.run_task(ALERT, gateway=gateway)

        self.assertEqual(result, ALERT)  # task tetap sukses

    @override_settings(RECONCILIATION_ALERT_WA_TO=RECIPIENTS)
    def test_wa_menolak_pesan_hanya_dilog(self):
        # Gateway balas ok=False (mis. nomor tidak valid) → task tetap sukses.
        gateway = MagicMock()
        gateway.send_message.return_value = WAResponse(ok=False, error="nomor invalid")

        result, _, _ = self.run_task(ALERT, gateway=gateway)

        self.assertEqual(result, ALERT)
        self.assertEqual(gateway.send_message.call_count, len(RECIPIENTS))

    @override_settings(RECONCILIATION_ALERT_WA_TO=[])
    def test_nomor_tujuan_kosong_wa_dilewati(self):
        result, _, gateway = self.run_task(ALERT)

        self.assertEqual(result, ALERT)
        gateway.send_message.assert_not_called()

    def test_nomor_tujuan_kosong_gateway_tidak_dibuat(self):
        # Tanpa penerima, factory gateway tidak perlu dipanggil sama sekali.
        service = MagicMock()
        service.compare.return_value = ALERT
        with patch(SERVICE, return_value=service), patch(GATEWAY) as gateway_factory:
            with override_settings(RECONCILIATION_ALERT_WA_TO=[]):
                result = reconcile_stock.apply().get()

        self.assertEqual(result, ALERT)
        gateway_factory.assert_not_called()

    # ------------------------------------------------------------- registrasi
    def test_registrasi_nama_task(self):
        self.assertEqual(reconcile_stock.name, "erp_sync.reconcile_stock")
        self.assertIn("reconcile_stock", tasks_reconciliation.__all__)

    def test_error_transport_memicu_retry(self):
        # Konfigurasi retry: HANYA error transport/jaringan (impor tasks_master).
        self.assertIn(httpx.HTTPError, reconcile_stock.autoretry_for)
        self.assertIn(ConnectionError, reconcile_stock.autoretry_for)
        self.assertEqual(reconcile_stock.max_retries, 3)

        service = MagicMock()
        service.compare.side_effect = httpx.ConnectError("odoo mati")

        with patch(SERVICE, return_value=service):
            with self.assertRaises(httpx.HTTPError):
                reconcile_stock.apply().get()

    # ----------------------------------------------------------------- format
    def test_format_pesan_ringkas(self):
        body = format_reconciliation_alert(ALERT)

        self.assertEqual(
            body.splitlines(),
            [
                "Rekonsiliasi stok: 2 produk selisih.",
                "Top 5:",
                "- FG-001: MES=10, Odoo=4, diff=6",
                "- FG-002: MES=1000, Odoo=985, diff=15",
            ],
        )

    def test_format_tanpa_alert_tidak_ada_top_5(self):
        body = format_reconciliation_alert(NO_ALERT)

        self.assertEqual(body, "Rekonsiliasi stok: 0 produk selisih.")

    def test_format_tanpa_kode_produk_pakai_id(self):
        body = format_reconciliation_alert(
            {
                "alert_count": 1,
                "alerts": [
                    {
                        "product_odoo_id": 777,
                        "mes_qty": 0,
                        "odoo_qty": 3.5,
                        "diff": -3.5,
                    }
                ],
            }
        )

        self.assertIn("- #777: MES=0, Odoo=3.5, diff=-3.5", body)

    def test_format_alert_tanpa_key_diff_tidak_error(self):
        # Payload tanpa `diff` (service selalu mengirimnya) → tampil 0, tanpa error.
        body = format_reconciliation_alert(
            {"alert_count": 1, "alerts": [{"product_odoo_id": 778, "mes_qty": 2}]}
        )

        self.assertIn("- #778: MES=2, Odoo=0, diff=0", body)
