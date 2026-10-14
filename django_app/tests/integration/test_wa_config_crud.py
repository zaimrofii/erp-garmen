"""Test **H5.8** — WA Gateway Config (``/api/v1/settings/wa/``).

Cakupan: GET singleton (``config: null`` + ``effective`` + ``diverges`` +
``needs_restart`` + ``restart_command``) · PUT create-on-first-PUT (2× PUT = 1 baris) ·
**guard backend** (``real``/``api`` ⇒ url+key wajib) · validasi url (http/https + host,
**termasuk hostname internal tanpa TLD**) & backend & ``active`` · **masking rahasia**
(``wa_api_key`` = ``***``; PUT ``***`` = tak berubah, nilai baru/kosong = ganti/hapus;
``diverges`` **tidak pernah** membocorkan nilai) · izin (anonim 403; operator baca saja) ·
``POST …/test-connection/`` (mock default / backend tak dikenal → fallback mock / kredensial
kurang / gateway gagal / gateway tanpa ``health_check``) · ledger ``SyncRecord``
``master.wa_config``/``SKIPPED`` + ``AuditLog`` · non-breaking WA gateway existing
(``integrations.wa_bot``) + H5.1/H5.2/H5.3/H5.6.

Keputusan STEP 0 (H5.8 — **Opsi B**, pola H5.6): DB menyimpan **profil gateway**;
**konsumen TIDAK disentuh** (``get_wa_gateway`` tetap membaca ``settings.WA_*``) ⇒ nol
risiko regresi; aktivasi = salin ke ``.env`` + restart (``restart_command``); API key
**plaintext + mask** (Fernet = V2).

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_wa_config_crud.py -q
"""

from __future__ import annotations

from unittest import mock

from django.conf import settings
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.audit.models import AuditLog
from core.auth.models import Role, User
from integrations.erp_sync.models import SyncRecord, SyncResource, SyncStage, SyncStatus
from integrations.wa_bot.services import MockWAGateway, get_wa_gateway
from master.models import WAConfig
from master.wa_config_services import CONFIG_FIELDS, MASK, MES_ONLY_REASON

CONFIG_URL = "/api/v1/settings/wa/"
TEST_URL = "/api/v1/settings/wa/test-connection/"
ENVELOPE_KEYS = {"config", "effective", "diverges", "needs_restart", "restart_command"}
ROW_KEYS = set(CONFIG_FIELDS) | {"id", "is_active", "created_at", "updated_at"}

#: Override env agar perbandingan DB vs ``.env`` deterministik (gateway mock).
ENV_MOCK = {"WA_BACKEND": "mock", "WA_API_URL": None, "WA_API_KEY": None}


