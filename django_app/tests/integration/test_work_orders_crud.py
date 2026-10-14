"""Test H2.3 — Work Order CRUD + split + generate (`/api/v1/garmen/work-orders/…`).

Cakupan: create (nomor ``WO-<TAHUN>-<SEQ>`` dari Sprint C; kompatibel F2), update
DRAFT-only (guard ``qty_planned >= qty_done``), delete **hibrida** (hard delete DRAFT
tanpa Bundle / soft delete `CANCELLED` / 409 untuk yang sudah terminal), split
(sum qty = sumber), batch generate dari Order (idempoten), izin (anonim 403) dan
ledger ``SKIPPED`` + ``AuditLog`` (WO = **MES-only**: Odoo `mrp.workorder` = operasi
per `mrp.production`, tidak ada padanan WO per OrderLine).

Non-breaking yang diuji di sini: list F3 tetap **5 key** + AllowAny, detail F3 tetap
kontrak lamanya (+ `version`), jalur create F2 (`POST /work-orders/`) tetap 201,
transisi state via ActionView existing masih jalan, dan guard H2.1 `done_order`
(semua WO DONE/CANCELLED).
"""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.models import Bundle, Order, OrderLine, WorkOrder
from apps_industry.garment.services import order_services, work_order_services
from core.audit.models import AuditLog
from core.auth.models import Role, User
from integrations.erp_sync.models import SyncRecord, SyncResource, SyncStage, SyncStatus
from master import sequence_services
from master.models import Partner, Product

WO_URL = "/api/v1/garmen/work-orders/"
ORDERS_URL = "/api/v1/garmen/orders/"
ENVELOPE_KEYS = {"rows", "total_count", "has_more", "next_cursor", "resource", "industry"}
#: Kontrak list F3 yang di-pin `apps_industry/garment/tests/test_list_endpoint.py:44`.
F3_LIST_KEYS = {"id", "code", "state", "qty_planned", "qty_done"}


def detail_url(wo_id: int) -> str:
    """URL detail/CRUD satu WO (H2.3)."""
    return f"{WO_URL}{wo_id}/"


def split_url(wo_id: int) -> str:
    """URL split satu WO (H2.3)."""
    return f"{WO_URL}{wo_id}/split/"


def action_url(wo_id: int, action: str) -> str:
    """URL aksi state machine existing (`WO_START`/`WO_CLOSE`/`WO_CANCEL`)."""
    return f"{WO_URL}{wo_id}/{action}/"


def generate_url(order_id: int) -> str:
    """URL batch generate WO dari Order (H2.3)."""
    return f"{ORDERS_URL}{order_id}/generate-wo/"


class WorkOrderTestCase(TestCase):
    """Basis bersama: order + order line, user simulator (tanpa role) & admin."""

    @classmethod
    def setUpTestData(cls):
        cls.customer = Partner.objects.create(code="CUST-WO", name="PT Buyer WO", odoo_id=51)
        cls.product = Product.objects.create(
            code="KAOS-WO", name="Kaos WO", sale_price=50000, odoo_id=100, odoo_tmpl_id=10
        )
        cls.order = Order.objects.create(code="SO-WO-0001", customer=cls.customer, state="CONFIRMED")
        cls.line = OrderLine.objects.create(order=cls.order, product=cls.product, qty=20)
        cls.line2 = OrderLine.objects.create(order=cls.order, product=cls.product, qty=10)
        # F2/simulator memakai user TANPA role ⇒ tulis WO = IsAuthenticated saja.
        cls.sim = User.objects.create_user(username="sim-h23", password="x")  # noqa: S106
        cls.admin = User.objects.create_user(
            username="admin-h23",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.ADMIN),
        )

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.sim)

    def as_user(self, user):
        """Client terautentikasi sebagai ``user`` (anonim kalau ``None``)."""
        client = APIClient()
        if user is not None:
            client.force_authenticate(user)

        return client

    def payload(self, **overrides):
        """Payload create WO default (order line utama)."""
        data = {"order_line_id": self.line.pk}
        data.update(overrides)

        return data

    def make_wo(self, **kwargs):
        """WO DRAFT langsung di DB (untuk uji update/delete/split)."""
        code = kwargs.pop("code", f"WO-TEST-{WorkOrder.objects.count() + 1:03d}")

        return WorkOrder.objects.create(
            code=code, order_line=kwargs.pop("order_line", self.line), **kwargs
        )


