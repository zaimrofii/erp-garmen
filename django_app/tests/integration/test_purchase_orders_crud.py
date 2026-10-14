"""Test H2.2 — Purchase Order + PurchaseOrderLine (`/api/v1/garmen/purchase-orders/…`).

Cakupan: create (nomor otomatis ``PO-<TAHUN>-<SEQ>`` dari Sprint C), nested lines
atomic, update/delete **DRAFT-only**, transisi state §14 (CONFIRMED → push, DONE
manual MES-only, CANCELLED + cancel Odoo), guard harga §5, guard `vendor.odoo_id`,
izin (anonim 403, non-role 403, PURCHASING boleh), ledger ``PURCHASE_ORDER_PUSH`` +
``AuditLog``, endpoint **read-only** ``sync-odoo-state``, dan push task (payload Odoo
dengan **`taxes_id`**, guard ``odoo_id``, no-op dev, cancel).

Non-breaking: B10 monitoring (`GET /api/v1/purchase/orders/`) tetap 200 dengan bentuk
lama (9 key), I3 (`material_readiness.PO_STATES`) & I6 (`_vendor_bills`) tidak berubah.
"""

from __future__ import annotations

from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.models import PurchaseOrder, PurchaseOrderLine
from apps_industry.garment.services import purchase_order_services
from core.audit.models import AuditLog
from core.auth.models import Role, User
from integrations.erp_sync.models import SyncRecord, SyncResource, SyncStage, SyncStatus
from integrations.erp_sync.tasks_purchase_order_push import (
    MasterPushError,
    ODOO_MODEL,
    purchase_order_values,
    push_purchase_order,
)
from master import sequence_services
from master.models import Partner, Product, Tax

PO_URL = "/api/v1/garmen/purchase-orders/"
B10_URL = "/api/v1/purchase/orders/"
ENVELOPE_KEYS = {"rows", "total_count", "has_more", "next_cursor"}
ROW_KEYS = {
    "id",
    "code",
    "partner_ref",
    "vendor_id",
    "vendor_name",
    "vendor_code",
    "state",
    "expected_date",
    "notes",
    "lines_count",
    "amount_total",
    "odoo_id",
    "created_at",
    "updated_at",
}
DETAIL_EXTRA_KEYS = {"lines", "odoo_sync_status", "allowed_actions"}
LINE_KEYS = {
    "id",
    "product_id",
    "product_code",
    "product_name",
    "qty",
    "price_unit",
    "subtotal",
    "tax_ids",
    "date_planned",
    "odoo_id",
    "created_at",
    "updated_at",
}


def detail_url(po_id: int) -> str:
    """URL detail satu PO."""
    return f"{PO_URL}{po_id}/"


def action_url(po_id: int, action: str) -> str:
    """URL transisi state satu PO."""
    return f"{PO_URL}{po_id}/{action}/"


def sync_state_url(po_id: int) -> str:
    """URL baca state Odoo (read-only) satu PO."""
    return f"{PO_URL}{po_id}/sync-odoo-state/"


def odoo_client_stub(rows):
    """Klien Odoo palsu untuk `fetch_odoo_state` (transport.search_read saja)."""
    client = mock.MagicMock()
    client.transport.search_read.return_value = rows

    return client


class PurchaseOrderTestCase(TestCase):
    """Basis bersama: vendor, produk, pajak, user purchasing/admin/operator."""

    @classmethod
    def setUpTestData(cls):
        cls.vendor = Partner.objects.create(
            code="VEND-A", name="PT Supplier A", odoo_id=45
        )
        cls.vendor_no_odoo = Partner.objects.create(code="VEND-B", name="CV Supplier B")
        cls.product = Product.objects.create(
            code="KAIN-COTTON", name="Kain Cotton 30s", cost_price=30000, odoo_id=91
        )
        cls.product_no_odoo = Product.objects.create(
            code="BENANG-JAHIT", name="Benang Jahit", cost_price=18000
        )
        cls.tax = Tax.objects.create(code="PPN11-PO", name="PPN 11%", odoo_id=20)
        cls.purchasing = User.objects.create_user(
            username="pur-po",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.PURCHASING),
        )
        cls.admin = User.objects.create_user(
            username="admin-po",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.ADMIN),
        )
        cls.operator = User.objects.create_user(
            username="op-po",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.OPERATOR),
        )

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.purchasing)

    def as_user(self, user):
        """Client terautentikasi sebagai ``user`` (anonim kalau ``None``)."""
        client = APIClient()
        if user is not None:
            client.force_authenticate(user)

        return client

    def payload(self, **overrides):
        """Payload create PO default (1 baris, vendor & produk ber-odoo_id)."""
        data = {
            "vendor_id": self.vendor.pk,
            "expected_date": "2026-11-30",
            "notes": "PO uji",
            "lines": [
                {
                    "product_id": self.product.pk,
                    "qty": "10.50",
                    "price_unit": "30000.00",
                    "date_planned": "2026-11-25",
                }
            ],
        }
        data.update(overrides)

        return data