class WAConfigTestCase(TestCase):
    """Basis bersama: user admin/operator + klien admin siap pakai."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="admin-wacfg",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.ADMIN),
        )
        cls.operator = User.objects.create_user(
            username="op-wacfg",
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

    def config(self) -> WAConfig:
        """Baris singleton (baris pertama)."""
        return WAConfig.objects.order_by("pk").first()

    def sync_records(self, config: WAConfig):
        """Ledger ``SyncRecord`` milik baris config."""
        return SyncRecord.objects.filter(
            resource=SyncResource.MASTER_WA_CONFIG.value,
            resource_id=str(config.pk),
            stage=SyncStage.MASTER_PUSH.value,
        )

    def audit_logs(self, config: WAConfig, action: str | None = None):
        """AuditLog milik baris config (opsional difilter action)."""
        queryset = AuditLog.objects.filter(
            resource=SyncResource.MASTER_WA_CONFIG.value,
            resource_id=str(config.pk),
        )

        return queryset.filter(action=action) if action else queryset


class WAConfigGetPutTests(WAConfigTestCase):
    """``GET|PUT /settings/wa/`` — singleton + guard + masking rahasia."""

    def test_get_belum_ada_null_dan_effective(self):
        response = self.get()

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), ENVELOPE_KEYS)
        self.assertIsNone(body["config"])
        self.assertEqual(set(body["effective"]), set(CONFIG_FIELDS))
        # efektif = nilai .env/settings yang benar-benar aktif
        self.assertEqual(body["effective"]["wa_backend"], str(settings.WA_BACKEND))
        self.assertEqual(
            body["effective"]["wa_api_key"], MASK if settings.WA_API_KEY else ""
        )
        self.assertEqual(body["diverges"], {})
        self.assertFalse(body["needs_restart"])
        self.assertIn("restart", body["restart_command"])
        # GET tidak boleh membuat baris
        self.assertEqual(WAConfig.objects.count(), 0)

    def test_put_create_pertama_kali(self):
        response = self.put(
            wa_backend="real",
            wa_api_url="https://api.vendor-wa.test",
            wa_api_key="rahasia-klien",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), ENVELOPE_KEYS)
        row = body["config"]
        self.assertEqual(set(row), ROW_KEYS)
        self.assertEqual(row["wa_backend"], "real")
        self.assertEqual(row["wa_api_url"], "https://api.vendor-wa.test")
        self.assertEqual(row["wa_api_key"], MASK)  # selalu di-mask
        self.assertTrue(row["is_active"])
        self.assertTrue(body["needs_restart"])  # profil beda dari .env

        # DB menyimpan plaintext (keputusan STEP 0) — response & ledger tidak
        self.assertEqual(WAConfig.objects.count(), 1)
        config = self.config()

        self.assertEqual(config.wa_api_key, "rahasia-klien")

        record = self.sync_records(config).get()

        self.assertEqual(record.status, SyncStatus.SKIPPED)
        self.assertEqual(record.last_error, MES_ONLY_REASON)
        self.assertEqual(record.payload["wa_api_key"], MASK)

        logs = self.audit_logs(config, "master.create")

        self.assertEqual(logs.count(), 1)
        self.assertTrue(logs.first().metadata["mes_only"])

    def test_put_update_singleton(self):
        self.assertEqual(self.put(wa_backend="mock").status_code, 200)

        response = self.put(
            wa_backend="real", wa_api_url="http://wa-gateway:8080", wa_api_key="kunci-1"
        )

        self.assertEqual(response.status_code, 200)
        row = response.json()["config"]

        self.assertEqual(row["wa_backend"], "real")
        self.assertEqual(row["wa_api_url"], "http://wa-gateway:8080")

        # singleton: 2× PUT tetap 1 baris; ledger satu, audit bertambah
        self.assertEqual(WAConfig.objects.count(), 1)
        config = self.config()

        self.assertEqual(self.sync_records(config).count(), 1)
        self.assertEqual(self.audit_logs(config, "master.create").count(), 1)
        self.assertEqual(self.audit_logs(config, "master.update").count(), 1)

    def test_put_mask_tidak_mengubah_api_key(self):
        self.put(
            wa_backend="real",
            wa_api_url="http://wa-gateway:8080",
            wa_api_key="rahasia-asli",
        )

        response = self.put(wa_api_key=MASK)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["config"]["wa_api_key"], MASK)
        self.assertEqual(self.config().wa_api_key, "rahasia-asli")

    def test_put_api_key_nilai_baru_dan_kosong(self):
        self.put(wa_backend="mock", wa_api_key="rahasia-asli")

        baru = self.put(wa_api_key="rahasia-baru")

        self.assertEqual(baru.status_code, 200)
        self.assertEqual(self.config().wa_api_key, "rahasia-baru")

        kosong = self.put(wa_api_key="")

        self.assertEqual(kosong.status_code, 200)
        self.assertEqual(kosong.json()["config"]["wa_api_key"], "")
        self.assertEqual(self.config().wa_api_key, "")

        # guard: backend real/api TIDAK boleh kehilangan kredensial -> 400
        dijaga = self.put(wa_backend="real", wa_api_url="http://wa-gateway:8080")

        self.assertEqual(dijaga.status_code, 400)
        self.assertIn("membutuhkan", dijaga.json()["detail"])

    def test_validasi_backend_dan_url(self):
        # backend di luar mock|real|api -> 400
        salah_backend = self.put(wa_backend="waha")

        self.assertEqual(salah_backend.status_code, 400)
        self.assertIn("wa_backend", salah_backend.json()["detail"])

        # url tanpa skema http/https (tanpa host) -> 400
        salah_url = self.put(
            wa_backend="real", wa_api_url="bukan-url", wa_api_key="kunci"
        )

        self.assertEqual(salah_url.status_code, 400)
        self.assertIn("wa_api_url", salah_url.json()["detail"])

        # guard kredensial: real/api wajib url + key
        kurang = self.put(wa_backend="real", wa_api_url="http://wa-gateway:8080")

        self.assertEqual(kurang.status_code, 400)
        self.assertIn("membutuhkan", kurang.json()["detail"])

        kurang_api = self.put(wa_backend="api", wa_api_key="kunci")

        self.assertEqual(kurang_api.status_code, 400)
        self.assertEqual(WAConfig.objects.count(), 0)

        # 'mock' tidak butuh kredensial + hostname internal tanpa TLD diterima
        mock_ok = self.put(wa_backend="mock")

        self.assertEqual(mock_ok.status_code, 200)
        self.assertEqual(mock_ok.json()["config"]["wa_api_url"], "")

        internal = self.put(
            wa_backend="real", wa_api_url="http://wa-gateway:8080", wa_api_key="kunci"
        )

        self.assertEqual(internal.status_code, 200)
        self.assertEqual(internal.json()["config"]["wa_api_url"], "http://wa-gateway:8080")

    def test_active_boolean_toggle(self):
        self.assertEqual(self.put(wa_backend="mock").status_code, 200)

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


class WAConfigDivergenceTests(WAConfigTestCase):
    """``diverges`` / ``needs_restart`` — DB vs ``.env`` (tanpa membocorkan rahasia)."""

    @override_settings(**ENV_MOCK)
    def test_diverges_kosong_kalau_sama_dengan_env(self):
        self.put(wa_backend="mock")

        body = self.get().json()

        self.assertEqual(body["diverges"], {})
        self.assertFalse(body["needs_restart"])

        # satu field diubah -> itulah divergensinya
        self.put(
            wa_backend="real",
            wa_api_url="https://api.vendor-wa.test",
            wa_api_key="kunci-baru",
        )

        body2 = self.get().json()

        self.assertEqual(
            body2["diverges"],
            {
                "wa_backend": {"db": "real", "env": "mock"},
                "wa_api_url": {"db": "https://api.vendor-wa.test", "env": ""},
                "wa_api_key": {"db": MASK, "env": ""},
            },
        )
        self.assertTrue(body2["needs_restart"])

    @override_settings(WA_BACKEND="mock", WA_API_URL=None, WA_API_KEY="kunci-env")
    def test_diverges_tidak_membocorkan_rahasia(self):
        self.put(wa_backend="mock", wa_api_key="kunci-db")

        body = self.get().json()

        # rahasia beda -> terdeteksi, tetapi nilainya tetap di-mask
        self.assertEqual(body["diverges"]["wa_api_key"], {"db": MASK, "env": MASK})
        self.assertNotIn("kunci-db", str(body))
        self.assertNotIn("kunci-env", str(body))

    def test_put_tanpa_perubahan_tidak_menulis_ledger(self):
        self.put(wa_backend="mock")
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
        self.assertEqual(WAConfig.objects.count(), 0)


class FakeGateway:
    """Gateway WA palsu untuk ``test-connection`` (tanpa jaringan)."""

    def __init__(self, *, healthy: bool = True, name: str = "real") -> None:
        self.healthy = healthy
        self.name = name

    def health_check(self) -> bool:
        """Hasil ping yang dikonfigurasi test."""
        return self.healthy


class BrokenGateway:
    """Gateway WA tanpa ``health_check`` (kontrak tidak lengkap)."""

    name = "real"


class ExplodingGateway:
    """Gateway WA yang melempar saat diping."""

    name = "real"

    def health_check(self) -> bool:
        """Selalu gagal — menguji bahwa error dilaporkan ``ok=false``."""
        raise RuntimeError("vendor down")


class WAConfigTestConnectionTests(WAConfigTestCase):
    """``POST …/test-connection/`` — read-only, memakai ``.env`` + mock-friendly."""

    @override_settings(WA_BACKEND="mock", WA_API_URL=None, WA_API_KEY=None)
    def test_mock_default_ok(self):
        response = self.post_test_connection()

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["backend"], "mock")
        self.assertTrue(body["mock"])
        self.assertIn("Mock gateway", body["message"])
        # read-only: tidak membuat baris profil
        self.assertEqual(WAConfig.objects.count(), 0)

    @override_settings(WA_BACKEND="cloud-api", WA_API_URL=None, WA_API_KEY=None)
    def test_backend_tak_dikenal_fallback_mock(self):
        # NON-BREAKING: factory existing (`get_wa_gateway`) tetap fallback ke mock
        response = self.post_test_connection()

        self.assertEqual(response.status_code, 200)
        body = response.json()

        self.assertTrue(body["ok"])
        self.assertEqual(body["backend"], "mock")
        self.assertTrue(body["mock"])
        self.assertIsInstance(get_wa_gateway(), MockWAGateway)

    @override_settings(WA_BACKEND="real", WA_API_URL=None, WA_API_KEY=None)
    def test_kredensial_kurang_dilaporkan(self):
        response = self.post_test_connection()

        self.assertEqual(response.status_code, 200)
        body = response.json()

        self.assertFalse(body["ok"])
        self.assertEqual(body["backend"], "real")
        self.assertFalse(body["mock"])
        self.assertIn("belum lengkap", body["message"])
        self.assertIn("WA_API_URL", body["message"])
        self.assertIn("WA_API_KEY", body["message"])

    @override_settings(
        WA_BACKEND="real", WA_API_URL="http://wa-gateway:8080", WA_API_KEY="kunci"
    )
    def test_gateway_palsu_ok_dan_gagal(self):
        with mock.patch(
            "master.wa_config_services.get_wa_gateway",
            return_value=FakeGateway(healthy=True, name="real"),
        ):
            ok = self.post_test_connection()

        self.assertTrue(ok.json()["ok"])
        self.assertEqual(ok.json()["url"], "http://wa-gateway:8080")
        self.assertFalse(ok.json()["mock"])
        self.assertIn("health check OK", ok.json()["message"])

        with mock.patch(
            "master.wa_config_services.get_wa_gateway",
            return_value=FakeGateway(healthy=False, name="real"),
        ):
            gagal = self.post_test_connection()

        self.assertFalse(gagal.json()["ok"])
        self.assertIn("tidak siap", gagal.json()["message"])

    @override_settings(
        WA_BACKEND="real", WA_API_URL="http://wa-gateway:8080", WA_API_KEY="kunci"
    )
    def test_gateway_tanpa_health_check_dan_yang_meledak(self):
        with mock.patch(
            "master.wa_config_services.get_wa_gateway", return_value=BrokenGateway()
        ):
            tanpa = self.post_test_connection()

        self.assertEqual(tanpa.status_code, 200)
        self.assertFalse(tanpa.json()["ok"])
        self.assertIn("health_check", tanpa.json()["message"])

        with mock.patch(
            "master.wa_config_services.get_wa_gateway", return_value=ExplodingGateway()
        ):
            meledak = self.post_test_connection()

        self.assertEqual(meledak.status_code, 200)
        self.assertFalse(meledak.json()["ok"])
        self.assertIn("tidak menjawab", meledak.json()["message"])


class WAConfigNonBreakingTests(WAConfigTestCase):
    """Non-breaking: WA gateway existing + endpoint H5.1/H5.2/H5.3/H5.6 tetap hijau."""

    def test_setting_wa_dan_gateway_existing_utuh(self):
        self.assertTrue(hasattr(settings, "WA_BACKEND"))
        self.assertTrue(hasattr(settings, "WA_API_URL"))
        self.assertTrue(hasattr(settings, "WA_API_KEY"))

        # `POST /api/v1/wa/send/` (Fase F) tetap jalan dengan gateway mock
        sent = self.api.post(
            "/api/v1/wa/send/", {"to": "628123456789", "message": "tes"}, format="json"
        )

        self.assertEqual(sent.status_code, 200)
        self.assertTrue(sent.json()["ok"])

    def test_enum_ledger_dan_endpoint_settings_lain(self):
        self.assertEqual(SyncResource.MASTER_WA_CONFIG.value, "master.wa_config")

        integration = self.api.get("/api/v1/settings/integration/")
        company = self.api.get("/api/v1/settings/company/")
        currencies = self.api.get("/api/v1/settings/currencies/")
        sequences = self.api.get("/api/v1/settings/sequences/")

        self.assertEqual(integration.status_code, 200)
        self.assertEqual(company.status_code, 200)
        self.assertEqual(currencies.status_code, 200)
        self.assertEqual(sequences.status_code, 200)



