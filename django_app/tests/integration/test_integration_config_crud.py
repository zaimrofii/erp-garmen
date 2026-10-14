"""Test **H5.6** — Integration Config (``/api/v1/settings/integration/``).

Cakupan: GET singleton (``config: null`` + ``effective`` + ``diverges`` +
``needs_restart`` + ``restart_command``) · PUT create-on-first-PUT (2× PUT = 1 baris) ·
**guard adapter** (``odoo`` ⇒ url+db+user wajib) · validasi URL/timeout/id/toleransi/
alert-WA · **masking rahasia** (``odoo_api_key`` = ``***``; PUT ``***`` = tak berubah,
nilai baru/kosong = ganti/hapus; ``diverges`` **tidak pernah** membocorkan nilai) · izin
(anonim 403; operator baca saja) · ``POST …/test-connection/`` (adapter null / kredensial
kurang / adapter mock) · ledger ``SyncRecord`` ``master.integration_config``/``SKIPPED`` +
``AuditLog`` · non-breaking H5.1/H5.2/H5.3 + ``settings.ODOO_PICKING_TYPE_INTERNAL_ID``.

Keputusan STEP 0 (H5.6 — **Opsi B**): DB menyimpan **profil** config; **konsumen TIDAK
disentuh** (tetap membaca ``.env``) ⇒ nol risiko regresi (8 konsumen + 113 referensi
setting di test); aktivasi = salin ke ``.env`` + restart (``restart_command``); API key
**plaintext + mask** (Fernet = V2).

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_integration_config_crud.py -q
"""

from __future__ import annotations

from unittest import mock

from django.conf import settings
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.audit.models import AuditLog
from core.auth.models import Role, User
from integrations.erp_sync.models import SyncRecord, SyncResource, SyncStage, SyncStatus
from master.integration_config_services import CONFIG_FIELDS, MASK, MES_ONLY_REASON
from master.models import IntegrationConfig

CONFIG_URL = "/api/v1/settings/integration/"
TEST_URL = "/api/v1/settings/integration/test-connection/"
ENVELOPE_KEYS = {"config", "effective", "diverges", "needs_restart", "restart_command"}
ROW_KEYS = set(CONFIG_FIELDS) | {"id", "is_active", "created_at", "updated_at"}

#: Payload minimum agar lolos guard adapter ``odoo``.
ODOO_OK = {
    "erp_adapter": "odoo",
    "odoo_url": "http://odoo-klien:8069",
    "odoo_db": "garmen_klien",
    "odoo_user": "api_bot",
}


