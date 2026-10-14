"""Test H2.1 — Sales Order + OrderLine (`/api/v1/garmen/orders/…`).

Cakupan: create (nomor otomatis ``SO-<TAHUN>-<SEQ>`` dari Sprint C), nested lines
atomic, update/delete **DRAFT-only**, transisi state §14 (CONFIRMED → push, DONE
dengan guard WorkOrder, CANCELLED + cancel Odoo), guard harga §5, izin (anonim 403,
non-role 403), ledger ``SyncRecord`` stage ``SALE_ORDER_PUSH`` + ``AuditLog``, dan
**push task** (payload Odoo, guard ``odoo_id``, no-op dev, cancel).

Non-breaking: pull I2 (`test_sale_order_sync.py` tetap hijau), `tag_router`
(placeholder `{order_code}`), `material_readiness`, `bundle_engine`,
`test_order_lines_endpoint`.

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_sales_orders_crud.py -q
"""

from __future__ import annotations

from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.models import Bundle, Order, OrderLine, WorkOrder
from apps_industry.garment.services import order_services
from core.audit.models import AuditLog
from core.auth.models import Role, User
from integrations.erp_sync.models import SyncRecord, SyncResource, SyncStage, SyncStatus
from integrations.erp_sync.tasks_order_push import (
    MasterPushError,
    ODOO_MODEL,
    push_sale_order,
    sale_order_values,
)
from master import sequence_services
from master.models import Partner, Product, Tax

ORDERS_URL = "/api/v1/garmen/orders/"
ENVELOPE_KEYS = {"rows", "total_count", "has_more", "next_cursor"}
ROW_KEYS = {
    "id",
    "code",
    "client_order_ref",
    "customer_id",
    "customer_name",
    "order_type",
    "state",
    "priority",
    "deadline",
    "lines_count",
    "amount_total",
    "odoo_id",
    "created_at",
    "updated_at",
}
DETAIL_EXTRA_KEYS = {
    "lines",
    "work_orders_count",
    "odoo_sync_status",
    "allowed_actions",
}
LINE_KEYS = {
    "id",
    "product_id",
    "product_code",
    "product_name",
    "qty",
    "tag",
    "ticket_code",
    "price_unit",
    "subtotal",
    "tax_ids",
    "odoo_id",
    "created_at",
    "updated_at",
}


def detail_url(order_id: int) -> str:
    """URL detail satu order."""
    return f"{ORDERS_URL}{order_id}/"


def action_url(order_id: int, action: str) -> str:
    """URL transisi state satu order."""
    return f"{ORDERS_URL}{order_id}/{action}/"


