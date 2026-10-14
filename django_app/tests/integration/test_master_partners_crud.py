"""Test CRUD master Partner — ``/api/v1/master/partners/`` (H1.6).

Cakupan: list (pagination/filter customer-vendor/search), detail (dengan
``orders_count``), create (customer/vendor/keduanya), update, **soft delete**, izin
(anon 403, role non-admin 403), validasi 400 (name wajib, kode duplikat, **kedua flag
peran False**, NPWP bukan 15/16 digit, email tidak valid, panjang teks, flag bukan
bool), serta kewajiban H1.6: ``SyncRecord`` (``master.partner``/``MASTER_PUSH``) +
``AuditLog`` setiap POST/PUT/DELETE dan enqueue task ``erp_sync.push_master_partner``.

Catatan khusus H1.6 (probe ``fields_get`` Odoo 17 ``res.partner``):
  * tidak ada field wajib selain ``name`` ⇒ push **create** boleh;
  * ``customer_rank``/``supplier_rank`` di Odoo = HITUNGAN transaksi ⇒ dikirim
    **hanya saat create** (1/0 penanda peran), tidak saat update;
  * ``is_company`` field mandiri ⇒ ``company_type`` di-derive (``company``/``person``);
  * ``npwp`` → ``vat`` (dinormalisasi digit), ``address`` → ``street``;
  * teks kosong tidak dikirim (tidak menghapus data Odoo karena MES belum diisi).

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_master_partners_crud.py -q
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.audit.models import AuditLog
from core.auth.models import Role, User
from integrations.erp_sync.models import SyncRecord, SyncResource, SyncStage, SyncStatus
from integrations.erp_sync.tasks_master_push import (
    MasterPushError,
    _partner_odoo_values,
    partner_payload,
    push_master_partner,
)
from master.models import Partner

PARTNERS_URL = "/api/v1/master/partners/"
ENVELOPE_KEYS = {"rows", "total_count", "has_more", "next_cursor"}
ROW_KEYS = {
    "id",
    "code",
    "name",
    "email",
    "phone",
    "city",
    "address",
    "npwp",
    "is_customer",
    "is_vendor",
    "is_company",
    "customer_rank",
    "supplier_rank",
    "active",
    "odoo_id",
    "created_at",
    "updated_at",
}
DETAIL_KEYS = ROW_KEYS | {"orders_count"}
#: Path patch enqueue task (service menulis SyncRecord lalu enqueue).
ENQUEUE = "master.partner_services.push_master_partner.apply_async"

#: NPWP valid 15 digit (format lama) & 16 digit (format NIK-NPWP).
NPWP_15 = "01.234.567.8-901.000"
NPWP_16 = "01.234.567.8-901.000.1"


def detail_url(pk: int) -> str:
    """URL detail partner."""
    return f"{PARTNERS_URL}{pk}/"


class MasterPartnersCrudTests(TestCase):
    """GET/POST/PUT/DELETE + peran customer/vendor + NPWP + idempotensi + push."""

    @classmethod
    def setUpTestData(cls):
        """4 user: admin, purchasing, operator, qc (uji 403 untuk 3 role terakhir)."""
        cls.admin = User.objects.create_user(
            username="admin-partner",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.ADMIN),
        )
        cls.purchasing = User.objects.create_user(
            username="beli-partner",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.PURCHASING),
        )
        cls.operator = User.objects.create_user(
            username="op-partner",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.OPERATOR),
        )
        cls.qc = User.objects.create_user(
            username="qc-partner",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.QC),
        )

    def setUp(self):
        """Klien admin (utama) + klien role lain (uji 403)."""
        self.api = APIClient()
        self.api.force_authenticate(self.admin)

        self.readonly_apis = {}
        for name, user in (
            ("purchasing", self.purchasing),
            ("operator", self.operator),
            ("qc", self.qc),
        ):
            client = APIClient()
            client.force_authenticate(user)
            self.readonly_apis[name] = client

    # ------------------------------------------------------------------ helper
    def partner_body(self, **overrides) -> dict:
        """Body create/update partner valid (default: customer perusahaan)."""
        body = {
            "name": "PT Buyer Export",
            "is_customer": True,
            "is_vendor": False,
            "is_company": True,
            "email": "buyer@example.com",
            "phone": "+62 812-3456-7890",
            "city": "Bandung",
            "address": "Jl. Merdeka 10\nBlok C",
            "npwp": NPWP_15,
            "active": True,
        }
        body.update(overrides)

        return body

    def post_partner(self, body: dict, client=None):
        """POST partner dengan enqueue task di-patch → ``(response, mock)``."""
        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-partner-1")) as enqueue:
            response = (client or self.api).post(PARTNERS_URL, body, format="json")

        return response, enqueue

    def put_partner(self, pk: int, body: dict, client=None):
        """PUT partner dengan enqueue task di-patch → ``(response, mock)``."""
        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-partner-2")) as enqueue:
            response = (client or self.api).put(detail_url(pk), body, format="json")

        return response, enqueue

    def delete_partner(self, pk: int, client=None):
        """DELETE partner dengan enqueue task di-patch → ``(response, mock)``."""
        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-partner-3")) as enqueue:
            response = (client or self.api).delete(detail_url(pk))

        return response, enqueue

    def make_partner(self, code: str = "V-001", **overrides) -> Partner:
        """Partner tersimpan langsung (tanpa lewat API) untuk test non-create."""
        return Partner.objects.create(
            code=code,
            name=overrides.pop("name", "PT Supplier Kain"),
            **overrides,
        )

    # ------------------------------------------------------------ POST / create
    def test_create_partner_customer_ok(self):
        """POST customer perusahaan → 201 + normalisasi NPWP + info sync."""
        response, enqueue = self.post_partner(self.partner_body())

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertTrue(ROW_KEYS <= set(body))
        self.assertEqual(body["name"], "PT Buyer Export")
        self.assertEqual(body["code"], "PTR-PT-BUYER-EXPORT")  # auto-generate
        self.assertEqual(body["npwp"], "012345678901000")  # digit-only
        self.assertIs(body["is_customer"], True)
        self.assertIs(body["is_vendor"], False)
        self.assertIs(body["is_company"], True)
        self.assertEqual(body["email"], "buyer@example.com")
        self.assertEqual(body["city"], "Bandung")
        self.assertEqual(body["customer_rank"], 0)  # belum ada tarikan Odoo
        self.assertIsNone(body["odoo_id"])
        self.assertEqual(body["orders_count"], 0)  # belum dipakai order

        partner = Partner.objects.get(pk=body["id"])
        self.assertEqual(partner.npwp, "012345678901000")
        self.assertEqual(partner.address, "Jl. Merdeka 10\nBlok C")
        enqueue.assert_called_once()
        self.assertEqual(enqueue.call_args.kwargs["args"], [partner.pk, body["sync_record_id"]])

    def test_create_partner_vendor_only_ok(self):
        """POST vendor saja (is_customer=False) → 201 (boleh salah satu peran)."""
        response, _ = self.post_partner(
            self.partner_body(name="Toko jahit Jaya", is_customer=False, is_vendor=True)
        )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertIs(body["is_customer"], False)
        self.assertIs(body["is_vendor"], True)

    def test_create_partner_person_ok(self):
        """``is_company=False`` → tersimpan sebagai perorangan (bukan badan usaha)."""
        response, _ = self.post_partner(
            self.partner_body(name="Budi Tailor", is_company=False, npwp="")
        )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertIs(body["is_company"], False)
        self.assertEqual(body["npwp"], "")

    def test_create_partner_auto_code_suffix(self):
        """Kode auto unik: ``PTR-<slug nama>`` lalu ``-2`` bila sudah terpakai."""
        self.make_partner(code="PTR-PT-BUYER-EXPORT")

        response, _ = self.post_partner(self.partner_body())

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["code"], "PTR-PT-BUYER-EXPORT-2")

    def test_create_partner_explicit_code_duplicate_400(self):
        """Kode eksplisit duplikat → 400 tanpa baris baru."""
        self.make_partner(code="C-001")

        response, enqueue = self.post_partner(self.partner_body(code="C-001"))

        self.assertEqual(response.status_code, 400)
        self.assertIn("sudah dipakai", response.json()["detail"])
        self.assertEqual(Partner.objects.count(), 1)
        enqueue.assert_not_called()

    def test_create_partner_invalid_payload_400(self):
        """Validasi: name wajib, peran tidak boleh dua-duanya False, NPWP/email/flag."""
        cases = (
            ({"name": "   "}, "name' wajib"),
            ({"name": None}, "name' wajib"),
            ({"is_customer": False, "is_vendor": False}, "minimal salah satu"),
            ({"npwp": "12345"}, "15 atau 16 digit"),
            ({"npwp": "1234567890123456789"}, "15 atau 16 digit"),
            ({"email": "bukan-email"}, "tidak valid"),
            ({"is_customer": "kadang"}, "is_customer"),
            ({"is_vendor": "kadang"}, "is_vendor"),
            ({"is_company": "kadang"}, "is_company"),
            ({"active": "kadang"}, "active"),
            ({"city": "X" * 65}, "maksimal"),
            ({"name": "Y" * 256}, "maksimal"),
        )

        for overrides, needle in cases:
            with self.subTest(overrides=overrides):
                response, _ = self.post_partner(self.partner_body(**overrides))
                self.assertEqual(response.status_code, 400)
                self.assertIn(needle, response.json()["detail"])

        self.assertEqual(Partner.objects.count(), 0)

    def test_create_partner_npwp_16_digit_ok(self):
        """NPWP 16 digit (format NIK-NPWP) diterima & dinormalisasi."""
        response, _ = self.post_partner(self.partner_body(npwp=NPWP_16))

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["npwp"], "0123456789010001")

    # ------------------------------------------------------------ PUT / detail
    def test_update_partner_ok(self):
        """PUT mengubah hanya field yang dikirim (200) + audit ``master.update``."""
        partner = self.make_partner(is_customer=True, is_vendor=False)

        response, enqueue = self.put_partner(
            partner.pk,
            {"name": "PT Supplier Kain (baru)", "is_vendor": True, "city": "Solo"},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["name"], "PT Supplier Kain (baru)")
        self.assertIs(body["is_vendor"], True)
        self.assertIs(body["is_customer"], True)  # tidak dikirim -> tetap
        self.assertEqual(body["city"], "Solo")
        self.assertEqual(body["code"], "V-001")  # tidak dikirim -> tetap

        partner.refresh_from_db()
        self.assertTrue(partner.is_vendor)
        self.assertEqual(partner.city, "Solo")

        enqueue.assert_called_once()
        self.assertTrue(
            AuditLog.objects.filter(
                action="master.update",
                resource="master.partner",
                resource_id=str(partner.pk),
            ).exists()
        )

    def test_update_partner_both_flags_false_400(self):
        """Mematikan kedua peran sekaligus → 400 (partner tanpa peran)."""
        partner = self.make_partner(is_customer=True, is_vendor=True)

        response, enqueue = self.put_partner(
            partner.pk, {"is_customer": False, "is_vendor": False}
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("minimal salah satu", response.json()["detail"])
        enqueue.assert_not_called()

        partner.refresh_from_db()
        self.assertTrue(partner.is_customer)  # tidak berubah

    def test_update_partner_npwp_invalid_400(self):
        """NPWP ngawur pada update → 400, nilai lama tidak berubah."""
        partner = self.make_partner(npwp="012345678901000")

        response, _ = self.put_partner(partner.pk, {"npwp": "123"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("15 atau 16 digit", response.json()["detail"])
        partner.refresh_from_db()
        self.assertEqual(partner.npwp, "012345678901000")

    def test_update_partner_empty_body_no_syncrecord(self):
        """PUT tanpa satu pun field → 200 tanpa ``SyncRecord``/audit/push."""
        partner = self.make_partner()

        response, enqueue = self.put_partner(partner.pk, {})

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["sync_record_id"])
        self.assertIsNone(response.json()["task_id"])
        self.assertFalse(response.json()["queued"])
        enqueue.assert_not_called()
        self.assertFalse(
            SyncRecord.objects.filter(resource=SyncResource.MASTER_PARTNER.value).exists()
        )

    def test_detail_and_missing_partner_404(self):
        """GET detail → 200 (+ ``orders_count``); id tak dikenal → 404 GET/PUT/DELETE."""
        partner = self.make_partner(email="kain@example.com", city="Solo")

        detail = self.api.get(detail_url(partner.pk))
        self.assertEqual(detail.status_code, 200)
        body = detail.json()
        self.assertTrue(DETAIL_KEYS <= set(body))
        self.assertEqual(body["id"], partner.pk)
        self.assertEqual(body["email"], "kain@example.com")
        self.assertEqual(body["orders_count"], 0)
        self.assertNotIn("orders_count", self.api.get(PARTNERS_URL).json()["rows"][0])

        self.assertEqual(self.api.get(detail_url(999999)).status_code, 404)
        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-none")):
            self.assertEqual(
                self.api.put(detail_url(999999), {"name": "X"}, format="json").status_code,
                404,
            )
            self.assertEqual(self.api.delete(detail_url(999999)).status_code, 404)

    def test_detail_orders_count(self):
        """``orders_count`` menghitung order yang memakai partner (relasi ``orders``)."""
        from apps_industry.garment.models import Order

        partner = self.make_partner()
        Order.objects.create(code="SO-1", customer=partner)
        Order.objects.create(code="SO-2", customer=partner)

        self.assertEqual(self.api.get(detail_url(partner.pk)).json()["orders_count"], 2)

    # ---------------------------------------------------------- DELETE (soft)
    def test_delete_partner_soft_delete(self):
        """DELETE → 200 soft delete: ``active=False``, baris MASIH ada di DB."""
        partner = self.make_partner(email="kain@example.com")

        response, enqueue = self.delete_partner(partner.pk)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["id"], partner.pk)
        self.assertTrue(body["deleted"])
        self.assertFalse(body["active"])

        partner.refresh_from_db()
        self.assertFalse(partner.is_active)
        self.assertTrue(Partner.objects.filter(pk=partner.pk).exists())
        self.assertFalse(self.api.get(detail_url(partner.pk)).json()["active"])
        enqueue.assert_called_once()

    # ------------------------------------------------------------------- GET list
    def test_list_partners_pagination_and_envelope(self):
        """Envelope ListPage + pagination + urut ``code``."""
        for index in range(3):
            self.make_partner(code=f"P-{index}", name=f"Partner {index}")

        first = self.api.get(PARTNERS_URL, {"limit": 2}).json()
        self.assertEqual(set(first), ENVELOPE_KEYS)
        self.assertEqual(first["total_count"], 3)
        self.assertEqual(len(first["rows"]), 2)
        self.assertTrue(first["has_more"])
        self.assertEqual(first["next_cursor"], 2)
        self.assertEqual([row["code"] for row in first["rows"]], ["P-0", "P-1"])
        self.assertTrue(ROW_KEYS <= set(first["rows"][0]))

        second = self.api.get(PARTNERS_URL, {"limit": 2, "cursor": 2}).json()
        self.assertEqual(len(second["rows"]), 1)
        self.assertFalse(second["has_more"])
        self.assertIsNone(second["next_cursor"])

    def test_list_partners_filters(self):
        """Filter ``search`` (code/name/email/city), ``is_customer``, ``is_vendor``, ``active``."""
        self.make_partner(
            code="C-001", name="Toko Retail", email="retail@example.com",
            city="Bandung", is_customer=True, is_vendor=False,
        )
        self.make_partner(
            code="V-001", name="PT Supplier Kain", email="kain@example.com",
            city="Solo", is_customer=False, is_vendor=True,
        )
        self.make_partner(
            code="B-001", name="PT Dua Peran", is_customer=True, is_vendor=True,
        )
        self.make_partner(code="X-001", name="Partner Nonaktif", is_active=False)

        by_name = self.api.get(PARTNERS_URL, {"search": "supplier"}).json()
        self.assertEqual([row["code"] for row in by_name["rows"]], ["V-001"])

        by_email = self.api.get(PARTNERS_URL, {"search": "retail@"}).json()
        self.assertEqual([row["code"] for row in by_email["rows"]], ["C-001"])

        by_city = self.api.get(PARTNERS_URL, {"search": "solo"}).json()
        self.assertEqual([row["code"] for row in by_city["rows"]], ["V-001"])

        customers = self.api.get(PARTNERS_URL, {"is_customer": "true"}).json()
        # X-001 nonaktif ikut cocok: filter peran TIDAK memfilter `active`.
        self.assertEqual([row["code"] for row in customers["rows"]], ["B-001", "C-001", "X-001"])

        active_customers = self.api.get(
            PARTNERS_URL, {"is_customer": "true", "active": "true"}
        ).json()
        self.assertEqual([row["code"] for row in active_customers["rows"]], ["B-001", "C-001"])

        vendors = self.api.get(PARTNERS_URL, {"is_vendor": "true"}).json()
        self.assertEqual([row["code"] for row in vendors["rows"]], ["B-001", "V-001"])

        inactive = self.api.get(PARTNERS_URL, {"active": "false"}).json()
        self.assertEqual([row["code"] for row in inactive["rows"]], ["X-001"])

    def test_list_partners_invalid_params_400(self):
        """Parameter list ngawur → 400 (bukan 500)."""
        cases = (
            {"limit": "nol"},
            {"limit": "0"},
            {"limit": "201"},
            {"cursor": "-1"},
            {"is_customer": "kadang"},
            {"is_vendor": "kadang"},
            {"active": "kadang"},
        )

        for params in cases:
            with self.subTest(params=params):
                response = self.api.get(PARTNERS_URL, params)
                self.assertEqual(response.status_code, 400)
                self.assertIn("detail", response.json())

    # -------------------------------------------------------------------- izin
    def test_anonymous_forbidden(self):
        """Tanpa kredensial → 403 untuk semua metode (GET/POST/PUT/DELETE)."""
        partner = self.make_partner()
        client = APIClient()

        self.assertEqual(client.get(PARTNERS_URL).status_code, 403)
        self.assertEqual(client.post(PARTNERS_URL, self.partner_body(), format="json").status_code, 403)
        self.assertEqual(client.get(detail_url(partner.pk)).status_code, 403)
        self.assertEqual(
            client.put(detail_url(partner.pk), {"name": "X"}, format="json").status_code, 403
        )
        self.assertEqual(client.delete(detail_url(partner.pk)).status_code, 403)

    def test_non_admin_roles_read_only(self):
        """Role non-ADMIN/OWNER: GET 200, tapi POST/PUT/DELETE 403 (tanpa efek)."""
        partner = self.make_partner()

        for name, client in self.readonly_apis.items():
            with self.subTest(role=name):
                self.assertEqual(client.get(PARTNERS_URL).status_code, 200)
                self.assertEqual(
                    client.post(PARTNERS_URL, self.partner_body(), format="json").status_code, 403
                )
                self.assertEqual(
                    client.put(detail_url(partner.pk), {"name": "X"}, format="json").status_code,
                    403,
                )
                self.assertEqual(client.delete(detail_url(partner.pk)).status_code, 403)

        self.assertEqual(Partner.objects.count(), 1)
        partner.refresh_from_db()
        self.assertEqual(partner.name, "PT Supplier Kain")
        self.assertTrue(partner.is_active)

    # --------------------------------------------- idempotensi & audit (H1.6)
    def test_syncrecord_written_on_create(self):
        """POST → ``SyncRecord`` PENDING (``master.partner``/``MASTER_PUSH``)."""
        response, _ = self.post_partner(self.partner_body())
        partner_id = response.json()["id"]

        record = SyncRecord.objects.get(
            resource=SyncResource.MASTER_PARTNER.value,
            resource_id=str(partner_id),
            stage=SyncStage.MASTER_PUSH.value,
        )
        self.assertEqual(record.status, SyncStatus.PENDING)
        self.assertEqual(record.payload["code"], "PTR-PT-BUYER-EXPORT")
        self.assertIs(record.payload["is_customer"], True)
        self.assertIs(record.payload["is_vendor"], False)
        self.assertEqual(record.payload["npwp"], "012345678901000")
        self.assertIsNone(record.erp_id)

    def test_auditlog_written_on_create(self):
        """POST → ``AuditLog`` ``master.create`` resource ``master.partner``."""
        response, _ = self.post_partner(self.partner_body())
        partner_id = response.json()["id"]

        log = AuditLog.objects.get(action="master.create", resource_id=str(partner_id))
        self.assertEqual(log.resource, "master.partner")
        self.assertEqual(log.result, AuditLog.Result.OK)
        self.assertEqual(log.user_id, self.admin.pk)
        self.assertEqual(log.payload["name"], "PT Buyer Export")

    def test_update_and_delete_reuse_syncrecord_and_write_audit(self):
        """PUT lalu DELETE memakai SATU ``SyncRecord`` + audit keduanya."""
        partner = self.make_partner()

        self.put_partner(partner.pk, {"city": "Solo"})
        response, _ = self.delete_partner(partner.pk)

        records = SyncRecord.objects.filter(
            resource=SyncResource.MASTER_PARTNER.value, resource_id=str(partner.pk)
        )
        self.assertEqual(records.count(), 1)

        record = records.get()
        self.assertEqual(record.stage, SyncStage.MASTER_PUSH.value)
        self.assertEqual(record.status, SyncStatus.PENDING)
        self.assertIs(record.payload["active"], False)  # payload terbaru = soft delete
        self.assertEqual(record.payload["city"], "Solo")
        self.assertEqual(record.pk, response.json()["sync_record_id"])

        actions = set(
            AuditLog.objects.filter(resource_id=str(partner.pk)).values_list("action", flat=True)
        )
        self.assertEqual(actions, {"master.update", "master.delete"})

    # --------------------------------------------------------------- push task
    @override_settings(ERP_ADAPTER="null")
    def test_push_task_enqueued_and_null_mode_marks_sent(self):
        """Task ``erp_sync.push_master_partner``: no-op mode null → SENT + idempotent."""
        response, enqueue = self.post_partner(self.partner_body())
        body = response.json()
        enqueue.assert_called_once()

        result = push_master_partner.apply(args=[body["id"], body["sync_record_id"]]).get()

        self.assertEqual(result["status"], "sent")
        self.assertTrue(str(result["erp_id"]).startswith("NULL-"))
        self.assertEqual(result["resource"], SyncResource.MASTER_PARTNER.value)

        record = SyncRecord.objects.get(pk=body["sync_record_id"])
        self.assertEqual(record.status, SyncStatus.SENT)
        self.assertIsNotNone(record.sent_at)
        self.assertTrue(
            AuditLog.objects.filter(
                action="erp_sync.push_master_partner", resource_id=str(body["id"])
            ).exists()
        )

        again = push_master_partner.apply(args=[body["id"], body["sync_record_id"]]).get()
        self.assertEqual(again["status"], "duplicate-ignored")

    def test_partner_push_values_mapping(self):
        """Pemetaan payload → ``res.partner``: rank hanya create, npwp→vat, address→street."""
        partner = Partner.objects.create(
            code="V-001",
            name="PT Supplier Kain",
            is_vendor=True,
            is_customer=False,
            is_company=True,
            email="kain@example.com",
            phone="+62 812",
            city="Solo",
            address="Jl. Kain 1\nBlok B",
            npwp="012345678901000",
        )

        values = _partner_odoo_values(partner, partner_payload(partner))
        self.assertEqual(
            values,
            {
                "name": "PT Supplier Kain",
                "is_company": True,
                "company_type": "company",
                "active": True,
                "ref": "V-001",
                "email": "kain@example.com",
                "phone": "+62 812",
                "street": "Jl. Kain 1\nBlok B",
                "city": "Solo",
                "vat": "012345678901000",
                "customer_rank": 0,  # create -> penanda peran dikirim
                "supplier_rank": 1,
            },
        )

        # Update (punya odoo_id) → rank TIDAK dikirim (hitungan Odoo tidak diturunkan).
        partner.odoo_id = 45
        partner.save(update_fields=("odoo_id",))
        updated = _partner_odoo_values(partner, partner_payload(partner))
        self.assertNotIn("customer_rank", updated)
        self.assertNotIn("supplier_rank", updated)

        # Perorangan tanpa NPWP & teks kosong → field teks tidak dikirim.
        person = Partner.objects.create(code="P-002", name="Budi Tailor", is_company=False)
        person_values = _partner_odoo_values(person, partner_payload(person))
        self.assertEqual(person_values["company_type"], "person")
        self.assertIs(person_values["is_company"], False)
        self.assertNotIn("vat", person_values)
        self.assertNotIn("email", person_values)
        self.assertNotIn("phone", person_values)
        self.assertNotIn("street", person_values)
        self.assertNotIn("city", person_values)

        # Nama kosong (mis. hasil tarikan janggal) → MasterPushError, bukan kirim sampah.
        person.name = ""
        person.save(update_fields=("name",))
        with self.assertRaises(MasterPushError):
            _partner_odoo_values(person, partner_payload(person))




