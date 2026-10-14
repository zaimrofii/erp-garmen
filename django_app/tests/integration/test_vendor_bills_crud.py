"""Test CRUD Vendor Bill MES — ``/api/v1/finance/vendor-bills/`` (H3.2).

Cakupan: create (auto-fill dari `PurchaseOrderLine` **dan** ``lines[]`` eksplisit,
termasuk bill **tanpa PO**), validasi **400** (vendor/tanggal/qty/harga/pajak/ref),
update & delete **DRAFT-only**, list (pagination/filter/search), detail, izin
(anon **403**, role selain ADMIN/OWNER **403**), transisi ``confirm`` (guard
``vendor.odoo_id`` + ``product.odoo_id`` + ``tax.odoo_id`` + ``qty > 0`` +
``price_unit >= 0``) → ``done`` → ``cancel``, ledger ``SyncRecord`` (resource
**`vendor_bill`**, stage **`VENDOR_BILL`** — keduanya BARU, tidak menabrak
``INVOICE`` milik I5/H3.1) + ``AuditLog``, task ``erp_sync.push_vendor_bill``
(sukses → SENT + ``odoo_id``; gagal → SyncRecord FAILED tapi state tetap
CONFIRMED), serta **non-breaking**: I6 (`fetch_vendor_bills` +
`MaterialReadiness.vendor_bill_*`), H2.2 (purchase orders CRUD), H3.1 (customer
invoice) + F15 monitoring tetap hijau.

Catatan:
  * enqueue task di-patch (pola H1.2/H2.1/H2.2/H3.1) supaya test tidak menyentuh broker;
  * adapter di-patch untuk menguji payload push nyata (tanpa Odoo);
  * ``ref`` = best-effort: boleh kosong & boleh duplikat (probe STEP 0).

Jalankan (di dalam container):

    docker compose exec -T django python -m pytest tests/integration/test_vendor_bills_crud.py -q
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.models import (
    PurchaseOrder,
    PurchaseOrderLine,
    VendorBill,
    VendorBillLine,
)
from apps_industry.garment.services import vendor_bill_services as svc
from core.audit.models import AuditLog
from core.auth.models import Role, User
from integrations.erp_sync.adapters.base import ERPResponse
from integrations.erp_sync.adapters.odoo import STAGE_VENDOR_BILL, OdooAdapter
from integrations.erp_sync.models import SyncRecord, SyncResource, SyncStage, SyncStatus
from integrations.erp_sync.tasks_vendor_bill_push import push_vendor_bill
from master.models import Partner, Product, Tax

BILLS_URL = "/api/v1/finance/vendor-bills/"
ENVELOPE_KEYS = {"rows", "total_count", "has_more", "next_cursor"}
ROW_KEYS = {
    "id",
    "code",
    "purchase_order_id",
    "purchase_order_no",
    "vendor_id",
    "vendor_name",
    "vendor_code",
    "ref",
    "invoice_date",
    "due_date",
    "state",
    "notes",
    "lines_count",
    "amount_total",
    "odoo_id",
    "created_at",
    "updated_at",
}
DETAIL_EXTRA_KEYS = {
    "lines",
    "odoo_sync_status",
    "odoo_sync_error",
    "allowed_actions",
}
#: Info tulis (hanya pada respons POST/PUT/aksi — ``_write_body``).
WRITE_EXTRA_KEYS = {"sync_record_id", "task_id", "queued"}
#: Path patch enqueue task (service meng-enqueue saat confirm/cancel).
ENQUEUE = "integrations.erp_sync.tasks_vendor_bill_push.push_vendor_bill.apply_async"
#: Path patch adapter di module task (menguji payload & jalur sukses/gagal).
ADAPTER = "integrations.erp_sync.tasks_vendor_bill_push.get_adapter"


def detail_url(pk: int) -> str:
    """URL detail bill."""
    return f"{BILLS_URL}{pk}/"


def action_url(pk: int, action: str) -> str:
    """URL aksi transisi bill."""
    return f"{BILLS_URL}{pk}/{action}/"


class FakeAdapter:
    """Adapter palsu: mencatat payload push/cancel tanpa menyentuh Odoo."""

    def __init__(self, ok: bool = True, erp_id: str = "888", error: str | None = None):
        """Simpan konfigurasi respons + riwayat panggilan."""
        self.ok = ok
        self.erp_id = erp_id
        self.error = error
        self.pushed: list[dict] = []
        self.cancelled: list[str] = []
        self.closed = False

    def push_vendor_bill(self, payload: dict) -> ERPResponse:
        """Catat payload push & balas sesuai konfigurasi."""
        self.pushed.append(dict(payload))

        return ERPResponse(
            ok=self.ok,
            erp_id=self.erp_id if self.ok else None,
            raw={"payload": dict(payload)},
            error=None if self.ok else (self.error or "push gagal"),
            stage=STAGE_VENDOR_BILL,
            ref=str(payload.get("ref") or ""),
        )

    def cancel_vendor_bill(self, erp_id: str) -> ERPResponse:
        """Catat erp_id yang dibatalkan & balas sesuai konfigurasi."""
        self.cancelled.append(str(erp_id))

        return ERPResponse(
            ok=self.ok,
            erp_id=self.erp_id if self.ok else None,
            raw={"cancelled": erp_id},
            error=None if self.ok else (self.error or "cancel gagal"),
            stage=STAGE_VENDOR_BILL,
            ref=str(erp_id),
        )

    def close(self) -> None:
        """Tandai adapter ditutup (task wajib menutup di ``finally``)."""
        self.closed = True


class VendorBillBase(TestCase):
    """Fixture bersama: user (admin/operator), master (vendor/produk/pajak), PO + baris."""

    @classmethod
    def setUpTestData(cls):
        """Master data + PO H2.2 dengan satu baris berharga > 0 + pajak."""
        cls.admin = User.objects.create_user(
            username="admin-vb",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.ADMIN),
        )
        cls.operator = User.objects.create_user(
            username="op-vb",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.OPERATOR),
        )

        cls.vendor = Partner.objects.create(
            code="SUP-VB", name="PT Vendor Bill", odoo_id=14
        )
        cls.product = Product.objects.create(
            code="BENANG-VB", name="Benang Vendor", odoo_id=34, cost_price=Decimal("1500.00")
        )
        cls.tax = Tax.objects.create(
            code="PPN11-VB", name="PPN 11%", amount=Decimal("11.00"), odoo_id=20
        )

        cls.po = PurchaseOrder.objects.create(code="PO-2026-9001", vendor=cls.vendor)
        cls.po_line = PurchaseOrderLine.objects.create(
            po=cls.po, product=cls.product, qty=Decimal("10.00"), price_unit=Decimal("1500.00")
        )
        cls.po_line.tax_ids.set([cls.tax])

    def setUp(self):
        """Klien admin (utama) + operator (uji 403)."""
        self.api = APIClient()
        self.api.force_authenticate(self.admin)
        self.operator_api = APIClient()
        self.operator_api.force_authenticate(self.operator)

    # ------------------------------------------------------------------ helper
    def post_bill(self, body: dict, client=None):
        """POST bill (enqueue di-patch) → ``(response, mock)``."""
        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-vb-1")) as enqueue:
            response = (client or self.api).post(BILLS_URL, body, format="json")

        return response, enqueue

    def put_bill(self, pk: int, body: dict, client=None):
        """PUT bill (enqueue di-patch) → ``(response, mock)``."""
        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-vb-2")) as enqueue:
            response = (client or self.api).put(detail_url(pk), body, format="json")

        return response, enqueue

    def delete_bill(self, pk: int, client=None):
        """DELETE bill (enqueue di-patch) → ``(response, mock)``."""
        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-vb-3")) as enqueue:
            response = (client or self.api).delete(detail_url(pk))

        return response, enqueue

    def act(self, pk: int, action: str, client=None):
        """POST aksi transisi (enqueue di-patch) → ``(response, mock)``."""
        with patch(ENQUEUE, return_value=SimpleNamespace(id=f"task-vb-{action}")) as enqueue:
            response = (client or self.api).post(action_url(pk, action), {}, format="json")

        return response, enqueue

    def make_bill(self, **overrides) -> VendorBill:
        """Buat bill DRAFT lewat service dengan body standar (auto-fill dari PO)."""
        body: dict = {"vendor_id": self.vendor.pk, "invoice_date": "2026-10-13"}
        body.update(overrides)
        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-vb-seed")):
            result = svc.create_bill(body)

        self.assertIsNone(result.error, result.error)
        return result.bill

    def confirm_bill_service(self, pk: int):
        """CONFIRM bill lewat service (enqueue di-patch) → ``(bill, result)``."""
        bill = VendorBill.objects.get(pk=pk)
        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-vb-confirm")):
            result = svc.confirm_bill(bill)

        self.assertIsNone(result.error, result.error)
        bill.refresh_from_db()
        return bill, result


class VendorBillCrudTests(VendorBillBase):
    """CRUD bill lewat API (create auto-fill/eksplisit, update, delete, izin)."""

    # ---------------------------------------------------------------- create
    def test_create_autofill_dari_po_line(self):
        """POST ``purchase_order_id`` tanpa ``lines`` → auto-fill dari PO Line."""
        response, _enqueue = self.post_bill(
            {"vendor_id": self.vendor.pk, "purchase_order_id": self.po.pk,
             "invoice_date": "2026-10-13", "ref": "INV-VENDOR-001"}
        )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertTrue(body["code"].startswith("VB-"))
        self.assertEqual(body["state"], "DRAFT")
        self.assertEqual(body["vendor_id"], self.vendor.pk)
        self.assertEqual(body["purchase_order_id"], self.po.pk)
        self.assertEqual(body["purchase_order_no"], self.po.code)
        self.assertEqual(body["ref"], "INV-VENDOR-001")
        self.assertEqual(body["lines_count"], 1)
        self.assertEqual(body["amount_total"], "15000.00")
        self.assertFalse(body["queued"])
        self.assertIsNone(body["odoo_id"])

        line = body["lines"][0]
        self.assertEqual(line["product_id"], self.product.pk)
        self.assertEqual(line["qty"], "10.00")
        self.assertEqual(line["price_unit"], "1500.00")
        self.assertEqual(line["subtotal"], "15000.00")
        self.assertEqual(line["tax_ids"], [self.tax.pk])
        self.assertEqual(line["tax_odoo_ids"], [20])
        self.assertEqual(line["po_line_id"], self.po_line.pk)

        record = SyncRecord.objects.get(pk=body["sync_record_id"])
        self.assertEqual(record.resource, SyncResource.VENDOR_BILL.value)
        self.assertEqual(record.stage, SyncStage.VENDOR_BILL.value)
        self.assertEqual(record.status, SyncStatus.PENDING)
        self.assertTrue(
            AuditLog.objects.filter(action=svc.ACTION_CREATE, resource_id=str(body["id"])).exists()
        )

    def test_create_tanpa_po_dengan_lines_eksplisit(self):
        """Bill **tanpa PO** (biaya jasa) sah selama ``lines`` dikirim."""
        response, _enqueue = self.post_bill(
            {
                "vendor_id": self.vendor.pk,
                "invoice_date": "2026-10-13",
                "lines": [
                    {"product_id": self.product.pk, "qty": "2", "price_unit": "1500.50"}
                ],
            }
        )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertIsNone(body["purchase_order_id"])
        self.assertIsNone(body["purchase_order_no"])
        self.assertEqual(body["amount_total"], "3001.00")
        self.assertIsNone(body["lines"][0]["po_line_id"])

    def test_create_tanpa_po_tanpa_lines_400(self):
        """Bill tanpa PO **harus** kirim ``lines`` (tidak ada sumber auto-fill)."""
        response, enqueue = self.post_bill(
            {"vendor_id": self.vendor.pk, "invoice_date": "2026-10-13"}
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("lines", response.json()["detail"])
        enqueue.assert_not_called()
        self.assertEqual(VendorBill.objects.count(), 0)

    def test_create_tanpa_vendor_400(self):
        """``vendor_id`` kosong → 400 dan tidak ada baris tersimpan."""
        response, enqueue = self.post_bill(
            {"purchase_order_id": self.po.pk, "invoice_date": "2026-10-13"}
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("vendor_id", response.json()["detail"])
        enqueue.assert_not_called()
        self.assertEqual(VendorBill.objects.count(), 0)

    def test_create_vendor_tidak_ada_dan_po_tidak_ada_400(self):
        """Vendor/PO yang tidak dikenal → 400 dengan pesan jelas."""
        no_vendor, _ = self.post_bill(
            {"vendor_id": 999999, "invoice_date": "2026-10-13",
             "lines": [{"product_id": self.product.pk, "qty": "1", "price_unit": "1"}]}
        )
        self.assertEqual(no_vendor.status_code, 400)
        self.assertIn("Vendor 999999 tidak ditemukan", no_vendor.json()["detail"])

        no_po, _ = self.post_bill(
            {"vendor_id": self.vendor.pk, "purchase_order_id": 999999,
             "invoice_date": "2026-10-13"}
        )
        self.assertEqual(no_po.status_code, 400)
        self.assertIn("Purchase Order 999999 tidak ditemukan", no_po.json()["detail"])

    def test_create_tanggal_tidak_valid_400(self):
        """``invoice_date`` wajib ISO; tanggal kosong/salah → 400."""
        missing, _ = self.post_bill(
            {"vendor_id": self.vendor.pk, "purchase_order_id": self.po.pk}
        )
        self.assertEqual(missing.status_code, 400)
        self.assertIn("invoice_date", missing.json()["detail"])

        invalid, _ = self.post_bill(
            {"vendor_id": self.vendor.pk, "purchase_order_id": self.po.pk,
             "invoice_date": "13-10-2026"}
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertIn("ISO", invalid.json()["detail"])

    def test_create_qty_dan_harga_tidak_valid_400(self):
        """``qty <= 0``, harga negatif, atau produk tak ada → 400."""
        base = {"vendor_id": self.vendor.pk, "invoice_date": "2026-10-13"}

        qty_zero, _ = self.post_bill(
            base | {"lines": [{"product_id": self.product.pk, "qty": 0, "price_unit": "10"}]}
        )
        self.assertEqual(qty_zero.status_code, 400)
        self.assertIn("qty", qty_zero.json()["detail"])

        negative, _ = self.post_bill(
            base | {"lines": [{"product_id": self.product.pk, "qty": "1", "price_unit": "-1"}]}
        )
        self.assertEqual(negative.status_code, 400)
        self.assertIn("negatif", negative.json()["detail"])

        no_product, _ = self.post_bill(
            base | {"lines": [{"product_id": 999999, "qty": "1", "price_unit": "1"}]}
        )
        self.assertEqual(no_product.status_code, 400)
        self.assertIn("tidak ditemukan", no_product.json()["detail"])

    def test_create_tax_tidak_ada_400(self):
        """``tax_ids`` menunjuk pajak yang tidak ada → 400."""
        response, _ = self.post_bill(
            {
                "vendor_id": self.vendor.pk,
                "invoice_date": "2026-10-13",
                "lines": [
                    {"product_id": self.product.pk, "qty": "1", "price_unit": "10",
                     "tax_ids": [999999]}
                ],
            }
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("pajak 999999 tidak ditemukan", response.json()["detail"])

    def test_create_ref_panjang_400_dan_duplikat_201(self):
        """``ref`` > 64 char → 400; ``ref`` duplikat → tetap 201 (best-effort)."""
        too_long, _ = self.post_bill(
            {"vendor_id": self.vendor.pk, "purchase_order_id": self.po.pk,
             "invoice_date": "2026-10-13", "ref": "X" * 65}
        )
        self.assertEqual(too_long.status_code, 400)
        self.assertIn("ref", too_long.json()["detail"])

        first, _ = self.post_bill(
            {"vendor_id": self.vendor.pk, "purchase_order_id": self.po.pk,
             "invoice_date": "2026-10-13", "ref": "INV-VENDOR-SAMA"}
        )
        self.assertEqual(first.status_code, 201)
        self.assertNotIn("duplicate_warning", first.json())

        second, _ = self.post_bill(
            {"vendor_id": self.vendor.pk, "purchase_order_id": self.po.pk,
             "invoice_date": "2026-10-13", "ref": "INV-VENDOR-SAMA"}
        )
        self.assertEqual(second.status_code, 201)
        self.assertIn("bill aktif", second.json()["duplicate_warning"])
        self.assertEqual(VendorBill.objects.filter(ref="INV-VENDOR-SAMA").count(), 2)

    def test_create_po_tanpa_baris_400(self):
        """PO tanpa baris + tanpa ``lines`` → 400 (jelas, bukan bill kosong)."""
        po = PurchaseOrder.objects.create(code="PO-2026-9002", vendor=self.vendor)

        response, _ = self.post_bill(
            {"vendor_id": self.vendor.pk, "purchase_order_id": po.pk,
             "invoice_date": "2026-10-13"}
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("tidak punya baris", response.json()["detail"])

    # ------------------------------------------------------- update / delete
    def test_update_draft_mengganti_lines(self):
        """PUT DRAFT → header berubah + ``lines`` **mengganti** seluruh baris."""
        bill = self.make_bill(purchase_order_id=self.po.pk)

        response, _enqueue = self.put_bill(
            bill.pk,
            {
                "ref": "INV-REV-001",
                "notes": "koreksi harga",
                "lines": [
                    {"product_id": self.product.pk, "qty": "3", "price_unit": "1000",
                     "tax_ids": [self.tax.pk]}
                ],
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["ref"], "INV-REV-001")
        self.assertEqual(body["notes"], "koreksi harga")
        self.assertEqual(body["lines_count"], 1)
        self.assertEqual(body["amount_total"], "3000.00")
        self.assertEqual(VendorBillLine.objects.filter(bill=bill).count(), 1)

    def test_update_dan_delete_confirmed_400(self):
        """Bill ``CONFIRMED`` tidak boleh diubah/dihapus (DRAFT-only)."""
        bill = self.make_bill(purchase_order_id=self.po.pk)
        bill.state = "CONFIRMED"
        bill.save(update_fields=("state",))

        put_response, _ = self.put_bill(bill.pk, {"notes": "x"})
        self.assertEqual(put_response.status_code, 400)
        self.assertIn("hanya boleh saat DRAFT", put_response.json()["detail"])

        delete_response, _ = self.delete_bill(bill.pk)
        self.assertEqual(delete_response.status_code, 400)
        self.assertTrue(VendorBill.objects.filter(pk=bill.pk).exists())

    def test_delete_draft_ok(self):
        """DELETE DRAFT → hard delete (baris ikut CASCADE) + audit."""
        bill = self.make_bill(purchase_order_id=self.po.pk)
        pk = bill.pk

        response, _enqueue = self.delete_bill(pk)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"id": pk, "deleted": True})
        self.assertFalse(VendorBill.objects.filter(pk=pk).exists())
        self.assertEqual(VendorBillLine.objects.filter(bill_id=pk).count(), 0)
        self.assertTrue(AuditLog.objects.filter(action=svc.ACTION_DELETE).exists())

    def test_operator_403_pada_tulis(self):
        """Role selain ADMIN/OWNER → 403 untuk POST/PUT/DELETE (baca tetap boleh)."""
        post_response, _ = self.post_bill(
            {"vendor_id": self.vendor.pk, "purchase_order_id": self.po.pk,
             "invoice_date": "2026-10-13"},
            client=self.operator_api,
        )
        self.assertEqual(post_response.status_code, 403)

        bill = self.make_bill(purchase_order_id=self.po.pk)
        put_response, _ = self.put_bill(bill.pk, {"notes": "x"}, client=self.operator_api)
        self.assertEqual(put_response.status_code, 403)

        delete_response, _ = self.delete_bill(bill.pk, client=self.operator_api)
        self.assertEqual(delete_response.status_code, 403)

        self.assertEqual(self.operator_api.get(BILLS_URL).status_code, 200)


class VendorBillListDetailTests(VendorBillBase):
    """List (amplop/pagination/filter/search) + detail + izin & 404."""

    def test_list_amplop_dan_row_keys(self):
        """GET list → amplop ListPage + 17 key baris (kontrak H3.2)."""
        self.make_bill(purchase_order_id=self.po.pk, ref="INV-LIST-1")

        response = self.api.get(BILLS_URL)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), ENVELOPE_KEYS)
        self.assertEqual(body["total_count"], 1)
        self.assertFalse(body["has_more"])
        self.assertIsNone(body["next_cursor"])
        self.assertEqual(set(body["rows"][0]), ROW_KEYS)
        self.assertEqual(body["rows"][0]["ref"], "INV-LIST-1")
        self.assertEqual(body["rows"][0]["amount_total"], "15000.00")

    def test_list_filter_state_vendor_po(self):
        """Filter ``?state=``, ``?vendor_id=``, ``?purchase_order_id=`` + state tak dikenal 400."""
        bill = self.make_bill(purchase_order_id=self.po.pk)
        manual = self.make_bill(
            lines=[{"product_id": self.product.pk, "qty": "1", "price_unit": "100"}]
        )
        manual.state = "CANCELLED"
        manual.save(update_fields=("state",))

        only_draft = self.api.get(f"{BILLS_URL}?state=DRAFT").json()
        self.assertEqual(only_draft["total_count"], 1)
        self.assertEqual(only_draft["rows"][0]["id"], bill.pk)

        by_po = self.api.get(f"{BILLS_URL}?purchase_order_id={self.po.pk}").json()
        self.assertEqual(by_po["total_count"], 1)

        by_vendor = self.api.get(f"{BILLS_URL}?vendor_id={self.vendor.pk}").json()
        self.assertEqual(by_vendor["total_count"], 2)

        unknown = self.api.get(f"{BILLS_URL}?state=BOGUS")
        self.assertEqual(unknown.status_code, 400)
        self.assertIn("state", unknown.json()["detail"])

    def test_list_search_ref_dan_kode_po(self):
        """``?search=`` mencocokkan kode, ref, nama vendor, dan kode PO."""
        self.make_bill(purchase_order_id=self.po.pk, ref="INV-CARI-777")

        by_ref = self.api.get(f"{BILLS_URL}?search=CARI-777").json()
        self.assertEqual(by_ref["total_count"], 1)

        by_po = self.api.get(f"{BILLS_URL}?search=PO-2026-9001").json()
        self.assertEqual(by_po["total_count"], 1)

        by_vendor = self.api.get(f"{BILLS_URL}?search=Vendor Bill").json()
        self.assertEqual(by_vendor["total_count"], 1)

        kosong = self.api.get(f"{BILLS_URL}?search=tidak-ada").json()
        self.assertEqual(kosong["total_count"], 0)

    def test_list_pagination_dan_limit_invalid(self):
        """``?limit``/``?cursor`` → ``has_more``/``next_cursor``; nilai salah → 400."""
        for index in range(3):
            self.make_bill(
                lines=[{"product_id": self.product.pk, "qty": "1", "price_unit": str(index + 1)}]
            )

        page1 = self.api.get(f"{BILLS_URL}?limit=2").json()
        self.assertEqual(len(page1["rows"]), 2)
        self.assertTrue(page1["has_more"])
        self.assertEqual(page1["next_cursor"], 2)

        page2 = self.api.get(f"{BILLS_URL}?limit=2&cursor={page1['next_cursor']}").json()
        self.assertEqual(len(page2["rows"]), 1)
        self.assertFalse(page2["has_more"])

        self.assertEqual(self.api.get(f"{BILLS_URL}?limit=0").status_code, 400)
        self.assertEqual(self.api.get(f"{BILLS_URL}?cursor=x").status_code, 400)

    def test_detail_keys_dan_allowed_actions(self):
        """Detail DRAFT → key lengkap + ``allowed_actions`` = confirm/cancel."""
        bill = self.make_bill(purchase_order_id=self.po.pk)

        response = self.api.get(detail_url(bill.pk))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), ROW_KEYS | DETAIL_EXTRA_KEYS)
        self.assertEqual(body["allowed_actions"], ["CONFIRMED", "CANCELLED"])
        # Baris ledger sudah di-arm saat create (PENDING) — pola H3.1.
        self.assertEqual(body["odoo_sync_status"], "PENDING")
        self.assertEqual(body["lines"][0]["product_code"], self.product.code)

    def test_detail_404_dan_aksi_tak_dikenal_404(self):
        """Bill tidak ada → 404; aksi tak dikenal → 404."""
        self.assertEqual(self.api.get(detail_url(999999)).status_code, 404)

        bill = self.make_bill(purchase_order_id=self.po.pk)
        unknown = self.api.post(action_url(bill.pk, "kirim"), {}, format="json")
        self.assertEqual(unknown.status_code, 404)
        self.assertIn("tidak dikenal", unknown.json()["detail"])

    def test_anonim_403_list_dan_detail(self):
        """Anonim → 403 untuk list & detail (IsAuthenticated)."""
        bill = self.make_bill(purchase_order_id=self.po.pk)
        anon = APIClient()

        self.assertEqual(anon.get(BILLS_URL).status_code, 403)
        self.assertEqual(anon.get(detail_url(bill.pk)).status_code, 403)
        self.assertEqual(anon.post(BILLS_URL, {}, format="json").status_code, 403)


class VendorBillTransitionTests(VendorBillBase):
    """Transisi ``confirm``/``done``/``cancel`` + ledger + sync_complete/sync_failed."""

    def test_confirm_guard_qty_dan_harga(self):
        """``qty <= 0`` dan ``price_unit < 0`` menahan CONFIRMED (400, bukan push cacat)."""
        bill = self.make_bill(purchase_order_id=self.po.pk)
        bill.lines.all().delete()
        VendorBillLine.objects.create(
            bill=bill, product=self.product, qty=Decimal("0.00"),
            price_unit=Decimal("1000.00"),
        )

        response, enqueue = self.act(bill.pk, "confirm")

        self.assertEqual(response.status_code, 400)
        self.assertIn("Qty baris", response.json()["detail"])
        enqueue.assert_not_called()
        bill.refresh_from_db()
        self.assertEqual(bill.state, "DRAFT")

        VendorBillLine.objects.filter(bill=bill).update(
            qty=Decimal("5.00"), price_unit=Decimal("-1.00")
        )
        negative, _ = self.act(bill.pk, "confirm")
        self.assertEqual(negative.status_code, 400)
        self.assertIn("negatif", negative.json()["detail"])

    def test_confirm_guard_odoo_id_vendor_dan_produk(self):
        """Vendor/produk tanpa ``odoo_id`` → CONFIRMED ditolak dengan pesan jelas."""
        vendor = Partner.objects.create(code="SUP-NO-ODOO", name="Vendor Tanpa Odoo")
        bill = self.make_bill(
            vendor_id=vendor.pk,
            lines=[{"product_id": self.product.pk, "qty": "1", "price_unit": "10",
                    "tax_ids": [self.tax.pk]}],
        )
        no_vendor_odoo, _ = self.act(bill.pk, "confirm")
        self.assertEqual(no_vendor_odoo.status_code, 400)
        self.assertIn("belum punya odoo_id", no_vendor_odoo.json()["detail"])

        product = Product.objects.create(code="PROD-NO-ODOO", name="Produk Tanpa Odoo")
        bill2 = self.make_bill(
            lines=[{"product_id": product.pk, "qty": "1", "price_unit": "10",
                    "tax_ids": [self.tax.pk]}]
        )
        no_product_odoo, _ = self.act(bill2.pk, "confirm")
        self.assertEqual(no_product_odoo.status_code, 400)
        self.assertIn("Produk baris belum punya odoo_id", no_product_odoo.json()["detail"])

    def test_confirm_guard_tax_odoo_id(self):
        """Pajak tanpa ``odoo_id`` menahan CONFIRMED (tidak bisa dikirim ke Odoo)."""
        tax = Tax.objects.create(code="PPN-NO-ODOO", name="PPN Tanpa Odoo", amount=Decimal("11.00"))
        bill = self.make_bill(
            lines=[{"product_id": self.product.pk, "qty": "1", "price_unit": "10",
                    "tax_ids": [tax.pk]}]
        )

        response, _ = self.act(bill.pk, "confirm")

        self.assertEqual(response.status_code, 400)
        self.assertIn("belum punya odoo_id", response.json()["detail"])

    def test_confirm_ok_ledger_dan_enqueue(self):
        """DRAFT→CONFIRMED: state, ledger ``vendor_bill``/``VENDOR_BILL``, enqueue push."""
        bill = self.make_bill(purchase_order_id=self.po.pk, ref="INV-CONF-1")

        response, enqueue = self.act(bill.pk, "confirm")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["state"], "CONFIRMED")
        self.assertTrue(body["queued"])
        self.assertEqual(body["task_id"], "task-vb-confirm")
        self.assertEqual(body["allowed_actions"], ["DONE", "CANCELLED"])

        enqueue.assert_called_once()
        self.assertEqual(enqueue.call_args.kwargs["args"], [bill.pk, body["sync_record_id"], "push"])

        record = SyncRecord.objects.get(pk=body["sync_record_id"])
        self.assertEqual(record.resource, SyncResource.VENDOR_BILL.value)
        self.assertEqual(record.stage, SyncStage.VENDOR_BILL.value)
        self.assertEqual(record.status, SyncStatus.PENDING)
        self.assertTrue(
            AuditLog.objects.filter(action=svc.ACTION_CONFIRM, resource_id=str(bill.pk)).exists()
        )

    def test_confirm_harga_nol_diizinkan(self):
        """Beda dari H3.1: harga 0 **boleh** (tagihan menyusul) — ``>= 0`` saja."""
        bill = self.make_bill(
            lines=[{"product_id": self.product.pk, "qty": "5", "price_unit": "0"}]
        )

        bill, _result = self.confirm_bill_service(bill.pk)

        self.assertEqual(bill.state, "CONFIRMED")
        self.assertEqual(bill.lines.first().line_total, Decimal("0.00"))

    def test_done_transition(self):
        """``CONFIRMED → DONE`` (murni MES); ``DRAFT → DONE`` ditolak."""
        bill = self.make_bill(purchase_order_id=self.po.pk)
        draft_done, _ = self.act(bill.pk, "done")
        self.assertEqual(draft_done.status_code, 400)
        self.assertIn("tidak diizinkan", draft_done.json()["detail"])

        bill, _result = self.confirm_bill_service(bill.pk)
        response, _enqueue = self.act(bill.pk, "done")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], "DONE")
        self.assertEqual(response.json()["allowed_actions"], [])
        self.assertTrue(AuditLog.objects.filter(action=svc.ACTION_DONE).exists())

    def test_cancel_tanpa_dan_dengan_odoo_id(self):
        """``CANCELLED``: tanpa ``odoo_id`` → MES-only; dengan ``odoo_id`` → push cancel."""
        draft = self.make_bill(purchase_order_id=self.po.pk)
        response, enqueue = self.act(draft.pk, "cancel")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], "CANCELLED")
        enqueue.assert_not_called()

        sent = self.make_bill(purchase_order_id=self.po.pk)
        sent, _result = self.confirm_bill_service(sent.pk)
        sent.odoo_id = 4321
        sent.state = "SENT"
        sent.save(update_fields=("odoo_id", "state"))

        cancel_response, cancel_enqueue = self.act(sent.pk, "cancel")
        self.assertEqual(cancel_response.status_code, 200)
        self.assertEqual(cancel_response.json()["state"], "CANCELLED")
        self.assertTrue(cancel_response.json()["queued"])
        self.assertEqual(
            cancel_enqueue.call_args.kwargs["args"],
            [sent.pk, cancel_response.json()["sync_record_id"], "cancel"],
        )

    def test_sync_complete_confirmed_ke_sent(self):
        """``sync_complete`` (task) → state SENT + ``odoo_id`` + ledger SENT."""
        bill = self.make_bill(purchase_order_id=self.po.pk)
        bill, result = self.confirm_bill_service(bill.pk)

        completed = svc.sync_complete(bill, "555")

        bill.refresh_from_db()
        self.assertEqual(bill.state, "SENT")
        self.assertEqual(bill.odoo_id, 555)
        self.assertEqual(completed.sync_record_id, result.sync_record_id)

        record = SyncRecord.objects.get(pk=completed.sync_record_id)
        self.assertEqual(record.status, SyncStatus.SENT)
        self.assertEqual(record.erp_id, "555")
        self.assertTrue(AuditLog.objects.filter(action=svc.ACTION_SYNC_COMPLETE).exists())

    def test_sync_failed_tetap_confirmed(self):
        """Push gagal → ``SyncRecord`` FAILED + audit; **state bill tetap CONFIRMED**."""
        bill = self.make_bill(purchase_order_id=self.po.pk)
        bill, result = self.confirm_bill_service(bill.pk)

        failed = svc.sync_failed(bill, "Odoo menolak: vendor tidak ada")

        bill.refresh_from_db()
        self.assertEqual(bill.state, "CONFIRMED")
        self.assertIsNone(bill.odoo_id)
        self.assertEqual(failed.error, "Odoo menolak: vendor tidak ada")

        record = SyncRecord.objects.get(pk=result.sync_record_id)
        self.assertEqual(record.status, SyncStatus.FAILED)
        self.assertIn("vendor tidak ada", record.last_error)
        self.assertTrue(AuditLog.objects.filter(action=svc.ACTION_SYNC_FAILED).exists())


class VendorBillTaskTests(VendorBillBase):
    """Task ``erp_sync.push_vendor_bill``: payload, sukses/gagal, cancel, idempoten."""

    def _confirmed_bill(self):
        """Bill CONFIRMED + SyncRecord PENDING (enqueue di-patch) → ``(bill, record)``."""
        bill = self.make_bill(purchase_order_id=self.po.pk, ref="INV-TASK-1")
        bill, result = self.confirm_bill_service(bill.pk)
        return bill, SyncRecord.objects.get(pk=result.sync_record_id)

    def test_task_push_sukses_dan_idempoten(self):
        """Sukses → SENT + ``odoo_id`` + payload ``in_invoice``; push ulang diabaikan."""
        bill, record = self._confirmed_bill()

        # Baris tanpa `product.odoo_id` DILEWATI dari payload (guard CONFIRMED sudah ada).
        product = Product.objects.create(code="PROD-NO-SYNC", name="Produk Belum Sync")
        VendorBillLine.objects.create(
            bill=bill, product=product, qty=Decimal("1.00"), price_unit=Decimal("5.00")
        )

        adapter = FakeAdapter(ok=True, erp_id="888")

        with patch(ADAPTER, return_value=adapter):
            outcome = push_vendor_bill.apply(args=[bill.pk, record.pk, "push"]).get()

        self.assertEqual(outcome["status"], "sent")
        self.assertEqual(outcome["erp_id"], "888")
        self.assertEqual(outcome["state"], "SENT")
        self.assertTrue(adapter.closed)

        bill.refresh_from_db()
        self.assertEqual(bill.state, "SENT")
        self.assertEqual(bill.odoo_id, 888)

        payload = adapter.pushed[0]
        self.assertEqual(payload["partner_odoo_id"], self.vendor.odoo_id)
        self.assertEqual(payload["ref"], "INV-TASK-1")
        self.assertEqual(payload["invoice_date"], "2026-10-13")
        self.assertEqual(len(payload["lines"]), 1)
        line = payload["lines"][0]
        self.assertEqual(line["product_odoo_id"], self.product.odoo_id)
        self.assertEqual(line["price_unit"], "1500.00")
        self.assertEqual(line["tax_odoo_ids"], [self.tax.odoo_id])

        record.refresh_from_db()
        self.assertEqual(record.status, SyncStatus.SENT)
        self.assertEqual(record.erp_id, "888")

        # Push ulang dengan payload sama → status sync sudah SENT ⇒ diabaikan.
        with patch(ADAPTER, return_value=FakeAdapter(ok=True, erp_id="999")):
            again = push_vendor_bill.apply(args=[bill.pk, record.pk, "push"]).get()
        self.assertEqual(again["status"], "duplicate-ignored")

    def test_task_push_gagal_tetap_confirmed(self):
        """Adapter ``ok=False`` → task balas failed; bill tetap CONFIRMED + ledger FAILED."""
        bill, record = self._confirmed_bill()
        adapter = FakeAdapter(ok=False, error="Odoo: journal tidak ditemukan")

        with patch(ADAPTER, return_value=adapter):
            outcome = push_vendor_bill.apply(args=[bill.pk, record.pk, "push"]).get()

        self.assertEqual(outcome["status"], "failed")
        self.assertIn("journal", outcome["error"])

        bill.refresh_from_db()
        self.assertEqual(bill.state, "CONFIRMED")
        self.assertIsNone(bill.odoo_id)

        record.refresh_from_db()
        self.assertEqual(record.status, SyncStatus.FAILED)
        self.assertIn("journal", record.last_error)

    def test_task_cancel_dan_not_found(self):
        """``action="cancel"`` memanggil ``cancel_vendor_bill``; id tak ada → not-found."""
        bill, record = self._confirmed_bill()
        bill.odoo_id = 4321
        bill.state = "SENT"
        bill.save(update_fields=("odoo_id", "state"))

        adapter = FakeAdapter(ok=True, erp_id="4321")
        with patch(ADAPTER, return_value=adapter):
            outcome = push_vendor_bill.apply(args=[bill.pk, record.pk, "cancel"]).get()

        self.assertEqual(outcome["status"], "sent")
        self.assertEqual(adapter.cancelled, ["4321"])
        self.assertEqual(adapter.pushed, [])

        self.assertEqual(push_vendor_bill.apply(args=[999999]).get()["status"], "not-found")

    def test_adapter_odoo_payload_dan_guard(self):
        """Adapter Odoo: ``move_type=in_invoice`` + ``tax_ids`` m2m + guard payload."""
        client = MagicMock()
        client.execute_kw.return_value = [42]
        adapter = OdooAdapter(client=client)

        response = adapter.push_vendor_bill(
            {
                "ref": "INV-VENDOR-001",
                "partner_odoo_id": 14,
                "invoice_date": "2026-10-13",
                "due_date": "2026-11-13",
                "lines": [
                    {
                        "product_odoo_id": 34,
                        "quantity": "10.00",
                        "price_unit": "1500.00",
                        "tax_odoo_ids": [20],
                    }
                ],
            }
        )

        self.assertTrue(response.ok, response.error)
        self.assertEqual(response.erp_id, "42")
        self.assertEqual(response.stage, STAGE_VENDOR_BILL)

        values = client.execute_kw.call_args.args[2][0][0]
        self.assertEqual(values["move_type"], "in_invoice")
        self.assertEqual(values["partner_id"], 14)
        self.assertEqual(values["ref"], "INV-VENDOR-001")
        self.assertEqual(values["invoice_date_due"], "2026-11-13")
        for absent in ("journal_id", "currency_id", "date", "invoice_origin"):
            self.assertNotIn(absent, values)

        line = values["invoice_line_ids"][0][2]
        self.assertEqual(line["tax_ids"], [(6, 0, [20])])
        self.assertNotIn("account_id", line)
        self.assertNotIn("product_uom_id", line)
        self.assertNotIn("purchase_line_id", line)

        missing = adapter.push_vendor_bill({"ref": "INV-VENDOR-001"})
        self.assertFalse(missing.ok)
        self.assertIn("field wajib", missing.error)

        zero_qty = adapter.push_vendor_bill(
            {
                "ref": "INV-1",
                "partner_odoo_id": 14,
                "lines": [{"product_odoo_id": 34, "quantity": 0, "price_unit": "10"}],
            }
        )
        self.assertFalse(zero_qty.ok)
        self.assertIn("quantity", zero_qty.error)


class VendorBillNonBreakingTests(VendorBillBase):
    """Non-breaking: I6/material_readiness + H2.2 + H3.1 + monitoring F15 tetap hijau."""

    def test_i6_dan_h3_1_tidak_tersentuh(self):
        """I6 `fetch_vendor_bills`/`VendorBillStatus` & endpoint H3.1 tetap utuh."""
        from apps_industry.garment.models import MaterialReadiness
        from integrations.erp_sync.transport.odoo_transport import (
            VENDOR_BILL_FIELDS,
            OdooTransport,
        )

        self.assertTrue(hasattr(OdooTransport, "fetch_vendor_bills"))
        self.assertIn("payment_state", VENDOR_BILL_FIELDS)
        self.assertEqual(
            [value for value, _label in MaterialReadiness.VendorBillStatus.choices],
            ["NONE", "DRAFT", "POSTED", "PAID"],
        )

        # Endpoint H3.1 + F15 monitoring tetap melayani (anon 403, admin 200).
        self.assertEqual(self.api.get("/api/v1/finance/customer-invoices/").status_code, 200)
        self.assertEqual(self.api.get("/api/v1/finance/invoices/").status_code, 200)
        self.assertEqual(APIClient().get("/api/v1/finance/invoices/").status_code, 403)

        # Ledger customer invoice TIDAK memakai stage/resource H3.2.
        self.assertEqual(SyncResource.CUSTOMER_INVOICE.value, "customer_invoice")
        self.assertEqual(SyncStage.INVOICE.value, "INVOICE")

    def test_h2_2_purchase_orders_tetap_hijau(self):
        """H2.2 `|/garmen/purchase-orders/` tetap melayani + bill tidak mengubah relasinya."""
        self.assertEqual(self.api.get("/api/v1/garmen/purchase-orders/").status_code, 200)

        self.make_bill(purchase_order_id=self.po.pk)
        self.make_bill(purchase_order_id=self.po.pk)

        # Satu PO boleh >1 bill (termin/partial) — tanpa unique, PO tetap utuh.
        self.assertEqual(self.po.vendor_bills.count(), 2)
        self.assertEqual(self.po.lines.count(), 1)









