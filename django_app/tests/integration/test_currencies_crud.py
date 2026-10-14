"""Test **H5.2** — Currency CRUD (``/api/v1/settings/currencies/``).

Cakupan: list (+filter ``?search=&active=``) · create (``code`` ISO ``^[A-Z]{3}$``
auto-upper & unik, ``name`` wajib, ``symbol`` ≤8, ``rate`` ≥0, ``is_default``) · update
(termasuk **echo kode hasil pull** ``ODOO-<id>`` yang tidak boleh 400) · soft delete
dengan **3 guard** (``is_default`` / kode terlindungi IDR–USD / baris hasil pull) ·
``GET /default/`` + ``POST /<id>/set-default/`` (atomik, maksimal 1 default) · izin
(anonim 403 semua; operator hanya baca; tulis **ADMIN/OWNER**) · ledger
``SyncRecord`` ``master.currency``/``MASTER_PUSH`` ber-status **``SKIPPED``** (MES-only)
+ ``AuditLog``.

Keputusan STEP 0 (H5.2):
  * path **``/api/v1/settings/currencies/``** (bukan ``/master/*``) — konsisten H5-series
    (H5.3 Number Sequence juga model ``master.*`` di ``/settings/*``);
  * **MES-only** (``SKIPPED``): tidak ada konsumen MES yang mengirim mata uang ke Odoo,
    ``rate`` di-maintain Odoo, ``res.currency`` = konfigurasi akuntansi sensitif;
  * guard DELETE: ``is_default`` → 400; ``code ∈ {IDR, USD}`` → 400; ``odoo_id`` (baris
    pull I1) → 400. Baris tidak dihapus dari DB (soft delete).

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_currencies_crud.py -q
"""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from core.audit.models import AuditLog
from core.auth.models import Role, User
from integrations.erp_sync.models import SyncRecord, SyncResource, SyncStage, SyncStatus
from master.currency_services import MES_ONLY_REASON
from master.models import Currency

LIST_URL = "/api/v1/settings/currencies/"
DEFAULT_URL = f"{LIST_URL}default/"
ENVELOPE_KEYS = {"rows", "total_count", "has_more", "next_cursor"}
ROW_KEYS = {
    "id",
    "code",
    "name",
    "symbol",
    "rate",
    "is_default",
    "is_active",
    "odoo_id",
}


def detail_url(currency_id: int) -> str:
    """URL detail (GET/PUT/DELETE) satu mata uang."""
    return f"{LIST_URL}{currency_id}/"


def set_default_url(currency_id: int) -> str:
    """URL aksi jadikan-default satu mata uang."""
    return f"{LIST_URL}{currency_id}/set-default/"


