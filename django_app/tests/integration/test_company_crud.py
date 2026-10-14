"""Test **H5.1** — Company Profile (``/api/v1/settings/company/``).

Cakupan: GET **singleton** (``{"company": null}`` bila belum ada — **tanpa** seed/efek
samping) · PUT **create-on-first-PUT** (``get_or_create`` ⇒ 2× PUT tetap **1 baris**) ·
validasi (``name`` wajib saat create, ``country`` ISO 2 huruf auto-upper, ``npwp``
15/16 digit ternormalisasi — pola H1.6, ``email``/``website``/``logo_url`` valid,
``currency_id`` harus ada) · izin (anonim 403 semua; operator hanya baca; tulis
**ADMIN/OWNER**) · ledger ``SyncRecord`` ``master.company``/``MASTER_PUSH`` ber-status
**``SKIPPED``** (MES-only) + ``AuditLog`` · non-breaking H5.2/H5.3.

Keputusan STEP 0 (H5.1):
  * **greenfield** ``master.Company`` (tidak ada model/konsumen/transport ``res.company``
    di MES) — 13 field bisnis + ``created_at``/``updated_at``;
  * **MES-only** (``SKIPPED``): ``res.company`` = konfigurasi akuntansi Odoo ⇒ tidak
    di-push/di-pull; preseden H5.2/Sprint C;
  * ``GET`` kosong → **200** ``{"company": null}`` (pola ``/taxes/default/`` H3.6),
    **tanpa** seed;
  * ``PUT`` = **create-on-first-PUT** (tanpa POST terpisah).

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_company_crud.py -q
"""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from core.audit.models import AuditLog
from core.auth.models import Role, User
from integrations.erp_sync.models import SyncRecord, SyncResource, SyncStage, SyncStatus
from master import company_services
from master.company_services import MES_ONLY_REASON
from master.models import Company, Currency

COMPANY_URL = "/api/v1/settings/company/"
ROW_KEYS = {
    "id",
    "name",
    "legal_name",
    "address",
    "city",
    "country",
    "phone",
    "email",
    "npwp",
    "website",
    "logo_url",
    "currency_id",
    "currency",
    "timezone",
    "is_active",
    "created_at",
    "updated_at",
}

#: NPWP valid 15 digit (format lama) & 16 digit (format NIK-NPWP) — pola H1.6.
NPWP_15 = "01.234.567.8-901.000"
NPWP_16 = "01.234.567.8-901.000.1"