class SalesOrderTestCase(TestCase):
    """Basis bersama: customer, produk, pajak, user admin/operator."""

    @classmethod
    def setUpTestData(cls):
        cls.customer = Partner.objects.create(code="CUST-A", name="PT Buyer", odoo_id=51)
        cls.other_customer = Partner.objects.create(code="CUST-B", name="PT Lain")
        cls.product = Product.objects.create(
            code="KAOS-L", name="Kaos L", sale_price=75000, odoo_id=100, odoo_tmpl_id=10
        )
        cls.product_no_odoo = Product.objects.create(code="KAOS-M", name="Kaos M", sale_price=50000)
        cls.tax = Tax.objects.create(code="PPN11", name="PPN 11%", odoo_id=19)
        cls.admin = User.objects.create_user(
            username="admin-order",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.ADMIN),
        )
        cls.operator = User.objects.create_user(
            username="op-order",
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

    def payload(self, **overrides):
        """Payload create order default (1 baris, harga dari payload)."""
        data = {
            "customer_id": self.customer.pk,
            "order_type": "EXPORT",
            "deadline": "2026-11-30",
            "lines": [
                {"product_id": self.product.pk, "qty": 12, "price_unit": "75000.00", "tag": "EXPORT"}
            ],
        }
        data.update(overrides)

        return data


class SalesOrderCreateTests(SalesOrderTestCase):
    """Create: nomor otomatis, nested lines atomic, validasi 400, izin."""

    def test_create_ok_nomor_otomatis_dan_ledger(self):
        year = sequence_services.current_year()
        response = self.api.post(ORDERS_URL, self.payload(), format="json")

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["code"], f"SO-{year}-0001")
        self.assertEqual(body["client_order_ref"], f"SO-{year}-0001")
        self.assertEqual(body["state"], "DRAFT")
        self.assertEqual(body["lines_count"], 1)
        self.assertEqual(body["amount_total"], "900000.00")
        self.assertEqual(set(body["lines"][0]), LINE_KEYS)
        self.assertTrue(body["queued"] is False or isinstance(body["queued"], bool))

        record = SyncRecord.objects.get(
            resource=SyncResource.ORDER.value,
            resource_id=str(body["id"]),
            stage=SyncStage.SALE_ORDER_PUSH.value,
        )
        self.assertEqual(record.status, SyncStatus.PENDING)
        self.assertEqual(record.payload["code"], f"SO-{year}-0001")

    def test_create_nomor_berlanjut_dan_tidak_bentrok(self):
        first = self.api.post(ORDERS_URL, self.payload(), format="json").json()
        second = self.api.post(ORDERS_URL, self.payload(), format="json").json()

        self.assertNotEqual(first["code"], second["code"])
        self.assertTrue(second["code"].endswith("-0002"))

    def test_create_customer_wajib_dan_harus_ada_400(self):
        tanpa = self.payload()
        tanpa.pop("customer_id")

        kosong = self.api.post(ORDERS_URL, tanpa, format="json")
        asing = self.api.post(ORDERS_URL, self.payload(customer_id=999999), format="json")

        self.assertEqual(kosong.status_code, 400)
        self.assertIn("customer_id", kosong.json()["detail"])
        self.assertEqual(asing.status_code, 400)
        self.assertIn("tidak ditemukan", asing.json()["detail"])
        self.assertEqual(Order.objects.count(), 0)

    def test_create_validation_400_deadline_type_dan_state(self):
        deadline = self.api.post(ORDERS_URL, self.payload(deadline="besok"), format="json")
        order_type = self.api.post(
            ORDERS_URL, self.payload(order_type="WHOLESALE"), format="json"
        )
        state = self.api.post(ORDERS_URL, self.payload(state="CONFIRMED"), format="json")

        self.assertEqual(deadline.status_code, 400)
        self.assertIn("deadline", deadline.json()["detail"])
        self.assertEqual(order_type.status_code, 400)
        self.assertEqual(state.status_code, 400)
        self.assertIn("/confirm/", state.json()["detail"])
        self.assertEqual(Order.objects.count(), 0)

    def test_create_kode_manual_duplikat_400(self):
        self.api.post(ORDERS_URL, self.payload(code="SO-MANUAL"), format="json")

        response = self.api.post(ORDERS_URL, self.payload(code="SO-MANUAL"), format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("sudah dipakai", response.json()["detail"])

    def test_create_lines_kosong_atau_invalid_rollback_atomic(self):
        """``lines`` kosong / satu baris cacat ⇒ SELURUH order di-rollback."""
        kosong = self.api.post(ORDERS_URL, self.payload(lines=[]), format="json")
        cacat = self.api.post(
            ORDERS_URL,
            self.payload(
                lines=[
                    {"product_id": self.product.pk, "qty": 5, "price_unit": "1000.00"},
                    {"product_id": 999999, "qty": 5, "price_unit": "1000.00"},
                ]
            ),
            format="json",
        )

        self.assertEqual(kosong.status_code, 400)
        self.assertEqual(cacat.status_code, 400)
        self.assertIn("lines[1]", cacat.json()["detail"])
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(OrderLine.objects.count(), 0)

    def test_create_qty_nol_dan_harga_negatif_400(self):
        nol = self.api.post(
            ORDERS_URL,
            self.payload(lines=[{"product_id": self.product.pk, "qty": 0, "price_unit": "1.00"}]),
            format="json",
        )
        negatif = self.api.post(
            ORDERS_URL,
            self.payload(
                lines=[{"product_id": self.product.pk, "qty": 1, "price_unit": "-5.00"}]
            ),
            format="json",
        )

        self.assertEqual(nol.status_code, 400)
        self.assertEqual(negatif.status_code, 400)

    def test_create_harga_kosong_pakai_sale_price_produk(self):
        response = self.api.post(
            ORDERS_URL,
            self.payload(lines=[{"product_id": self.product.pk, "qty": 2}]),
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        line = response.json()["lines"][0]
        self.assertEqual(line["price_unit"], "75000.00")
        self.assertEqual(line["subtotal"], "150000.00")

    def test_create_dengan_pajak_dan_deadline_date(self):
        response = self.api.post(
            ORDERS_URL,
            self.payload(
                lines=[
                    {
                        "product_id": self.product.pk,
                        "qty": 1,
                        "price_unit": "1000.00",
                        "tax_ids": [self.tax.pk],
                    }
                ]
            ),
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["lines"][0]["tax_ids"], [self.tax.pk])
        self.assertTrue(body["deadline"].startswith("2026-11-30"))

    def test_create_deadline_ngawur_400(self):
        response = self.api.post(ORDERS_URL, self.payload(deadline="besok"), format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("deadline", response.json()["detail"])

    def test_create_order_type_invalid_400(self):
        response = self.api.post(ORDERS_URL, self.payload(order_type="WHOLESALE"), format="json")

        self.assertEqual(response.status_code, 400)

    def test_create_state_tidak_boleh_dikirim_400(self):
        response = self.api.post(ORDERS_URL, self.payload(state="CONFIRMED"), format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("/confirm/", response.json()["detail"])


class SalesOrderUpdateDeleteTests(SalesOrderTestCase):
    """Update/delete hanya DRAFT + replace lines atomic."""

    def _create(self, **overrides):
        response = self.api.post(ORDERS_URL, self.payload(**overrides), format="json")

        return response.json()

    def test_update_draft_ok_dan_replace_lines(self):
        order = self._create()
        payload = {
            "customer_id": self.other_customer.pk,
            "lines": [
                {"product_id": self.product.pk, "qty": 3, "price_unit": "10000.00"},
                {"product_id": self.product.pk, "qty": 1, "price_unit": "20000.00"},
            ],
        }

        response = self.api.put(detail_url(order["id"]), payload, format="json")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["customer_id"], self.other_customer.pk)
        self.assertEqual(body["lines_count"], 2)
        self.assertEqual(body["amount_total"], "50000.00")
        self.assertEqual(len(body["lines"]), 2)

    def test_update_tanpa_lines_tidak_menyentuh_baris(self):
        order = self._create()

        response = self.api.put(
            detail_url(order["id"]), {"priority": 5}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["priority"], 5)
        self.assertEqual(response.json()["lines_count"], 1)

    def test_update_setelah_confirm_400(self):
        order = self._create()
        self.api.post(action_url(order["id"], "confirm"), {}, format="json")

        response = self.api.put(detail_url(order["id"]), {"priority": 9}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("DRAFT", response.json()["detail"])

    def test_delete_draft_ok_dan_hapus_ledger(self):
        order = self._create()

        response = self.api.delete(detail_url(order["id"]))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["deleted"])
        self.assertFalse(Order.objects.filter(pk=order["id"]).exists())
        self.assertFalse(
            SyncRecord.objects.filter(
                resource=SyncResource.ORDER.value, resource_id=str(order["id"])
            ).exists()
        )

    def test_delete_setelah_confirm_400(self):
        order = self._create()
        self.api.post(action_url(order["id"], "confirm"), {}, format="json")

        response = self.api.delete(detail_url(order["id"]))

        self.assertEqual(response.status_code, 400)
        self.assertIn("DRAFT", response.json()["detail"])

    def test_detail_dan_update_404(self):
        self.assertEqual(self.api.get(detail_url(999999)).status_code, 404)
        self.assertEqual(
            self.api.put(detail_url(999999), {"priority": 1}, format="json").status_code, 404
        )


class SalesOrderTransitionTests(SalesOrderTestCase):
    """State machine §14: CONFIRMED (push), DONE (guard WO), CANCELLED."""

    def _create(self, price="1000.00", **overrides):
        response = self.api.post(
            ORDERS_URL,
            self.payload(
                lines=[{"product_id": self.product.pk, "qty": 2, "price_unit": price}],
                **overrides,
            ),
            format="json",
        )

        return response.json()

    def test_confirm_draft_ok_enqueue_push_dan_ledger_pending(self):
        order = self._create()

        with mock.patch(
            "apps_industry.garment.services.order_services._enqueue_push", return_value="task-1"
        ) as enqueue:
            response = self.api.post(action_url(order["id"], "confirm"), {}, format="json")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["state"], "CONFIRMED")
        self.assertEqual(body["task_id"], "task-1")
        self.assertTrue(body["queued"])
        self.assertEqual(body["allowed_actions"], ["DONE", "CANCELLED"])
        enqueue.assert_called_once()

    def test_confirm_tanpa_harga_400(self):
        order = self._create(price="0")

        response = self.api.post(action_url(order["id"], "confirm"), {}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("Harga satuan", response.json()["detail"])
        self.assertEqual(Order.objects.get(pk=order["id"]).state, "DRAFT")

    def test_transisi_tidak_diizinkan_400(self):
        order = self._create()
        self.api.post(action_url(order["id"], "confirm"), {}, format="json")

        dobel = self.api.post(action_url(order["id"], "confirm"), {}, format="json")
        done = self.api.post(action_url(order["id"], "done"), {}, format="json")

        self.assertEqual(dobel.status_code, 400)
        self.assertIn("tidak diizinkan", dobel.json()["detail"])
        # belum ada WorkOrder ⇒ DONE justru diizinkan (tidak ada yang menggantung)
        self.assertEqual(done.status_code, 200)
        self.assertEqual(done.json()["state"], "DONE")

    def test_done_butuh_semua_work_order_selesai(self):
        order = self._create()
        self.api.post(action_url(order["id"], "confirm"), {}, format="json")

        line = OrderLine.objects.get(order_id=order["id"])
        WorkOrder.objects.create(
            code="WO-H21-001", order_line=line, state="DRAFT", qty_planned=line.qty
        )

        ditolak = self.api.post(action_url(order["id"], "done"), {}, format="json")

        self.assertEqual(ditolak.status_code, 400)
        self.assertIn("WorkOrder belum selesai", ditolak.json()["detail"])

        WorkOrder.objects.filter(code="WO-H21-001").update(state="DONE")
        diterima = self.api.post(action_url(order["id"], "done"), {}, format="json")

        self.assertEqual(diterima.status_code, 200)
        self.assertEqual(diterima.json()["state"], "DONE")

    def test_cancel_draft_tanpa_push_dan_cancel_confirmed_dengan_odoo_id(self):
        draft = self._create()

        with mock.patch(
            "apps_industry.garment.services.order_services._enqueue_push", return_value="task-c"
        ) as enqueue:
            response = self.api.post(action_url(draft["id"], "cancel"), {}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], "CANCELLED")
        self.assertIsNone(response.json()["task_id"])
        enqueue.assert_not_called()

        confirmed = self._create()
        Order.objects.filter(pk=confirmed["id"]).update(odoo_id=777)
        Order.objects.filter(pk=confirmed["id"]).update(state="CONFIRMED")

        with mock.patch(
            "apps_industry.garment.services.order_services._enqueue_push", return_value="task-x"
        ) as enqueue_cancel:
            response2 = self.api.post(
                action_url(confirmed["id"], "cancel"), {"reason": "batal klien"}, format="json"
            )

        self.assertEqual(response2.status_code, 200)
        self.assertEqual(response2.json()["state"], "CANCELLED")
        self.assertEqual(response2.json()["task_id"], "task-x")
        enqueue_cancel.assert_called_once()

    def test_action_tidak_dikenal_404(self):
        order = self._create()

        response = self.api.post(action_url(order["id"], "approve"), {}, format="json")

        self.assertEqual(response.status_code, 404)
        self.assertIn("tidak dikenal", response.json()["detail"])


class SalesOrderPermissionAndListTests(SalesOrderTestCase):
    """Izin (anonim/non-role) + list/filter/pagination."""

    def test_anonim_403_dan_non_role_403(self):
        order = self.api.post(ORDERS_URL, self.payload(), format="json").json()
        anonim = self.as_user(None)

        self.assertEqual(anonim.get(ORDERS_URL).status_code, 403)
        self.assertEqual(anonim.post(ORDERS_URL, self.payload(), format="json").status_code, 403)

        operator = self.as_user(self.operator)
        self.assertEqual(operator.get(ORDERS_URL).status_code, 200)  # baca boleh
        self.assertEqual(
            operator.post(ORDERS_URL, self.payload(), format="json").status_code, 403
        )
        self.assertEqual(
            operator.put(detail_url(order["id"]), {"priority": 1}, format="json").status_code,
            403,
        )
        self.assertEqual(operator.delete(detail_url(order["id"])).status_code, 403)
        self.assertEqual(
            operator.post(action_url(order["id"], "confirm"), {}, format="json").status_code, 403
        )

    def test_list_envelope_filter_state_dan_search(self):
        first = self.api.post(ORDERS_URL, self.payload(code="SO-LIST-1"), format="json").json()
        self.api.post(ORDERS_URL, self.payload(customer_id=self.other_customer.pk), format="json")
        self.api.post(action_url(first["id"], "confirm"), {}, format="json")

        body = self.api.get(ORDERS_URL).json()

        self.assertEqual(set(body), ENVELOPE_KEYS)
        self.assertEqual(body["total_count"], 2)
        self.assertEqual(set(body["rows"][0]), ROW_KEYS)

        draft = self.api.get(ORDERS_URL, {"state": "draft"}).json()
        confirmed = self.api.get(ORDERS_URL, {"state": "CONFIRMED"}).json()
        cari = self.api.get(ORDERS_URL, {"search": "Lain"}).json()
        customer = self.api.get(ORDERS_URL, {"customer_id": self.customer.pk}).json()

        self.assertEqual(draft["total_count"], 1)
        self.assertEqual(confirmed["total_count"], 1)
        self.assertEqual(cari["total_count"], 1)
        self.assertEqual(customer["total_count"], 1)

    def test_list_pagination_dan_param_invalid_400(self):
        self.api.post(ORDERS_URL, self.payload(), format="json")
        self.api.post(ORDERS_URL, self.payload(), format="json")

        page1 = self.api.get(ORDERS_URL, {"limit": 1}).json()

        self.assertEqual(page1["total_count"], 2)
        self.assertTrue(page1["has_more"])
        self.assertEqual(page1["next_cursor"], 1)

        self.assertEqual(self.api.get(ORDERS_URL, {"limit": "abc"}).status_code, 400)
        self.assertEqual(self.api.get(ORDERS_URL, {"state": "NGACO"}).status_code, 400)
        self.assertEqual(self.api.get(ORDERS_URL, {"customer_id": "x"}).status_code, 400)


class SalesOrderLedgerTests(SalesOrderTestCase):
    """Ledger ``SALE_ORDER_PUSH`` + ``AuditLog`` per operasi."""

    def test_syncrecord_dan_auditlog_per_transisi(self):
        order = self.api.post(ORDERS_URL, self.payload(), format="json").json()
        record = SyncRecord.objects.get(
            resource=SyncResource.ORDER.value,
            resource_id=str(order["id"]),
            stage=SyncStage.SALE_ORDER_PUSH.value,
        )
        self.assertEqual(record.status, SyncStatus.PENDING)

        self.api.post(action_url(order["id"], "confirm"), {}, format="json")
        self.api.post(action_url(order["id"], "cancel"), {"reason": "tes"}, format="json")

        actions = sorted(
            AuditLog.objects.filter(resource=SyncResource.ORDER.value, resource_id=str(order["id"]))
            .values_list("action", flat=True)
        )
        self.assertEqual(actions, ["order.cancel", "order.confirm", "order.create"])
        record.refresh_from_db()
        self.assertEqual(record.payload["state"], "CANCELLED")
        self.assertEqual(record.payload["lines"][0]["qty"], 12)


class SalesOrderPushTaskTests(SalesOrderTestCase):
    """Task push ``sale.order`` — payload, guard odoo_id, SENT + odoo_id tersimpan."""

    def _confirmed_order(self, product=None):
        product = product or self.product
        response = self.api.post(
            ORDERS_URL,
            self.payload(
                lines=[
                    {
                        "product_id": product.pk,
                        "qty": 4,
                        "price_unit": "25000.00",
                        "tax_ids": [self.tax.pk],
                    }
                ]
            ),
            format="json",
        )
        order_id = response.json()["id"]
        # Pakai service (bukan update DB langsung) supaya ledger ikut di-arm ulang
        # dengan payload pasca-confirm — sama seperti alur nyata endpoint /confirm/.
        with mock.patch.object(order_services, "_enqueue_push", return_value=None):
            result = order_services.confirm_order(Order.objects.get(pk=order_id))
        self.assertIsNone(result.error)

        return Order.objects.get(pk=order_id)

    def test_sale_order_values_payload_odoo(self):
        order = self._confirmed_order()
        payload = order_services.order_payload(order)

        values = sale_order_values(payload)

        self.assertEqual(values["partner_id"], 51)
        self.assertEqual(values["partner_invoice_id"], 51)
        self.assertEqual(values["partner_shipping_id"], 51)
        self.assertEqual(values["client_order_ref"], order.code)
        # company_id/warehouse_id/date_order/name TIDAK dikirim (default Odoo)
        for forbidden in ("company_id", "warehouse_id", "date_order", "name", "state"):
            self.assertNotIn(forbidden, values)

        line = values["order_line"][0][2]
        self.assertEqual(values["order_line"][0][:2], (0, 0))
        self.assertEqual(line["product_id"], 100)
        self.assertEqual(line["product_uom_qty"], 4)
        self.assertEqual(line["price_unit"], 25000.0)
        self.assertEqual(line["tax_id"], [(6, 0, [19])])

    def test_sale_order_values_guard_odoo_id(self):
        order = self._confirmed_order(product=self.product_no_odoo)
        payload = order_services.order_payload(order)

        with self.assertRaises(MasterPushError) as ctx:
            sale_order_values(payload)

        self.assertIn("odoo_id", str(ctx.exception))
        self.assertIn("KAOS-M", str(ctx.exception))

        payload_customer = order_services.order_payload(self._confirmed_order())
        payload_customer["customer_odoo_id"] = None

        with self.assertRaises(MasterPushError):
            sale_order_values(payload_customer)

    def test_push_sukses_menyimpan_odoo_id_dan_mark_sent(self):
        order = self._confirmed_order()
        record = SyncRecord.objects.get(
            resource=SyncResource.ORDER.value, resource_id=str(order.pk)
        )

        with mock.patch(
            "integrations.erp_sync.tasks_order_push._push_create", return_value="555"
        ) as create:
            result = push_sale_order.run(order.pk, record.pk, "create")

        self.assertEqual(result["status"], "sent")
        self.assertEqual(result["erp_id"], "555")
        create.assert_called_once()
        order.refresh_from_db()
        self.assertEqual(order.odoo_id, 555)
        record.refresh_from_db()
        self.assertEqual(record.status, SyncStatus.SENT)
        self.assertEqual(record.erp_id, "555")

    def test_push_noop_dev_dan_duplicate_diabaikan(self):
        order = self._confirmed_order()
        record = SyncRecord.objects.get(
            resource=SyncResource.ORDER.value, resource_id=str(order.pk)
        )

        with mock.patch(
            "integrations.erp_sync.tasks_order_push.is_noop_mode", return_value=True
        ):
            first = push_sale_order.run(order.pk, record.pk, "create")
            second = push_sale_order.run(order.pk, record.pk, "create")

        self.assertEqual(first["status"], "sent")
        self.assertTrue(str(first["erp_id"]).startswith("NULL-"))
        self.assertEqual(second["status"], "duplicate-ignored")
        order.refresh_from_db()
        self.assertIsNone(order.odoo_id)  # no-op tidak menyimpan id ERP


class SalesOrderNonBreakingTests(SalesOrderTestCase):
    """Konsumen lama tetap jalan dengan Order/OrderLine dari API H2.1."""

    def test_tag_router_bundle_engine_dan_material_readiness(self):
        from apps_industry.garment.services.bundle_engine import BundleEngine
        from apps_industry.garment.services.tag_router import TagRouter
        from apps_industry.garment.tests.factories import make_routing, make_step, make_tag_rule
        from integrations.erp_sync.services.material_readiness import MaterialReadinessService

        routing_obj = make_routing(code="RT-H21")
        make_step(routing_obj, "STEP-1", 1, label="CUTTING", is_initial=True, is_terminal=True)
        make_tag_rule(
            "h21-export", routing_code=routing_obj.code, ticket_format="{order_code}-{qty}"
        )

        order = self.api.post(
            ORDERS_URL,
            self.payload(
                lines=[
                    {
                        "product_id": self.product.pk,
                        "qty": 5,
                        "price_unit": "1000.00",
                        "tag": "FAST_TRACK",
                    }
                ]
            ),
            format="json",
        ).json()
        line = OrderLine.objects.get(order_id=order["id"])

        # TagRouter (pakai `order.code` + `product.code`) — jalur kupon.
        plan = TagRouter().resolve(line)
        self.assertEqual(plan.routing, routing_obj)
        self.assertEqual(plan.piece_rate_ticket, f"{line.order.code}-5")

        # MaterialReadiness: helper murni `_find_bom` tetap menerima OrderLine H2.1
        # (tanpa transport/Odoo — modul yang sama dipakai job sync sesungguhnya).
        self.assertIsNone(MaterialReadinessService._find_bom(line))

        # BundleEngine: OrderLine dari API H2.1 tetap bisa dipecah jadi bundle
        # (BundleEngine menuntut WorkOrder dulu — alur normal FASE 3.4).
        WorkOrder.objects.create(
            code="WO-H21-BDL", order_line=line, state="DRAFT", qty_planned=line.qty
        )
        bundles = BundleEngine.create_bundles(line, {"M": 5}, 5)
        self.assertEqual(len(bundles), 1)
        self.assertEqual(Bundle.objects.filter(work_order__order_line=line).count(), 1)


    def test_order_lines_endpoint_lama_tetap_melayani(self):
        order = self.api.post(ORDERS_URL, self.payload(), format="json").json()
        line = OrderLine.objects.get(order_id=order["id"])

        response = self.api.get(f"/api/v1/garmen/order-lines/{line.pk}/")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(
            {
                "id",
                "order_id",
                "order_code",
                "product_code",
                "qty",
                "tag",
                "ticket_code",
                "work_order_ids",
                "updated_at",
            }.issubset(set(body))
        )
        self.assertEqual(body["order_code"], order["code"])
        self.assertEqual(body["product_code"], self.product.code)
        self.assertEqual(body["qty"], 12)