class CurrencyTestCase(TestCase):
    """Basis bersama: user admin/operator + klien admin siap pakai."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="admin-cur",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.ADMIN),
        )
        cls.operator = User.objects.create_user(
            username="op-cur",
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

    def create(self, **body):
        """POST create mata uang dengan klien admin."""
        return self.api.post(LIST_URL, body, format="json")

    def currency(self, code: str) -> Currency:
        """Baris mata uang (case-insensitive)."""
        return Currency.objects.get(code__iexact=code)

    def sync_records(self, currency: Currency):
        """Ledger ``SyncRecord`` milik satu mata uang."""
        return SyncRecord.objects.filter(
            resource=SyncResource.MASTER_CURRENCY.value,
            resource_id=str(currency.pk),
            stage=SyncStage.MASTER_PUSH.value,
        )

    def audit_logs(self, currency: Currency, action: str | None = None):
        """AuditLog milik satu mata uang (opsional difilter action)."""
        queryset = AuditLog.objects.filter(
            resource=SyncResource.MASTER_CURRENCY.value,
            resource_id=str(currency.pk),
        )

        return queryset.filter(action=action) if action else queryset


class CurrencyListCreateTests(CurrencyTestCase):
    """``GET|POST /settings/currencies/`` — list, filter, create + validasi + ledger."""

    def test_list_filter_dan_envelope(self):
        body = self.api.get(LIST_URL).json()

        self.assertEqual(set(body), ENVELOPE_KEYS)
        self.assertEqual(body["total_count"], 0)
        self.assertEqual(body["rows"], [])

        self.create(code="GBP", name="Pound Sterling", symbol="£")
        self.create(code="JPY", name="Japanese Yen", symbol="¥")
        self.create(code="AUD", name="Australian Dollar")

        body = self.api.get(LIST_URL).json()

        self.assertEqual(body["total_count"], 3)
        self.assertEqual([row["code"] for row in body["rows"]], ["AUD", "GBP", "JPY"])
        self.assertEqual(set(body["rows"][0]), ROW_KEYS)

        cari = self.api.get(LIST_URL, {"search": "Pound"}).json()

        self.assertEqual([row["code"] for row in cari["rows"]], ["GBP"])
        simbol = self.api.get(LIST_URL, {"search": "¥"}).json()

        self.assertEqual([row["code"] for row in simbol["rows"]], ["JPY"])

        self.api.delete(detail_url(self.currency("GBP").pk))
        nonaktif = self.api.get(LIST_URL, {"active": "false"}).json()

        self.assertEqual([row["code"] for row in nonaktif["rows"]], ["GBP"])
        self.assertEqual(self.api.get(LIST_URL, {"active": "bukan-bool"}).status_code, 400)

    def test_create_currency_ok(self):
        response = self.create(code="gbp", name=" Pound Sterling ", symbol="£", rate="0.000052")

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(set(body), ROW_KEYS)
        self.assertEqual(body["code"], "GBP")  # auto-upper
        self.assertEqual(body["name"], "Pound Sterling")  # trim
        self.assertEqual(body["symbol"], "£")
        self.assertAlmostEqual(body["rate"], 0.000052)
        self.assertFalse(body["is_default"])
        self.assertTrue(body["is_active"])
        self.assertIsNone(body["odoo_id"])

        currency = self.currency("GBP")
        record = self.sync_records(currency).get()

        self.assertEqual(record.status, SyncStatus.SKIPPED)
        self.assertEqual(record.last_error, MES_ONLY_REASON)
        self.assertEqual(record.payload["code"], "GBP")
        self.assertTrue(record.payload["active"])

        logs = self.audit_logs(currency, "master.create")

        self.assertEqual(logs.count(), 1)
        self.assertTrue(logs.first().metadata["mes_only"])

        # tanpa symbol/rate → nilai default ("" / None)
        bawaan = self.create(code="AUD", name="Australian Dollar").json()

        self.assertEqual(bawaan["symbol"], "")
        self.assertIsNone(bawaan["rate"])

    def test_create_duplicate_code_400(self):
        self.assertEqual(self.create(code="GBP", name="Pound").status_code, 201)

        response = self.create(code="GBP", name="Pound lain")

        self.assertEqual(response.status_code, 400)
        self.assertIn("sudah dipakai", response.json()["detail"])
        # duplikat juga case-insensitive
        self.assertEqual(self.create(code="gbp", name="Lower").status_code, 400)
        self.assertEqual(Currency.objects.filter(code__iexact="GBP").count(), 1)

    def test_create_code_invalid_400(self):
        for code in ("", "   ", "GB", "GBPP", "GB1", "G-B", "12A"):
            with self.subTest(code=code):
                response = self.create(code=code, name="X")

                self.assertEqual(response.status_code, 400)
                self.assertIn("code", response.json()["detail"])

    def test_create_validasi_name_symbol_rate_400(self):
        self.assertEqual(self.create(code="GBP").status_code, 400)

        panjang = self.create(code="GBP", name="X" * 256)

        self.assertEqual(panjang.status_code, 400)
        self.assertIn("name", panjang.json()["detail"])

        simbol = self.create(code="GBP", name="Pound", symbol="123456789")

        self.assertEqual(simbol.status_code, 400)
        self.assertIn("symbol", simbol.json()["detail"])

        for rate in (-1, "abc", True, "1e999"):
            with self.subTest(rate=rate):
                response = self.create(code="GBP", name="Pound", rate=rate)

                self.assertEqual(response.status_code, 400)
                self.assertIn("rate", response.json()["detail"])

    def test_create_is_default_langsung_dan_tunggal(self):
        pertama = self.create(code="GBP", name="Pound", is_default=True)

        self.assertEqual(pertama.status_code, 201)
        self.assertTrue(pertama.json()["is_default"])

        kedua = self.create(code="JPY", name="Japanese Yen", is_default=True)

        self.assertTrue(kedua.json()["is_default"])
        self.assertFalse(self.currency("GBP").is_default)
        self.assertEqual(Currency.objects.filter(is_default=True).count(), 1)


class CurrencyUpdateTests(CurrencyTestCase):
    """``GET|PUT /settings/currencies/<id>/`` — detail, update + non-breaking mirror I1."""

    def test_get_detail_dan_404(self):
        created = self.create(code="GBP", name="Pound").json()

        body = self.api.get(detail_url(created["id"])).json()

        self.assertEqual(set(body), ROW_KEYS)
        self.assertEqual(body["code"], "GBP")
        self.assertEqual(self.api.get(detail_url(999999)).status_code, 404)
        self.assertEqual(
            self.api.put(detail_url(999999), {"name": "X"}, format="json").status_code, 404
        )

    def test_update_currency_ok(self):
        created = self.create(code="GBP", name="Pound").json()

        response = self.api.put(
            detail_url(created["id"]),
            {"name": "Pound Sterling", "symbol": "£", "rate": "0.00005", "active": False},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["name"], "Pound Sterling")
        self.assertEqual(body["symbol"], "£")
        self.assertFalse(body["is_active"])

        currency = self.currency("GBP")

        self.assertEqual(self.sync_records(currency).get().status, SyncStatus.SKIPPED)
        logs = self.audit_logs(currency, "master.update")

        self.assertEqual(logs.count(), 1)
        self.assertIn("name", logs.first().metadata["fields"])

        # PUT tanpa perubahan → 200 & tidak menambah audit/ledger
        sebelum = self.audit_logs(currency).count()
        kosong = self.api.put(detail_url(created["id"]), {}, format="json")

        self.assertEqual(kosong.status_code, 200)
        self.assertEqual(self.audit_logs(currency).count(), sebelum)

    def test_update_echo_kode_hasil_pull_tidak_400(self):
        """Baris mirror I1 (``code='ODOO-12'``) tetap bisa diubah name/symbol."""
        pull = Currency.objects.create(odoo_id=12, code="ODOO-12", name="Rupiah")

        response = self.api.put(
            detail_url(pull.pk),
            {"code": "ODOO-12", "name": "Rupiah (mirror)", "symbol": "Rp"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["code"], "ODOO-12")
        self.assertEqual(body["name"], "Rupiah (mirror)")
        self.assertEqual(body["symbol"], "Rp")
        self.assertEqual(body["odoo_id"], 12)

    def test_update_kode_invalid_dan_duplikat_400(self):
        gbp = self.create(code="GBP", name="Pound").json()
        self.create(code="JPY", name="Japanese Yen")

        self.assertEqual(
            self.api.put(detail_url(gbp["id"]), {"code": "GB"}, format="json").status_code, 400
        )

        duplikat = self.api.put(detail_url(gbp["id"]), {"code": "JPY"}, format="json")

        self.assertEqual(duplikat.status_code, 400)
        self.assertIn("sudah dipakai", duplikat.json()["detail"])
        self.assertEqual(self.currency("GBP").code, "GBP")


class CurrencyDeleteTests(CurrencyTestCase):
    """``DELETE /settings/currencies/<id>/`` — soft delete + 3 guard + ledger/audit."""

    def test_delete_ok_soft_delete(self):
        created = self.create(code="GBP", name="Pound").json()
        currency = self.currency("GBP")

        response = self.api.delete(detail_url(created["id"]))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["id"], created["id"])
        self.assertTrue(body["deleted"])
        self.assertFalse(body["is_active"])
        self.assertIsNotNone(body["sync_record_id"])

        currency.refresh_from_db()
        self.assertFalse(currency.is_active)
        # baris TIDAK dihapus dari DB (soft delete)
        self.assertTrue(Currency.objects.filter(pk=currency.pk).exists())

        record = self.sync_records(currency).get()

        self.assertEqual(record.status, SyncStatus.SKIPPED)
        logs = self.audit_logs(currency, "master.delete")

        self.assertEqual(logs.count(), 1)
        self.assertTrue(logs.first().metadata["soft_delete"])

    def test_delete_guard_default_400(self):
        created = self.create(code="GBP", name="Pound", is_default=True).json()

        response = self.api.delete(detail_url(created["id"]))

        self.assertEqual(response.status_code, 400)
        self.assertIn("default MES", response.json()["detail"])
        self.assertTrue(self.currency("GBP").is_active)

    def test_delete_guard_protected_iso_400(self):
        for code, nama in (("IDR", "Rupiah"), ("USD", "US Dollar")):
            with self.subTest(code=code):
                created = self.create(code=code, name=nama).json()
                response = self.api.delete(detail_url(created["id"]))

                self.assertEqual(response.status_code, 400)
                self.assertIn("protected ISO", response.json()["detail"])
                self.assertTrue(self.currency(code).is_active)

    def test_delete_guard_baris_pull_400(self):
        pull = Currency.objects.create(odoo_id=12, code="ODOO-12", name="Rupiah")

        response = self.api.delete(detail_url(pull.pk))

        self.assertEqual(response.status_code, 400)
        self.assertIn("hasil pull", response.json()["detail"])
        pull.refresh_from_db()
        self.assertTrue(pull.is_active)
        self.assertEqual(self.api.delete(detail_url(999999)).status_code, 404)


class CurrencyDefaultTests(CurrencyTestCase):
    """``GET /default/`` + ``POST /<id>/set-default/`` — default MES tunggal (atomik)."""

    def test_default_endpoint_fallback_dan_odoo_id(self):
        self.assertEqual(self.api.get(DEFAULT_URL).json(), {"currency": None})

        # fallback: kode IDR aktif (I1 memetakan res.currency.name → name; kode IDR bisa
        # dibuat lewat MES karena guard proteksi hanya berlaku di DELETE)
        self.create(code="IDR", name="Rupiah", symbol="Rp")

        body = self.api.get(DEFAULT_URL).json()

        self.assertEqual(body["currency"]["code"], "IDR")

        # penanda is_default menang atas fallback
        gbp = self.create(code="GBP", name="Pound").json()
        self.assertEqual(self.api.post(set_default_url(gbp["id"])).status_code, 200)

        self.assertEqual(self.api.get(DEFAULT_URL).json()["currency"]["code"], "GBP")

    def test_set_default_atomic_tunggal(self):
        gbp = self.create(code="GBP", name="Pound").json()
        jpy = self.create(code="JPY", name="Japanese Yen").json()

        pertama = self.api.post(set_default_url(gbp["id"]))

        self.assertEqual(pertama.status_code, 200)
        self.assertTrue(pertama.json()["is_default"])
        self.assertFalse(self.currency("JPY").is_default)

        kedua = self.api.post(set_default_url(jpy["id"]))

        self.assertTrue(kedua.json()["is_default"])
        self.assertFalse(self.currency("GBP").is_default)
        self.assertEqual(Currency.objects.filter(is_default=True).count(), 1)

        gbp_currency = self.currency("GBP")
        logs = self.audit_logs(gbp_currency, "master.update")

        self.assertTrue(any(log.metadata.get("is_default") for log in logs))

    def test_set_default_nonaktif_400_dan_404(self):
        created = self.create(code="GBP", name="Pound", active=False).json()

        self.assertFalse(created["is_active"])
        response = self.api.post(set_default_url(created["id"]))

        self.assertEqual(response.status_code, 400)
        self.assertIn("nonaktif", response.json()["detail"])
        self.assertEqual(self.api.post(set_default_url(999999)).status_code, 404)


class CurrencyAuthAndNonBreakingTests(CurrencyTestCase):
    """Izin (anonim 403 semua · operator baca saja) + non-breaking H5.3 & mirror I1."""

    def test_auth_anonim_403_semua_endpoint(self):
        created = self.create(code="GBP", name="Pound").json()
        anonim = self.as_user(None)

        self.assertEqual(anonim.get(LIST_URL).status_code, 403)
        self.assertEqual(anonim.get(DEFAULT_URL).status_code, 403)
        self.assertEqual(anonim.get(detail_url(created["id"])).status_code, 403)
        self.assertEqual(
            anonim.post(LIST_URL, {"code": "AAA", "name": "A"}, format="json").status_code, 403
        )
        self.assertEqual(
            anonim.put(detail_url(created["id"]), {"name": "X"}, format="json").status_code, 403
        )
        self.assertEqual(anonim.delete(detail_url(created["id"])).status_code, 403)
        self.assertEqual(anonim.post(set_default_url(created["id"])).status_code, 403)

    def test_operator_hanya_baca_403_saat_tulis(self):
        created = self.create(code="GBP", name="Pound").json()
        operator = self.as_user(self.operator)

        # baca → boleh
        self.assertEqual(operator.get(LIST_URL).status_code, 200)
        self.assertEqual(operator.get(DEFAULT_URL).status_code, 200)
        self.assertEqual(operator.get(detail_url(created["id"])).status_code, 200)

        # tulis → 403 (ADMIN/OWNER)
        self.assertEqual(
            operator.post(LIST_URL, {"code": "AAA", "name": "A"}, format="json").status_code, 403
        )
        self.assertEqual(
            operator.put(detail_url(created["id"]), {"name": "X"}, format="json").status_code, 403
        )
        self.assertEqual(operator.delete(detail_url(created["id"])).status_code, 403)
        self.assertEqual(operator.post(set_default_url(created["id"])).status_code, 403)

        self.assertTrue(self.currency("GBP").is_active)
        self.assertFalse(Currency.objects.filter(code="AAA").exists())

    def test_non_breaking_h5_3_sequences_dan_mirror_pull(self):
        # H5.3 (Sprint C) tidak boleh rusak: list sequence tetap 9 seed
        sequences = self.api.get("/api/v1/settings/sequences/")

        self.assertEqual(sequences.status_code, 200)
        self.assertEqual(sequences.json()["total_count"], 9)

        # mirror pull I1 tetap utuh: baris ber-odoo_id tampil di list & bisa diubah
        pull = Currency.objects.create(odoo_id=12, code="ODOO-12", name="Rupiah")
        rows = self.api.get(LIST_URL).json()["rows"]

        self.assertEqual([row["code"] for row in rows], ["ODOO-12"])
        self.assertEqual(rows[0]["odoo_id"], 12)

        updated = self.api.put(
            detail_url(pull.pk), {"name": "Rupiah Odoo"}, format="json"
        )

        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["name"], "Rupiah Odoo")
        self.assertEqual(updated.json()["odoo_id"], 12)

