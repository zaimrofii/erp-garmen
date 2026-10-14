"""Test CRUD master Tax — ``/api/v1/master/taxes/`` (H3.6).

Cakupan: list (pagination/filter/search), detail, create, update, **soft delete**
(``active=False`` — baris tetap di DB supaya relasi ``tax_ids`` H2.1/H2.2 utuh),
izin (anon **403**, role bukan ADMIN/OWNER **403**, admin boleh), validasi **400**
(name/kode/amount/amount_type/type_tax_use), pajak default MES
(``set-default`` atomik + ``default`` dengan fallback PPN 11%), serta kewajiban
H3.6: ``SyncRecord`` (``master.tax``/``MASTER_PUSH``) + ``AuditLog``
(``master.create``/``update``/``delete``) setiap POST/PUT/DELETE dan enqueue task
``erp_sync.push_master_tax``.

Berkas ini juga mengunci **non-breaking** konsumen lama: ``OrderLine.tax_ids``
(H2.1) & ``PurchaseOrderLine.tax_ids`` (H2.2) tetap M2M ``master.Tax`` yang sama.

Catatan:
  * push Odoo di-enqueue asinkron → ``apply_async`` di-patch (pola
    ``test_master_uoms_crud.py``) supaya test tidak menyentuh broker/worker;
  * ``tax_group_id`` **tidak** boleh ada di payload push — probe STEP 0 + sumber
    Odoo 17 membuktikan field itu ``compute``/``readonly=False`` (Odoo mengisinya);
  * ``is_default`` **tidak** pernah ditarik dari Odoo (keputusan MES).

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_master_taxes_crud.py -q
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.audit.models import AuditLog
from core.auth.models import Role, User
from apps_industry.garment.models import OrderLine, PurchaseOrderLine
from integrations.erp_sync.idempotency import SyncIdempotency
from integrations.erp_sync.models import SyncRecord, SyncResource, SyncStage, SyncStatus
from integrations.erp_sync.tasks_master import _tax_defaults, sync_master_taxes
from integrations.erp_sync.tasks_master_push import (
    ODOO_TAX_MODEL,
    _push_tax_to_odoo,
    _tax_odoo_values,
    push_master_tax,
    tax_payload,
)
from master.models import Tax

TAXES_URL = "/api/v1/master/taxes/"
DEFAULT_URL = f"{TAXES_URL}default/"
ENVELOPE_KEYS = {"rows", "total_count", "has_more", "next_cursor"}
ROW_KEYS = {
    "id",
    "code",
    "name",
    "amount",
    "amount_type",
    "type_tax_use",
    "price_include",
    "is_default",
    "active",
    "odoo_id",
}
#: Path patch enqueue task (service menulis SyncRecord lalu enqueue).
ENQUEUE = "master.tax_services.push_master_tax.apply_async"
#: Path patch klien Odoo di modul task (jalur create/update nyata).
CREATE_CLIENT = "integrations.erp_sync.tasks_master_push.get_odoo_rpc_client"
#: Field yang HARUS tetap tidak dikirim (dihitung Odoo sendiri).
FORBIDDEN_FIELDS = ("tax_group_id",)

VALID_BODY = {
    "code": "PPN12-SALE",
    "name": "PPN 12%",
    "amount": 12,
    "amount_type": "percent",
    "type_tax_use": "sale",
    "price_include": False,
    "active": True,
}


def detail_url(pk: int) -> str:
    """URL detail pajak."""
    return f"{TAXES_URL}{pk}/"


def set_default_url(pk: int) -> str:
    """URL aksi set-default pajak."""
    return f"{TAXES_URL}{pk}/set-default/"


class FakeTransport:
    """Transport RPC palsu: mencatat ``create``/``write`` tanpa jaringan."""

    def __init__(self, created_id: int = 555) -> None:
        """Simpan id palsu hasil create + daftar panggilan."""
        self.created_id = created_id
        self.created: list[tuple[str, dict]] = []
        self.written: list[tuple[str, list[int], dict]] = []

    def create(self, model: str, values: dict) -> int:
        """Catat pemanggilan create & kembalikan id palsu."""
        self.created.append((model, dict(values)))

        return self.created_id

    def write(self, model: str, ids: list[int], values: dict) -> bool:
        """Catat pemanggilan write & kembalikan True (sukses)."""
        self.written.append((model, list(ids), dict(values)))

        return True


class FakeOdooClient:
    """Klien Odoo palsu (punya ``.transport`` + ``.close()`` seperti klien asli)."""

    def __init__(self, created_id: int = 555) -> None:
        """Bangun transport palsu + penanda klien ditutup."""
        self.transport = FakeTransport(created_id)
        self.closed = False

    @property
    def created(self) -> list[tuple[str, dict]]:
        """Daftar pemanggilan ``create`` (model, values)."""
        return self.transport.created

    @property
    def written(self) -> list[tuple[str, list[int], dict]]:
        """Daftar pemanggilan ``write`` (model, ids, values)."""
        return self.transport.written

    def close(self) -> None:
        """Tandai klien ditutup (task wajib menutup klien di ``finally``)."""
        self.closed = True



class MasterTaxesCrudTests(TestCase):
    """GET/POST/PUT/DELETE + pajak default + idempotensi (SyncRecord) + audit + izin."""

    @classmethod
    def setUpTestData(cls):
        """3 user: admin (ADMIN), purchasing (PURCHASING), operator (OPERATOR)."""
        cls.admin = User.objects.create_user(
            username="admin-tax",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.ADMIN),
        )
        cls.purchasing = User.objects.create_user(
            username="beli-tax",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.PURCHASING),
        )
        cls.operator = User.objects.create_user(
            username="op-tax",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.OPERATOR),
        )

    def setUp(self):
        """Klien admin (utama) + klien purchasing/operator (uji 403).

        Baris hasil migrasi seed ``master.0019`` (PPN 11% sale/purchase + PPN 0%)
        **dihapus** supaya assertion jumlah/kode tidak bergantung pada data seed.
        """
        Tax.objects.all().delete()

        self.api = APIClient()
        self.api.force_authenticate(self.admin)
        self.purchasing_api = APIClient()
        self.purchasing_api.force_authenticate(self.purchasing)
        self.operator_api = APIClient()
        self.operator_api.force_authenticate(self.operator)

    # ------------------------------------------------------------------ helper
    def post_tax(self, body: dict, client=None):
        """POST pajak dengan enqueue task di-patch → ``(response, mock)``."""
        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-tax-1")) as enqueue:
            response = (client or self.api).post(TAXES_URL, body, format="json")

        return response, enqueue

    def put_tax(self, pk: int, body: dict, client=None):
        """PUT pajak dengan enqueue task di-patch → ``(response, mock)``."""
        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-tax-2")) as enqueue:
            response = (client or self.api).put(detail_url(pk), body, format="json")

        return response, enqueue

    def delete_tax(self, pk: int, client=None):
        """DELETE pajak dengan enqueue task di-patch → ``(response, mock)``."""
        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-tax-3")) as enqueue:
            response = (client or self.api).delete(detail_url(pk))

        return response, enqueue

    # -------------------------------------------------------------------- GET
    def test_list_taxes_pagination(self):
        """ListPage: ``limit``/``cursor`` offset-based + ``has_more``/``next_cursor``."""
        for index in range(3):
            Tax.objects.create(
                code=f"PAJAK-{index:03d}",
                name=f"Pajak {index}",
                amount=Decimal("11.00"),
            )

        response = self.api.get(TAXES_URL, {"limit": 2})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), ENVELOPE_KEYS)
        self.assertEqual(body["total_count"], 3)
        self.assertTrue(body["has_more"])
        self.assertEqual(body["next_cursor"], 2)
        self.assertEqual(len(body["rows"]), 2)
        self.assertEqual(set(body["rows"][0]), ROW_KEYS)
        self.assertEqual(body["rows"][0]["code"], "PAJAK-000")
        self.assertEqual(body["rows"][0]["amount"], 11.0)
        self.assertEqual(body["rows"][0]["amount_type"], "percent")
        self.assertEqual(body["rows"][0]["type_tax_use"], "sale")
        self.assertFalse(body["rows"][0]["price_include"])
        self.assertFalse(body["rows"][0]["is_default"])
        self.assertIsNone(body["rows"][0]["odoo_id"])

        second = self.api.get(TAXES_URL, {"limit": 2, "cursor": 2}).json()
        self.assertEqual(len(second["rows"]), 1)
        self.assertFalse(second["has_more"])
        self.assertIsNone(second["next_cursor"])

    def test_list_taxes_filter_type_tax_use(self):
        """Filter ``?type_tax_use=purchase`` hanya mengembalikan pajak pembelian."""
        Tax.objects.create(code="BELI-11", name="PPN 11% Beli", type_tax_use="purchase")
        Tax.objects.create(code="JUAL-11", name="PPN 11% Jual", type_tax_use="sale")

        response = self.api.get(TAXES_URL, {"type_tax_use": "purchase"})

        self.assertEqual(response.status_code, 200)
        rows = response.json()["rows"]
        self.assertEqual([row["code"] for row in rows], ["BELI-11"])
        self.assertEqual(rows[0]["type_tax_use"], "purchase")

    def test_list_taxes_filter_type_tax_use_invalid_400(self):
        """Nilai ``type_tax_use`` di luar selection → 400 (bukan diam-diam kosong)."""
        response = self.api.get(TAXES_URL, {"type_tax_use": "sale;drop"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("type_tax_use", response.json()["detail"])

    def test_list_taxes_search_and_active_filter(self):
        """``?search=`` (code/name) + ``?active=`` bekerja bersamaan."""
        Tax.objects.create(code="PPN11-SALE", name="PPN 11%", amount=Decimal("11.00"))
        Tax.objects.create(code="PPN0-SALE", name="PPN 0% (Export)", is_active=False)

        found = self.api.get(TAXES_URL, {"search": "export"}).json()
        self.assertEqual([row["code"] for row in found["rows"]], ["PPN0-SALE"])

        active_only = self.api.get(TAXES_URL, {"active": "true"}).json()
        self.assertEqual([row["code"] for row in active_only["rows"]], ["PPN11-SALE"])

        invalid = self.api.get(TAXES_URL, {"active": "mungkin"})
        self.assertEqual(invalid.status_code, 400)

    def test_auth_required_403_anonymous(self):
        """Anonim: GET & POST → 403 (``IsAuthenticated``)."""
        anon = APIClient()

        self.assertEqual(anon.get(TAXES_URL).status_code, 403)
        self.assertEqual(anon.post(TAXES_URL, VALID_BODY, format="json").status_code, 403)
        self.assertEqual(anon.get(DEFAULT_URL).status_code, 403)

    def test_detail_and_missing_tax_404(self):
        """Detail pajak + 404 untuk id yang tidak ada."""
        tax = Tax.objects.create(code="PPN11", name="PPN 11%", amount=Decimal("11.00"))

        ok = self.api.get(detail_url(tax.pk))
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(set(ok.json()), ROW_KEYS)
        self.assertEqual(ok.json()["name"], "PPN 11%")

        missing = self.api.get(detail_url(999999))
        self.assertEqual(missing.status_code, 404)
        self.assertIn("tidak ditemukan", missing.json()["detail"])



    # -------------------------------------------------------------------- POST
    def test_create_tax_ok_records_sync_and_audit(self):
        """POST valid → 201 + baris pajak + ``SyncRecord`` + ``AuditLog`` + enqueue."""
        response, enqueue = self.post_tax(VALID_BODY)

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(set(body), ROW_KEYS | {"sync_record_id", "task_id", "queued"})
        self.assertEqual(body["code"], "PPN12-SALE")
        self.assertEqual(body["amount"], 12.0)
        self.assertEqual(body["type_tax_use"], "sale")
        self.assertFalse(body["is_default"])
        self.assertIsNone(body["odoo_id"])
        enqueue.assert_called_once()

        record = SyncRecord.objects.get(pk=body["sync_record_id"])
        self.assertEqual(record.resource, SyncResource.MASTER_TAX.value)
        self.assertEqual(record.stage, SyncStage.MASTER_PUSH.value)
        self.assertEqual(record.status, SyncStatus.PENDING)
        self.assertEqual(record.resource_id, str(body["id"]))
        # Payload push TIDAK memuat `tax_group_id` (Odoo mengisinya sendiri).
        for forbidden in FORBIDDEN_FIELDS:
            self.assertNotIn(forbidden, record.payload)
        self.assertEqual(record.payload["amount"], 12.0)

        self.assertTrue(
            AuditLog.objects.filter(
                action="master.create",
                resource=SyncResource.MASTER_TAX.value,
                resource_id=str(body["id"]),
            ).exists()
        )

    def test_create_tax_auto_code_when_omitted(self):
        """``code`` kosong → dibuat dari ``name`` (kolom ``code`` ``unique=True``)."""
        response, _enqueue = self.post_tax({"name": "PPN 2,2%", "amount": "2.2"})

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["code"], "PPN-2-2")

    def test_create_tax_duplicate_code_400(self):
        """Kode duplikat (case-insensitive) → 400."""
        Tax.objects.create(code="PPN11", name="Pajak Lama")

        response, _enqueue = self.post_tax(VALID_BODY | {"code": "ppn11"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("sudah dipakai", response.json()["detail"])
        self.assertEqual(Tax.objects.filter(code__iexact="ppn11").count(), 1)

    def test_create_tax_name_required_400(self):
        """``name`` kosong → 400 dan tidak ada baris baru."""
        response, enqueue = self.post_tax({"code": "TANPA-NAMA", "amount": 11})

        self.assertEqual(response.status_code, 400)
        self.assertIn("name", response.json()["detail"])
        self.assertFalse(Tax.objects.filter(code="TANPA-NAMA").exists())
        enqueue.assert_not_called()

    def test_create_tax_amount_negative_400(self):
        """``amount`` negatif → 400 (guard H3.6; 0 diizinkan)."""
        response, _enqueue = self.post_tax(VALID_BODY | {"amount": -1})

        self.assertEqual(response.status_code, 400)
        self.assertIn("negatif", response.json()["detail"])

    def test_create_tax_amount_zero_allowed(self):
        """``amount=0`` (PPN 0% / bebas pajak) → **201**, bukan 400."""
        response, _enqueue = self.post_tax(
            {"code": "EXPORT-0", "name": "PPN 0% (Export)", "amount": 0}
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["amount"], 0.0)

    def test_create_tax_invalid_amount_type_and_type_tax_use_400(self):
        """``amount_type``/``type_tax_use`` di luar selection Odoo → 400."""
        bad_amount_type, _ = self.post_tax(VALID_BODY | {"amount_type": "division"})
        self.assertEqual(bad_amount_type.status_code, 400)
        self.assertIn("amount_type", bad_amount_type.json()["detail"])

        bad_use, _ = self.post_tax(VALID_BODY | {"type_tax_use": "both"})
        self.assertEqual(bad_use.status_code, 400)
        self.assertIn("type_tax_use", bad_use.json()["detail"])

        bad_bool, _ = self.post_tax(VALID_BODY | {"price_include": "kadang"})
        self.assertEqual(bad_bool.status_code, 400)
        self.assertIn("price_include", bad_bool.json()["detail"])

    def test_create_tax_with_is_default_true_single_default(self):
        """``is_default=true`` saat create → hanya satu pajak default di MES."""
        lama = Tax.objects.create(code="LAMA", name="Pajak Lama", is_default=True)

        response, _enqueue = self.post_tax(VALID_BODY | {"is_default": True})

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["is_default"])
        lama.refresh_from_db()
        self.assertFalse(lama.is_default)
        self.assertEqual(Tax.objects.filter(is_default=True).count(), 1)

    # --------------------------------------------------------------------- PUT
    def test_update_tax_ok_reuses_sync_record(self):
        """PUT → 200, ``SyncRecord`` yang sama di-arm ulang + audit ``master.update``."""
        created, _ = self.post_tax(VALID_BODY)
        tax_id = created.json()["id"]
        record_id = created.json()["sync_record_id"]

        response, enqueue = self.put_tax(tax_id, {"amount": 11, "name": "PPN 11%"})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["amount"], 11.0)
        self.assertEqual(body["name"], "PPN 11%")
        self.assertEqual(body["sync_record_id"], record_id)
        enqueue.assert_called_once()

        record = SyncRecord.objects.get(pk=record_id)
        self.assertEqual(record.payload["amount"], 11.0)
        self.assertEqual(SyncRecord.objects.filter(resource=SyncResource.MASTER_TAX.value).count(), 1)

        self.assertTrue(
            AuditLog.objects.filter(
                action="master.update",
                resource=SyncResource.MASTER_TAX.value,
                resource_id=str(tax_id),
            ).exists()
        )

    def test_update_tax_invalid_amount_400(self):
        """PUT ``amount`` negatif → 400 dan nilai lama tidak berubah."""
        tax = Tax.objects.create(code="PPN11", name="PPN 11%", amount=Decimal("11.00"))

        response, enqueue = self.put_tax(tax.pk, {"amount": -5})

        self.assertEqual(response.status_code, 400)
        enqueue.assert_not_called()
        tax.refresh_from_db()
        self.assertEqual(tax.amount, Decimal("11.00"))

    def test_update_tax_missing_404(self):
        """PUT/DELETE id yang tidak ada → 404."""
        self.assertEqual(self.put_tax(999999, {"amount": 5})[0].status_code, 404)
        self.assertEqual(self.delete_tax(999999)[0].status_code, 404)

    def test_update_tax_only_is_default_skips_push(self):
        """Perubahan ``is_default`` saja = mes-only → tidak ada push baru."""
        tax = Tax.objects.create(code="PPN11", name="PPN 11%", amount=Decimal("11.00"))

        response, enqueue = self.put_tax(tax.pk, {"is_default": True})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["is_default"])
        self.assertIsNone(response.json()["sync_record_id"])
        enqueue.assert_not_called()
        self.assertEqual(
            SyncRecord.objects.filter(resource=SyncResource.MASTER_TAX.value).count(), 0
        )

    # ------------------------------------------------------------------ DELETE
    def test_delete_tax_soft_delete_keeps_row(self):
        """DELETE = soft delete: ``active=False``, baris tetap ada, default dilepas."""
        tax = Tax.objects.create(
            code="PPN11", name="PPN 11%", amount=Decimal("11.00"), is_default=True
        )

        response, enqueue = self.delete_tax(tax.pk)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["id"], tax.pk)
        self.assertFalse(body["active"])
        self.assertTrue(body["deleted"])
        self.assertFalse(body["is_default"])
        enqueue.assert_called_once()

        tax.refresh_from_db()
        self.assertFalse(tax.is_active)
        self.assertFalse(tax.is_default)
        self.assertTrue(Tax.objects.filter(pk=tax.pk).exists())

        record = SyncRecord.objects.get(resource=SyncResource.MASTER_TAX.value, resource_id=str(tax.pk))
        self.assertEqual(record.payload["active"], False)
        self.assertTrue(
            AuditLog.objects.filter(
                action="master.delete",
                resource=SyncResource.MASTER_TAX.value,
                resource_id=str(tax.pk),
            ).exists()
        )


    # -------------------------------------------------------------------- izin
    def test_write_requires_admin_only(self):
        """PURCHASING & OPERATOR boleh baca, tetapi tulis (POST/PUT/DELETE/set-default) 403."""
        tax = Tax.objects.create(code="PPN11", name="PPN 11%", amount=Decimal("11.00"))

        for client in (self.purchasing_api, self.operator_api):
            self.assertEqual(client.get(TAXES_URL).status_code, 200)
            self.assertEqual(
                client.post(TAXES_URL, VALID_BODY, format="json").status_code, 403
            )
            self.assertEqual(client.put(detail_url(tax.pk), {"amount": 5}).status_code, 403)
            self.assertEqual(client.delete(detail_url(tax.pk)).status_code, 403)
            self.assertEqual(
                client.post(set_default_url(tax.pk)).status_code, 403
            )

        self.assertTrue(tax.is_active)
        self.assertEqual(Tax.objects.count(), 1)

    # ------------------------------------------------------------ pajak default
    def test_set_default_tax_atomic_single_default(self):
        """``set-default`` meng-unset default lain (atomik, maksimal satu)."""
        lama = Tax.objects.create(code="LAMA", name="Pajak Lama", is_default=True)
        baru = Tax.objects.create(code="BARU", name="Pajak Baru")

        response = self.api.post(set_default_url(baru.pk))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["is_default"])
        lama.refresh_from_db()
        baru.refresh_from_db()
        self.assertFalse(lama.is_default)
        self.assertTrue(baru.is_default)
        self.assertEqual(Tax.objects.filter(is_default=True).count(), 1)
        # mes-only: tidak ada push ke Odoo hanya karena penanda default.
        self.assertEqual(
            SyncRecord.objects.filter(resource=SyncResource.MASTER_TAX.value).count(), 0
        )

    def test_set_default_tax_inactive_400(self):
        """Pajak nonaktif tidak boleh dijadikan default → 400."""
        tax = Tax.objects.create(code="MATI", name="Pajak Mati", is_active=False)

        response = self.api.post(set_default_url(tax.pk))

        self.assertEqual(response.status_code, 400)
        self.assertIn("nonaktif", response.json()["detail"])

    def test_set_default_tax_missing_404(self):
        """``set-default`` id tidak ada → 404."""
        self.assertEqual(self.api.post(set_default_url(999999)).status_code, 404)

    def test_default_endpoint_returns_marked_default(self):
        """``GET /taxes/default/`` → pajak ber-``is_default``."""
        tax = Tax.objects.create(
            code="PPN11-SALE", name="PPN 11%", amount=Decimal("11.00"), is_default=True
        )

        response = self.api.get(DEFAULT_URL)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["tax"]["id"], tax.pk)
        self.assertEqual(response.json()["tax"]["code"], "PPN11-SALE")

    def test_default_endpoint_fallback_ppn11_without_marker(self):
        """Tanpa penanda: fallback PPN 11% penjualan (bukan nama — ``amount``+``type``)."""
        Tax.objects.create(code="PPN11-SALE", name="PPN 11%", amount=Decimal("11.00"))
        Tax.objects.create(code="PPN12-SALE", name="PPN 12%", amount=Decimal("12.00"))

        body = self.api.get(DEFAULT_URL).json()

        self.assertEqual(body["tax"]["code"], "PPN11-SALE")
        self.assertEqual(body["tax"]["amount"], 11.0)

    def test_default_endpoint_null_when_no_tax(self):
        """Belum ada pajak sama sekali → ``{"tax": null}`` (bukan 404)."""
        self.assertEqual(Tax.objects.count(), 0)

        response = self.api.get(DEFAULT_URL)

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["tax"])



class PushTaxTaskTests(TestCase):
    """Push Odoo: pemetaan payload, jalur create/update, no-op mode, guard."""

    def test_tax_odoo_values_mapping_without_tax_group(self):
        """Payload MES → nilai ``account.tax``; ``tax_group_id`` TIDAK dikirim."""
        values = _tax_odoo_values(tax_payload(
            Tax(code="PPN11-SALE", name="PPN 11%", amount=Decimal("11.00"))
        ))

        self.assertEqual(values["name"], "PPN 11%")
        self.assertEqual(values["amount"], 11.0)
        self.assertEqual(values["amount_type"], "percent")
        self.assertEqual(values["type_tax_use"], "sale")
        self.assertFalse(values["price_include"])
        self.assertTrue(values["active"])
        for forbidden in FORBIDDEN_FIELDS:
            self.assertNotIn(forbidden, values)

    def test_push_tax_create_calls_odoo_create(self):
        """Belum punya ``odoo_id`` → ``create`` + ``odoo_id`` tersimpan dari respons."""
        tax = Tax.objects.create(code="PPN12", name="PPN 12%", amount=Decimal("12.00"))
        client = FakeOdooClient(created_id=777)

        with patch(CREATE_CLIENT, return_value=client):
            erp_id = _push_tax_to_odoo(tax, tax_payload(tax))

        self.assertEqual(erp_id, "777")
        self.assertEqual(len(client.created), 1)
        model, values = client.created[0]
        self.assertEqual(model, ODOO_TAX_MODEL)
        self.assertEqual(values["amount"], 12.0)
        self.assertNotIn("tax_group_id", values)
        self.assertTrue(client.closed)

    def test_push_tax_update_calls_odoo_write(self):
        """Sudah punya ``odoo_id`` → ``write`` (tidak menambah record Odoo)."""
        tax = Tax.objects.create(
            code="PPN12", name="PPN 12%", amount=Decimal("12.00"), odoo_id=321
        )
        client = FakeOdooClient()

        with patch(CREATE_CLIENT, return_value=client):
            erp_id = _push_tax_to_odoo(tax, tax_payload(tax))

        self.assertEqual(erp_id, "321")
        self.assertEqual(client.created, [])
        model, ids, values = client.written[0]
        self.assertEqual(model, ODOO_TAX_MODEL)
        self.assertEqual(ids, [321])
        self.assertEqual(values["name"], "PPN 12%")

    def test_push_task_noop_mode_marks_sent_and_idempotent(self):
        """Task ``erp_sync.push_master_tax`` di mode no-op → SENT + idempotent."""
        tax = Tax.objects.create(code="PPN11", name="PPN 11%", amount=Decimal("11.00"))
        payload = tax_payload(tax)
        record = SyncIdempotency().get_or_create_sync_record(
            SyncResource.MASTER_TAX.value, tax.pk, SyncStage.MASTER_PUSH.value, payload
        )

        with override_settings(ERP_ADAPTER="null"):
            result = push_master_tax.apply(args=[tax.pk, record.pk]).get()

        self.assertEqual(result["status"], "sent")
        self.assertEqual(result["resource"], SyncResource.MASTER_TAX.value)
        self.assertTrue(str(result["erp_id"]).startswith("NULL-"))

        record.refresh_from_db()
        self.assertEqual(record.status, SyncStatus.SENT)
        self.assertTrue(
            AuditLog.objects.filter(
                action="erp_sync.push_master_tax", resource_id=str(tax.pk)
            ).exists()
        )

        again = push_master_tax.apply(args=[tax.pk, record.pk]).get()
        self.assertEqual(again["status"], "duplicate-ignored")

    def test_push_task_missing_tax_not_found(self):
        """Task untuk id yang tidak ada → ``not-found`` (tidak melempar)."""
        result = push_master_tax.apply(args=[999999]).get()

        self.assertEqual(result["status"], "not-found")



class TaxPullTests(TestCase):
    """Pull Odoo → MES: ``amount``/pajak jenis diisi **hanya bila MES belum diisi**."""

    def setUp(self):
        """Bersihkan baris seed ``master.0019`` (kode seed bisa bentrok dengan fixture)."""
        Tax.objects.all().delete()

    def test_pull_mengisi_amount_kosong(self):
        """Baris baru (MES belum punya) → ``amount``/``amount_type`` ikut terisi."""
        defaults = _tax_defaults(
            {
                "id": 19,
                "name": "12% (Non-Luxury Good)",
                "amount": 11.0,
                "amount_type": "percent",
                "type_tax_use": "sale",
                "price_include": False,
                "active": True,
            }
        )

        self.assertEqual(defaults["code"], "ODOO-19")
        self.assertEqual(defaults["name"], "12% (Non-Luxury Good)")
        self.assertEqual(defaults["amount"], Decimal("11.00"))
        self.assertEqual(defaults["amount_type"], "percent")
        self.assertEqual(defaults["type_tax_use"], "sale")
        self.assertFalse(defaults["price_include"])

    def test_pull_tidak_menimpa_amount_mes(self):
        """MES sudah punya tarif sendiri → pull TIDAK menimpa (pelajaran H3.5)."""
        tax = Tax.objects.create(
            code="PPN11-SALE",
            name="PPN 11%",
            amount=Decimal("11.00"),
            odoo_id=19,
        )

        defaults = _tax_defaults(
            {
                "id": tax.odoo_id,
                "name": tax.name,
                "amount": 12.0,
                "amount_type": "percent",
                "type_tax_use": "sale",
                "price_include": False,
                "active": True,
            }
        )

        self.assertNotIn("amount", defaults)

    def test_pull_mengisi_amount_nol_dan_type_default(self):
        """``amount`` MES masih 0 + ``type_tax_use`` masih default → keduanya diisi."""
        tax = Tax.objects.create(code="ODOO-34", name="12% IM", amount=Decimal("0.00"), odoo_id=34)

        defaults = _tax_defaults(
            {
                "id": tax.odoo_id,
                "name": tax.name,
                "amount": 12.0,
                "amount_type": "percent",
                "type_tax_use": "purchase",
                "price_include": True,
                "active": True,
            }
        )

        self.assertEqual(defaults["amount"], Decimal("12.00"))
        self.assertEqual(defaults["type_tax_use"], "purchase")
        self.assertTrue(defaults["price_include"])

    def test_pull_tidak_menimpa_konfigurasi_mes_yang_disengaja(self):
        """``type_tax_use`` MES sudah bukan default (mis. purchase) → tidak ditimpa."""
        tax = Tax.objects.create(
            code="BELI-SENDIRI",
            name="Pajak Beli MES",
            amount=Decimal("5.00"),
            amount_type="fixed",
            type_tax_use="purchase",
            odoo_id=77,
        )

        defaults = _tax_defaults(
            {
                "id": tax.odoo_id,
                "name": "Tax Odoo",
                "amount": 3.0,
                "amount_type": "percent",
                "type_tax_use": "sale",
                "price_include": False,
                "active": True,
            }
        )

        self.assertNotIn("amount", defaults)
        self.assertNotIn("amount_type", defaults)
        self.assertNotIn("type_tax_use", defaults)

    def test_pull_tidak_pernah_menyentuh_is_default(self):
        """``is_default`` = keputusan MES → TIDAK PERNAH ikut ditarik dari Odoo."""
        tax = Tax.objects.create(code="PPN11-SALE", name="PPN 11%", is_default=True, odoo_id=88)

        defaults = _tax_defaults(
            {"id": tax.odoo_id, "name": tax.name, "amount": 11.0, "active": True}
        )

        self.assertNotIn("is_default", defaults)
        tax.refresh_from_db()
        self.assertTrue(tax.is_default)

    def test_pull_amount_tidak_valid_dilewati_tanpa_galat(self):
        """``amount`` kotor dari Odoo → dilewati, pull tetap jalan."""
        defaults = _tax_defaults(
            {"id": 99, "name": "Pajak Aneh", "amount": "bukan-angka", "active": True}
        )

        self.assertNotIn("amount", defaults)
        self.assertEqual(defaults["name"], "Pajak Aneh")

    def test_pull_end_to_end_task_upsert_by_odoo_id(self):
        """Task ``sync_master_taxes`` men-upsert lewat ``odoo_id`` (bukan nama)."""

        class FakePullTransport:
            """Transport palsu: hanya menyediakan ``fetch_taxes``/``close``."""

            def fetch_taxes(self, since=None):
                """Baris Odoo contoh (pola data dev: nama '12%' tapi amount 11.0)."""
                return [
                    {
                        "id": 19,
                        "name": "12% (Non-Luxury Good)",
                        "amount": 11.0,
                        "amount_type": "percent",
                        "type_tax_use": "sale",
                        "price_include": False,
                        "active": True,
                    }
                ]

            def close(self):
                """Tidak ada resource jaringan untuk ditutup."""

        with patch(
            "integrations.erp_sync.tasks_master.get_transport",
            return_value=FakePullTransport(),
        ):
            result = sync_master_taxes.apply(kwargs={"since": None}).get()

        self.assertEqual(result["created"], 1)
        self.assertEqual(result["skipped"], 0)

        tax = Tax.objects.get(odoo_id=19)
        self.assertEqual(tax.code, "ODOO-19")
        self.assertEqual(tax.amount, Decimal("11.00"))
        self.assertEqual(tax.name, "12% (Non-Luxury Good)")
        self.assertTrue(tax.is_active)
        self.assertFalse(tax.is_default)


class TaxNonBreakingTests(TestCase):
    """Konsumen lama wajib tetap hijau (H2.1/H2.2 M2M ``master.Tax``)."""

    def test_order_line_tax_ids_masih_m2m_master_tax(self):
        """``OrderLine.tax_ids`` (H2.1) tetap M2M ke ``master.Tax``."""
        field = OrderLine._meta.get_field("tax_ids")

        self.assertEqual(field.related_model, Tax)
        self.assertTrue(field.blank)

    def test_purchase_order_line_tax_ids_masih_m2m_master_tax(self):
        """``PurchaseOrderLine.tax_ids`` (H2.2) tetap M2M ke ``master.Tax``."""
        field = PurchaseOrderLine._meta.get_field("tax_ids")

        self.assertEqual(field.related_model, Tax)
        self.assertTrue(field.blank)

    def test_tax_bisa_dipakai_relasi_lama_setelah_field_baru(self):
        """Field H3.6 tidak mengubah relasi: ``tax.amount`` & ``tax.type_tax_use`` aman."""
        tax = Tax.objects.create(code="PPN11", name="PPN 11%", amount=Decimal("11.00"))

        self.assertEqual(tax.amount, Decimal("11.00"))
        self.assertEqual(tax.type_tax_use, Tax.TaxUse.SALE)
        self.assertFalse(tax.price_include)
        self.assertEqual(str(tax), "PPN11 - PPN 11%")

