"""Test CRUD Customer Invoice MES — ``/api/v1/finance/customer-invoices/`` (H3.1).

Cakupan: create (auto-fill dari `OrderLine` **dan** ``lines[]`` eksplisit), validasi
**400** (order/tanggal/qty/harga/pajak), update & delete **DRAFT-only**, list
(pagination/filter/search), detail, izin (anon **403**, role selain ADMIN/OWNER
**403**), transisi ``confirm`` (guard harga > 0 + ``odoo_id`` customer/produk/pajak)
→ ``done`` → ``cancel``, ledger ``SyncRecord`` (resource **`customer_invoice`**,
stage **`INVOICE``** yang di-reuse dari I5) + ``AuditLog``, task
``erp_sync.push_customer_invoice`` (sukses → SENT + ``odoo_id``; gagal → SyncRecord
FAILED tapi state tetap CONFIRMED), serta **non-breaking**: I5 (resource `order`) +
F10/F15 monitoring (`/finance/invoices/`, amplop `has_next`) + H2.1 + H3.6.

Catatan:
  * enqueue task di-patch (pola H1.2/H2.1/H2.2) supaya test tidak menyentuh broker;
  * adapter di-patch untuk menguji payload push nyata (tanpa Odoo);
  * ``ERP_ADAPTER=null`` dipakai untuk jalur no-op (erp_id ``NULL-<uuid>``).

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_customer_invoices_crud.py -q
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps_industry.garment.models import CustomerInvoice, Order, OrderLine
from apps_industry.garment.services import customer_invoice_services as svc
from core.audit.models import AuditLog
from core.auth.models import Role, User
from integrations.erp_sync.adapters.base import ERPResponse
from integrations.erp_sync.adapters.odoo import STAGE_INVOICE, OdooAdapter
from integrations.erp_sync.models import SyncRecord, SyncResource, SyncStage, SyncStatus
from integrations.erp_sync.services.invoice_sync import InvoiceSyncService
from integrations.erp_sync.tasks_customer_invoice_push import push_customer_invoice
from master.models import Partner, Product, Tax, UoM

INVOICES_URL = "/api/v1/finance/customer-invoices/"
ENVELOPE_KEYS = {"rows", "total_count", "has_more", "next_cursor"}
ROW_KEYS = {
    "id",
    "code",
    "order_id",
    "order_no",
    "customer_id",
    "customer_name",
    "customer_code",
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
ENQUEUE = "integrations.erp_sync.tasks_customer_invoice_push.push_customer_invoice.apply_async"
#: Path patch adapter di module task (menguji payload & jalur sukses/gagal).
ADAPTER = "integrations.erp_sync.tasks_customer_invoice_push.get_adapter"


def detail_url(pk: int) -> str:
    """URL detail invoice."""
    return f"{INVOICES_URL}{pk}/"


def action_url(pk: int, action: str) -> str:
    """URL aksi transisi invoice."""
    return f"{INVOICES_URL}{pk}/{action}/"


class FakeAdapter:
    """Adapter palsu: mencatat payload push/cancel tanpa menyentuh Odoo."""

    def __init__(self, ok: bool = True, erp_id: str = "777", error: str | None = None) -> None:
        """Simpan perilaku yang diinginkan + daftar panggilan."""
        self.ok = ok
        self.erp_id = erp_id
        self.error = error
        self.pushed: list[dict] = []
        self.cancelled: list[str] = []
        self.closed = False

    def push_customer_invoice(self, payload: dict) -> ERPResponse:
        """Catat payload push & balas sesuai konfigurasi."""
        self.pushed.append(dict(payload))

        return ERPResponse(
            ok=self.ok,
            erp_id=self.erp_id if self.ok else None,
            raw={"payload": dict(payload)},
            error=None if self.ok else (self.error or "push gagal"),
            stage=STAGE_INVOICE,
            ref=str(payload.get("ref") or ""),
        )

    def cancel_customer_invoice(self, erp_id: str) -> ERPResponse:
        """Catat erp_id yang dibatalkan & balas sesuai konfigurasi."""
        self.cancelled.append(str(erp_id))

        return ERPResponse(
            ok=self.ok,
            erp_id=self.erp_id if self.ok else None,
            raw={"cancelled": erp_id},
            error=None if self.ok else (self.error or "cancel gagal"),
            stage=STAGE_INVOICE,
            ref=str(erp_id),
        )

    def close(self) -> None:
        """Tandai adapter ditutup (task wajib menutup di ``finally``)."""
        self.closed = True



class CustomerInvoiceBase(TestCase):
    """Fixture bersama: user (admin/operator), master (customer/produk/pajak), order."""

    @classmethod
    def setUpTestData(cls):
        """Master data + order dengan satu baris berharga > 0 + pajak."""
        cls.admin = User.objects.create_user(
            username="admin-inv",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.ADMIN),
        )
        cls.operator = User.objects.create_user(
            username="op-inv",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.OPERATOR),
        )

        cls.uom = UoM.objects.create(
            code="PCS-INV", name="Pieces", category="Unit", factor=1, rounding=0.01
        )
        cls.customer = Partner.objects.create(code="CUST-INV", name="PT Buyer Invoice", odoo_id=10)
        cls.product = Product.objects.create(
            code="KAOS-INV", name="Kaos Invoice", odoo_id=34, sale_price=Decimal("4000.00")
        )
        cls.tax = Tax.objects.create(
            code="PPN11-INV", name="PPN 11%", amount=Decimal("11.00"), odoo_id=19
        )

        cls.order = Order.objects.create(
            code="SO-2026-9001", customer=cls.customer, order_type="EXPORT"
        )
        cls.order_line = OrderLine.objects.create(
            order=cls.order, product=cls.product, qty=5, price_unit=Decimal("4000.00")
        )
        cls.order_line.tax_ids.set([cls.tax])

    def setUp(self):
        """Klien admin (utama) + operator (uji 403)."""
        self.api = APIClient()
        self.api.force_authenticate(self.admin)
        self.operator_api = APIClient()
        self.operator_api.force_authenticate(self.operator)

    # ------------------------------------------------------------------ helper
    def post_invoice(self, body: dict, client=None):
        """POST invoice (enqueue di-patch) → ``(response, mock)``."""
        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-inv-1")) as enqueue:
            response = (client or self.api).post(INVOICES_URL, body, format="json")

        return response, enqueue

    def put_invoice(self, pk: int, body: dict, client=None):
        """PUT invoice (enqueue di-patch) → ``(response, mock)``."""
        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-inv-2")) as enqueue:
            response = (client or self.api).put(detail_url(pk), body, format="json")

        return response, enqueue

    def delete_invoice(self, pk: int, client=None):
        """DELETE invoice (enqueue di-patch) → ``(response, mock)``."""
        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-inv-3")) as enqueue:
            response = (client or self.api).delete(detail_url(pk))

        return response, enqueue

    def act(self, pk: int, action: str, client=None):
        """POST aksi transisi (enqueue di-patch) → ``(response, mock)``."""
        with patch(ENQUEUE, return_value=SimpleNamespace(id=f"task-inv-{action}")) as enqueue:
            response = (client or self.api).post(action_url(pk, action), {}, format="json")

        return response, enqueue

    def create_invoice_service(self, body: dict):
        """Buat invoice lewat service (test transisi) → ``(invoice, result)``."""
        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-inv-seed")):
            result = svc.create_invoice(body)

        self.assertIsNone(result.error, result.error)
        return result.invoice, result

    def make_invoice(self, **overrides):
        """Buat invoice DRAFT lewat service dengan body standar."""
        body = {"order_id": self.order.pk, "invoice_date": "2026-10-12"}
        body.update(overrides)
        invoice, _result = self.create_invoice_service(body)

        return invoice

    def confirm_invoice_service(self, pk: int):
        """CONFIRM invoice lewat service (enqueue di-patch) → ``(invoice, result)``."""
        invoice = CustomerInvoice.objects.get(pk=pk)
        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-inv-confirm")):
            result = svc.confirm_invoice(invoice)

        self.assertIsNone(result.error, result.error)
        invoice.refresh_from_db()
        return invoice, result


class CustomerInvoiceCrudTests(CustomerInvoiceBase):
    """CRUD + transisi invoice lewat API (create/list/detail/update/delete/aksi)."""

    # ---------------------------------------------------------------- create
    def test_create_autofill_dari_order_line(self):
        """POST tanpa ``lines`` → auto-fill dari `OrderLine` (qty × harga + pajak)."""
        response, _enqueue = self.post_invoice(
            {"order_id": self.order.pk, "invoice_date": "2026-10-12"}
        )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertTrue(body["code"].startswith("INV-"))
        self.assertEqual(body["state"], "DRAFT")
        self.assertEqual(body["order_id"], self.order.pk)
        self.assertEqual(body["customer_id"], self.customer.pk)
        self.assertEqual(body["lines_count"], 1)
        self.assertEqual(body["amount_total"], "20000.00")
        self.assertFalse(body["queued"])
        self.assertIsNone(body["odoo_id"])

        line = body["lines"][0]
        self.assertEqual(line["product_id"], self.product.pk)
        self.assertEqual(line["qty"], "5.00")
        self.assertEqual(line["price_unit"], "4000.00")
        self.assertEqual(line["subtotal"], "20000.00")
        self.assertEqual(line["tax_ids"], [self.tax.pk])
        self.assertEqual(line["tax_odoo_ids"], [19])
        self.assertEqual(line["order_line_id"], self.order_line.pk)

        record = SyncRecord.objects.get(pk=body["sync_record_id"])
        self.assertEqual(record.resource, SyncResource.CUSTOMER_INVOICE.value)
        self.assertEqual(record.stage, SyncStage.INVOICE.value)
        self.assertEqual(record.status, SyncStatus.PENDING)
        self.assertTrue(
            AuditLog.objects.filter(action=svc.ACTION_CREATE, resource_id=str(body["id"])).exists()
        )

    def test_create_dengan_lines_eksplisit(self):
        """POST dengan ``lines`` eksplisit → baris dipakai apa adanya (bukan auto-fill)."""
        response, _enqueue = self.post_invoice(
            {
                "order_id": self.order.pk,
                "invoice_date": "2026-10-12",
                "notes": "DP 50%",
                "lines": [
                    {
                        "product_id": self.product.pk,
                        "qty": "2",
                        "price_unit": "1500.50",
                        "tax_ids": [self.tax.pk],
                    }
                ],
            }
        )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["notes"], "DP 50%")
        self.assertEqual(body["amount_total"], "3001.00")
        self.assertEqual(body["lines"][0]["subtotal"], "3001.00")

    def test_create_duplikat_order_memberi_warning_bukan_400(self):
        """Order yang sama boleh >1 invoice (termin/DP) → 201 + ``duplicate_warning``."""
        self.make_invoice()

        response, _enqueue = self.post_invoice(
            {"order_id": self.order.pk, "invoice_date": "2026-10-13"}
        )

        self.assertEqual(response.status_code, 201)
        self.assertIn("invoice aktif", response.json()["duplicate_warning"])
        self.assertEqual(CustomerInvoice.objects.count(), 2)

    def test_create_tanpa_order_400(self):
        """``order_id`` kosong → 400 dan tidak ada baris tersimpan."""
        response, enqueue = self.post_invoice({"invoice_date": "2026-10-12"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("order_id", response.json()["detail"])
        enqueue.assert_not_called()
        self.assertEqual(CustomerInvoice.objects.count(), 0)

    def test_create_tanpa_invoice_date_400(self):
        """``invoice_date`` wajib → 400."""
        response, _enqueue = self.post_invoice({"order_id": self.order.pk})

        self.assertEqual(response.status_code, 400)
        self.assertIn("invoice_date", response.json()["detail"])

    def test_create_order_tanpa_baris_400(self):
        """Order tanpa `OrderLine` + tanpa ``lines`` → 400 (jelas, bukan invoice kosong)."""
        order = Order.objects.create(code="SO-2026-9002", customer=self.customer)

        response, _enqueue = self.post_invoice(
            {"order_id": order.pk, "invoice_date": "2026-10-12"}
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("tidak punya baris", response.json()["detail"])


    def test_create_qty_dan_harga_tidak_valid_400(self):
        """``qty <= 0``, harga negatif, atau produk tidak ada → 400."""
        base = {"order_id": self.order.pk, "invoice_date": "2026-10-12"}

        qty_zero, _ = self.post_invoice(
            base | {"lines": [{"product_id": self.product.pk, "qty": 0, "price_unit": "10"}]}
        )
        self.assertEqual(qty_zero.status_code, 400)
        self.assertIn("qty", qty_zero.json()["detail"])

        negative, _ = self.post_invoice(
            base | {"lines": [{"product_id": self.product.pk, "qty": 1, "price_unit": "-1"}]}
        )
        self.assertEqual(negative.status_code, 400)
        self.assertIn("negatif", negative.json()["detail"])

        missing, _ = self.post_invoice(
            base | {"lines": [{"product_id": 999999, "qty": 1, "price_unit": "10"}]}
        )
        self.assertEqual(missing.status_code, 400)
        self.assertIn("tidak ditemukan", missing.json()["detail"])

    def test_create_pajak_tidak_dikenal_400(self):
        """``tax_ids`` bukan array / id pajak tidak ada → 400."""
        base = {"order_id": self.order.pk, "invoice_date": "2026-10-12"}
        not_array, _ = self.post_invoice(
            base
            | {
                "lines": [
                    {
                        "product_id": self.product.pk,
                        "qty": 1,
                        "price_unit": "10",
                        "tax_ids": "PPN11-INV",
                    }
                ]
            }
        )
        self.assertEqual(not_array.status_code, 400)
        self.assertIn("array", not_array.json()["detail"])

        unknown, _ = self.post_invoice(
            base
            | {
                "lines": [
                    {
                        "product_id": self.product.pk,
                        "qty": 1,
                        "price_unit": "10",
                        "tax_ids": [999999],
                    }
                ]
            }
        )
        self.assertEqual(unknown.status_code, 400)
        self.assertIn("tidak ditemukan", unknown.json()["detail"])

    # ------------------------------------------------------------------- read
    def test_list_pagination_dan_envelope(self):
        """ListPage: ``limit``/``cursor`` + ``has_more``/``next_cursor`` + kolom pinned."""
        for _ in range(3):
            self.make_invoice()

        response = self.api.get(INVOICES_URL, {"limit": 2})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), ENVELOPE_KEYS)
        self.assertEqual(body["total_count"], 3)
        self.assertTrue(body["has_more"])
        self.assertEqual(body["next_cursor"], 2)
        self.assertEqual(set(body["rows"][0]), ROW_KEYS)

        second = self.api.get(INVOICES_URL, {"limit": 2, "cursor": 2}).json()
        self.assertEqual(len(second["rows"]), 1)
        self.assertFalse(second["has_more"])

    def test_list_filter_state_customer_order_dan_search(self):
        """Filter ``?state=``, ``?customer_id=``, ``?order_id=``, ``?search=`` + nilai salah."""
        invoice = self.make_invoice()

        self.assertEqual(self.api.get(INVOICES_URL, {"state": "DRAFT"}).json()["total_count"], 1)
        self.assertEqual(self.api.get(INVOICES_URL, {"state": "SENT"}).json()["total_count"], 0)
        self.assertEqual(
            self.api.get(INVOICES_URL, {"customer_id": self.customer.pk}).json()["total_count"], 1
        )
        by_order = self.api.get(INVOICES_URL, {"order_id": self.order.pk}).json()
        self.assertEqual(by_order["rows"][0]["id"], invoice.pk)
        self.assertEqual(self.api.get(INVOICES_URL, {"search": "buyer"}).json()["total_count"], 1)

        self.assertEqual(self.api.get(INVOICES_URL, {"state": "NGACO"}).status_code, 400)
        self.assertEqual(self.api.get(INVOICES_URL, {"customer_id": "abc"}).status_code, 400)

    def test_detail_dan_missing_404(self):
        """Detail invoice + 404 id yang tidak ada."""
        invoice = self.make_invoice()

        response = self.api.get(detail_url(invoice.pk))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), ROW_KEYS | DETAIL_EXTRA_KEYS)
        self.assertEqual(body["allowed_actions"], ["CONFIRMED", "CANCELLED"])
        self.assertEqual(body["odoo_sync_status"], SyncStatus.PENDING)
        self.assertEqual(len(body["lines"]), 1)

        self.assertEqual(self.api.get(detail_url(999999)).status_code, 404)


    # ----------------------------------------------------------- update/delete
    def test_update_draft_ok_dan_replace_lines(self):
        """PUT DRAFT: header berubah + ``lines`` mengganti seluruh baris + audit."""
        invoice = self.make_invoice()

        response, _enqueue = self.put_invoice(
            invoice.pk,
            {
                "due_date": "2026-11-12",
                "lines": [
                    {
                        "product_id": self.product.pk,
                        "qty": "1",
                        "price_unit": "900.00",
                        "tax_ids": [],
                    }
                ],
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["due_date"], "2026-11-12")
        self.assertEqual(body["lines_count"], 1)
        self.assertEqual(body["amount_total"], "900.00")
        self.assertEqual(body["lines"][0]["tax_ids"], [])
        self.assertTrue(
            AuditLog.objects.filter(
                action=svc.ACTION_UPDATE, resource_id=str(invoice.pk)
            ).exists()
        )

    def test_update_dan_delete_setelah_confirm_400(self):
        """Ubah/hapus hanya boleh saat DRAFT → 400 setelah CONFIRMED."""
        invoice = self.make_invoice()
        self.act(invoice.pk, "confirm")

        put_response, _ = self.put_invoice(invoice.pk, {"notes": "ubah"})
        self.assertEqual(put_response.status_code, 400)
        self.assertIn("DRAFT", put_response.json()["detail"])

        delete_response, _ = self.delete_invoice(invoice.pk)
        self.assertEqual(delete_response.status_code, 400)
        self.assertTrue(CustomerInvoice.objects.filter(pk=invoice.pk).exists())

    def test_delete_draft_ok(self):
        """DELETE DRAFT: invoice terhapus + audit delete."""
        invoice = self.make_invoice()

        response, _enqueue = self.delete_invoice(invoice.pk)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["deleted"])
        self.assertFalse(CustomerInvoice.objects.filter(pk=invoice.pk).exists())
        self.assertTrue(
            AuditLog.objects.filter(
                action=svc.ACTION_DELETE, resource_id=str(invoice.pk)
            ).exists()
        )

    # ----------------------------------------------------------------- transisi
    def test_confirm_ok_pakai_sync_record_dan_enqueue(self):
        """POST confirm → CONFIRMED + ledger PENDING (`customer_invoice`/`INVOICE`) + task."""
        invoice = self.make_invoice()

        response, enqueue = self.act(invoice.pk, "confirm")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["state"], "CONFIRMED")
        self.assertEqual(body["allowed_actions"], ["SENT", "DONE", "CANCELLED"])
        self.assertTrue(body["queued"])
        enqueue.assert_called_once()

        record = SyncRecord.objects.get(
            resource=SyncResource.CUSTOMER_INVOICE.value, resource_id=str(invoice.pk)
        )
        self.assertEqual(record.stage, SyncStage.INVOICE.value)
        self.assertEqual(record.status, SyncStatus.PENDING)
        self.assertEqual(record.payload["action"], "push")
        self.assertTrue(
            AuditLog.objects.filter(
                action=svc.ACTION_CONFIRM, resource_id=str(invoice.pk)
            ).exists()
        )

    def test_confirm_guard_harga_nol_400(self):
        """Baris berharga 0 → 400 (§5) dan state tetap DRAFT."""
        invoice = self.make_invoice(
            lines=[{"product_id": self.product.pk, "qty": 1, "price_unit": "0"}]
        )

        response, enqueue = self.act(invoice.pk, "confirm")

        self.assertEqual(response.status_code, 400)
        self.assertIn("harus > 0", response.json()["detail"])
        enqueue.assert_not_called()
        invoice.refresh_from_db()
        self.assertEqual(invoice.state, "DRAFT")

    def test_confirm_guard_customer_tanpa_odoo_id_400(self):
        """Customer tanpa ``odoo_id`` → 400 dengan pesan sync partner."""
        customer = Partner.objects.create(code="CUST-NOODOO", name="Belum Sync")
        order = Order.objects.create(code="SO-2026-9003", customer=customer)
        OrderLine.objects.create(
            order=order, product=self.product, qty=1, price_unit=Decimal("10.00")
        )

        invoice, _result = self.create_invoice_service(
            {"order_id": order.pk, "invoice_date": "2026-10-12"}
        )
        response, _enqueue = self.act(invoice.pk, "confirm")

        self.assertEqual(response.status_code, 400)
        self.assertIn("odoo_id", response.json()["detail"])


    def test_confirm_guard_produk_tanpa_odoo_id_400(self):
        """Produk baris tanpa ``odoo_id`` → 400 (sync produk dulu)."""
        product = Product.objects.create(code="KAOS-NOODOO", name="Belum Sync")

        invoice, _result = self.create_invoice_service(
            {
                "order_id": self.order.pk,
                "invoice_date": "2026-10-12",
                "lines": [{"product_id": product.pk, "qty": 1, "price_unit": "10"}],
            }
        )
        response, _enqueue = self.act(invoice.pk, "confirm")

        self.assertEqual(response.status_code, 400)
        self.assertIn("odoo_id", response.json()["detail"])

    def test_confirm_guard_pajak_tanpa_odoo_id_400(self):
        """Pajak baris tanpa ``odoo_id`` → 400 (sync master pajak dulu)."""
        tax = Tax.objects.create(code="PPN-BARU", name="PPN Baru", amount=Decimal("12.00"))

        invoice, _result = self.create_invoice_service(
            {
                "order_id": self.order.pk,
                "invoice_date": "2026-10-12",
                "lines": [
                    {
                        "product_id": self.product.pk,
                        "qty": 1,
                        "price_unit": "10",
                        "tax_ids": [tax.pk],
                    }
                ],
            }
        )
        response, _enqueue = self.act(invoice.pk, "confirm")

        self.assertEqual(response.status_code, 400)
        self.assertIn("odoo_id", response.json()["detail"])

    def test_confirm_dua_kali_400(self):
        """Transisi ganda (CONFIRMED → CONFIRMED) → 400."""
        invoice = self.make_invoice()
        self.act(invoice.pk, "confirm")

        response, _enqueue = self.act(invoice.pk, "confirm")

        self.assertEqual(response.status_code, 400)
        self.assertIn("tidak diizinkan", response.json()["detail"])

    def test_done_dari_sent_ok_dan_dari_draft_400(self):
        """``done`` hanya dari CONFIRMED/SENT (bukan DRAFT)."""
        draft = self.make_invoice()

        blocked, _ = self.act(draft.pk, "done")
        self.assertEqual(blocked.status_code, 400)

        confirmed = self.make_invoice()
        self.act(confirmed.pk, "confirm")
        ok, _enqueue = self.act(confirmed.pk, "done")

        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["state"], "DONE")
        self.assertEqual(ok.json()["allowed_actions"], [])

    def test_cancel_draft_tanpa_odoo_id_tidak_enqueue(self):
        """``cancel`` dari DRAFT (tanpa ``odoo_id``) → CANCELLED, tanpa push cancel."""
        invoice = self.make_invoice()

        response, enqueue = self.act(invoice.pk, "cancel")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], "CANCELLED")
        self.assertIsNone(response.json()["sync_record_id"])
        enqueue.assert_not_called()
        self.assertTrue(
            AuditLog.objects.filter(
                action=svc.ACTION_CANCEL, resource_id=str(invoice.pk)
            ).exists()
        )


class CustomerInvoiceTaskTests(CustomerInvoiceBase):
    """Task ``erp_sync.push_customer_invoice``: sukses/gagal/cancel/no-op + payload."""

    def test_push_sukses_set_sent_dan_odoo_id(self):
        """Adapter sukses → state SENT + ``odoo_id`` + ``SyncRecord`` SENT + audit."""
        invoice = self.make_invoice()
        invoice, result = self.confirm_invoice_service(invoice.pk)
        adapter = FakeAdapter(ok=True, erp_id="777")

        with patch(ADAPTER, return_value=adapter):
            outcome = push_customer_invoice.apply(
                args=[invoice.pk, result.sync_record_id, "push"]
            ).get()

        self.assertEqual(outcome["status"], "sent")
        self.assertEqual(outcome["erp_id"], "777")

        invoice.refresh_from_db()
        self.assertEqual(invoice.state, "SENT")
        self.assertEqual(invoice.odoo_id, 777)

        record = SyncRecord.objects.get(pk=result.sync_record_id)
        self.assertEqual(record.status, SyncStatus.SENT)
        self.assertEqual(record.erp_id, "777")
        self.assertTrue(adapter.closed)
        self.assertTrue(
            AuditLog.objects.filter(
                action=svc.ACTION_SYNC_COMPLETE, resource_id=str(invoice.pk)
            ).exists()
        )

    def test_push_gagal_pertahankan_state_confirmed(self):
        """Adapter gagal → ``SyncRecord`` FAILED, **state invoice tetap CONFIRMED**."""
        invoice = self.make_invoice()
        invoice, result = self.confirm_invoice_service(invoice.pk)
        adapter = FakeAdapter(ok=False, error="partner tidak ditemukan di Odoo")

        with patch(ADAPTER, return_value=adapter):
            outcome = push_customer_invoice.apply(
                args=[invoice.pk, result.sync_record_id, "push"]
            ).get()

        self.assertEqual(outcome["status"], "failed")
        self.assertIn("partner tidak ditemukan", outcome["error"])

        invoice.refresh_from_db()
        self.assertEqual(invoice.state, "CONFIRMED")
        self.assertIsNone(invoice.odoo_id)

        record = SyncRecord.objects.get(pk=result.sync_record_id)
        self.assertEqual(record.status, SyncStatus.FAILED)
        self.assertIn("partner tidak ditemukan", record.last_error)
        self.assertTrue(
            AuditLog.objects.filter(
                action=svc.ACTION_SYNC_FAILED, resource_id=str(invoice.pk)
            ).exists()
        )


    @override_settings(ERP_ADAPTER="null")
    def test_push_noop_adapter_null_still_sent(self):
        """``ERP_ADAPTER=null`` → push disimulasikan, state SENT tanpa ``odoo_id``."""
        invoice = self.make_invoice()
        invoice, result = self.confirm_invoice_service(invoice.pk)

        outcome = push_customer_invoice.apply(
            args=[invoice.pk, result.sync_record_id, "push"]
        ).get()

        self.assertEqual(outcome["status"], "sent")
        self.assertTrue(str(outcome["erp_id"]).startswith("NULL-"))

        invoice.refresh_from_db()
        self.assertEqual(invoice.state, "SENT")
        self.assertIsNone(invoice.odoo_id)  # bukan digit → tidak disimpan sebagai odoo_id

    def test_payload_push_memuat_harga_pajak_tanpa_journal(self):
        """Payload push: harga & pajak NYATA, tanpa ``journal_id``/``account_id``."""
        invoice = self.make_invoice()
        invoice, result = self.confirm_invoice_service(invoice.pk)
        adapter = FakeAdapter(ok=True, erp_id="321")

        with patch(ADAPTER, return_value=adapter):
            push_customer_invoice.apply(args=[invoice.pk, result.sync_record_id, "push"]).get()

        payload = adapter.pushed[0]
        self.assertEqual(payload["ref"], invoice.code)
        self.assertEqual(payload["partner_odoo_id"], 10)
        self.assertEqual(payload["invoice_date"], "2026-10-12")
        self.assertNotIn("journal_id", payload)
        self.assertNotIn("currency_id", payload)

        line = payload["lines"][0]
        self.assertEqual(
            set(line), {"product_odoo_id", "quantity", "price_unit", "name", "tax_odoo_ids"}
        )
        self.assertEqual(line["product_odoo_id"], 34)
        self.assertEqual(line["quantity"], "5.00")
        self.assertEqual(line["price_unit"], "4000.00")
        self.assertEqual(line["tax_odoo_ids"], [19])
        self.assertNotIn("account_id", line)

    def test_push_ulang_payload_sama_duplicate_ignored(self):
        """Percobaan kedua dengan payload identik → ``duplicate-ignored``."""
        invoice = self.make_invoice()
        invoice, result = self.confirm_invoice_service(invoice.pk)
        adapter = FakeAdapter(ok=True, erp_id="777")

        with patch(ADAPTER, return_value=adapter):
            push_customer_invoice.apply(args=[invoice.pk, result.sync_record_id, "push"]).get()
            again = push_customer_invoice.apply(
                args=[invoice.pk, result.sync_record_id, "push"]
            ).get()

        self.assertEqual(again["status"], "duplicate-ignored")
        self.assertEqual(len(adapter.pushed), 1)

    def test_task_cancel_memanggil_button_cancel(self):
        """``action='cancel'`` dengan ``odoo_id`` → adapter ``cancel_customer_invoice``."""
        invoice = self.make_invoice()
        invoice.odoo_id = 555
        invoice.state = "SENT"
        invoice.save(update_fields=("odoo_id", "state"))

        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-cancel")):
            result = svc.cancel_invoice(invoice)

        self.assertIsNotNone(result.sync_record_id)
        adapter = FakeAdapter(ok=True, erp_id="555")

        with patch(ADAPTER, return_value=adapter):
            outcome = push_customer_invoice.apply(
                args=[invoice.pk, result.sync_record_id, "cancel"]
            ).get()

        self.assertEqual(outcome["status"], "sent")
        self.assertEqual(adapter.cancelled, ["555"])
        self.assertEqual(adapter.pushed, [])

    def test_task_invoice_tidak_ada_not_found(self):
        """Task untuk id yang tidak ada → ``not-found`` (tidak melempar)."""
        outcome = push_customer_invoice.apply(args=[999999]).get()

        self.assertEqual(outcome["status"], "not-found")



class CustomerInvoiceOdooAdapterTests(CustomerInvoiceBase):
    """Adapter Odoo: payload ``account.move.create`` + guard (mock client)."""

    def _adapter(self, move_id: int = 42):
        """``OdooAdapter`` dengan client palsu (tanpa jaringan)."""
        client = MagicMock()
        client.execute_kw.return_value = [move_id]

        return OdooAdapter(client=client), client

    def test_push_customer_invoice_payload_dan_tax_ids_command(self):
        """Baris memakai command ``(0,0,…)``; pajak = m2m command ``(6,0,[ids])``."""
        adapter, client = self._adapter(move_id=42)

        response = adapter.push_customer_invoice(
            {
                "ref": "INV-2026-0001",
                "partner_odoo_id": 10,
                "invoice_date": "2026-10-12",
                "due_date": "2026-11-12",
                "lines": [
                    {
                        "product_odoo_id": 34,
                        "quantity": "5.00",
                        "price_unit": "4000.00",
                        "name": "KAOS-INV",
                        "tax_odoo_ids": [19],
                    }
                ],
            }
        )

        self.assertTrue(response.ok, response.error)
        self.assertEqual(response.erp_id, "42")
        self.assertEqual(response.stage, STAGE_INVOICE)

        call = client.execute_kw.call_args
        self.assertEqual(call.args[0], "account.move")
        self.assertEqual(call.args[1], "create")
        values = call.args[2][0][0]
        self.assertEqual(values["move_type"], "out_invoice")
        self.assertEqual(values["invoice_date_due"], "2026-11-12")
        self.assertNotIn("journal_id", values)
        self.assertNotIn("currency_id", values)

        command = values["invoice_line_ids"][0]
        self.assertEqual(command[:2], (0, 0))
        line = command[2]
        self.assertEqual(line["product_id"], 34)
        self.assertEqual(line["quantity"], 5.0)
        self.assertEqual(line["price_unit"], 4000.0)
        self.assertEqual(line["tax_ids"], [(6, 0, [19])])
        self.assertNotIn("account_id", line)
        self.assertNotIn("product_uom_id", line)

    def test_push_customer_invoice_guard_payload_dan_qty(self):
        """Payload tidak lengkap / qty ≤ 0 / produk tanpa id → ``ok=False`` (bukan raise)."""
        adapter, client = self._adapter()

        missing = adapter.push_customer_invoice({"ref": "INV-1"})
        self.assertFalse(missing.ok)
        self.assertIn("field wajib", missing.error)

        zero_qty = adapter.push_customer_invoice(
            {
                "ref": "INV-1",
                "partner_odoo_id": 10,
                "lines": [{"product_odoo_id": 34, "quantity": 0, "price_unit": "10"}],
            }
        )
        self.assertFalse(zero_qty.ok)
        self.assertIn("quantity", zero_qty.error)

        no_product = adapter.push_customer_invoice(
            {"ref": "INV-1", "partner_odoo_id": 10, "lines": [{"quantity": 1, "price_unit": "10"}]}
        )
        self.assertFalse(no_product.ok)
        self.assertIn("product_odoo_id", no_product.error)

        client.execute_kw.assert_not_called()

    def test_cancel_customer_invoice_memanggil_button_cancel(self):
        """``cancel_customer_invoice`` memanggil ``button_cancel`` dengan id move."""
        adapter, client = self._adapter()
        client.execute_kw.return_value = True

        response = adapter.cancel_customer_invoice("555")

        self.assertTrue(response.ok, response.error)
        call = client.execute_kw.call_args
        self.assertEqual(call.args[0], "account.move")
        self.assertEqual(call.args[1], "button_cancel")
        self.assertEqual(call.args[2][0][0], 555)

        invalid = adapter.cancel_customer_invoice("bukan-angka")
        self.assertFalse(invalid.ok)
        self.assertIn("tidak valid", invalid.error)



class CustomerInvoicePermissionTests(CustomerInvoiceBase):
    """Izin: anonim 403; tulis/transisi hanya ADMIN/OWNER."""

    def test_anonim_403_semua_endpoint(self):
        """Tanpa sesi → GET/POST/detail/aksi semua **403**."""
        anon = APIClient()
        invoice = self.make_invoice()

        self.assertEqual(anon.get(INVOICES_URL).status_code, 403)
        self.assertEqual(anon.post(INVOICES_URL, {}, format="json").status_code, 403)
        self.assertEqual(anon.get(detail_url(invoice.pk)).status_code, 403)
        self.assertEqual(anon.post(action_url(invoice.pk, "confirm")).status_code, 403)

    def test_tulis_hanya_admin_owner(self):
        """OPERATOR boleh baca, tetapi POST/PUT/DELETE/aksi → 403."""
        invoice = self.make_invoice()

        self.assertEqual(self.operator_api.get(INVOICES_URL).status_code, 200)
        self.assertEqual(self.operator_api.get(detail_url(invoice.pk)).status_code, 200)
        self.assertEqual(
            self.operator_api.post(
                INVOICES_URL, {"order_id": self.order.pk}, format="json"
            ).status_code,
            403,
        )
        self.assertEqual(
            self.operator_api.put(
                detail_url(invoice.pk), {"notes": "x"}, format="json"
            ).status_code,
            403,
        )
        self.assertEqual(self.operator_api.delete(detail_url(invoice.pk)).status_code, 403)
        self.assertEqual(
            self.operator_api.post(action_url(invoice.pk, "confirm")).status_code, 403
        )

        invoice.refresh_from_db()
        self.assertEqual(invoice.state, "DRAFT")

    def test_aksi_tidak_dikenal_404(self):
        """Aksi di luar confirm/done/cancel → 404 (bukan 500)."""
        invoice = self.make_invoice()

        response = self.api.post(action_url(invoice.pk, "approve"))

        self.assertEqual(response.status_code, 404)
        self.assertIn("tidak dikenal", response.json()["detail"])


class CustomerInvoiceNonBreakingTests(CustomerInvoiceBase):
    """Non-breaking: I5 (resource `order`) + F10/F15 monitoring + H2.1 + H3.6."""

    def test_resource_baru_tidak_menabrak_i5(self):
        """H3.1 memakai resource BARU `customer_invoice`, stage I5 di-REUSE."""
        self.assertEqual(SyncResource.CUSTOMER_INVOICE.value, "customer_invoice")
        self.assertEqual(SyncResource.ORDER.value, "order")
        self.assertEqual(SyncStage.INVOICE.value, "INVOICE")
        self.assertEqual(svc.INVOICE_RESOURCE, SyncResource.CUSTOMER_INVOICE.value)
        self.assertEqual(svc.INVOICE_STAGE, SyncStage.INVOICE.value)

    def test_i5_invoice_sync_service_tetap_bekerja(self):
        """`InvoiceSyncService.enqueue` (I5) tetap menulis record resource `order`."""
        record = InvoiceSyncService().enqueue(self.order)

        self.assertEqual(record.resource, SyncResource.ORDER.value)
        self.assertEqual(record.stage, SyncStage.INVOICE.value)
        self.assertEqual(record.resource_id, str(self.order.pk))
        self.assertEqual(record.payload["ref"], f"INV-{self.order.code}")

        # Invoice MES (H3.1) memakai record TERPISAH → tidak saling menimpa.
        invoice = self.make_invoice()
        self.assertEqual(SyncRecord.objects.filter(resource=svc.INVOICE_RESOURCE).count(), 1)
        self.assertTrue(CustomerInvoice.objects.filter(pk=invoice.pk).exists())

    def test_monitoring_finance_invoices_tetap_utuh(self):
        """F10/F15 `GET /finance/invoices/` (amplop `has_next`) tidak berubah."""
        InvoiceSyncService().enqueue(self.order)

        response = self.api.get("/api/v1/finance/invoices/")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), {"rows", "total_count", "has_next", "next_cursor"})
        self.assertEqual(body["total_count"], 1)
        self.assertEqual(
            set(body["rows"][0]),
            {
                "order_id",
                "order_no",
                "invoice_status",
                "erp_id",
                "attempts",
                "last_error",
                "sent_at",
                "created_at",
            },
        )
        self.assertEqual(body["rows"][0]["order_no"], self.order.code)

    def test_order_line_h2_1_dan_tax_h3_6_tetap_utuh(self):
        """`OrderLine.tax_ids` (H2.1) & `Product.sale_price` (H3.5) tidak diubah H3.1."""
        self.assertEqual(
            list(self.order_line.tax_ids.values_list("id", flat=True)), [self.tax.pk]
        )
        self.assertEqual(self.order_line.price_unit, Decimal("4000.00"))
        self.assertEqual(self.product.sale_price, Decimal("4000.00"))
        self.assertEqual(self.tax.odoo_id, 19)