class WorkOrderCreateTests(WorkOrderTestCase):
    """Create manual: nomor otomatis, fallback qty, validasi, ledger SKIPPED."""

    def test_create_ok_nomor_otomatis_dan_ledger_mes_only(self):
        year = sequence_services.current_year()

        response = self.api.post(WO_URL, self.payload(), format="json")

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["code"], f"WO-{year}-0001")
        self.assertEqual(body["state"], "DRAFT")
        self.assertEqual(body["qty_planned"], 20)  # fallback OrderLine.qty
        self.assertEqual(body["order_line_id"], self.line.pk)
        self.assertEqual(body["order_code"], self.order.code)
        self.assertEqual(body["product_code"], self.product.code)
        self.assertEqual(len(body["version"]), 64)

        record = SyncRecord.objects.get(
            resource=SyncResource.WORK_ORDER.value,
            resource_id=str(body["id"]),
            stage=SyncStage.WORK_ORDER_PUSH.value,
        )
        self.assertEqual(record.status, SyncStatus.SKIPPED)
        self.assertIn("mrp.workorder", record.last_error)
        self.assertEqual(record.payload["mes_only"], True)

    def test_create_nomor_berlanjut_dan_kode_manual(self):
        first = self.api.post(WO_URL, self.payload(), format="json").json()
        second = self.api.post(
            WO_URL, self.payload(order_line_id=self.line2.pk), format="json"
        ).json()

        self.assertTrue(first["code"].endswith("-0001"))
        self.assertTrue(second["code"].endswith("-0002"))

        manual = self.api.post(WO_URL, self.payload(code="WO-MANUAL-1"), format="json")

        self.assertEqual(manual.status_code, 201)
        self.assertEqual(manual.json()["code"], "WO-MANUAL-1")

    def test_create_order_line_wajib_dan_harus_ada(self):
        response = self.api.post(WO_URL, {}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("order_line_id", response.json()["detail"])

        asing = self.api.post(WO_URL, self.payload(order_line_id=999999), format="json")

        # 404 (bukan 400) = kontrak F2 yang dipertahankan H2.3.
        self.assertEqual(asing.status_code, 404)
        self.assertIn("tidak ditemukan", asing.json()["detail"])

    def test_create_kode_duplikat_dan_state_400(self):
        self.api.post(WO_URL, self.payload(code="WO-DUP-1"), format="json")

        duplikat = self.api.post(WO_URL, self.payload(code="WO-DUP-1"), format="json")
        state = self.api.post(WO_URL, self.payload(state="IN_PROGRESS"), format="json")

        self.assertEqual(duplikat.status_code, 400)
        self.assertIn("sudah dipakai", duplikat.json()["detail"])
        self.assertEqual(state.status_code, 400)
        self.assertIn("WO_START", state.json()["detail"])

    def test_create_qty_planned_eksplisit_dan_invalid(self):
        eksplisit = self.api.post(
            WO_URL, self.payload(order_line_id=self.line2.pk, qty_planned=4), format="json"
        )

        self.assertEqual(eksplisit.status_code, 201)
        self.assertEqual(eksplisit.json()["qty_planned"], 4)

        nol = self.api.post(WO_URL, self.payload(qty_planned=0), format="json")
        negatif = self.api.post(WO_URL, self.payload(qty_planned=-3), format="json")

        self.assertEqual(nol.status_code, 400)
        self.assertEqual(negatif.status_code, 400)
        self.assertIn("qty_planned", nol.json()["detail"])

    def test_create_order_line_qty_nol_tanpa_qty_planned_400(self):
        kosong = OrderLine.objects.create(order=self.order, product=self.product, qty=0)

        response = self.api.post(WO_URL, {"order_line_id": kosong.pk}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("qty_planned", response.json()["detail"])

    def test_create_anonim_403_dan_simulator_tanpa_role_boleh(self):
        self.assertEqual(
            self.as_user(None).post(WO_URL, self.payload(), format="json").status_code, 403
        )
        # user tanpa role (pola F2/simulator) TETAP boleh.
        self.assertEqual(self.api.post(WO_URL, self.payload(), format="json").status_code, 201)


class WorkOrderUpdateDeleteTests(WorkOrderTestCase):
    """Update DRAFT-only + delete hibrida (hard/soft/409)."""

    def test_update_draft_ok_dan_refresh_ledger(self):
        wo = self.make_wo(qty_planned=10)

        response = self.api.put(
            detail_url(wo.pk), {"qty_planned": 25, "code": "WO-UPD-1"}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["qty_planned"], 25)
        self.assertEqual(body["code"], "WO-UPD-1")

        record = SyncRecord.objects.get(
            resource=SyncResource.WORK_ORDER.value,
            resource_id=str(wo.pk),
            stage=SyncStage.WORK_ORDER_PUSH.value,
        )
        self.assertEqual(record.status, SyncStatus.SKIPPED)
        self.assertEqual(record.payload["qty_planned"], 25)

    def test_update_ditolak_kalau_qty_di_bawah_qty_done(self):
        wo = self.make_wo(qty_planned=10, qty_done=6)

        response = self.api.put(detail_url(wo.pk), {"qty_planned": 5}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("qty_done", response.json()["detail"])

    def test_update_bukan_draft_400_dan_404(self):
        wo = self.make_wo(state="IN_PROGRESS", qty_planned=10)

        bukan_draft = self.api.put(detail_url(wo.pk), {"qty_planned": 12}, format="json")
        hilang = self.api.put(detail_url(999999), {"qty_planned": 12}, format="json")

        self.assertEqual(bukan_draft.status_code, 400)
        self.assertIn("DRAFT", bukan_draft.json()["detail"])
        self.assertEqual(hilang.status_code, 404)

    def test_delete_draft_tanpa_bundle_hard_delete(self):
        wo = self.make_wo(qty_planned=5)
        wo_id = wo.pk
        work_order_services._write_ledger(wo, "create")

        response = self.api.delete(detail_url(wo_id))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["deleted"])
        self.assertFalse(WorkOrder.objects.filter(pk=wo_id).exists())
        self.assertFalse(
            SyncRecord.objects.filter(
                resource=SyncResource.WORK_ORDER.value, resource_id=str(wo_id)
            ).exists()
        )
        self.assertTrue(
            AuditLog.objects.filter(resource=SyncResource.WORK_ORDER.value, action="work_order.delete").exists()
        )

    def test_delete_draft_dengan_bundle_soft_delete(self):
        wo = self.make_wo(qty_planned=5)
        bundle = Bundle.objects.create(
            code="BND-WO-1", work_order=wo, size="M", qty=5, state="DRAFT"
        )

        response = self.api.delete(detail_url(wo.pk))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["cancelled"])
        work_order = WorkOrder.objects.get(pk=wo.pk)
        self.assertEqual(work_order.state, "CANCELLED")
        self.assertTrue(Bundle.objects.filter(pk=bundle.pk).exists())

    def test_delete_non_draft_soft_dan_cancelled_409(self):
        wo = self.make_wo(state="IN_PROGRESS", qty_planned=5)

        response = self.api.delete(detail_url(wo.pk))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["cancelled"])

        lagi = self.api.delete(detail_url(wo.pk))

        self.assertEqual(lagi.status_code, 409)
        self.assertIn("CANCELLED", lagi.json()["detail"])


