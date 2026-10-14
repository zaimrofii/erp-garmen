"""Test driver ESC/POS (Fase 5): urutan byte tiap perintah + validasi input."""

from __future__ import annotations

from django.test import TestCase

from integrations.printing.escpos import ESCPOSDriver, ESCPOSError


class ESCPOSDriverTests(TestCase):
    """Perintah dasar driver (buffer, teks, feed, cut, bold, align)."""

    def setUp(self):
        self.driver = ESCPOSDriver()

    def test_buffer_awal_kosong(self):
        self.assertEqual(self.driver.build(), b"")
        self.assertEqual(self.driver.buffer, b"")

    def test_init_mengirim_esc_at(self):
        self.assertEqual(self.driver.init().build()[:2], b"\x1b@")

    def test_text_tanpa_baris_baru(self):
        self.assertEqual(self.driver.text("AB").build(), b"AB")

    def test_line_menambah_newline(self):
        self.assertEqual(self.driver.line("AB").build(), b"AB\n")

    def test_line_tanpa_argumen_menulis_baris_kosong(self):
        self.assertEqual(self.driver.line().build(), b"\n")

    def test_feed_default_satu_baris(self):
        self.assertEqual(self.driver.feed().build(), b"\x1bd\x01")

    def test_feed_tiga_baris(self):
        self.assertEqual(self.driver.feed(3).build(), b"\x1bd\x03")

    def test_feed_di_luar_rentang_atau_bukan_int_error(self):
        for value in (-1, 256, "2", 1.5, True):
            with self.subTest(value=value), self.assertRaises(ESCPOSError):
                self.driver.feed(value)

    def test_cut_penuh_dan_sebagian(self):
        self.assertEqual(self.driver.cut().build(), b"\x1dV\x00")
        self.assertEqual(ESCPOSDriver().cut(full=False).build(), b"\x1dV\x01")

    def test_cut_butuh_bool(self):
        with self.assertRaises(ESCPOSError):
            self.driver.cut(full="yes")

    def test_bold_on_dan_off(self):
        self.assertEqual(self.driver.bold(True).bold(False).build(), b"\x1bE\x01\x1bE\x00")

    def test_bold_butuh_bool(self):
        with self.assertRaises(ESCPOSError):
            self.driver.bold("yes")

    def test_align_tiga_posisi(self):
        self.assertEqual(self.driver.align("left").build(), b"\x1ba\x00")
        self.assertEqual(ESCPOSDriver().align("center").build(), b"\x1ba\x01")
        self.assertEqual(ESCPOSDriver().align("RIGHT").build(), b"\x1ba\x02")

    def test_align_tidak_dikenal_error(self):
        with self.assertRaisesMessage(ESCPOSError, "align"):
            self.driver.align("middle")

    def test_chaining_mengembalikan_driver_yang_sama(self):
        self.assertIs(self.driver.text("A").line().feed(), self.driver)

    def test_build_tidak_menghapus_buffer(self):
        driver = self.driver.init().line("X")

        self.assertEqual(driver.build(), driver.build())
        self.assertTrue(driver.buffer)

    def test_teks_non_ascii_diencode_cp437(self):
        self.assertEqual(self.driver.text("é").build(), "é".encode("cp437"))

    def test_teks_bukan_str_error(self):
        with self.assertRaisesMessage(ESCPOSError, "harus str"):
            self.driver.text(123)

    def test_urutan_lengkap_sederhana(self):
        data = (
            ESCPOSDriver()
            .init()
            .align("center")
            .bold(True)
            .line("BUNDLE TAG")
            .bold(False)
            .cut()
            .build()
        )

        self.assertTrue(data.startswith(b"\x1b@\x1ba\x01\x1bE\x01BUNDLE TAG\n\x1bE\x00"))
        self.assertTrue(data.endswith(b"\x1dV\x00"))

    def test_qr_memuat_perintah_gs_k_dan_data(self):
        data = self.driver.qr("BND-1").build()

        self.assertIn(b"\x1d(k", data)
        self.assertIn(b"BND-1", data)
        self.assertTrue(data.startswith(b"\x1d(k\x04\x001A\x02\x00"))  # set model 2
        self.assertIn(b"\x1d(k\x03\x001C\x06", data)  # ukuran modul default 6
        self.assertIn(b"\x1d(k\x03\x001E\x31", data)  # koreksi error level M
        self.assertTrue(data.endswith(b"\x1d(k\x03\x001Q\x30"))  # perintah cetak

    def test_qr_ukuran_kustom(self):
        self.assertIn(b"\x1d(k\x03\x001C\x08", self.driver.qr("X", size=8).build())
        self.assertIn(b"\x1d(k\x03\x001C\x01", ESCPOSDriver().qr("X", size=1).build())

    def test_qr_ukuran_di_luar_rentang_error(self):
        for size in (0, 9, "6", True):
            with self.subTest(size=size), self.assertRaises(ESCPOSError):
                ESCPOSDriver().qr("X", size=size)

    def test_qr_data_kosong_atau_bukan_str_error(self):
        with self.assertRaisesMessage(ESCPOSError, "tidak boleh kosong"):
            self.driver.qr("   ")
        with self.assertRaisesMessage(ESCPOSError, "harus str"):
            self.driver.qr(123)  # type: ignore[arg-type]

    def test_qr_panjang_data_tertulis_benar(self):
        # pL/pH = len(data) + 3 -> data 10 karakter menghasilkan 0x0D
        data = self.driver.qr("BND-000001").build()

        self.assertIn(b"\x1d(k\x0d\x00\x001P0BND-000001", data)

    def test_barcode_code128_default(self):
        data = self.driver.barcode("BND-1").build()

        self.assertIn(b"\x1dh\x50", data)  # tinggi barcode 80
        self.assertIn(b"\x1dw\x02", data)  # lebar modul 2
        self.assertIn(b"\x1dk\x49\x05BND-1", data)  # CODE128 + 1 byte panjang

    def test_barcode_code39_diakhiri_nul(self):
        self.assertIn(
            b"\x1dk\x45ABC\x00", self.driver.barcode("ABC", type="CODE39").build()
        )

    def test_barcode_tipe_tidak_didukung_error(self):
        with self.assertRaisesMessage(ESCPOSError, "tidak didukung"):
            self.driver.barcode("X", type="PDF417")

    def test_barcode_data_kosong_error(self):
        with self.assertRaisesMessage(ESCPOSError, "tidak boleh kosong"):
            self.driver.barcode("   ")