class IntegrationConfigTestCase(TestCase):
    """Basis bersama: user admin/operator + klien admin siap pakai."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="admin-intcfg",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.ADMIN),
        )
        cls.operator = User.objects.create_user(
            username="op-intcfg",
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

    def config(self) -> IntegrationConfig:
        """Baris singleton (baris pertama)."""
        return IntegrationConfig.objects.order_by("pk").first()

    def sync_records(self, config: IntegrationConfig):
        """Ledger ``SyncRecord`` milik baris config."""
        return SyncRecord.objects.filter(
            resource=SyncResource.MASTER_INTEGRATION_CONFIG.value,
            resource_id=str(config.pk),
            stage=SyncStage.MASTER_PUSH.value,
        )

    def audit_logs(self, config: IntegrationConfig, action: str | None = None):
        """AuditLog milik baris config (opsional difilter action)."""
        queryset = AuditLog.objects.filter(
            resource=SyncResource.MASTER_INTEGRATION_CONFIG.value,
            resource_id=str(config.pk),
        )

        return queryset.filter(action=action) if action else queryset


class IntegrationConfigGetPutTests(IntegrationConfigTestCase):
    """``GET|PUT /settings/integration/`` — singleton + guard + masking rahasia."""

    def test_get_belum_ada_null_dan_effective(self):
        response = self.get()

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), ENVELOPE_KEYS)
        self.assertIsNone(body["config"])
        self.assertEqual(set(body["effective"]), set(CONFIG_FIELDS))
        # efektif = nilai .env/settings yang benar-benar aktif
        self.assertEqual(body["effective"]["erp_adapter"], str(settings.ERP_ADAPTER))
        self.assertEqual(body["effective"]["odoo_url"], str(settings.ODOO_URL))
        self.assertEqual(
            body["effective"]["odoo_api_key"], MASK if settings.ODOO_API_KEY else ""
        )
        self.assertEqual(body["diverges"], {})
        self.assertFalse(body["needs_restart"])
        self.assertIn("restart", body["restart_command"])
        # GET tidak boleh membuat baris
        self.assertEqual(IntegrationConfig.objects.count(), 0)

    def test_put_create_pertama_kali(self):
        response = self.put(
            **ODOO_OK,
            odoo_api_key="rahasia-klien",
            odoo_timeout="45.5",
            odoo_location_wip_id=11,
            odoo_uom_id=33,
            reconciliation_tolerance_units="7.5",
            reconciliation_tolerance_pct="0.02",
            reconciliation_alert_wa_to="6281,6282",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), ENVELOPE_KEYS)
        row = body["config"]
        self.assertEqual(set(row), ROW_KEYS)
        self.assertEqual(row["erp_adapter"], "odoo")
        self.assertEqual(row["odoo_url"], "http://odoo-klien:8069")
        self.assertEqual(row["odoo_api_key"], MASK)  # selalu di-mask
        self.assertEqual(row["odoo_timeout"], 45.5)
        self.assertEqual(row["odoo_location_wip_id"], 11)
        self.assertEqual(row["odoo_uom_id"], 33)
        self.assertEqual(row["reconciliation_tolerance_units"], 7.5)
        self.assertEqual(row["reconciliation_tolerance_pct"], 0.02)
        self.assertEqual(row["reconciliation_alert_wa_to"], ["6281", "6282"])
        self.assertIsNone(row["odoo_location_fg_id"])
        self.assertTrue(row["is_active"])
        self.assertTrue(body["needs_restart"])  # profil beda dari .env

        # DB menyimpan plaintext (keputusan STEP 0) — response & ledger tidak
        self.assertEqual(IntegrationConfig.objects.count(), 1)
        config = self.config()

        self.assertEqual(config.odoo_api_key, "rahasia-klien")

        record = self.sync_records(config).get()

        self.assertEqual(record.status, SyncStatus.SKIPPED)
        self.assertEqual(record.last_error, MES_ONLY_REASON)
        self.assertEqual(record.payload["odoo_api_key"], MASK)

        logs = self.audit_logs(config, "master.create")

        self.assertEqual(logs.count(), 1)
        self.assertTrue(logs.first().metadata["mes_only"])

    def test_put_update_singleton(self):
        self.assertEqual(self.put(**ODOO_OK).status_code, 200)

        response = self.put(odoo_db="garmen_baru", odoo_uom_id=44)

        self.assertEqual(response.status_code, 200)
        row = response.json()["config"]

        self.assertEqual(row["odoo_db"], "garmen_baru")
        self.assertEqual(row["odoo_uom_id"], 44)

        # singleton: 2× PUT tetap 1 baris; field lain tidak berubah
        self.assertEqual(IntegrationConfig.objects.count(), 1)
        config = self.config()

        self.assertEqual(config.odoo_url, ODOO_OK["odoo_url"])
        self.assertEqual(self.sync_records(config).count(), 1)
        self.assertEqual(self.audit_logs(config, "master.create").count(), 1)
        self.assertEqual(self.audit_logs(config, "master.update").count(), 1)

    def test_put_mask_tidak_mengubah_api_key(self):
        self.put(**ODOO_OK, odoo_api_key="rahasia-asli")

        response = self.put(odoo_api_key=MASK)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["config"]["odoo_api_key"], MASK)
        self.assertEqual(self.config().odoo_api_key, "rahasia-asli")

    def test_put_api_key_nilai_baru_dan_kosong(self):
        self.put(**ODOO_OK, odoo_api_key="rahasia-asli")

        baru = self.put(odoo_api_key="rahasia-baru")

        self.assertEqual(baru.status_code, 200)
        self.assertEqual(self.config().odoo_api_key, "rahasia-baru")

        kosong = self.put(odoo_api_key="")

        self.assertEqual(kosong.status_code, 200)
        self.assertEqual(kosong.json()["config"]["odoo_api_key"], "")
        self.assertEqual(self.config().odoo_api_key, "")

    def test_guard_adapter_odoo_wajib_kredensial(self):
        salah = self.put(erp_adapter="accurate")

        self.assertEqual(salah.status_code, 400)
        self.assertIn("erp_adapter", salah.json()["detail"])

        kurang = self.put(erp_adapter="odoo", odoo_url="http://x:8069")

        self.assertEqual(kurang.status_code, 400)
        self.assertIn("membutuhkan", kurang.json()["detail"])
        self.assertEqual(IntegrationConfig.objects.count(), 0)

        # adapter 'null' tidak butuh kredensial
        null_ok = self.put(erp_adapter="null")

        self.assertEqual(null_ok.status_code, 200)
        self.assertEqual(null_ok.json()["config"]["erp_adapter"], "null")
        self.assertEqual(null_ok.json()["config"]["odoo_url"], "")

    def test_validasi_url_dan_timeout(self):
        salah_url = self.put(**{**ODOO_OK, "odoo_url": "bukan-url"})

        self.assertEqual(salah_url.status_code, 400)
        self.assertIn("odoo_url", salah_url.json()["detail"])

        self.assertEqual(self.put(**ODOO_OK, odoo_timeout=0).status_code, 400)
        self.assertEqual(self.put(**ODOO_OK, odoo_timeout=700).status_code, 400)
        self.assertEqual(self.put(**ODOO_OK, odoo_timeout="abc").status_code, 400)
        self.assertEqual(IntegrationConfig.objects.count(), 0)

    def test_validasi_id_dan_toleransi(self):
        self.assertEqual(self.put(**ODOO_OK, odoo_uom_id=-1).status_code, 400)
        self.assertEqual(self.put(**ODOO_OK, odoo_uom_id="abc").status_code, 400)
        self.assertEqual(
            self.put(**ODOO_OK, reconciliation_tolerance_pct=1.5).status_code, 400
        )
        self.assertEqual(
            self.put(**ODOO_OK, reconciliation_tolerance_units="x").status_code, 400
        )

        ok = self.put(**ODOO_OK, odoo_uom_id=33, reconciliation_tolerance_pct=1)

        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["config"]["odoo_uom_id"], 33)
        self.assertEqual(ok.json()["config"]["reconciliation_tolerance_pct"], 1.0)

        kosong = self.put(odoo_uom_id=None)

        self.assertEqual(kosong.status_code, 200)
        self.assertIsNone(kosong.json()["config"]["odoo_uom_id"])

    def test_validasi_alert_wa_list_dan_string(self):
        teks = self.put(**ODOO_OK, reconciliation_alert_wa_to="6281, 6282 ,")

        self.assertEqual(teks.status_code, 200)
        self.assertEqual(
            teks.json()["config"]["reconciliation_alert_wa_to"], ["6281", "6282"]
        )

        list_ok = self.put(reconciliation_alert_wa_to=["6283", "  "])

        self.assertEqual(list_ok.json()["config"]["reconciliation_alert_wa_to"], ["6283"])

        salah = self.put(reconciliation_alert_wa_to=123)

        self.assertEqual(salah.status_code, 400)
        self.assertIn("reconciliation_alert_wa_to", salah.json()["detail"])


#: Override env yang membuat **16 field** config sama dengan `.env` (deterministik).
ENV_SAMA = {
    "ERP_ADAPTER": "odoo",
    "ODOO_URL": "http://env-odoo:8069",
    "ODOO_DB": "env_db",
    "ODOO_USER": "env_user",
    "ODOO_API_KEY": "kunci-env",
    "ODOO_TIMEOUT": 30.0,
    "ODOO_LOCATION_WIP_ID": None,
    "ODOO_LOCATION_PRODUCTION_ID": None,
    "ODOO_LOCATION_FG_ID": None,
    "ODOO_LOCATION_SCRAP_ID": None,
    "ODOO_UOM_ID": None,
    "ODOO_PAYMENT_JOURNAL_ID": None,
    "ODOO_PICKING_TYPE_INTERNAL_ID": None,
    "RECONCILIATION_TOLERANCE_UNITS": 5,
    "RECONCILIATION_TOLERANCE_PCT": 0.01,
    "RECONCILIATION_ALERT_WA_TO": [],
}

#: Payload config yang persis sama dengan ``ENV_SAMA``.
CONFIG_SAMA = {
    "erp_adapter": "odoo",
    "odoo_url": "http://env-odoo:8069",
    "odoo_db": "env_db",
    "odoo_user": "env_user",
    "odoo_api_key": "kunci-env",
}


class IntegrationConfigDivergenceTests(IntegrationConfigTestCase):
    """``diverges`` / ``needs_restart`` — DB vs ``.env`` (tanpa membocorkan rahasia)."""

    @override_settings(**ENV_SAMA)
    def test_diverges_kosong_kalau_sama_dengan_env(self):
        self.put(**CONFIG_SAMA)

        body = self.get().json()

        self.assertEqual(body["diverges"], {})
        self.assertFalse(body["needs_restart"])

        # satu field diubah -> itulah divergensinya
        self.put(odoo_uom_id=33)

        body2 = self.get().json()

        self.assertEqual(body2["diverges"], {"odoo_uom_id": {"db": 33, "env": None}})
        self.assertTrue(body2["needs_restart"])

    @override_settings(**ENV_SAMA)
    def test_diverges_tidak_membocorkan_rahasia(self):
        self.put(**{**CONFIG_SAMA, "odoo_api_key": "kunci-db"})

        body = self.get().json()

        # rahasia beda -> terdeteksi, tetapi nilainya tetap di-mask
        self.assertEqual(body["diverges"]["odoo_api_key"], {"db": MASK, "env": MASK})
        self.assertNotIn("kunci-db", str(body))
        self.assertNotIn("kunci-env", str(body))

    def test_put_tanpa_perubahan_tidak_menulis_ledger(self):
        self.put(**ODOO_OK)
        config = self.config()
        sebelum = self.audit_logs(config).count()

        response = self.put()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.audit_logs(config).count(), sebelum)
        self.assertEqual(self.sync_records(config).count(), 1)

    def test_auth_anonim_403_dan_operator_baca_saja(self):
        anonim = self.as_user(None)

        self.assertEqual(anonim.get(CONFIG_URL).status_code, 403)
        self.assertEqual(anonim.put(CONFIG_URL, ODOO_OK, format="json").status_code, 403)
        self.assertEqual(anonim.post(TEST_URL, {}, format="json").status_code, 403)

        operator = self.as_user(self.operator)

        self.assertEqual(operator.get(CONFIG_URL).status_code, 200)
        self.assertEqual(operator.put(CONFIG_URL, ODOO_OK, format="json").status_code, 403)
        self.assertEqual(operator.post(TEST_URL, {}, format="json").status_code, 403)
        self.assertEqual(IntegrationConfig.objects.count(), 0)


class FakeAdapter:
    """Adapter ERP palsu untuk ``test-connection`` (tanpa Odoo nyata)."""

    def __init__(self, *, healthy: bool = True, version: dict | None = None) -> None:
        self.healthy = healthy
        self._version = version or {}
        self.closed = False

    def health_check(self) -> bool:
        """Hasil ping yang dikonfigurasi test."""
        return self.healthy

    def version(self) -> dict:
        """Info versi palsu (``server_version``)."""
        return self._version

    def close(self) -> None:
        """Tandai adapter sudah ditutup (dipanggil blok ``finally``)."""
        self.closed = True


#: Kredensial lengkap agar lolos cek ``ODOO_CREDENTIAL_KEYS``.
ENV_KREDENSIAL_LENGKAP = {
    "ERP_ADAPTER": "odoo",
    "ODOO_URL": "http://odoo.test:8069",
    "ODOO_DB": "odoo_db",
    "ODOO_USER": "api_bot",
    "ODOO_API_KEY": "kunci",
}


class IntegrationConfigTestConnectionTests(IntegrationConfigTestCase):
    """``POST …/test-connection/`` — read-only, memakai kredensial ``.env``."""

    @override_settings(ERP_ADAPTER="null")
    def test_adapter_null_tidak_diuji(self):
        response = self.post_test_connection()

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["adapter"], "null")
        self.assertIn("bukan 'odoo'", body["message"])
        self.assertIsNone(body["url"])
        self.assertIsNone(body["server_version"])

    @override_settings(ERP_ADAPTER="odoo", ODOO_DB="", ODOO_USER="", ODOO_API_KEY="")
    def test_kredensial_kurang_dilaporkan(self):
        response = self.post_test_connection()

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["ok"])
        self.assertIn("belum lengkap", body["message"])
        self.assertIn("ODOO_DB", body["message"])
        self.assertIn("ODOO_API_KEY", body["message"])

    @override_settings(**ENV_KREDENSIAL_LENGKAP)
    def test_ok_dengan_adapter_mock(self):
        adapter = FakeAdapter(healthy=True, version={"server_version": "17.0"})

        with mock.patch(
            "master.integration_config_services.get_adapter", return_value=adapter
        ) as getter:
            response = self.post_test_connection()

        self.assertEqual(response.status_code, 200)
        body = response.json()

        self.assertTrue(body["ok"])
        self.assertEqual(body["adapter"], "odoo")
        self.assertEqual(body["url"], "http://odoo.test:8069")
        self.assertEqual(body["server_version"], "17.0")
        self.assertIn("OK", body["message"])
        self.assertTrue(adapter.closed)
        getter.assert_called_once_with("odoo")

    @override_settings(**ENV_KREDENSIAL_LENGKAP)
    def test_gagal_dengan_adapter_mock(self):
        adapter = FakeAdapter(healthy=False)

        with mock.patch(
            "master.integration_config_services.get_adapter", return_value=adapter
        ):
            response = self.post_test_connection()

        body = response.json()

        self.assertFalse(body["ok"])
        self.assertIsNone(body["server_version"])
        self.assertIn("tidak menjawab", body["message"])
        self.assertTrue(adapter.closed)

    def test_non_breaking_setting_baru_dan_h5_lain(self):
        # H5.6 menambah ODOO_PICKING_TYPE_INTERNAL_ID sebagai env resmi (aditif)
        self.assertTrue(hasattr(settings, "ODOO_PICKING_TYPE_INTERNAL_ID"))

        currencies = self.api.get("/api/v1/settings/currencies/")
        sequences = self.api.get("/api/v1/settings/sequences/")
        company = self.api.get("/api/v1/settings/company/")

        self.assertEqual(currencies.status_code, 200)
        self.assertEqual(sequences.status_code, 200)
        self.assertEqual(sequences.json()["total_count"], 9)
        self.assertEqual(company.status_code, 200)
        self.assertIn("company", company.json())