class CompanyTestCase(TestCase):
    """Basis bersama: user admin/operator + klien admin siap pakai."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="admin-company",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.ADMIN),
        )
        cls.operator = User.objects.create_user(
            username="op-company",
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

    def put(self, **body):
        """PUT profil perusahaan dengan klien admin."""
        return self.api.put(COMPANY_URL, body, format="json")

    def get(self):
        """GET profil perusahaan dengan klien admin."""
        return self.api.get(COMPANY_URL)

    def company(self) -> Company:
        """Baris singleton (baris pertama)."""
        return Company.objects.order_by("pk").first()

    def sync_records(self, company: Company):
        """Ledger ``SyncRecord`` milik baris company."""
        return SyncRecord.objects.filter(
            resource=SyncResource.MASTER_COMPANY.value,
            resource_id=str(company.pk),
            stage=SyncStage.MASTER_PUSH.value,
        )

    def audit_logs(self, company: Company, action: str | None = None):
        """AuditLog milik baris company (opsional difilter action)."""
        queryset = AuditLog.objects.filter(
            resource=SyncResource.MASTER_COMPANY.value,
            resource_id=str(company.pk),
        )

        return queryset.filter(action=action) if action else queryset


class CompanyGetPutTests(CompanyTestCase):
    """``GET|PUT /settings/company/`` — singleton, create-on-first-PUT, validasi."""

    def test_get_belum_ada_null_tanpa_membuat_baris(self):
        response = self.get()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"company": None})
        # GET tidak boleh membuat baris (tanpa seed — keputusan STEP 0)
        self.assertEqual(Company.objects.count(), 0)

    def test_put_create_pertama_kali(self):
        currency = Currency.objects.create(code="IDR", name="Rupiah", symbol="Rp")

        response = self.put(
            name="PT Garmen Jaya",
            legal_name="PT Garmen Jaya Sejahtera",
            address="Jl. Industri 1",
            city="Bandung",
            country="id",
            phone="022-123456",
            email="admin@garmen.test",
            npwp=NPWP_15,
            website="https://garmen.test",
            logo_url="https://garmen.test/logo.png",
            currency_id=currency.pk,
            timezone="Asia/Makassar",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()["company"]
        self.assertEqual(set(body), ROW_KEYS)
        self.assertEqual(body["name"], "PT Garmen Jaya")
        self.assertEqual(body["legal_name"], "PT Garmen Jaya Sejahtera")
        self.assertEqual(body["country"], "ID")  # auto-upper
        self.assertEqual(body["npwp"], "012345678901000")  # digit-only (H1.6)
        self.assertEqual(body["currency_id"], currency.pk)
        self.assertEqual(body["currency"]["code"], "IDR")
        self.assertEqual(body["timezone"], "Asia/Makassar")
        self.assertTrue(body["is_active"])

        self.assertEqual(Company.objects.count(), 1)
        company = self.company()
        record = self.sync_records(company).get()

        self.assertEqual(record.status, SyncStatus.SKIPPED)
        self.assertEqual(record.last_error, MES_ONLY_REASON)
        self.assertEqual(record.payload["name"], "PT Garmen Jaya")
        self.assertTrue(record.payload["active"])

        logs = self.audit_logs(company, "master.create")

        self.assertEqual(logs.count(), 1)
        self.assertTrue(logs.first().metadata["mes_only"])

    def test_put_update_tanpa_duplikat_singleton(self):
        self.assertEqual(self.put(name="PT Awal").status_code, 200)

        response = self.put(name="PT Baru", city="Solo")

        self.assertEqual(response.status_code, 200)
        body = response.json()["company"]

        self.assertEqual(body["name"], "PT Baru")
        self.assertEqual(body["city"], "Solo")
        # timezone default diberikan saat create, tetap saat update
        self.assertEqual(body["timezone"], "Asia/Jakarta")

        # singleton: 2× PUT tetap 1 baris
        self.assertEqual(Company.objects.count(), 1)
        company = self.company()

        self.assertEqual(self.sync_records(company).count(), 1)
        self.assertEqual(self.audit_logs(company, "master.create").count(), 1)
        self.assertEqual(self.audit_logs(company, "master.update").count(), 1)

    def test_put_tanpa_name_400_saat_belum_ada(self):
        response = self.put(city="Bandung")

        self.assertEqual(response.status_code, 400)
        self.assertIn("name", response.json()["detail"])
        self.assertEqual(Company.objects.count(), 0)

    def test_put_name_kosong_400_saat_update(self):
        self.put(name="PT Awal")

        response = self.put(name="   ")

        self.assertEqual(response.status_code, 400)
        self.assertIn("name", response.json()["detail"])
        self.assertEqual(self.company().name, "PT Awal")

    def test_put_npwp_invalid_dan_normalisasi(self):
        invalid = self.put(name="PT A", npwp="12345")

        self.assertEqual(invalid.status_code, 400)
        self.assertIn("15 atau 16 digit", invalid.json()["detail"])
        self.assertEqual(Company.objects.count(), 0)

        self.assertEqual(self.put(name="PT A", npwp=NPWP_15).status_code, 200)
        self.assertEqual(self.company().npwp, "012345678901000")

        self.assertEqual(self.put(npwp=NPWP_16).status_code, 200)
        self.assertEqual(self.company().npwp, "0123456789010001")

        self.assertEqual(self.put(npwp="").status_code, 200)
        self.assertEqual(self.company().npwp, "")

    def test_put_email_website_logo_url_invalid_400(self):
        self.put(name="PT A")

        salah_email = self.put(email="bukan-email")

        self.assertEqual(salah_email.status_code, 400)
        self.assertIn("email", salah_email.json()["detail"])

        salah_website = self.put(website="bukan-url")

        self.assertEqual(salah_website.status_code, 400)
        self.assertIn("website", salah_website.json()["detail"])

        salah_logo = self.put(logo_url="bukan-url")

        self.assertEqual(salah_logo.status_code, 400)
        self.assertIn("logo_url", salah_logo.json()["detail"])

        # tidak ada perubahan tersimpan & tidak ada audit tambahan
        company = self.company()

        self.assertEqual(company.email, "")
        self.assertEqual(self.audit_logs(company).count(), 1)

    def test_put_currency_id_invalid_dan_dikosongkan(self):
        currency = Currency.objects.create(code="USD", name="US Dollar")

        self.assertEqual(self.put(name="PT A", currency_id=999999).status_code, 400)
        self.assertEqual(self.put(name="PT A", currency_id="abc").status_code, 400)

        dibuat = self.put(name="PT A", currency_id=currency.pk)

        self.assertEqual(dibuat.status_code, 200)
        self.assertEqual(dibuat.json()["company"]["currency"]["code"], "USD")

        kosong = self.put(currency_id=None)

        self.assertEqual(kosong.status_code, 200)
        self.assertIsNone(kosong.json()["company"]["currency_id"])
        self.assertIsNone(kosong.json()["company"]["currency"])

    def test_put_country_invalid_dan_auto_upper(self):
        self.assertEqual(self.put(name="PT A", country="IDN").status_code, 400)
        self.assertEqual(self.put(name="PT A", country="ID").json()["company"]["country"], "ID")
        self.assertEqual(self.put(country="").json()["company"]["country"], "")

    def test_put_tanpa_perubahan_tidak_menulis_ledger_baru(self):
        self.put(name="PT A")
        company = self.company()
        sebelum = self.audit_logs(company).count()

        response = self.put()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["company"]["name"], "PT A")
        self.assertEqual(self.audit_logs(company).count(), sebelum)
        self.assertEqual(self.sync_records(company).count(), 1)

    def test_get_setelah_put_mengembalikan_baris(self):
        self.put(name="PT Garmen", city="Bandung")

        body = self.get().json()["company"]

        self.assertEqual(body["name"], "PT Garmen")
        self.assertEqual(body["city"], "Bandung")
        self.assertEqual(Company.objects.count(), 1)


class CompanyAuthAndServiceTests(CompanyTestCase):
    """Izin (anonim 403 semua · operator baca saja) + service singleton + non-breaking."""

    def test_auth_anonim_403_semua_dan_operator_hanya_baca(self):
        anonim = self.as_user(None)

        self.assertEqual(anonim.get(COMPANY_URL).status_code, 403)
        self.assertEqual(
            anonim.put(COMPANY_URL, {"name": "PT X"}, format="json").status_code, 403
        )

        operator = self.as_user(self.operator)

        self.assertEqual(operator.get(COMPANY_URL).status_code, 200)
        self.assertEqual(
            operator.put(COMPANY_URL, {"name": "PT X"}, format="json").status_code, 403
        )
        # tidak ada baris yang dibuat oleh percobaan tulis non-admin
        self.assertEqual(Company.objects.count(), 0)

    def test_service_get_or_create_company_default(self):
        company, created = company_services.get_or_create_company()

        self.assertTrue(created)
        self.assertEqual(company.name, company_services.DEFAULT_COMPANY_NAME)
        self.assertEqual(company.timezone, company_services.DEFAULT_TIMEZONE)

        lagi, created_lagi = company_services.get_or_create_company()

        self.assertFalse(created_lagi)
        self.assertEqual(lagi.pk, company.pk)
        self.assertEqual(Company.objects.count(), 1)

    def test_non_breaking_h5_2_dan_h5_3(self):
        currencies = self.api.get("/api/v1/settings/currencies/")
        sequences = self.api.get("/api/v1/settings/sequences/")

        self.assertEqual(currencies.status_code, 200)
        self.assertEqual(set(currencies.json()), {"rows", "total_count", "has_more", "next_cursor"})
        self.assertEqual(sequences.status_code, 200)
        self.assertEqual(sequences.json()["total_count"], 9)

