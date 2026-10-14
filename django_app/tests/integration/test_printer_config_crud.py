"""Test **H5.7** — Printer Config (``/api/v1/settings/printer/``).

Cakupan: GET singleton (``config: null`` + ``effective`` + ``diverges`` +
``needs_restart`` + ``restart_command``) · PUT create-on-first-PUT (2× PUT = 1 baris) ·
**guard kondisional** (``usb`` ⇒ vendor+product wajib; ``network`` ⇒ host+port wajib) ·
validasi backend/port/panjang teks/``active`` · **tanpa mask** (host/USB id tampil apa
adanya) · izin (anonim 403; operator baca saja) · ``POST …/test-connection/`` (mock =
folder siap / folder gagal · usb = pesan stub + USB id · network = host/port kosong &
TCP connect gagal/sukses dengan socket dipatch) · ledger ``SyncRecord``
``master.printer_config``/``SKIPPED`` + ``AuditLog`` · non-breaking: modul printing
existing (``get_backend`` + ``POST /api/v1/print/bundle-tag/``) + ``PrintJob`` +
H5.1/H5.2/H5.3/H5.5/H5.6/H5.8.

Keputusan STEP 0 (H5.7 — **Opsi B**, pola H5.6/H5.8): DB menyimpan **profil printer**;
**konsumen TIDAK disentuh** (``integrations/printing`` tetap membaca ``.env``) ⇒ nol
risiko regresi; test-connection **TIDAK PERNAH mencetak** (mock = cek folder, usb = pesan
stub, network = TCP connect tanpa bytes); aktivasi = salin ke ``.env`` + restart.

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_printer_config_crud.py -q
"""

from __future__ import annotations

from unittest import mock

from django.conf import settings
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.audit.models import AuditLog
from core.auth.models import Role, User
from integrations.erp_sync.models import SyncRecord, SyncResource, SyncStage, SyncStatus
from integrations.printing.backends import MockBackend, get_backend
from master.models import PrinterConfig
from master.printer_config_services import CONFIG_FIELDS, MES_ONLY_REASON

CONFIG_URL = "/api/v1/settings/printer/"
TEST_URL = "/api/v1/settings/printer/test-connection/"
ENVELOPE_KEYS = {"config", "effective", "diverges", "needs_restart", "restart_command"}
ROW_KEYS = set(CONFIG_FIELDS) | {"id", "is_active", "created_at", "updated_at"}

#: Env deterministik untuk perbandingan DB vs ``.env`` (backend mock).
ENV_MOCK = {
    "PRINTER_BACKEND": "mock",
    "PRINTER_MOCK_DIR": "/tmp/print_mock_test",
    "PRINTER_NETWORK_HOST": None,
    "PRINTER_NETWORK_PORT": None,
    "PRINTER_USB_VENDOR_ID": None,
    "PRINTER_USB_PRODUCT_ID": None,
}