class PurchaseOrderCreateTests(PurchaseOrderTestCase):
    """Create: nomor otomatis, nested lines atomic, validasi 400, ledger."""

    def test_create_ok_nomor_otomatis_dan_ledger(self):
        year = sequence_services.current_year()

        response = self.api.post(PO_URL, self.payload(), format="json")

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["code"], f"PO-{year}-0001")
        self.assertEqual(body["partner_ref"], f"PO-{year}-0001")
        self.assertEqual(body["state"], "DRAFT")
        self.assertEqual(body["lines_count"], 1)
        self.assertEqual(body["amount_total"], "315000.00")
        self.assertEqual(set(body["lines"][0]), LINE_KEYS)
        self.assertEqual(body["lines"][0]["qty"], "10.50")
        self.assertEqual(body["lines"][0]["date_planned"], "2026-11-25")
        self.assertEqual(body["expected_date"], "2026-11-30")

        record = SyncRecord.objects.get(
            resource=SyncResource.PURCHASE_ORDER.value,
            resource_id=str(body["id"]),
            stage=SyncStage.PURCHASE_ORDER_PUSH.value,
        )
        self.assertEqual(record.status, SyncStatus.PENDING)
        self.assertEqual(record.payload["partner_ref"], f"PO-{year}-0001")

    def test_create_nomor_berlanjut_dan_vendor_wajib(self):
        first = self.api.post(PO_URL, self.payload(), format="json").json()
        second = self.api.post(PO_URL, self.payload(), format="json").json()

        self.assertNotEqual(first["code"], second["code"])
        self.assertTrue(second["code"].endswith("-0002"))

        tanpa = self.payload()
        tanpa.pop("vendor_id")
        kosong = self.api.post(PO_URL, tanpa, format="json")
        asing = self.api.post(PO_URL, self.payload(vendor_id=999999), format="json")

        self.assertEqual(kosong.status_code, 400)
        self.assertIn("vendor_id", kosong.json()["detail"])
        self.assertEqual(asing.status_code, 400)
        self.assertIn("tidak ditemukan", asing.json()["detail"])

    def test_create_kode_manual_duplikat_dan_state_400(self):
        self.api.post(PO_URL, self.payload(code="PO-MANUAL"), format="json")

        duplikat = self.api.post(PO_URL, self.payload(code="PO-MANUAL"), format="json")
        state = self.api.post(PO_URL, self.payload(state="CONFIRMED"), format="json")

        self.assertEqual(duplikat.status_code, 400)
        self.assertIn("sudah dipakai", duplikat.json()["detail"])
        self.assertEqual(state.status_code, 400)
        self.assertIn("/confirm/", state.json()["detail"])

    def test_create_lines_kosong_atau_invalid_rollback_atomic(self):
        kosong = self.api.post(PO_URL, self.payload(lines=[]), format="json")
        cacat = self.api.post(
            PO_URL,
            self.payload(
                lines=[
                    {"product_id": self.product.pk, "qty": "1.00", "price_unit": "1000.00"},
                    {"product_id": 999999, "qty": "1.00", "price_unit": "1000.00"},
                ]
            ),
            format="json",
        )

        self.assertEqual(kosong.status_code, 400)
        self.assertEqual(cacat.status_code, 400)
        self.assertIn("lines[1]", cacat.json()["detail"])
        self.assertEqual(PurchaseOrder.objects.count(), 0)
        self.assertEqual(PurchaseOrderLine.objects.count(), 0)

    def test_create_qty_nol_harga_negatif_dan_tanggal_ngawur_400(self):
        nol = self.api.post(
            PO_URL,
            self.payload(lines=[{"product_id": self.product.pk, "qty": "0", "price_unit": "1.00"}]),
            format="json",
        )
        negatif = self.api.post(
            PO_URL,
            self.payload(
                lines=[{"product_id": self.product.pk, "qty": "1.00", "price_unit": "-5.00"}]
            ),
            format="json",
        )
        tanggal = self.api.post(PO_URL, self.payload(expected_date="besok"), format="json")

        self.assertEqual(nol.status_code, 400)
        self.assertIn("qty", nol.json()["detail"])
        self.assertEqual(negatif.status_code, 400)
        self.assertEqual(tanggal.status_code, 400)
        self.assertIn("expected_date", tanggal.json()["detail"])

    def test_create_harga_kosong_pakai_cost_price_dan_pajak(self):
        response = self.api.post(
            PO_URL,
            self.payload(
                lines=[
                    {
                        "product_id": self.product.pk,
                        "qty": "2.00",
                        "tax_ids": [self.tax.pk],
                    }
                ]
            ),
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        line = response.json()["lines"][0]
        self.assertEqual(line["price_unit"], "30000.00")
        self.assertEqual(line["subtotal"], "60000.00")
        self.assertEqual(line["tax_ids"], [self.tax.pk])


class PurchaseOrderUpdateDeleteTests(PurchaseOrderTestCase):
    """Update/delete hanya DRAFT + replace lines atomic."""

    def _create(self, **overrides):
        return self.api.post(PO_URL, self.payload(**overrides), format="json").json()

    def test_update_draft_ok_dan_replace_lines(self):
        po = self._create()

        response = self.api.put(
            detail_url(po["id"]),
            {
                "vendor_id": self.vendor_no_odoo.pk,
                "notes": "diubah",
                "lines": [
                    {"product_id": self.product.pk, "qty": "3.00", "price_unit": "10000.00"},
                    {"product_id": self.product.pk, "qty": "1.50", "price_unit": "20000.00"},
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["vendor_id"], self.vendor_no_odoo.pk)
        self.assertEqual(body["notes"], "diubah")
        self.assertEqual(body["lines_count"], 2)
        self.assertEqual(body["amount_total"], "60000.00")

    def test_update_tanpa_lines_tidak_menyentuh_baris(self):
        po = self._create()

        response = self.api.put(detail_url(po["id"]), {"notes": "catatan saja"}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["lines_count"], 1)
        self.assertEqual(response.json()["notes"], "catatan saja")

    def test_update_setelah_confirm_400(self):
        po = self._create()
        self.api.post(action_url(po["id"], "confirm"), {}, format="json")

        response = self.api.put(detail_url(po["id"]), {"notes": "x"}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("DRAFT", response.json()["detail"])

    def test_delete_draft_ok_dan_hapus_ledger(self):
        po = self._create()

        response = self.api.delete(detail_url(po["id"]))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["deleted"])
        self.assertFalse(PurchaseOrder.objects.filter(pk=po["id"]).exists())
        self.assertFalse(
            SyncRecord.objects.filter(
                resource=SyncResource.PURCHASE_ORDER.value, resource_id=str(po["id"])
            ).exists()
        )

    def test_delete_setelah_confirm_400(self):
        po = self._create()
        self.api.post(action_url(po["id"], "confirm"), {}, format="json")

        response = self.api.delete(detail_url(po["id"]))

        self.assertEqual(response.status_code, 400)
        self.assertIn("DRAFT", response.json()["detail"])

    def test_detail_dan_update_404(self):
        self.assertEqual(self.api.get(detail_url(999999)).status_code, 404)
        self.assertEqual(
            self.api.put(detail_url(999999), {"notes": "x"}, format="json").status_code, 404
        )


class PurchaseOrderTransitionTests(PurchaseOrderTestCase):
    """State machine §14: CONFIRMED (push), DONE (manual), CANCELLED."""

    def _create(self, price="1000.00", vendor=None, product=None, **overrides):
        vendor = vendor or self.vendor
        product = product or self.product

        return self.api.post(
            PO_URL,
            self.payload(
                vendor_id=vendor.pk,
                lines=[{"product_id": product.pk, "qty": "2.00", "price_unit": price}],
                **overrides,
            ),
            format="json",
        ).json()

    def test_confirm_draft_ok_enqueue_push_dan_ledger_pending(self):
        po = self._create()

        with mock.patch(
            "apps_industry.garment.services.purchase_order_services._enqueue_push",
            return_value="task-po-1",
        ) as enqueue:
            response = self.api.post(action_url(po["id"], "confirm"), {}, format="json")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["state"], "CONFIRMED")
        self.assertEqual(body["task_id"], "task-po-1")
        self.assertTrue(body["queued"])
        self.assertEqual(body["allowed_actions"], ["DONE", "CANCELLED"])
        enqueue.assert_called_once()

    def test_confirm_tanpa_harga_400(self):
        po = self._create(price="0")

        response = self.api.post(action_url(po["id"], "confirm"), {}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("Harga satuan", response.json()["detail"])
        self.assertEqual(PurchaseOrder.objects.get(pk=po["id"]).state, "DRAFT")

    def test_confirm_vendor_tanpa_odoo_id_400(self):
        po = self._create(vendor=self.vendor_no_odoo)

        response = self.api.post(action_url(po["id"], "confirm"), {}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("odoo_id", response.json()["detail"])
        self.assertEqual(PurchaseOrder.objects.get(pk=po["id"]).state, "DRAFT")

    def test_transisi_tidak_diizinkan_dan_done_manual(self):
        po = self._create()

        done_dari_draft = self.api.post(action_url(po["id"], "done"), {}, format="json")

        self.assertEqual(done_dari_draft.status_code, 400)
        self.assertIn("tidak diizinkan", done_dari_draft.json()["detail"])

        self.api.post(action_url(po["id"], "confirm"), {}, format="json")
        dobel_confirm = self.api.post(action_url(po["id"], "confirm"), {}, format="json")
        done = self.api.post(action_url(po["id"], "done"), {}, format="json")

        self.assertEqual(dobel_confirm.status_code, 400)
        self.assertEqual(done.status_code, 200)
        self.assertEqual(done.json()["state"], "DONE")
        self.assertEqual(done.json()["allowed_actions"], [])

    def test_cancel_draft_tanpa_push_dan_cancel_confirmed_dengan_odoo_id(self):
        draft = self._create()

        with mock.patch(
            "apps_industry.garment.services.purchase_order_services._enqueue_push",
            return_value="task-c",
        ) as enqueue:
            response = self.api.post(action_url(draft["id"], "cancel"), {}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], "CANCELLED")
        self.assertIsNone(response.json()["task_id"])
        enqueue.assert_not_called()

        confirmed = self._create()
        PurchaseOrder.objects.filter(pk=confirmed["id"]).update(odoo_id=999)
        PurchaseOrder.objects.filter(pk=confirmed["id"]).update(state="CONFIRMED")

        with mock.patch(
            "apps_industry.garment.services.purchase_order_services._enqueue_push",
            return_value="task-x",
        ) as enqueue_cancel:
            response2 = self.api.post(
                action_url(confirmed["id"], "cancel"), {"reason": "vendor batal"}, format="json"
            )

        self.assertEqual(response2.status_code, 200)
        self.assertEqual(response2.json()["state"], "CANCELLED")
        self.assertEqual(response2.json()["task_id"], "task-x")
        enqueue_cancel.assert_called_once()

    def test_action_tidak_dikenal_404(self):
        po = self._create()

        response = self.api.post(action_url(po["id"], "approve"), {}, format="json")

        self.assertEqual(response.status_code, 404)
        self.assertIn("tidak dikenal", response.json()["detail"])


class PurchaseOrderPermissionAndListTests(PurchaseOrderTestCase):
    """Izin (anonim/non-role/PURCHASING) + list/filter/pagination."""

    def test_anonim_403_non_role_403_dan_purchasing_boleh(self):
        po = self.api.post(PO_URL, self.payload(), format="json").json()
        anonim = self.as_user(None)

        self.assertEqual(anonim.get(PO_URL).status_code, 403)
        self.assertEqual(anonim.post(PO_URL, self.payload(), format="json").status_code, 403)

        operator = self.as_user(self.operator)
        self.assertEqual(operator.get(PO_URL).status_code, 200)  # baca boleh
        self.assertEqual(operator.post(PO_URL, self.payload(), format="json").status_code, 403)
        self.assertEqual(
            operator.put(detail_url(po["id"]), {"notes": "x"}, format="json").status_code, 403
        )
        self.assertEqual(operator.delete(detail_url(po["id"])).status_code, 403)
        self.assertEqual(
            operator.post(action_url(po["id"], "confirm"), {}, format="json").status_code, 403
        )

        # Role PURCHASING (default client) boleh menulis.
        self.assertEqual(self.api.post(PO_URL, self.payload(), format="json").status_code, 201)

    def test_list_envelope_filter_state_search_dan_vendor(self):
        first = self.api.post(PO_URL, self.payload(code="PO-LIST-1"), format="json").json()
        self.api.post(
            PO_URL, self.payload(vendor_id=self.vendor_no_odoo.pk), format="json"
        )
        self.api.post(action_url(first["id"], "confirm"), {}, format="json")

        body = self.api.get(PO_URL).json()

        self.assertEqual(set(body), ENVELOPE_KEYS)
        self.assertEqual(body["total_count"], 2)
        self.assertEqual(set(body["rows"][0]), ROW_KEYS)

        draft = self.api.get(PO_URL, {"state": "draft"}).json()
        confirmed = self.api.get(PO_URL, {"state": "CONFIRMED"}).json()
        cari = self.api.get(PO_URL, {"search": "Supplier B"}).json()
        vendor = self.api.get(PO_URL, {"vendor_id": self.vendor.pk}).json()

        self.assertEqual(draft["total_count"], 1)
        self.assertEqual(confirmed["total_count"], 1)
        self.assertEqual(cari["total_count"], 1)
        self.assertEqual(vendor["total_count"], 1)

    def test_list_pagination_dan_param_invalid_400(self):
        self.api.post(PO_URL, self.payload(), format="json")
        self.api.post(PO_URL, self.payload(), format="json")

        page1 = self.api.get(PO_URL, {"limit": 1}).json()

        self.assertEqual(page1["total_count"], 2)
        self.assertTrue(page1["has_more"])
        self.assertEqual(page1["next_cursor"], 1)

        self.assertEqual(self.api.get(PO_URL, {"limit": "abc"}).status_code, 400)
        self.assertEqual(self.api.get(PO_URL, {"state": "NGACO"}).status_code, 400)
        self.assertEqual(self.api.get(PO_URL, {"vendor_id": "x"}).status_code, 400)


class PurchaseOrderLedgerTests(PurchaseOrderTestCase):
    """Ledger ``PURCHASE_ORDER_PUSH`` + ``AuditLog`` per operasi."""

    def test_syncrecord_dan_auditlog_per_transisi(self):
        po = self.api.post(PO_URL, self.payload(), format="json").json()
        record = SyncRecord.objects.get(
            resource=SyncResource.PURCHASE_ORDER.value,
            resource_id=str(po["id"]),
            stage=SyncStage.PURCHASE_ORDER_PUSH.value,
        )
        self.assertEqual(record.status, SyncStatus.PENDING)

        self.api.post(action_url(po["id"], "confirm"), {}, format="json")
        self.api.post(action_url(po["id"], "cancel"), {"reason": "tes"}, format="json")

        actions = sorted(
            AuditLog.objects.filter(
                resource=SyncResource.PURCHASE_ORDER.value, resource_id=str(po["id"])
            ).values_list("action", flat=True)
        )
        self.assertEqual(
            actions, ["purchase_order.cancel", "purchase_order.confirm", "purchase_order.create"]
        )
        record.refresh_from_db()
        self.assertEqual(record.payload["state"], "CANCELLED")
        self.assertEqual(record.payload["lines"][0]["qty"], "10.50")


class PurchaseOrderSyncOdooStateTests(PurchaseOrderTestCase):
    """Endpoint read-only ``sync-odoo-state`` (tanpa menulis field MES)."""

    def _create(self, odoo_id=None):
        po = self.api.post(PO_URL, self.payload(), format="json").json()
        if odoo_id is not None:
            PurchaseOrder.objects.filter(pk=po["id"]).update(odoo_id=odoo_id)

        return po

    def test_sync_state_mengembalikan_state_odoo(self):
        po = self._create(odoo_id=13)

        with mock.patch(
            "integrations.erp_sync.client.get_odoo_rpc_client",
            return_value=odoo_client_stub([{"name": "P00013", "state": "purchase"}]),
        ):
            response = self.api.post(sync_state_url(po["id"]), {}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(), {"odoo_id": 13, "odoo_state": "purchase", "odoo_name": "P00013"}
        )
        # Read-only: state MES TIDAK berubah.
        self.assertEqual(PurchaseOrder.objects.get(pk=po["id"]).state, "DRAFT")

    def test_sync_state_guard_tanpa_odoo_id_dan_tidak_ada_di_odoo(self):
        tanpa = self._create()
        kosong = self.api.post(sync_state_url(tanpa["id"]), {}, format="json")

        self.assertEqual(kosong.status_code, 400)
        self.assertIn("odoo_id", kosong.json()["detail"])

        ada = self._create(odoo_id=99)
        with mock.patch(
            "integrations.erp_sync.client.get_odoo_rpc_client",
            return_value=odoo_client_stub([]),
        ):
            hilang = self.api.post(sync_state_url(ada["id"]), {}, format="json")

        self.assertEqual(hilang.status_code, 400)
        self.assertIn("tidak ditemukan di Odoo", hilang.json()["detail"])

        operator = self.as_user(self.operator)
        self.assertEqual(
            operator.post(sync_state_url(ada["id"]), {}, format="json").status_code, 403
        )


class PurchaseOrderPushTaskTests(PurchaseOrderTestCase):
    """Task push ``purchase.order`` — payload, guard odoo_id, SENT + odoo_id tersimpan."""

    def _confirmed_po(self, product=None, vendor=None):
        product = product or self.product
        vendor = vendor or self.vendor
        po = self.api.post(
            PO_URL,
            self.payload(
                vendor_id=vendor.pk,
                lines=[
                    {
                        "product_id": product.pk,
                        "qty": "4.00",
                        "price_unit": "25000.00",
                        "tax_ids": [self.tax.pk],
                        "date_planned": "2026-11-25",
                    }
                ],
            ),
            format="json",
        ).json()
        with mock.patch.object(purchase_order_services, "_enqueue_push", return_value=None):
            result = purchase_order_services.confirm_purchase_order(
                PurchaseOrder.objects.get(pk=po["id"])
            )
        self.assertIsNone(result.error)

        return PurchaseOrder.objects.get(pk=po["id"])

    def test_purchase_order_values_payload_odoo(self):
        po = self._confirmed_po()
        payload = purchase_order_services.purchase_order_payload(po)

        values = purchase_order_values(payload)

        self.assertEqual(values["partner_id"], 45)
        self.assertEqual(values["partner_ref"], po.code)
        # `picking_type_id`/`company_id`/`currency_id`/`date_order`/`name` TIDAK dikirim
        # (default_get Odoo mengisinya sendiri, termasuk nomor `P00013`).
        for forbidden in ("picking_type_id", "company_id", "currency_id", "date_order", "name"):
            self.assertNotIn(forbidden, values)

        line = values["order_line"][0][2]
        self.assertEqual(values["order_line"][0][:2], (0, 0))
        self.assertEqual(line["product_id"], 91)
        self.assertEqual(line["product_qty"], 4.0)
        self.assertEqual(line["price_unit"], 25000.0)
        self.assertEqual(line["date_planned"], "2026-11-25 00:00:00")
        # ⚠️ `taxes_id` (m2m) — BUKAN `tax_id` (probe: `tax_id` tidak ada di PO line).
        self.assertEqual(line["taxes_id"], [(6, 0, [20])])
        self.assertNotIn("tax_id", line)

    def test_purchase_order_values_guard_odoo_id(self):
        po = self._confirmed_po(product=self.product_no_odoo)
        payload = purchase_order_services.purchase_order_payload(po)

        with self.assertRaises(MasterPushError) as ctx:
            purchase_order_values(payload)

        self.assertIn("odoo_id", str(ctx.exception))
        self.assertIn("BENANG-JAHIT", str(ctx.exception))

        # Vendor tanpa odoo_id sudah ditolak 400 di endpoint /confirm/, jadi payload
        # disusun manual untuk membuktikan guard task-nya juga aktif.
        payload_vendor = purchase_order_services.purchase_order_payload(self._confirmed_po())
        payload_vendor["vendor_odoo_id"] = None

        with self.assertRaises(MasterPushError):
            purchase_order_values(payload_vendor)

    def test_push_sukses_menyimpan_odoo_id_dan_mark_sent(self):
        po = self._confirmed_po()
        record = SyncRecord.objects.get(
            resource=SyncResource.PURCHASE_ORDER.value, resource_id=str(po.pk)
        )

        with mock.patch(
            "integrations.erp_sync.tasks_purchase_order_push._push_create", return_value="777"
        ) as create:
            result = push_purchase_order.run(po.pk, record.pk, "create")

        self.assertEqual(result["status"], "sent")
        self.assertEqual(result["erp_id"], "777")
        create.assert_called_once()
        po.refresh_from_db()
        self.assertEqual(po.odoo_id, 777)
        record.refresh_from_db()
        self.assertEqual(record.status, SyncStatus.SENT)
        self.assertEqual(record.erp_id, "777")

    def test_push_noop_dev_dan_duplicate_diabaikan(self):
        po = self._confirmed_po()
        record = SyncRecord.objects.get(
            resource=SyncResource.PURCHASE_ORDER.value, resource_id=str(po.pk)
        )

        with mock.patch(
            "integrations.erp_sync.tasks_purchase_order_push.is_noop_mode", return_value=True
        ):
            first = push_purchase_order.run(po.pk, record.pk, "create")
            second = push_purchase_order.run(po.pk, record.pk, "create")

        self.assertEqual(first["status"], "sent")
        self.assertTrue(str(first["erp_id"]).startswith("NULL-"))
        self.assertEqual(second["status"], "duplicate-ignored")
        po.refresh_from_db()
        self.assertIsNone(po.odoo_id)  # no-op tidak menyimpan id ERP


class PurchaseOrderNonBreakingTests(PurchaseOrderTestCase):
    """B10 monitoring + I3/I6 tetap seperti semula (H2.2 tidak menyentuhnya)."""

    def test_b10_monitoring_tetap_bentuk_lama(self):
        transport = mock.MagicMock()
        transport.fetch_purchase_orders.return_value = [
            {
                "id": 1,
                "name": "P00001",
                "partner_id": [45, "PT Supplier A"],
                "state": "purchase",
                "date_order": "2026-10-06 10:00:00",
                "date_planned": "2026-10-10 10:00:00",
                "amount_total": 1500000.0,
            }
        ]
        transport.fetch_purchase_order_lines.return_value = []

        with mock.patch("integrations.erp_sync.monitoring.get_transport", return_value=transport):
            response = self.api.get(B10_URL)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), ENVELOPE_KEYS)
        self.assertEqual(
            set(body["rows"][0]),
            {
                "id",
                "name",
                "partner_name",
                "state",
                "date_order",
                "date_planned",
                "amount_total",
                "vendor_code",
                "lines",
            },
        )
        # Path CRUD H2.2 TIDAK menimpa B10 (dua endpoint berbeda).
        self.assertEqual(transport.fetch_purchase_orders.call_count, 1)

    def test_i3_dan_i6_konstanta_tidak_berubah(self):
        from integrations.erp_sync.services import material_readiness

        self.assertEqual(material_readiness.PO_STATES, ("purchase", "done"))
        self.assertEqual(
            material_readiness.MaterialReadinessService._vendor_bills([], [], set()),
            ([], material_readiness.MaterialReadiness.VendorBillStatus.NONE, 0.0),
        )







