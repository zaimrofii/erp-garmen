"""Test backend printer (Fase 5): mock, usb (stub), network (socket mock), factory."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from integrations.printing.backends import (
    BACKENDS,
    MockBackend,
    NetworkBackend,
    PrintResult,
    PrinterBackend,
    UsbBackend,
    get_backend,
)
from integrations.printing.backends.usb import MESSAGE as USB_MESSAGE

PAYLOAD = b"\x1b@halo"
CREATE_CONNECTION = "integrations.printing.backends.network.socket.create_connection"


class MockBackendTests(TestCase):
    """MockBackend: memori + file .bin, tidak menyentuh printer fisik."""

    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix="printmock-"))
        self.backend = MockBackend(directory=self.directory)

    def test_print_bytes_sukses(self):
        result = self.backend.print_bytes(PAYLOAD, ref="BND-1")

        self.assertIsInstance(result, PrintResult)
        self.assertTrue(result.ok)
        self.assertEqual(result.backend, "mock")
        self.assertEqual(result.bytes_sent, len(PAYLOAD))
        self.assertEqual(result.ref, "BND-1")
        self.assertIsNone(result.error)

    def test_bytes_disimpan_di_memori(self):
        self.backend.print_bytes(PAYLOAD, ref="BND-1")

        self.assertEqual(len(self.backend.printed), 1)
        self.assertEqual(self.backend.printed[0]["bytes"], PAYLOAD)
        self.assertEqual(self.backend.printed[0]["ref"], "BND-1")

    def test_file_bin_ditulis(self):
        self.backend.print_bytes(PAYLOAD, ref="BND-1")

        path = self.directory / "BND-1.bin"
        self.assertTrue(path.exists())
        self.assertEqual(path.read_bytes(), PAYLOAD)

    def test_ref_dengan_karakter_aneh_dinormalisasi(self):
        self.backend.print_bytes(PAYLOAD, ref="a/b c")

        self.assertTrue((self.directory / "a_b_c.bin").exists())

    def test_tanpa_ref_tetap_sukses(self):
        result = self.backend.print_bytes(PAYLOAD)

        self.assertTrue(result.ok)
        self.assertEqual(result.ref, "")
        self.assertTrue((self.directory / "print.bin").exists())

    def test_data_kosong_ditolak(self):
        result = self.backend.print_bytes(b"", ref="X")

        self.assertFalse(result.ok)
        self.assertEqual(result.bytes_sent, 0)
        self.assertIn("kosong", result.error)

    def test_data_bukan_bytes_ditolak(self):
        result = self.backend.print_bytes("teks", ref="X")  # type: ignore[arg-type]

        self.assertFalse(result.ok)
        self.assertIn("bukan bytes", result.error)

    def test_penulisan_file_bisa_dimatikan(self):
        backend = MockBackend(directory=self.directory, write_file=False)

        backend.print_bytes(PAYLOAD, ref="NOFILE")

        self.assertEqual(list(self.directory.glob("*.bin")), [])
        self.assertTrue(backend.printed)

    def test_gagal_tulis_file_tidak_menggagalkan_cetak(self):
        target = self.directory / "file_bukan_dir"
        target.write_text("x")

        result = MockBackend(directory=target).print_bytes(PAYLOAD, ref="X")

        self.assertTrue(result.ok)
        self.assertEqual(result.bytes_sent, len(PAYLOAD))

    def test_implement_kontrak_backend(self):
        self.assertIsInstance(self.backend, PrinterBackend)
        self.assertEqual(self.backend.name, "mock")

class UsbBackendTests(TestCase):
    """UsbBackend = stub yang jelas (raise), bukan diam-diam gagal."""

    def test_print_bytes_raise_not_implemented(self):
        with self.assertRaisesMessage(NotImplementedError, USB_MESSAGE):
            UsbBackend().print_bytes(PAYLOAD, ref="BND-1")

    def test_konfigurasi_dibaca_dari_settings(self):
        with override_settings(PRINTER_USB_VENDOR_ID=1234, PRINTER_USB_PRODUCT_ID=5678):
            backend = UsbBackend()

        self.assertEqual((backend.vendor_id, backend.product_id), (1234, 5678))

    def test_parameter_menimpa_settings(self):
        backend = UsbBackend(vendor_id=1, product_id=2)

        self.assertEqual((backend.vendor_id, backend.product_id), (1, 2))


class NetworkBackendTests(TestCase):
    """NetworkBackend: TCP raw (socket di-mock, tanpa jaringan nyata)."""

    def test_tanpa_host_atau_port_ditolak(self):
        with override_settings(PRINTER_NETWORK_HOST=None, PRINTER_NETWORK_PORT=None):
            result = NetworkBackend().print_bytes(PAYLOAD, ref="BND-1")

        self.assertFalse(result.ok)
        self.assertIn("belum dikonfigurasi", result.error)
        self.assertEqual(result.bytes_sent, 0)

    def test_kirim_via_socket(self):
        connection = MagicMock()
        # `with socket.create_connection(...) as connection` memakai hasil
        # __enter__(), jadi mock-nya harus mengembalikan dirinya sendiri.
        connection.__enter__.return_value = connection

        with patch(CREATE_CONNECTION, return_value=connection) as create:
            result = NetworkBackend(host="10.0.0.9", port=9100).print_bytes(
                PAYLOAD, ref="BND-1"
            )

        self.assertTrue(result.ok)
        self.assertEqual(result.backend, "network")
        self.assertEqual(result.bytes_sent, len(PAYLOAD))
        connection.sendall.assert_called_once_with(PAYLOAD)
        create.assert_called_once_with(("10.0.0.9", 9100), timeout=5.0)

    def test_kegagalan_jaringan_jadi_ok_false(self):
        with patch(CREATE_CONNECTION, side_effect=OSError("connection refused")):
            result = NetworkBackend(host="10.0.0.9", port=9100).print_bytes(PAYLOAD)

        self.assertFalse(result.ok)
        self.assertIn("connection refused", result.error)
        self.assertEqual(result.bytes_sent, 0)

    def test_data_kosong_ditolak_tanpa_membuka_koneksi(self):
        with patch(CREATE_CONNECTION) as create:
            result = NetworkBackend(host="10.0.0.9", port=9100).print_bytes(b"")

        self.assertFalse(result.ok)
        create.assert_not_called()


class GetBackendTests(TestCase):
    """Factory get_backend(): mapping + fail-safe."""

    def test_default_mock(self):
        with override_settings(PRINTER_BACKEND="mock"):
            self.assertIsInstance(get_backend(), MockBackend)

    def test_backend_usb_dan_network(self):
        with override_settings(PRINTER_BACKEND="usb"):
            self.assertIsInstance(get_backend(), UsbBackend)
        with override_settings(PRINTER_BACKEND="network"):
            self.assertIsInstance(get_backend(), NetworkBackend)

    def test_tidak_dikenal_fallback_mock_dengan_warning(self):
        with override_settings(PRINTER_BACKEND="bluetooth"), self.assertLogs(
            "integrations.printing.backends", level="WARNING"
        ) as logs:
            backend = get_backend()

        self.assertIsInstance(backend, MockBackend)
        self.assertIn("tidak dikenal", logs.output[0])

    def test_kosong_fallback_mock(self):
        with override_settings(PRINTER_BACKEND=""):
            self.assertIsInstance(get_backend(), MockBackend)

    def test_parameter_menimpa_settings(self):
        with override_settings(PRINTER_BACKEND="network"):
            self.assertIsInstance(get_backend("mock"), MockBackend)

    def test_mapping_lengkap(self):
        self.assertEqual(set(BACKENDS), {"mock", "usb", "network"})