class PrinterConfigTestCase(TestCase):
    """Basis bersama: user admin/operator + klien admin siap pakai."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="admin-prtcfg",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.ADMIN),
        )
        cls.operator = User.objects.create_user(
            username="op-prtcfg",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.OPERATOR),
        )

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.admin)

    def as_user(self, user):
        """Client terautentikasi sebagai ``user`` (anonim kalau ``None``)."""
        client = APIClient()
        if user is not None:
            client.force_authenticate(user)
        return client

    def get(self):
        """GET amplop config dengan klien admin."""
        return self.api.get(CONFIG_URL)

    def put(self, **body):
        """PUT config dengan klien admin."""
        return self.api.put(CONFIG_URL, body, format="json")

    def post_test_connection(self):
        """POST test-connection dengan klien admin."""
        return self.api.post(TEST_URL, {}, format="json")

    def config(self) -> PrinterConfig:
        """Baris singleton (baris pertama)."""
        return PrinterConfig.objects.order_by("pk").first()

    def sync_records(self, config: PrinterConfig):
        """Ledger ``SyncRecord`` milik baris config."""
        return SyncRecord.objects.filter(
            resource=SyncResource.MASTER_PRINTER_CONFIG.value,
            resource_id=str(config.pk),
            stage=SyncStage.MASTER_PUSH.value,
        )

    def audit_logs(self, config: PrinterConfig, action: str | None = None):
        """AuditLog milik baris config (opsional difilter action)."""
        queryset = AuditLog.objects.filter(
            resource=SyncResource.MASTER_PRINTER_CONFIG.value,
            resource_id=str(config.pk),
        )

        return queryset.filter(action=action) if action else queryset


class PrinterConfigGetPutTests(PrinterConfigTestCase):
    """``GET|PUT /settings/printer/`` — singleton, guard kondisional, tanpa mask."""

    def test_get_belum_ada_null_dan_effective(self):
        response = self.get()

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), ENVELOPE_KEYS)
        self.assertIsNone(body["config"])
        self.assertEqual(set(body["effective"]), set(CONFIG_FIELDS))
        # efektif = nilai .env/settings yang benar-benar aktif
        self.assertEqual(
            body["effective"]["printer_backend"], str(settings.PRINTER_BACKEND)
        )
        self.assertEqual(
            body["effective"]["printer_mock_dir"], str(settings.PRINTER_MOCK_DIR or "")
        )
        self.assertIsNone(body["effective"]["printer_network_port"])
        self.assertEqual(body["diverges"], {})
        self.assertFalse(body["needs_restart"])
        self.assertIn("restart", body["restart_command"])
        # GET tidak boleh membuat baris
        self.assertEqual(PrinterConfig.objects.count(), 0)

    def test_put_create_pertama_kali(self):
        response = self.put(
            printer_backend="network",
            printer_network_host="192.168.1.50",
            printer_network_port=9100,
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), ENVELOPE_KEYS)
        row = body["config"]
        self.assertEqual(set(row), ROW_KEYS)
        self.assertEqual(row["printer_backend"], "network")
        self.assertEqual(row["printer_network_host"], "192.168.1.50")
        self.assertEqual(row["printer_network_port"], 9100)
        self.assertTrue(row["is_active"])
        self.assertTrue(body["needs_restart"])  # profil beda dari .env

        # DB menyimpan nilai apa adanya (tanpa mask — bukan rahasia)
        self.assertEqual(PrinterConfig.objects.count(), 1)
        config = self.config()

        self.assertEqual(config.printer_network_host, "192.168.1.50")

        record = self.sync_records(config).get()

        self.assertEqual(record.status, SyncStatus.SKIPPED)
        self.assertEqual(record.last_error, MES_ONLY_REASON)
        self.assertEqual(record.payload["printer_network_port"], 9100)

        logs = self.audit_logs(config, "master.create")

        self.assertEqual(logs.count(), 1)
        self.assertTrue(logs.first().metadata["mes_only"])

    def test_put_update_singleton(self):
        self.assertEqual(self.put(printer_backend="mock").status_code, 200)

        response = self.put(printer_mock_dir="/tmp/cetak")

        self.assertEqual(response.status_code, 200)
        row = response.json()["config"]

        self.assertEqual(row["printer_backend"], "mock")
        self.assertEqual(row["printer_mock_dir"], "/tmp/cetak")

        # singleton: 2× PUT tetap 1 baris; ledger satu, audit bertambah
        self.assertEqual(PrinterConfig.objects.count(), 1)
        config = self.config()

        self.assertEqual(self.sync_records(config).count(), 1)
        self.assertEqual(self.audit_logs(config, "master.create").count(), 1)
        self.assertEqual(self.audit_logs(config, "master.update").count(), 1)

    def test_tanpa_mask_host_dan_usb_id_tampil_apa_adanya(self):
        self.put(
            printer_backend="usb",
            printer_usb_vendor_id="0x04b8",
            printer_usb_product_id="1234",
        )

        row = self.get().json()["config"]

        self.assertEqual(row["printer_usb_vendor_id"], "0x04b8")
        self.assertEqual(row["printer_usb_product_id"], "1234")
        self.assertNotEqual(row["printer_usb_vendor_id"], "***")

    def test_guard_backend_usb_wajib_vendor_dan_product(self):
        salah_backend = self.put(printer_backend="bluetooth")

        self.assertEqual(salah_backend.status_code, 400)
        self.assertIn("printer_backend", salah_backend.json()["detail"])

        kurang = self.put(printer_backend="usb", printer_usb_vendor_id="0x04b8")

        self.assertEqual(kurang.status_code, 400)
        self.assertIn("membutuhkan", kurang.json()["detail"])
        self.assertEqual(PrinterConfig.objects.count(), 0)

        lengkap = self.put(
            printer_backend="usb",
            printer_usb_vendor_id="0x04b8",
            printer_usb_product_id="0x0202",
        )

        self.assertEqual(lengkap.status_code, 200)
        self.assertEqual(lengkap.json()["config"]["printer_backend"], "usb")

    def test_guard_backend_network_wajib_host_dan_port(self):
        host_saja = self.put(printer_backend="network", printer_network_host="10.0.0.9")

        self.assertEqual(host_saja.status_code, 400)
        self.assertIn("membutuhkan", host_saja.json()["detail"])

        port_saja = self.put(printer_backend="network", printer_network_port=9100)

        self.assertEqual(port_saja.status_code, 400)
        self.assertEqual(PrinterConfig.objects.count(), 0)

        # 'mock' tidak butuh host/port
        mock_ok = self.put(printer_backend="mock")

        self.assertEqual(mock_ok.status_code, 200)
        self.assertEqual(mock_ok.json()["config"]["printer_network_host"], "")

        lengkap = self.put(
            printer_backend="network",
            printer_network_host="10.0.0.9",
            printer_network_port=9100,
        )

        self.assertEqual(lengkap.status_code, 200)
        self.assertEqual(lengkap.json()["config"]["printer_network_port"], 9100)

    def test_validasi_port_dan_panjang_teks(self):
        self.assertEqual(self.put(printer_network_port=0).status_code, 400)
        self.assertEqual(self.put(printer_network_port=65536).status_code, 400)
        self.assertEqual(self.put(printer_network_port="abc").status_code, 400)
        self.assertIn(
            "printer_network_port", self.put(printer_network_port=0).json()["detail"]
        )

        panjang = self.put(printer_backend="mock", printer_network_host="x" * 201)

        self.assertEqual(panjang.status_code, 400)
        self.assertIn("printer_network_host", panjang.json()["detail"])

        vendor_panjang = self.put(printer_usb_vendor_id="x" * 33)

        self.assertEqual(vendor_panjang.status_code, 400)
        self.assertEqual(PrinterConfig.objects.count(), 0)

        # port boleh dikosongkan (None) bila backend bukan network
        kosong = self.put(printer_backend="mock", printer_network_port="")

        self.assertEqual(kosong.status_code, 200)
        self.assertIsNone(kosong.json()["config"]["printer_network_port"])

    def test_active_boolean_toggle(self):
        self.assertEqual(self.put(printer_backend="mock").status_code, 200)

        off = self.put(active=False)

        self.assertEqual(off.status_code, 200)
        self.assertFalse(off.json()["config"]["is_active"])
        self.assertFalse(self.config().is_active)

        on = self.put(active="true")

        self.assertEqual(on.status_code, 200)
        self.assertTrue(on.json()["config"]["is_active"])

        salah = self.put(active="kadang")

        self.assertEqual(salah.status_code, 400)
        self.assertIn("active", salah.json()["detail"])


class PrinterConfigDivergenceTests(PrinterConfigTestCase):
    """``diverges`` / ``needs_restart`` / izin — DB vs ``.env`` (tanpa mask)."""

    @override_settings(**ENV_MOCK)
    def test_diverges_kosong_kalau_sama_dengan_env(self):
        self.put(printer_backend="mock", printer_mock_dir="/tmp/print_mock_test")

        body = self.get().json()

        self.assertEqual(body["diverges"], {})
        self.assertFalse(body["needs_restart"])

        # ubah host + port -> itulah divergensinya (nilai apa adanya, tanpa mask)
        self.put(printer_network_host="10.0.0.9", printer_network_port=9100)

        body2 = self.get().json()

        self.assertEqual(
            body2["diverges"],
            {
                "printer_network_host": {"db": "10.0.0.9", "env": ""},
                "printer_network_port": {"db": 9100, "env": None},
            },
        )
        self.assertTrue(body2["needs_restart"])

    @override_settings(
        PRINTER_BACKEND="network",
        PRINTER_NETWORK_HOST="10.0.0.9",
        PRINTER_NETWORK_PORT=9100,
    )
    def test_effective_mengikuti_env(self):
        self.put(printer_backend="mock")

        body = self.get().json()

        self.assertEqual(body["effective"]["printer_backend"], "network")
        self.assertEqual(body["effective"]["printer_network_host"], "10.0.0.9")
        self.assertEqual(body["effective"]["printer_network_port"], 9100)
        self.assertEqual(
            body["diverges"]["printer_network_port"], {"db": None, "env": 9100}
        )

    def test_put_tanpa_perubahan_tidak_menulis_ledger(self):
        self.put(printer_backend="mock")
        config = self.config()
        sebelum = self.audit_logs(config).count()

        response = self.put()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.audit_logs(config).count(), sebelum)
        self.assertEqual(self.sync_records(config).count(), 1)

    def test_auth_anonim_403_dan_operator_baca_saja(self):
        anonim = self.as_user(None)

        self.assertEqual(anonim.get(CONFIG_URL).status_code, 403)
        self.assertEqual(anonim.put(CONFIG_URL, {}, format="json").status_code, 403)
        self.assertEqual(anonim.post(TEST_URL, {}, format="json").status_code, 403)

        operator = self.as_user(self.operator)

        self.assertEqual(operator.get(CONFIG_URL).status_code, 200)
        self.assertEqual(operator.put(CONFIG_URL, {}, format="json").status_code, 403)
        self.assertEqual(operator.post(TEST_URL, {}, format="json").status_code, 403)
        self.assertEqual(PrinterConfig.objects.count(), 0)


class PrinterConfigTestConnectionTests(PrinterConfigTestCase):
    """``POST …/test-connection/`` — read-only, **tidak pernah mencetak**."""

    def test_mock_ok_folder_dibuat(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            target = f"{tmp}/print_mock"
            with override_settings(PRINTER_BACKEND="mock", PRINTER_MOCK_DIR=target):
                response = self.post_test_connection()

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertTrue(body["ok"])
            self.assertEqual(body["backend"], "mock")
            self.assertIn("Mock dir siap", body["message"])
            self.assertIn(target, body["message"])

        # read-only: tidak membuat baris profil
        self.assertEqual(PrinterConfig.objects.count(), 0)

    @override_settings(PRINTER_BACKEND="mock", PRINTER_MOCK_DIR="/tmp/tidak-bisa")
    def test_mock_gagal_folder_tidak_bisa_dibuat(self):
        with mock.patch(
            "master.printer_config_services.os.makedirs",
            side_effect=OSError("read-only file system"),
        ):
            response = self.post_test_connection()

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["backend"], "mock")
        self.assertIn("tidak bisa dibuat", body["message"])
        self.assertIn("read-only", body["message"])

    @override_settings(
        PRINTER_BACKEND="usb", PRINTER_USB_VENDOR_ID=0x04B8, PRINTER_USB_PRODUCT_ID=1234
    )
    def test_usb_stub_laporkan_vendor_product(self):
        response = self.post_test_connection()

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["backend"], "usb")
        self.assertIn("stub", body["message"])
        self.assertIn("python-escpos", body["message"])
        self.assertIn("0x04B8", body["message"])
        self.assertIn("0x04D2", body["message"])

    @override_settings(
        PRINTER_BACKEND="network", PRINTER_NETWORK_HOST=None, PRINTER_NETWORK_PORT=None
    )
    def test_network_tanpa_host_port_dilaporkan(self):
        response = self.post_test_connection()

        body = response.json()

        self.assertFalse(body["ok"])
        self.assertEqual(body["backend"], "network")
        self.assertIn("belum dikonfigurasi", body["message"])

    @override_settings(
        PRINTER_BACKEND="network",
        PRINTER_NETWORK_HOST="192.168.1.50",
        PRINTER_NETWORK_PORT=9100,
    )
    def test_network_tcp_connect_sukses_dan_gagal(self):
        with mock.patch(
            "master.printer_config_services.socket.create_connection"
        ) as connect:
            ok = self.post_test_connection()

        self.assertTrue(ok.json()["ok"])
        self.assertIn("192.168.1.50:9100", ok.json()["message"])
        self.assertIn("tanpa mengirim bytes", ok.json()["message"])
        connect.assert_called_once_with(("192.168.1.50", 9100), timeout=5.0)

        with mock.patch(
            "master.printer_config_services.socket.create_connection",
            side_effect=OSError("connection refused"),
        ):
            gagal = self.post_test_connection()

        self.assertFalse(gagal.json()["ok"])
        self.assertIn("TCP connect gagal", gagal.json()["message"])
        self.assertIn("refused", gagal.json()["message"])

    def test_backend_tak_dikenal_fallback_mock(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(PRINTER_BACKEND="bluetooth", PRINTER_MOCK_DIR=tmp):
                response = self.post_test_connection()

                # NON-BREAKING: factory existing tetap fail-safe ke mock
                self.assertIsInstance(get_backend(), MockBackend)

        body = response.json()

        self.assertTrue(body["ok"])
        self.assertEqual(body["backend"], "bluetooth")
        self.assertIn("tidak dikenal", body["message"])
        self.assertIn("fallback mock", body["message"])


class PrinterConfigNonBreakingTests(PrinterConfigTestCase):
    """Non-breaking: modul printing existing + PrintJob + H5.1–H5.8 tetap hijau."""

    def test_printing_module_enum_dan_endpoint_settings_lain(self):
        self.assertEqual(
            SyncResource.MASTER_PRINTER_CONFIG.value, "master.printer_config"
        )

        # settelan lama masih ada + factory existing memilih MockBackend
        for name in (
            "PRINTER_BACKEND",
            "PRINTER_USB_VENDOR_ID",
            "PRINTER_USB_PRODUCT_ID",
            "PRINTER_NETWORK_HOST",
            "PRINTER_NETWORK_PORT",
            "PRINTER_MOCK_DIR",
        ):
            self.assertTrue(hasattr(settings, name), name)

        self.assertIsInstance(get_backend(), MockBackend)

        # endpoint cetak existing hidup (400 karena body kosong, BUKAN 404/500)
        cetak = self.api.post("/api/v1/print/bundle-tag/", {}, format="json")

        self.assertEqual(cetak.status_code, 400)
        self.assertIn("bundle_id", cetak.json()["detail"])

        # PrintJob (audit cetak) tetap terdaftar apa adanya
        from integrations.printing.models import PrintJob

        self.assertEqual(PrintJob._meta.db_table, "printing_printjob")

        # endpoint Settings H5.1/H5.5/H5.6/H5.8 tetap hijau
        self.assertEqual(self.api.get("/api/v1/settings/company/").status_code, 200)
        self.assertEqual(self.api.get("/api/v1/settings/audit/").status_code, 200)
        self.assertEqual(self.api.get("/api/v1/settings/integration/").status_code, 200)
        self.assertEqual(self.api.get("/api/v1/settings/wa/").status_code, 200)




