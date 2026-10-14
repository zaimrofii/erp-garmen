"""Test CRUD Payment MES — ``/api/v1/finance/payments/`` (H3.3).

Cakupan: create **INBOUND** (sumber `CustomerInvoice`) & **OUTBOUND** (sumber
`VendorBill`), validasi **400** (sumber harus tepat satu, tipe ↔ sumber cocok,
amount ≤ 0, tanggal, enum, referensi), **guard anti-overpay** (create, update, dan
diulang saat `confirm`), update & delete **DRAFT-only**, list (pagination/filter/
search), detail (termasuk `source_remaining_amount`), izin (anon **403**, role
selain ADMIN/OWNER **403**), transisi ``confirm`` → ``done`` → ``cancel``, ledger
``SyncRecord`` (resource **`payment`**, stage **`PAYMENT`** — keduanya BARU) +
``AuditLog``, task ``erp_sync.push_payment`` (sukses → SENT + ``odoo_id``; gagal →
SyncRecord FAILED tapi state tetap CONFIRMED), adapter Odoo (payload tanpa
``currency_id``/``payment_method_line_id``/``reconciled_*``; ``journal_id`` hanya
bila setting diisi), serta **non-breaking**: H3.1/H3.2 (+ `amount_total` baru),
I6/material_readiness, F15 monitoring tetap hijau.

Catatan:
  * enqueue task di-patch (pola H1.2/H2.1/H2.2/H3.1/H3.2) supaya test tidak menyentuh broker;
  * adapter di-patch untuk menguji payload push nyata (tanpa Odoo);
  * **rekonsiliasi TIDAK diuji** karena memang bukan tanggung jawab MES (keputusan STEP 0).

Jalankan (di dalam container):

    docker compose exec -T django python -m pytest tests/integration/test_payments_crud.py -q
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps_industry.garment.models import (
    CustomerInvoice,
    Order,
    OrderLine,
    Payment,
    PurchaseOrder,
    PurchaseOrderLine,
    VendorBill,
)
from apps_industry.garment.services import customer_invoice_services as invoice_svc
from apps_industry.garment.services import payment_services as svc
from apps_industry.garment.services import vendor_bill_services as bill_svc
from core.audit.models import AuditLog
from core.auth.models import Role, User
from integrations.erp_sync.adapters.base import ERPResponse
from integrations.erp_sync.adapters.odoo import STAGE_PAYMENT, OdooAdapter
from integrations.erp_sync.models import SyncRecord, SyncResource, SyncStage, SyncStatus
from integrations.erp_sync.tasks_payment_push import push_payment
from master.models import Partner, Product, Tax

PAYMENTS_URL = "/api/v1/finance/payments/"
ENVELOPE_KEYS = {"rows", "total_count", "has_more", "next_cursor"}
ROW_KEYS = {
    "id",
    "code",
    "payment_type",
    "partner_id",
    "partner_name",
    "partner_code",
    "customer_invoice_id",
    "customer_invoice_code",
    "vendor_bill_id",
    "vendor_bill_code",
    "source_type",
    "source_label",
    "amount",
    "currency",
    "payment_date",
    "payment_method",
    "reference",
    "memo",
    "state",
    "odoo_id",
    "created_at",
    "updated_at",
}
DETAIL_EXTRA_KEYS = {
    "odoo_sync_status",
    "odoo_sync_error",
    "allowed_actions",
    "source_amount_total",
    "source_remaining_amount",
}
#: Info tulis (hanya pada respons POST/PUT/aksi — ``_write_body``).
WRITE_EXTRA_KEYS = {"sync_record_id", "task_id", "queued"}
#: Path patch enqueue task (service meng-enqueue saat confirm/cancel).
ENQUEUE = "integrations.erp_sync.tasks_payment_push.push_payment.apply_async"
#: Path patch adapter di module task (menguji payload & jalur sukses/gagal).
ADAPTER = "integrations.erp_sync.tasks_payment_push.get_adapter"


def detail_url(pk: int) -> str:
    """URL detail payment."""
    return f"{PAYMENTS_URL}{pk}/"


def action_url(pk: int, action: str) -> str:
    """URL aksi transisi payment."""
    return f"{PAYMENTS_URL}{pk}/{action}/"


class FakeAdapter:
    """Adapter palsu: mencatat payload push/cancel tanpa menyentuh Odoo."""

    def __init__(self, ok: bool = True, erp_id: str = "777", error: str | None = None):
        """Simpan konfigurasi respons + riwayat panggilan."""
        self.ok = ok
        self.erp_id = erp_id
        self.error = error
        self.pushed: list[dict] = []
        self.cancelled: list[str] = []
        self.closed = False

    def push_payment(self, payload: dict) -> ERPResponse:
        """Catat payload push & balas sesuai konfigurasi."""
        self.pushed.append(dict(payload))

        return ERPResponse(
            ok=self.ok,
            erp_id=self.erp_id if self.ok else None,
            raw={"payload": dict(payload)},
            error=None if self.ok else (self.error or "push gagal"),
            stage=STAGE_PAYMENT,
            ref=str(payload.get("payment_reference") or ""),
        )

    def cancel_payment(self, erp_id: str) -> ERPResponse:
        """Catat erp_id yang dibatalkan & balas sesuai konfigurasi."""
        self.cancelled.append(str(erp_id))

        return ERPResponse(
            ok=self.ok,
            erp_id=self.erp_id if self.ok else None,
            raw={"cancelled": erp_id},
            error=None if self.ok else (self.error or "cancel gagal"),
            stage=STAGE_PAYMENT,
            ref=str(erp_id),
        )

    def close(self) -> None:
        """Tandai adapter ditutup (task wajib menutup di ``finally``)."""
        self.closed = True


class PaymentBase(TestCase):
    """Fixture bersama: user, master, invoice (Rp20.000) & bill (Rp15.000)."""

    @classmethod
    def setUpTestData(cls):
        """Master data + dokumen sumber H3.1/H3.2 (dibuat lewat service)."""
        cls.admin = User.objects.create_user(
            username="admin-pay",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.ADMIN),
        )
        cls.operator = User.objects.create_user(
            username="op-pay",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.OPERATOR),
        )

        cls.customer = Partner.objects.create(code="CUST-PAY", name="PT Buyer Payment", odoo_id=10)
        cls.vendor = Partner.objects.create(code="SUP-PAY", name="PT Vendor Payment", odoo_id=14)
        cls.product = Product.objects.create(
            code="KAOS-PAY", name="Kaos Payment", odoo_id=34, sale_price=Decimal("4000.00")
        )
        cls.tax = Tax.objects.create(
            code="PPN11-PAY", name="PPN 11%", amount=Decimal("11.00"), odoo_id=20
        )

        #: Invoice H3.1: qty 5 × 4000 = 20.000 (amount_total tersimpan sejak H3.3).
        cls.order = Order.objects.create(code="SO-2026-9500", customer=cls.customer)
        cls.order_line = OrderLine.objects.create(
            order=cls.order, product=cls.product, qty=5, price_unit=Decimal("4000.00")
        )
        cls.invoice = invoice_svc.create_invoice(
            {"order_id": cls.order.pk, "invoice_date": "2026-10-13"}
        ).invoice

        #: Bill H3.2: qty 10 × 1500 = 15.000.
        cls.po = PurchaseOrder.objects.create(code="PO-2026-9500", vendor=cls.vendor)
        cls.po_line = PurchaseOrderLine.objects.create(
            po=cls.po, product=cls.product, qty=Decimal("10.00"), price_unit=Decimal("1500.00")
        )
        cls.bill = bill_svc.create_bill(
            {"vendor_id": cls.vendor.pk, "purchase_order_id": cls.po.pk, "invoice_date": "2026-10-13"}
        ).bill

    def setUp(self):
        """Klien admin (utama) + operator (uji 403)."""
        self.api = APIClient()
        self.api.force_authenticate(self.admin)
        self.operator_api = APIClient()
        self.operator_api.force_authenticate(self.operator)

    # ------------------------------------------------------------------ helper
    def inbound_body(self, **overrides) -> dict:
        """Body create INBOUND standar (amount = sisa penuh invoice)."""
        body: dict = {
            "payment_type": "INBOUND",
            "customer_invoice_id": self.invoice.pk,
            "amount": "20000.00",
            "payment_date": "2026-10-13",
        }
        body.update(overrides)

        return body

    def outbound_body(self, **overrides) -> dict:
        """Body create OUTBOUND standar (amount = sisa penuh bill)."""
        body: dict = {
            "payment_type": "OUTBOUND",
            "vendor_bill_id": self.bill.pk,
            "amount": "15000.00",
            "payment_date": "2026-10-13",
        }
        body.update(overrides)

        return body

    def post_payment(self, body: dict, client=None):
        """POST payment (enqueue di-patch) → ``(response, mock)``."""
        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-pay-1")) as enqueue:
            response = (client or self.api).post(PAYMENTS_URL, body, format="json")

        return response, enqueue

    def put_payment(self, pk: int, body: dict, client=None):
        """PUT payment (enqueue di-patch) → ``(response, mock)``."""
        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-pay-2")) as enqueue:
            response = (client or self.api).put(detail_url(pk), body, format="json")

        return response, enqueue

    def delete_payment(self, pk: int, client=None):
        """DELETE payment (enqueue di-patch) → ``(response, mock)``."""
        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-pay-3")) as enqueue:
            response = (client or self.api).delete(detail_url(pk))

        return response, enqueue

    def act(self, pk: int, action: str, client=None):
        """POST aksi transisi (enqueue di-patch) → ``(response, mock)``."""
        with patch(ENQUEUE, return_value=SimpleNamespace(id=f"task-pay-{action}")) as enqueue:
            response = (client or self.api).post(action_url(pk, action), {}, format="json")

        return response, enqueue

    def make_payment(self, **overrides) -> Payment:
        """Buat payment DRAFT lewat service (tanpa enqueue)."""
        result = svc.create_payment(self.inbound_body(**overrides))

        self.assertIsNone(result.error, result.error)
        return result.payment

    def confirm_payment_service(self, pk: int):
        """CONFIRM payment lewat service (enqueue di-patch) → ``(payment, result)``."""
        payment = Payment.objects.get(pk=pk)
        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-pay-confirm")):
            result = svc.confirm_payment(payment)

        self.assertIsNone(result.error, result.error)
        payment.refresh_from_db()
        return payment, result


class PaymentCrudTests(PaymentBase):
    """CRUD payment lewat API + validasi + guard anti-overpay + izin."""

    def test_create_inbound_dari_invoice(self):
        """POST INBOUND → 201 (`PAY-…`), partner diturunkan, ledger `payment`/`PAYMENT`."""
        response, enqueue = self.post_payment(self.inbound_body(reference="TRF-001"))

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertTrue(body["code"].startswith("PAY-"))
        self.assertEqual(body["payment_type"], "INBOUND")
        self.assertEqual(body["state"], "DRAFT")
        self.assertEqual(body["customer_invoice_id"], self.invoice.pk)
        self.assertEqual(body["customer_invoice_code"], self.invoice.code)
        self.assertIsNone(body["vendor_bill_id"])
        self.assertEqual(body["source_type"], "CUSTOMER_INVOICE")
        self.assertEqual(body["partner_id"], self.customer.pk)
        self.assertEqual(body["amount"], "20000.00")
        self.assertEqual(body["currency"], "IDR")
        self.assertEqual(body["payment_method"], "manual")
        self.assertEqual(body["reference"], "TRF-001")
        self.assertEqual(body["source_amount_total"], "20000.00")
        #: Respons create dihitung SETELAH payment ini tersimpan ⇒ sisa dokumen = 0.
        self.assertEqual(body["source_remaining_amount"], "0.00")
        self.assertFalse(body["queued"])
        self.assertIsNone(body["odoo_id"])
        enqueue.assert_not_called()

        record = SyncRecord.objects.get(pk=body["sync_record_id"])
        self.assertEqual(record.resource, SyncResource.PAYMENT.value)
        self.assertEqual(record.stage, SyncStage.PAYMENT.value)
        self.assertEqual(record.status, SyncStatus.PENDING)
        self.assertTrue(
            AuditLog.objects.filter(action=svc.ACTION_CREATE, resource_id=str(body["id"])).exists()
        )

    def test_create_outbound_dari_bill(self):
        """POST OUTBOUND → 201, partner = vendor, sumber = vendor_bill."""
        response, _ = self.post_payment(self.outbound_body())

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["payment_type"], "OUTBOUND")
        self.assertEqual(body["vendor_bill_id"], self.bill.pk)
        self.assertIsNone(body["customer_invoice_id"])
        self.assertEqual(body["source_type"], "VENDOR_BILL")
        self.assertEqual(body["partner_id"], self.vendor.pk)
        self.assertEqual(body["amount"], "15000.00")
        self.assertEqual(body["source_amount_total"], "15000.00")

    def test_create_sumber_harus_tepat_satu(self):
        """Tanpa sumber atau dengan dua sumber sekaligus → 400."""
        without_source, _ = self.post_payment(
            {"payment_type": "INBOUND", "amount": "100", "payment_date": "2026-10-13"}
        )
        self.assertEqual(without_source.status_code, 400)
        self.assertIn("satu dokumen", without_source.json()["detail"])

        both, _ = self.post_payment(self.inbound_body(vendor_bill_id=self.bill.pk))
        self.assertEqual(both.status_code, 400)
        self.assertIn("salah satu saja", both.json()["detail"])

    def test_create_tipe_tidak_cocok_sumber_400(self):
        """INBOUND wajib customer_invoice; OUTBOUND wajib vendor_bill."""
        inbound_bill, _ = self.post_payment(
            {"payment_type": "INBOUND", "vendor_bill_id": self.bill.pk, "amount": "100",
             "payment_date": "2026-10-13"}
        )
        self.assertEqual(inbound_bill.status_code, 400)
        self.assertIn("INBOUND harus memakai", inbound_bill.json()["detail"])

        outbound_invoice, _ = self.post_payment(
            {"payment_type": "OUTBOUND", "customer_invoice_id": self.invoice.pk, "amount": "100",
             "payment_date": "2026-10-13"}
        )
        self.assertEqual(outbound_invoice.status_code, 400)
        self.assertIn("OUTBOUND harus memakai", outbound_invoice.json()["detail"])

    def test_create_amount_tidak_valid_400(self):
        """``amount`` kosong / 0 / negatif → 400 (tanpa baris tersimpan)."""
        for raw in (None, "0", "-5"):
            body = self.inbound_body()
            if raw is None:
                body.pop("amount")
            else:
                body["amount"] = raw

            response, enqueue = self.post_payment(body)

            self.assertEqual(response.status_code, 400, raw)
            self.assertIn("amount", response.json()["detail"])
            enqueue.assert_not_called()

        self.assertEqual(Payment.objects.count(), 0)

    def test_create_overpay_400(self):
        """Guard anti-overpay: melebihi sisa invoice → 400 dengan pesan sisa."""
        response, _ = self.post_payment(self.inbound_body(amount="20000.01"))

        self.assertEqual(response.status_code, 400)
        detail = response.json()["detail"]
        self.assertIn("melebihi sisa", detail)
        self.assertIn("20000.00", detail)
        self.assertEqual(Payment.objects.count(), 0)

    def test_create_partial_dua_kali_sampai_lunas(self):
        """Dua payment parsial boleh selama totalnya ≤ `amount_total`."""
        first, _ = self.post_payment(self.inbound_body(amount="12000.00"))
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.json()["source_remaining_amount"], "8000.00")

        second, _ = self.post_payment(self.inbound_body(amount="8000.00"))
        self.assertEqual(second.status_code, 201)
        self.assertEqual(second.json()["source_remaining_amount"], "0.00")

        third, _ = self.post_payment(self.inbound_body(amount="0.01"))
        self.assertEqual(third.status_code, 400)
        self.assertIn("melebihi sisa", third.json()["detail"])

    def test_create_enum_dan_tanggal_tidak_valid_400(self):
        """``payment_type``/``payment_method`` asing, tanggal & referensi salah → 400."""
        bad_type, _ = self.post_payment(self.inbound_body(payment_type="TRANSFER"))
        self.assertEqual(bad_type.status_code, 400)
        self.assertIn("payment_type", bad_type.json()["detail"])

        bad_method, _ = self.post_payment(self.inbound_body(payment_method="giro"))
        self.assertEqual(bad_method.status_code, 400)
        self.assertIn("payment_method", bad_method.json()["detail"])

        missing_date = self.inbound_body()
        missing_date.pop("payment_date")
        no_date, _ = self.post_payment(missing_date)
        self.assertEqual(no_date.status_code, 400)
        self.assertIn("payment_date", no_date.json()["detail"])

        bad_date, _ = self.post_payment(self.inbound_body(payment_date="13-10-2026"))
        self.assertEqual(bad_date.status_code, 400)
        self.assertIn("ISO", bad_date.json()["detail"])

        long_ref, _ = self.post_payment(self.inbound_body(reference="X" * 65))
        self.assertEqual(long_ref.status_code, 400)
        self.assertIn("reference", long_ref.json()["detail"])

    def test_update_draft_ok_dan_confirmed_400(self):
        """PUT hanya DRAFT; guard overpay mengecualikan payment itu sendiri."""
        payment = self.make_payment(amount="20000.00")

        response, _ = self.put_payment(
            payment.pk, {"amount": "5000.00", "payment_method": "bank", "memo": "DP pertama"}
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["amount"], "5000.00")
        self.assertEqual(body["payment_method"], "bank")
        self.assertEqual(body["memo"], "DP pertama")
        self.assertEqual(body["source_remaining_amount"], "15000.00")

        payment.state = "CONFIRMED"
        payment.save(update_fields=("state",))
        blocked, _ = self.put_payment(payment.pk, {"amount": "1000.00"})
        self.assertEqual(blocked.status_code, 400)
        self.assertIn("hanya boleh saat DRAFT", blocked.json()["detail"])

    def test_delete_draft_ok_dan_confirmed_400(self):
        """DELETE hanya DRAFT (hard delete) + audit."""
        payment = self.make_payment(amount="5000.00")
        pk = payment.pk

        response, _ = self.delete_payment(pk)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"id": pk, "deleted": True})
        self.assertFalse(Payment.objects.filter(pk=pk).exists())
        self.assertTrue(AuditLog.objects.filter(action=svc.ACTION_DELETE).exists())

        confirmed = self.make_payment(amount="1000.00")
        confirmed.state = "CONFIRMED"
        confirmed.save(update_fields=("state",))
        blocked, _ = self.delete_payment(confirmed.pk)
        self.assertEqual(blocked.status_code, 400)
        self.assertTrue(Payment.objects.filter(pk=confirmed.pk).exists())

    def test_operator_403_pada_tulis(self):
        """Role selain ADMIN/OWNER → 403 untuk POST/PUT/DELETE + aksi (baca 200)."""
        post_response, _ = self.post_payment(self.inbound_body(), client=self.operator_api)
        self.assertEqual(post_response.status_code, 403)

        payment = self.make_payment(amount="1000.00")
        put_response, _ = self.put_payment(
            payment.pk, {"amount": "1000.00"}, client=self.operator_api
        )
        self.assertEqual(put_response.status_code, 403)

        delete_response, _ = self.delete_payment(payment.pk, client=self.operator_api)
        self.assertEqual(delete_response.status_code, 403)

        self.assertEqual(self.operator_api.get(PAYMENTS_URL).status_code, 200)
        self.assertEqual(
            self.operator_api.post(action_url(payment.pk, "confirm"), {}, format="json").status_code,
            403,
        )


class PaymentListDetailTests(PaymentBase):
    """List (amplop/pagination/filter/search) + detail + izin & 404."""

    def test_list_amplop_dan_row_keys(self):
        """GET list → amplop ListPage + 22 key baris (kontrak H3.3)."""
        self.make_payment(amount="5000.00")

        response = self.api.get(PAYMENTS_URL)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), ENVELOPE_KEYS)
        self.assertEqual(body["total_count"], 1)
        self.assertFalse(body["has_more"])
        self.assertIsNone(body["next_cursor"])
        self.assertEqual(set(body["rows"][0]), ROW_KEYS)
        self.assertEqual(body["rows"][0]["amount"], "5000.00")
        self.assertEqual(body["rows"][0]["source_label"], f"Customer Invoice {self.invoice.code}")

    def test_list_filter_state_dan_payment_type(self):
        """Filter ``?state=``/``?payment_type=`` + nilai tak dikenal → 400."""
        draft = self.make_payment(amount="1000.00")
        outbound = svc.create_payment(self.outbound_body(amount="2000.00")).payment
        outbound.state = "CANCELLED"
        outbound.save(update_fields=("state",))

        only_draft = self.api.get(f"{PAYMENTS_URL}?state=DRAFT").json()
        self.assertEqual(only_draft["total_count"], 1)
        self.assertEqual(only_draft["rows"][0]["id"], draft.pk)

        inbound = self.api.get(f"{PAYMENTS_URL}?payment_type=INBOUND").json()
        self.assertEqual(inbound["total_count"], 1)

        outbound_rows = self.api.get(f"{PAYMENTS_URL}?payment_type=OUTBOUND").json()
        self.assertEqual(outbound_rows["total_count"], 1)

        bad_state = self.api.get(f"{PAYMENTS_URL}?state=BOGUS")
        self.assertEqual(bad_state.status_code, 400)
        self.assertIn("state", bad_state.json()["detail"])

        bad_type = self.api.get(f"{PAYMENTS_URL}?payment_type=BOGUS")
        self.assertEqual(bad_type.status_code, 400)
        self.assertIn("payment_type", bad_type.json()["detail"])

    def test_list_filter_partner_dan_dokumen_sumber(self):
        """Filter ``?partner_id=``, ``?customer_invoice_id=``, ``?vendor_bill_id=``."""
        self.make_payment(amount="1000.00")
        svc.create_payment(self.outbound_body(amount="2000.00"))

        by_partner = self.api.get(f"{PAYMENTS_URL}?partner_id={self.customer.pk}").json()
        self.assertEqual(by_partner["total_count"], 1)

        by_invoice = self.api.get(f"{PAYMENTS_URL}?customer_invoice_id={self.invoice.pk}").json()
        self.assertEqual(by_invoice["total_count"], 1)
        self.assertEqual(by_invoice["rows"][0]["source_type"], "CUSTOMER_INVOICE")

        by_bill = self.api.get(f"{PAYMENTS_URL}?vendor_bill_id={self.bill.pk}").json()
        self.assertEqual(by_bill["total_count"], 1)
        self.assertEqual(by_bill["rows"][0]["source_type"], "VENDOR_BILL")

        bad = self.api.get(f"{PAYMENTS_URL}?partner_id=x")
        self.assertEqual(bad.status_code, 400)

    def test_list_search(self):
        """``?search=`` mencocokkan kode, referensi, nama partner, dan kode sumber."""
        self.make_payment(amount="1000.00", reference="TRF-CARI-777")

        self.assertEqual(self.api.get(f"{PAYMENTS_URL}?search=CARI-777").json()["total_count"], 1)
        self.assertEqual(self.api.get(f"{PAYMENTS_URL}?search=Buyer Payment").json()["total_count"], 1)
        self.assertEqual(
            self.api.get(f"{PAYMENTS_URL}?search={self.invoice.code}").json()["total_count"], 1
        )
        self.assertEqual(self.api.get(f"{PAYMENTS_URL}?search=tidak-ada").json()["total_count"], 0)

    def test_list_pagination_dan_param_invalid(self):
        """``?limit``/``?cursor`` → ``has_more``/``next_cursor``; nilai salah → 400."""
        for index in range(3):
            self.make_payment(amount=str(index + 1))

        page1 = self.api.get(f"{PAYMENTS_URL}?limit=2").json()
        self.assertEqual(len(page1["rows"]), 2)
        self.assertTrue(page1["has_more"])
        self.assertEqual(page1["next_cursor"], 2)

        page2 = self.api.get(f"{PAYMENTS_URL}?limit=2&cursor={page1['next_cursor']}").json()
        self.assertEqual(len(page2["rows"]), 1)
        self.assertFalse(page2["has_more"])

        self.assertEqual(self.api.get(f"{PAYMENTS_URL}?limit=0").status_code, 400)
        self.assertEqual(self.api.get(f"{PAYMENTS_URL}?cursor=x").status_code, 400)

    def test_detail_keys_dan_sisa_dokumen(self):
        """Detail DRAFT → key lengkap + sisa dokumen + ``allowed_actions``."""
        payment = self.make_payment(amount="5000.00")

        response = self.api.get(detail_url(payment.pk))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), ROW_KEYS | DETAIL_EXTRA_KEYS)
        self.assertEqual(body["allowed_actions"], ["CONFIRMED", "CANCELLED"])
        self.assertEqual(body["odoo_sync_status"], "PENDING")
        self.assertEqual(body["source_amount_total"], "20000.00")
        self.assertEqual(body["source_remaining_amount"], "15000.00")

    def test_detail_404_aksi_tak_dikenal_dan_anonim_403(self):
        """404 (tidak ada), 404 (aksi asing), dan 403 untuk anonim."""
        self.assertEqual(self.api.get(detail_url(999999)).status_code, 404)

        payment = self.make_payment(amount="1000.00")
        unknown = self.api.post(action_url(payment.pk, "kirim"), {}, format="json")
        self.assertEqual(unknown.status_code, 404)
        self.assertIn("tidak dikenal", unknown.json()["detail"])

        anon = APIClient()
        self.assertEqual(anon.get(PAYMENTS_URL).status_code, 403)
        self.assertEqual(anon.get(detail_url(payment.pk)).status_code, 403)
        self.assertEqual(anon.post(PAYMENTS_URL, {}, format="json").status_code, 403)


class PaymentTransitionTests(PaymentBase):
    """Transisi ``confirm``/``done``/``cancel`` + guard + sync_complete/sync_failed."""

    def test_confirm_guard_partner_odoo_id(self):
        """Partner tanpa ``odoo_id`` menahan CONFIRMED (400)."""
        partner = Partner.objects.create(code="CUST-NO-ODOO", name="Customer Tanpa Odoo")
        invoice = invoice_svc.create_invoice(
            {"order_id": self.order.pk, "customer_id": partner.pk, "invoice_date": "2026-10-13"}
        ).invoice
        payment = svc.create_payment(
            {
                "payment_type": "INBOUND",
                "customer_invoice_id": invoice.pk,
                "amount": "20000.00",
                "payment_date": "2026-10-13",
            }
        ).payment

        response, enqueue = self.act(payment.pk, "confirm")

        self.assertEqual(response.status_code, 400)
        self.assertIn("belum punya odoo_id", response.json()["detail"])
        enqueue.assert_not_called()

    def test_confirm_guard_overpay_diulang(self):
        """Guard overpay diulang saat CONFIRMED: `amount_total` turun ⇒ 400."""
        payment = self.make_payment(amount="20000.00")

        #: Invoice diperkecil (qty 5 → 1) ⇒ amount_total jadi 4.000 < payment 20.000.
        invoice_svc.update_invoice(
            CustomerInvoice.objects.get(pk=self.invoice.pk),
            {"lines": [{"product_id": self.product.pk, "qty": "1", "price_unit": "4000.00"}]},
        )
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_total, Decimal("4000.00"))

        response, enqueue = self.act(payment.pk, "confirm")

        self.assertEqual(response.status_code, 400)
        self.assertIn("melebihi sisa", response.json()["detail"])
        enqueue.assert_not_called()
        payment.refresh_from_db()
        self.assertEqual(payment.state, "DRAFT")

    def test_confirm_ok_ledger_dan_enqueue(self):
        """DRAFT→CONFIRMED: state, ledger ``payment``/``PAYMENT``, enqueue push."""
        payment = self.make_payment(amount="5000.00")

        response, enqueue = self.act(payment.pk, "confirm")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["state"], "CONFIRMED")
        self.assertTrue(body["queued"])
        self.assertEqual(body["allowed_actions"], ["DONE", "CANCELLED"])

        enqueue.assert_called_once()
        self.assertEqual(
            enqueue.call_args.kwargs["args"], [payment.pk, body["sync_record_id"], "push"]
        )

        record = SyncRecord.objects.get(pk=body["sync_record_id"])
        self.assertEqual(record.resource, SyncResource.PAYMENT.value)
        self.assertEqual(record.stage, SyncStage.PAYMENT.value)
        self.assertEqual(record.status, SyncStatus.PENDING)
        self.assertEqual(record.payload["amount"], "5000.00")
        self.assertTrue(AuditLog.objects.filter(action=svc.ACTION_CONFIRM).exists())

    def test_done_transition(self):
        """``CONFIRMED → DONE``; ``DRAFT → DONE`` ditolak."""
        payment = self.make_payment(amount="1000.00")
        draft_done, _ = self.act(payment.pk, "done")
        self.assertEqual(draft_done.status_code, 400)
        self.assertIn("tidak diizinkan", draft_done.json()["detail"])

        payment, _result = self.confirm_payment_service(payment.pk)
        response, _ = self.act(payment.pk, "done")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], "DONE")
        self.assertEqual(response.json()["allowed_actions"], [])
        self.assertTrue(AuditLog.objects.filter(action=svc.ACTION_DONE).exists())

    def test_cancel_tanpa_dan_dengan_odoo_id(self):
        """``CANCELLED``: tanpa ``odoo_id`` MES-only; dengan ``odoo_id`` → push cancel."""
        draft = self.make_payment(amount="1000.00")
        response, enqueue = self.act(draft.pk, "cancel")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], "CANCELLED")
        enqueue.assert_not_called()

        sent = self.make_payment(amount="2000.00")
        sent, _result = self.confirm_payment_service(sent.pk)
        sent.odoo_id = 2468
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

    def test_sync_complete_ke_sent(self):
        """``sync_complete`` (task) → SENT + ``odoo_id`` + ledger SENT."""
        payment = self.make_payment(amount="3000.00")
        payment, result = self.confirm_payment_service(payment.pk)

        completed = svc.sync_complete(payment, "999")

        payment.refresh_from_db()
        self.assertEqual(payment.state, "SENT")
        self.assertEqual(payment.odoo_id, 999)
        self.assertEqual(completed.sync_record_id, result.sync_record_id)

        record = SyncRecord.objects.get(pk=completed.sync_record_id)
        self.assertEqual(record.status, SyncStatus.SENT)
        self.assertEqual(record.erp_id, "999")
        self.assertTrue(AuditLog.objects.filter(action=svc.ACTION_SYNC_COMPLETE).exists())

    def test_sync_failed_tetap_confirmed(self):
        """Push gagal → ``SyncRecord`` FAILED + audit; state payment tetap CONFIRMED."""
        payment = self.make_payment(amount="4000.00")
        payment, result = self.confirm_payment_service(payment.pk)

        failed = svc.sync_failed(payment, "Odoo menolak: journal tidak ada")

        payment.refresh_from_db()
        self.assertEqual(payment.state, "CONFIRMED")
        self.assertIsNone(payment.odoo_id)
        self.assertEqual(failed.error, "Odoo menolak: journal tidak ada")

        record = SyncRecord.objects.get(pk=result.sync_record_id)
        self.assertEqual(record.status, SyncStatus.FAILED)
        self.assertIn("journal", record.last_error)
        self.assertTrue(AuditLog.objects.filter(action=svc.ACTION_SYNC_FAILED).exists())


class PaymentTaskTests(PaymentBase):
    """Task ``erp_sync.push_payment``: payload dua arah, sukses/gagal, cancel, adapter."""

    def _confirmed_payment(self, outbound: bool = False, amount: str = "5000.00"):
        """Payment CONFIRMED + SyncRecord PENDING (enqueue di-patch)."""
        body = self.outbound_body(amount=amount) if outbound else self.inbound_body(amount=amount)
        payment = svc.create_payment(body).payment
        payment, result = self.confirm_payment_service(payment.pk)

        return payment, SyncRecord.objects.get(pk=result.sync_record_id)

    @override_settings(ODOO_PAYMENT_JOURNAL_ID=13)
    def test_task_push_inbound_sukses_dan_idempoten(self):
        """INBOUND → payload ``inbound``/``customer`` + journal dari setting; idempoten."""
        payment, record = self._confirmed_payment(outbound=False)
        adapter = FakeAdapter(ok=True, erp_id="777")

        with patch(ADAPTER, return_value=adapter):
            outcome = push_payment.apply(args=[payment.pk, record.pk, "push"]).get()

        self.assertEqual(outcome["status"], "sent")
        self.assertEqual(outcome["erp_id"], "777")
        self.assertEqual(outcome["state"], "SENT")
        self.assertTrue(adapter.closed)

        payload = adapter.pushed[0]
        self.assertEqual(payload["payment_type"], "inbound")
        self.assertEqual(payload["partner_type"], "customer")
        self.assertEqual(payload["partner_odoo_id"], self.customer.odoo_id)
        self.assertEqual(payload["amount"], "5000.00")
        self.assertEqual(payload["date"], "2026-10-13")
        self.assertEqual(payload["payment_reference"], payment.code)
        self.assertEqual(payload["ref"], payment.code)  # reference kosong → fallback kode
        self.assertEqual(payload["journal_odoo_id"], 13)
        self.assertEqual(payload["source"], "customer_invoice")

        payment.refresh_from_db()
        self.assertEqual(payment.state, "SENT")
        self.assertEqual(payment.odoo_id, 777)

        with patch(ADAPTER, return_value=FakeAdapter(ok=True, erp_id="888")):
            again = push_payment.apply(args=[payment.pk, record.pk, "push"]).get()
        self.assertEqual(again["status"], "duplicate-ignored")

    @override_settings(ODOO_PAYMENT_JOURNAL_ID=None)
    def test_task_push_outbound_tanpa_journal(self):
        """OUTBOUND → ``outbound``/``supplier``; tanpa setting ⇒ `journal_odoo_id` None."""
        payment, record = self._confirmed_payment(outbound=True, amount="15000.00")
        adapter = FakeAdapter(ok=True, erp_id="321")

        with patch(ADAPTER, return_value=adapter):
            outcome = push_payment.apply(args=[payment.pk, record.pk, "push"]).get()

        self.assertEqual(outcome["status"], "sent")
        payload = adapter.pushed[0]
        self.assertEqual(payload["payment_type"], "outbound")
        self.assertEqual(payload["partner_type"], "supplier")
        self.assertEqual(payload["partner_odoo_id"], self.vendor.odoo_id)
        self.assertIsNone(payload["journal_odoo_id"])
        self.assertEqual(payload["source"], "vendor_bill")

    def test_task_push_gagal_tetap_confirmed(self):
        """Adapter ``ok=False`` → task balas failed; payment tetap CONFIRMED."""
        payment, record = self._confirmed_payment()
        adapter = FakeAdapter(ok=False, error="Odoo: journal pembayaran tidak ada")

        with patch(ADAPTER, return_value=adapter):
            outcome = push_payment.apply(args=[payment.pk, record.pk, "push"]).get()

        self.assertEqual(outcome["status"], "failed")
        self.assertIn("journal", outcome["error"])

        payment.refresh_from_db()
        self.assertEqual(payment.state, "CONFIRMED")
        self.assertIsNone(payment.odoo_id)

        record.refresh_from_db()
        self.assertEqual(record.status, SyncStatus.FAILED)
        self.assertIn("journal", record.last_error)

    def test_task_cancel_dan_not_found(self):
        """``action="cancel"`` memanggil ``cancel_payment``; id tak ada → not-found."""
        payment, record = self._confirmed_payment()
        payment.odoo_id = 2468
        payment.state = "SENT"
        payment.save(update_fields=("odoo_id", "state"))

        adapter = FakeAdapter(ok=True, erp_id="2468")
        with patch(ADAPTER, return_value=adapter):
            outcome = push_payment.apply(args=[payment.pk, record.pk, "cancel"]).get()

        self.assertEqual(outcome["status"], "sent")
        self.assertEqual(adapter.cancelled, ["2468"])
        self.assertEqual(adapter.pushed, [])

        self.assertEqual(push_payment.apply(args=[999999]).get()["status"], "not-found")

    def test_adapter_odoo_payload_dan_guard(self):
        """Adapter Odoo: nilai `account.payment` + field yang TIDAK dikirim."""
        client = MagicMock()
        client.execute_kw.return_value = [55]
        adapter = OdooAdapter(client=client)

        response = adapter.push_payment(
            {
                "payment_type": "inbound",
                "partner_type": "customer",
                "partner_odoo_id": 10,
                "amount": "20000.00",
                "date": "2026-10-13",
                "payment_reference": "PAY-2026-0001",
                "ref": "TRF-123",
                "journal_odoo_id": 13,
            }
        )

        self.assertTrue(response.ok, response.error)
        self.assertEqual(response.erp_id, "55")
        self.assertEqual(response.stage, STAGE_PAYMENT)

        values = client.execute_kw.call_args.args[2][0][0]
        self.assertEqual(values["payment_type"], "inbound")
        self.assertEqual(values["partner_type"], "customer")
        self.assertEqual(values["partner_id"], 10)
        self.assertEqual(values["amount"], 20000.0)
        self.assertEqual(values["date"], "2026-10-13")
        self.assertEqual(values["payment_reference"], "PAY-2026-0001")
        self.assertEqual(values["ref"], "TRF-123")
        self.assertEqual(values["journal_id"], 13)
        for absent in (
            "currency_id",
            "payment_method_line_id",
            "reconciled_invoice_ids",
            "reconciled_bill_ids",
            "memo",
            "communication",
            "move_id",
        ):
            self.assertNotIn(absent, values)

        without_journal = OdooAdapter(client=client)
        without_journal.push_payment(
            {
                "payment_type": "outbound",
                "partner_type": "supplier",
                "partner_odoo_id": 14,
                "amount": "15000.00",
                "date": "2026-10-13",
                "payment_reference": "PAY-2026-0002",
            }
        )
        latest = client.execute_kw.call_args.args[2][0][0]
        self.assertNotIn("journal_id", latest)

        missing = adapter.push_payment({"payment_type": "inbound"})
        self.assertFalse(missing.ok)
        self.assertIn("field wajib", missing.error)

        zero = adapter.push_payment(
            {
                "payment_type": "inbound",
                "partner_type": "customer",
                "partner_odoo_id": 10,
                "amount": "0",
                "date": "2026-10-13",
            }
        )
        self.assertFalse(zero.ok)
        self.assertIn("> 0", zero.error)

        bad_type = adapter.push_payment(
            {
                "payment_type": "transfer",
                "partner_type": "customer",
                "partner_odoo_id": 10,
                "amount": "10",
                "date": "2026-10-13",
            }
        )
        self.assertFalse(bad_type.ok)
        self.assertIn("payment_type", bad_type.error)


class PaymentNonBreakingTests(PaymentBase):
    """Non-breaking: H3.1/H3.2 (+`amount_total`) + I6 + F15 monitoring tetap hijau."""

    def test_h3_1_h3_2_dan_i6_tidak_tersentuh(self):
        """`amount_total` tersimpan & endpoint lain tetap melayani; I6 read-only utuh."""
        from apps_industry.garment.models import MaterialReadiness
        from integrations.erp_sync.transport.odoo_transport import (
            VENDOR_BILL_FIELDS,
            OdooTransport,
        )

        #: H3.3 menambah field `amount_total` (disinkronkan service H3.1/H3.2).
        self.assertEqual(self.invoice.amount_total, Decimal("20000.00"))
        self.assertEqual(self.bill.amount_total, Decimal("15000.00"))

        self.assertEqual(self.api.get("/api/v1/finance/customer-invoices/").status_code, 200)
        self.assertEqual(self.api.get("/api/v1/finance/vendor-bills/").status_code, 200)
        self.assertEqual(self.api.get("/api/v1/garmen/purchase-orders/").status_code, 200)

        #: F15 monitoring (antrean I5 dari SyncRecord) tetap seperti semula.
        self.assertEqual(self.api.get("/api/v1/finance/invoices/").status_code, 200)
        self.assertEqual(APIClient().get("/api/v1/finance/invoices/").status_code, 403)

        #: I6 tetap tarik `payment_state` (MES TIDAK auto-update payment_state/paid_amount).
        self.assertTrue(hasattr(OdooTransport, "fetch_vendor_bills"))
        self.assertIn("payment_state", VENDOR_BILL_FIELDS)
        self.assertEqual(
            [value for value, _label in MaterialReadiness.VendorBillStatus.choices],
            ["NONE", "DRAFT", "POSTED", "PAID"],
        )

        #: Ledger jalur lain tidak berubah resource/stage-nya.
        self.assertEqual(SyncResource.PAYMENT.value, "payment")
        self.assertEqual(SyncStage.PAYMENT.value, "PAYMENT")
        self.assertEqual(SyncResource.CUSTOMER_INVOICE.value, "customer_invoice")
        self.assertEqual(SyncResource.VENDOR_BILL.value, "vendor_bill")
        self.assertEqual(SyncStage.INVOICE.value, "INVOICE")
        self.assertEqual(SyncStage.VENDOR_BILL.value, "VENDOR_BILL")