class WorkOrderSplitTests(WorkOrderTestCase):
    """Split WO: sum qty = sumber, DRAFT, tanpa Bundle."""

    def test_split_ok_wo_asli_jadi_bagian_pertama(self):
        wo = self.make_wo(qty_planned=100)

        response = self.api.post(split_url(wo.pk), {"splits": [60, 40]}, format="json")

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["qty_planned"], 60)  # WO asli = bagian pertama
        self.assertEqual(len(body["work_orders"]), 1)
        self.assertEqual(body["work_orders"][0]["qty_planned"], 40)
        self.assertEqual(body["summary"]["created"], 1)

        total = sum(
            WorkOrder.objects.filter(order_line=self.line).values_list("qty_planned", flat=True)
        )
        self.assertEqual(total, 100)

    def test_split_tiga_bagian_dan_kode_otomatis(self):
        wo = self.make_wo(qty_planned=30)
        year = sequence_services.current_year()

        response = self.api.post(split_url(wo.pk), {"splits": [10, 10, 10]}, format="json")

        self.assertEqual(response.status_code, 201)
        codes = [child["code"] for child in response.json()["work_orders"]]
        self.assertEqual(len(codes), 2)
        self.assertTrue(all(code.startswith(f"WO-{year}-") for code in codes))
        self.assertEqual(WorkOrder.objects.filter(order_line=self.line).count(), 3)

    def test_split_total_tidak_sesuai_400(self):
        wo = self.make_wo(qty_planned=100)

        response = self.api.post(split_url(wo.pk), {"splits": [60, 30]}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("harus sama dengan qty_planned", response.json()["detail"])
        self.assertEqual(WorkOrder.objects.filter(order_line=self.line).count(), 1)

    def test_split_payload_invalid_400(self):
        wo = self.make_wo(qty_planned=10)

        satu = self.api.post(split_url(wo.pk), {"splits": [10]}, format="json")
        nol = self.api.post(split_url(wo.pk), {"splits": [10, 0]}, format="json")
        bukan_array = self.api.post(split_url(wo.pk), {"splits": "10,10"}, format="json")

        self.assertEqual(satu.status_code, 400)
        self.assertIn("minimal", satu.json()["detail"])
        self.assertEqual(nol.status_code, 400)
        self.assertEqual(bukan_array.status_code, 400)

    def test_split_bukan_draft_400_dan_punya_bundle_409(self):
        bukan_draft = self.make_wo(code="WO-ND-1", state="IN_PROGRESS", qty_planned=10)
        response = self.api.post(split_url(bukan_draft.pk), {"splits": [5, 5]}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("DRAFT", response.json()["detail"])

        draft = self.make_wo(code="WO-BND-1", qty_planned=10)
        Bundle.objects.create(code="BND-SPLIT-1", work_order=draft, size="L", qty=10, state="DRAFT")

        konflik = self.api.post(split_url(draft.pk), {"splits": [5, 5]}, format="json")

        self.assertEqual(konflik.status_code, 409)
        self.assertIn("bundle", konflik.json()["detail"])


class WorkOrderGenerateTests(WorkOrderTestCase):
    """Batch generate WO dari Order (idempoten) + guard izin."""

    def setUp(self):
        super().setUp()
        # Endpoint generate ada di resource Order (H2.1) ⇒ tulis = ADMIN/OWNER.
        self.api = self.as_user(self.admin)

    def test_generate_membuat_wo_untuk_semua_order_line(self):
        response = self.api.post(generate_url(self.order.pk), {}, format="json")

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["summary"], {"created": 2, "skipped": 0})
        self.assertEqual(len(body["work_orders"]), 2)
        self.assertEqual(sorted(wo["qty_planned"] for wo in body["work_orders"]), [10, 20])
        self.assertEqual(body["order_code"], self.order.code)
        self.assertEqual(WorkOrder.objects.filter(order_line__order=self.order).count(), 2)

    def test_generate_idempoten(self):
        self.api.post(generate_url(self.order.pk), {}, format="json")

        kedua = self.api.post(generate_url(self.order.pk), {}, format="json")

        self.assertEqual(kedua.status_code, 201)
        self.assertEqual(kedua.json()["summary"], {"created": 0, "skipped": 2})
        self.assertEqual(kedua.json()["work_orders"], [])
        self.assertEqual(WorkOrder.objects.filter(order_line__order=self.order).count(), 2)

    def test_generate_hanya_untuk_order_line_tanpa_wo(self):
        self.make_wo(order_line=self.line, qty_planned=20)

        response = self.api.post(generate_url(self.order.pk), {}, format="json")

        self.assertEqual(response.json()["summary"], {"created": 1, "skipped": 1})

    def test_generate_404_order_dan_guard_izin(self):
        self.assertEqual(self.api.post(generate_url(999999), {}, format="json").status_code, 404)

        # Anonim & user tanpa role (simulator) ⇒ 403 (endpoint Order = ADMIN/OWNER).
        for user in (None, self.sim):
            client = self.as_user(user)
            response = client.post(generate_url(self.order.pk), {}, format="json")
            self.assertEqual(response.status_code, 403)


class WorkOrderNonBreakingTests(WorkOrderTestCase):
    """Konsumen existing WAJIB tetap hijau (list/detail F3, F2, ActionView, H2.1)."""

    def test_list_f3_tetap_lima_key_allowany(self):
        wo = self.make_wo(code="WO-F3-1", qty_planned=7)
        anonim = self.as_user(None)

        response = anonim.get(WO_URL)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), ENVELOPE_KEYS)
        row = next(item for item in body["rows"] if item["id"] == wo.pk)
        self.assertEqual(set(row), F3_LIST_KEYS)

    def test_detail_get_mempertahankan_kontrak_f3(self):
        wo = self.make_wo(code="WO-F3-2", qty_planned=20, qty_done=5)
        anonim = self.as_user(None)

        response = anonim.get(detail_url(wo.pk))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["code"], "WO-F3-2")
        self.assertEqual(body["state"], "DRAFT")
        self.assertEqual(body["qty_planned"], 20)
        self.assertEqual(body["qty_done"], 5)
        self.assertEqual(body["order_code"], self.order.code)
        self.assertEqual(body["product_code"], self.product.code)
        self.assertEqual(len(body["version"]), 64)
        # Aditif H2.3:
        self.assertIn("bundles", body)
        self.assertIn("allowed_actions", body)
        self.assertIn("order_line_id", body)

    def test_detail_404_dan_aksi_state_machine_existing(self):
        self.assertEqual(self.api.get(detail_url(999999)).status_code, 404)

        wo = self.make_wo(qty_planned=10)
        response = self.api.post(action_url(wo.pk, "WO_START"), {}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(WorkOrder.objects.get(pk=wo.pk).state, "IN_PROGRESS")

    def test_jalur_create_f2_tetap_201_draft(self):
        """`POST /work-orders/` versi F2 (kode `WO-<ol>-<seq>`) TIDAK diubah."""
        response = self.api.post(WO_URL, {"order_line_id": self.line.pk}, format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["state"], "DRAFT")
        self.assertEqual(response.json()["qty_planned"], self.line.qty)

    def test_h2_1_done_order_butuh_semua_wo_selesai(self):
        order = Order.objects.create(code="SO-WO-0002", customer=self.customer, state="CONFIRMED")
        line = OrderLine.objects.create(order=order, product=self.product, qty=5)
        pending = WorkOrder.objects.create(code="WO-PEND-1", order_line=line, qty_planned=5)

        ditolak = order_services.done_order(order)
        self.assertIsNotNone(ditolak.error)
        self.assertIn("WorkOrder", ditolak.error)

        pending.state = "DONE"
        pending.save(update_fields=("state", "updated_at"))
        diterima = order_services.done_order(order)

        self.assertIsNone(diterima.error)
        self.assertEqual(diterima.order.state, "DONE")

    def test_audit_ledger_action_tercatat(self):
        wo = self.make_wo(qty_planned=5)

        self.api.put(detail_url(wo.pk), {"qty_planned": 6}, format="json")

        actions = sorted(
            AuditLog.objects.filter(
                resource=SyncResource.WORK_ORDER.value, resource_id=str(wo.pk)
            ).values_list("action", flat=True)
        )
        self.assertEqual(actions, ["work_order.update"])



