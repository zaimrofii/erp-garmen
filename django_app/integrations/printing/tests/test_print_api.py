"""Test endpoint cetak (Fase F) — `POST /api/v1/print/bundle-tag/` & `/print/kupon/`.

Yang dibuktikan: 200 + jumlah bytes ESC/POS nyata (backend mock juga menulis file
`.bin`, jadi isi perintah bisa diperiksa), `PrintJob` selalu tercatat
(PENDING → SENT/FAILED), cetak ulang = baris baru (tanpa unique), dan semua
kegagalan (bundle/kupon tidak ada, field kosong, printer error) = **400**.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import mock

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps_industry.garment.tests.factories import make_bundle, make_order_line
from integrations.printing.backends.base import PrintResult
from integrations.printing.models import PrintJob

BUNDLE_URL = "/api/v1/print/bundle-tag/"
COUPON_URL = "/api/v1/print/kupon/"


class PrintBundleTagTests(TestCase):
    """Cetak tag bundle: sukses (200 + bytes) dan semua jalur 400."""

    def setUp(self):
        self.client = APIClient()
        self.bundle = make_bundle(code="BND-PRINT-001")
        self.tmp = tempfile.mkdtemp(prefix="print-test-")
        self.addCleanup(self._cleanup)

    def _cleanup(self) -> None:
        for path in Path(self.tmp).glob("*"):
            path.unlink()

    def post(self, body):
        return self.client.post(BUNDLE_URL, body, format="json")

    def test_sukses_200_dengan_bytes_escpos(self):
        with override_settings(PRINTER_MOCK_DIR=self.tmp, PRINTER_BACKEND="mock"):
            response = self.post({"bundle_id": self.bundle.pk})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertGreater(body["bytes"], 0)
        self.assertEqual(body["backend"], "mock")
        self.assertEqual(body["resource"], "bundle")
        self.assertEqual(body["resource_id"], str(self.bundle.pk))
        self.assertEqual(body["ref"], "BND-PRINT-001")
        self.assertEqual(body["status"], PrintJob.Status.SENT)
        self.assertIsInstance(body["print_job_id"], int)

        job = PrintJob.objects.get(pk=body["print_job_id"])
        self.assertEqual(job.status, PrintJob.Status.SENT)
        self.assertEqual(job.bytes_sent, body["bytes"])
        self.assertEqual(job.backend, "mock")

        # Backend mock menulis bytes ke file → payload ESC/POS benar-benar ada.
        file = Path(self.tmp) / "BND-PRINT-001.bin"
        self.assertTrue(file.exists())
        self.assertEqual(len(file.read_bytes()), body["bytes"])

    def test_bundle_id_string_angka_diterima(self):
        with override_settings(PRINTER_MOCK_DIR=self.tmp, PRINTER_BACKEND="mock"):
            response = self.post({"bundle_id": str(self.bundle.pk)})

        self.assertEqual(response.status_code, 200)

    def test_bundle_tidak_ada_400(self):
        response = self.post({"bundle_id": 999999})

        self.assertEqual(response.status_code, 400)
        self.assertIn("tidak ditemukan", response.json()["detail"])
        self.assertEqual(PrintJob.objects.count(), 0)

    def test_field_tidak_diisi_400(self):
        response = self.post({})

        self.assertEqual(response.status_code, 400)
        self.assertIn("wajib diisi", response.json()["detail"])

    def test_field_bukan_angka_400(self):
        response = self.post({"bundle_id": "bnd-1"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("harus berupa angka", response.json()["detail"])

    def test_cetak_ulang_menambah_baris_print_job(self):
        with override_settings(PRINTER_MOCK_DIR=self.tmp, PRINTER_BACKEND="mock"):
            pertama = self.post({"bundle_id": self.bundle.pk})
            kedua = self.post({"bundle_id": self.bundle.pk})

        self.assertEqual(pertama.status_code, 200)
        self.assertEqual(kedua.status_code, 200)
        self.assertEqual(PrintJob.objects.filter(resource_id=str(self.bundle.pk)).count(), 2)

    def test_printer_gagal_400_dan_job_failed(self):
        class FailingBackend:
            name = "network"

            def print_bytes(self, data: bytes, ref: str = "") -> PrintResult:
                return PrintResult(
                    ok=False, backend="network", bytes_sent=0, error="printer offline"
                )

        with mock.patch("integrations.printing.api.get_backend", return_value=FailingBackend()):
            response = self.post({"bundle_id": self.bundle.pk})

        self.assertEqual(response.status_code, 400)
        self.assertIn("printer offline", response.json()["detail"])

        job = PrintJob.objects.get()
        self.assertEqual(job.status, PrintJob.Status.FAILED)
        self.assertIn("printer offline", job.last_error)

    def test_backend_melempar_exception_400_dan_job_failed(self):
        class BoomBackend:
            name = "usb"

            def print_bytes(self, data: bytes, ref: str = "") -> PrintResult:
                raise NotImplementedError("Implementasi USB butuh python-escpos + libusb")

        with mock.patch("integrations.printing.api.get_backend", return_value=BoomBackend()):
            response = self.post({"bundle_id": self.bundle.pk})

        self.assertEqual(response.status_code, 400)
        self.assertIn("python-escpos", response.json()["detail"])

        job = PrintJob.objects.get()
        self.assertEqual(job.status, PrintJob.Status.FAILED)
        self.assertEqual(job.backend, "usb")

    def test_get_tidak_diizinkan(self):
        self.assertEqual(self.client.get(BUNDLE_URL).status_code, 405)


class PrintCouponTests(TestCase):
    """Cetak kupon piece-rate: `ticket_code` wajib & harus ada di order line."""

    def setUp(self):
        self.client = APIClient()
        self.order_line = make_order_line(tag="KUPON", qty=12, ticket_code="TKT-0001")
        self.tmp = tempfile.mkdtemp(prefix="print-coupon-")
        self.addCleanup(self._cleanup)

    def _cleanup(self) -> None:
        for path in Path(self.tmp).glob("*"):
            path.unlink()

    def post(self, body):
        return self.client.post(COUPON_URL, body, format="json")

    def test_sukses_200_dengan_bytes(self):
        with override_settings(PRINTER_MOCK_DIR=self.tmp, PRINTER_BACKEND="mock"):
            response = self.post({"ticket_code": "TKT-0001"})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertGreater(body["bytes"], 0)
        self.assertEqual(body["resource"], "coupon")
        self.assertEqual(body["resource_id"], str(self.order_line.pk))
        self.assertEqual(body["ref"], "TKT-0001")
        self.assertEqual(PrintJob.objects.get().resource, PrintJob.Resource.COUPON)

    def test_ticket_tidak_ada_400(self):
        response = self.post({"ticket_code": "TKT-TIDAK-ADA"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("tidak ditemukan", response.json()["detail"])
        self.assertEqual(PrintJob.objects.count(), 0)

    def test_ticket_kosong_400(self):
        response = self.post({"ticket_code": "   "})

        self.assertEqual(response.status_code, 400)
        self.assertIn("wajib diisi", response.json()["detail"])

    def test_kupon_dari_order_line_lain_tidak_bisa_dicetak(self):
        """Order line tanpa `ticket_code` tidak bisa jadi target cetak (400)."""
        make_order_line(tag="KUPON_TANPA_KODE", qty=3)

        response = self.post({"ticket_code": "TKT-0002"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("tidak ditemukan", response.json()["detail"])
