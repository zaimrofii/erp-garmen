"""Test H2.6 — Stock Transfer (`/api/v1/inventory/transfer*`) MES → Odoo.

Cakupan: validasi create (`qty`/`from != to`/usage internal/produk), create `DRAFT`
(+snapshot `qty_before`), `?commit=true`, list + filter + pagination, detail, commit
(`DRAFT → COMMITTED` + ledger `PENDING` + enqueue), guard commit (`odoo_id` 3 sisi,
tracking lot/serial), adapter **picking path** (`stock.picking` create →
`button_validate` + context `skip_backorder` → verifikasi `state == 'done'`), task push
(`SYNCED`/`FAILED`), dan non-breaking B7/B8/B30 + I4/I7 + **H2.5**.

Prinsip yang di-pin: **MES tidak menyimpan stok** (`docs/CHANGES-DETAIL-H1H5.md` §4) —
transfer hanya log + push satu arah; `stock.move` + `_action_done()` TIDAK dipakai
(private) melainkan `stock.picking.button_validate()` (publik).
"""

from __future__ import annotations

from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps_industry.garment.models import StockTransfer
from core.audit.models import AuditLog
from core.auth.models import Role, User
from integrations.erp_sync.adapters.base import ERPResponse
from integrations.erp_sync.adapters.odoo import OdooAdapter
from integrations.erp_sync.models import STAGE_STOCK_TRANSFER, SyncRecord, SyncResource, SyncStatus
from integrations.erp_sync.tasks_stock_transfer_push import push_stock_transfer
from master.models import Location, Product

TRANSFER_URL = "/api/v1/inventory/transfer/"
LIST_URL = "/api/v1/inventory/transfers/"

SERVICES = "apps_industry.garment.services.stock_transfer_services"
FETCH_QTY = f"{SERVICES}.fetch_stock_qty"
FETCH_TRACKING = f"{SERVICES}.fetch_product_tracking"
ENQUEUE = f"{SERVICES}._enqueue_push"
TASKS = "integrations.erp_sync.tasks_stock_transfer_push"
GET_ADAPTER = f"{TASKS}.get_adapter"

LEDGER = dict(resource=SyncResource.STOCK_TRANSFER.value, stage=STAGE_STOCK_TRANSFER)


def detail_url(transfer_id: int) -> str:
    """URL detail satu transfer (H2.6)."""
    return f"{LIST_URL}{transfer_id}/"


def commit_url(transfer_id: int) -> str:
    """URL commit satu transfer (H2.6)."""
    return f"{LIST_URL}{transfer_id}/commit/"


class FakeOdooClient:
    """Klien Odoo palsu untuk adapter transfer (merekam `execute_kw`, tanpa jaringan)."""

    def __init__(self, picking_state: str = "done", validate_result=None, picking_types=None):
        self.picking_state = picking_state
        self.validate_result = validate_result
        self.picking_types = (
            picking_types if picking_types is not None else [{"id": 5, "name": "Transfer Internal"}]
        )
        self.calls: list = []

    def execute_kw(self, model, method, args=None, kwargs=None):
        """Tiru `execute_kw` untuk pick type search/create/button_validate/search_read."""
        self.calls.append((model, method, args, kwargs))
        if (model, method) == ("stock.picking.type", "search_read"):
            return list(self.picking_types)
        if (model, method) == ("stock.picking", "create"):
            return [77]
        if (model, method) == ("stock.picking", "button_validate"):
            return self.validate_result
        if (model, method) == ("stock.picking", "search_read"):
            return [{"id": 77, "name": "WH/INT/00003", "state": self.picking_state}]

        return None


def transfer_payload(**overrides) -> dict:
    """Payload adapter default (hasil `transfer_push_payload` task)."""
    data = {
        "ref": "TRF-2026-0001",
        "product_odoo_id": 89,
        "from_location_odoo_id": 8,
        "to_location_odoo_id": 50,
        "qty": "5.00",
        "product_code": "KAIN-COTTON",
        "move_name": "TRF-2026-0001 opname",
        "origin": "TRF-2026-0001",
    }
    data.update(overrides)

    return data


class TransferBase(TestCase):
    """Basis bersama: produk + lokasi internal (2 sisi) + user simulator."""

    @classmethod
    def setUpTestData(cls):
        cls.product = Product.objects.create(code="KAIN-COTTON", name="Kain Cotton", odoo_id=89)
        cls.product_no_odoo = Product.objects.create(code="KAIN-BARU", name="Kain Baru")
        cls.from_loc = Location.objects.create(
            code="WH/STOK", name="Stok", usage=Location.Usage.INTERNAL, odoo_id=8
        )
        cls.to_loc = Location.objects.create(
            code="WH/PROD", name="Produksi", usage=Location.Usage.INTERNAL, odoo_id=50
        )
        cls.to_loc_no_odoo = Location.objects.create(
            code="WH/LOKAL", name="Lokal", usage=Location.Usage.INTERNAL
        )
        cls.loc_view = Location.objects.create(
            code="WH/VIEW", name="View", usage=Location.Usage.VIEW, odoo_id=1
        )
        cls.sim = User.objects.create_user(username="sim-h26", password="x")  # noqa: S106
        cls.admin = User.objects.create_user(  # noqa: S106 - kredensial test
            username="admin-h26",
            password="rahasia123",
            role=Role.objects.get(code=Role.Code.ADMIN),
        )

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.sim)

    def as_user(self, user):
        """Client terautentikasi (anonim bila ``user`` None)."""
        client = APIClient()
        if user is not None:
            client.force_authenticate(user)

        return client

    def payload(self, **overrides):
        """Payload create H2.6 default (5 unit dari WH/STOK ke WH/PROD)."""
        data = {
            "product_id": self.product.pk,
            "from_location_id": self.from_loc.pk,
            "to_location_id": self.to_loc.pk,
            "qty": "5",
            "reason": "Pindah ke lini produksi",
        }
        data.update(overrides)

        return data

    def make_transfer(self, **overrides):
        """Baris `StockTransfer` langsung di DB (bikin test commit ringkas)."""
        data = {
            "code": "TRF-TEST-1",
            "product": self.product,
            "from_location": self.from_loc,
            "to_location": self.to_loc,
            "qty": Decimal("5.00"),
            "qty_before": Decimal("60.00"),
            "reason": "Pindah lini",
            "state": StockTransfer.State.DRAFT,
        }
        data.update(overrides)

        return StockTransfer.objects.create(**data)


class StockTransferCreateTests(TransferBase):
    """`POST /api/v1/inventory/transfer/` — validasi + create DRAFT."""

    def test_create_ok_draft_dengan_snapshot_qty_before(self):
        with mock.patch(FETCH_QTY, return_value=Decimal("60.00")):
            response = self.api.post(TRANSFER_URL, self.payload(), format="json")

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["state"], "DRAFT")
        self.assertTrue(body["code"].startswith("TRF-"))
        self.assertEqual(body["qty"], "5.00")
        self.assertEqual(body["qty_before"], "60.00")
        self.assertEqual(body["from_location_code"], "WH/STOK")
        self.assertEqual(body["to_location_code"], "WH/PROD")
        self.assertIsNone(body["odoo_picking_id"])
        self.assertEqual(body["industry"], "garmen")
        self.assertEqual(StockTransfer.objects.count(), 1)

    def test_create_from_sama_to_400(self):
        response = self.api.post(
            TRANSFER_URL, self.payload(to_location_id=self.from_loc.pk), format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("TIDAK boleh sama", response.json()["detail"])
        self.assertEqual(StockTransfer.objects.count(), 0)

    def test_create_qty_nol_atau_negatif_400(self):
        for qty in ("0", "-3"):
            with self.subTest(qty=qty):
                response = self.api.post(TRANSFER_URL, self.payload(qty=qty), format="json")
                self.assertEqual(response.status_code, 400)
                self.assertIn("lebih besar dari 0", response.json()["detail"])

    def test_create_qty_bukan_angka_dan_terlalu_besar_400(self):
        bukan_angka = self.api.post(TRANSFER_URL, self.payload(qty="banyak"), format="json")
        terlalu_besar = self.api.post(TRANSFER_URL, self.payload(qty="1000001"), format="json")

        self.assertEqual(bukan_angka.status_code, 400)
        self.assertIn("angka", bukan_angka.json()["detail"])
        self.assertEqual(terlalu_besar.status_code, 400)
        self.assertIn("maksimal", terlalu_besar.json()["detail"])

    def test_create_lokasi_non_internal_400(self):
        from_view = self.api.post(
            TRANSFER_URL, self.payload(from_location_id=self.loc_view.pk), format="json"
        )
        to_view = self.api.post(
            TRANSFER_URL, self.payload(to_location_id=self.loc_view.pk), format="json"
        )

        self.assertEqual(from_view.status_code, 400)
        self.assertIn("internal", from_view.json()["detail"])
        self.assertEqual(to_view.status_code, 400)

    def test_create_produk_dan_lokasi_tidak_ada_404(self):
        produk = self.api.post(TRANSFER_URL, self.payload(product_id=999_999), format="json")
        lokasi = self.api.post(TRANSFER_URL, self.payload(from_location_id=999_999), format="json")

        self.assertEqual(produk.status_code, 404)
        self.assertEqual(lokasi.status_code, 404)

    def test_create_field_wajib_kosong_400(self):
        response = self.api.post(TRANSFER_URL, {"reason": "x"}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("product_id", response.json()["detail"])

    def test_create_anonim_403(self):
        response = self.as_user(None).post(TRANSFER_URL, self.payload(), format="json")

        self.assertEqual(response.status_code, 403)

    def test_create_menulis_audit_log(self):
        with mock.patch(FETCH_QTY, return_value=Decimal("1.00")):
            self.api.post(TRANSFER_URL, self.payload(), format="json")

        log = AuditLog.objects.filter(resource=SyncResource.STOCK_TRANSFER.value).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.action, "stock_transfer.create")

    def test_create_qty_before_none_kalau_odoo_tidak_terbaca(self):
        with mock.patch(FETCH_QTY, return_value=None):
            response = self.api.post(TRANSFER_URL, self.payload(), format="json")

        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.json()["qty_before"])

    def test_create_commit_true_langsung_committed(self):
        with (
            mock.patch(FETCH_QTY, return_value=Decimal("60.00")),
            mock.patch(FETCH_TRACKING, return_value="none"),
            mock.patch(ENQUEUE, return_value="task-trfs-1") as enqueue,
        ):
            response = self.api.post(f"{TRANSFER_URL}?commit=true", self.payload(), format="json")

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["state"], "COMMITTED")
        self.assertTrue(body["commit"]["ok"])
        self.assertEqual(body["commit"]["task_id"], "task-trfs-1")
        enqueue.assert_called_once()

        record = SyncRecord.objects.get(**LEDGER)
        self.assertEqual(record.status, SyncStatus.PENDING)
        self.assertEqual(record.resource_id, str(body["id"]))


class StockTransferReadTests(TransferBase):
    """List/detail/commit — envelope §3, filter, guard commit."""

    def test_list_envelope_dan_filter(self):
        self.make_transfer(code="TRF-1")
        self.make_transfer(
            code="TRF-2",
            to_location=self.to_loc_no_odoo,
            state=StockTransfer.State.COMMITTED,
            reason="Catatan lain",
        )

        all_rows = self.api.get(LIST_URL).json()
        self.assertEqual(
            set(all_rows),
            {"rows", "total_count", "has_more", "next_cursor", "resource", "industry"},
        )
        self.assertEqual(all_rows["total_count"], 2)
        self.assertEqual(all_rows["resource"], "stock_transfers")

        by_state = self.api.get(f"{LIST_URL}?state=COMMITTED").json()
        self.assertEqual(by_state["total_count"], 1)
        self.assertEqual(by_state["rows"][0]["code"], "TRF-2")

        by_product = self.api.get(f"{LIST_URL}?product_id={self.product.pk}").json()
        self.assertEqual(by_product["total_count"], 2)

        by_from = self.api.get(f"{LIST_URL}?from_location_id={self.from_loc.pk}").json()
        self.assertEqual(by_from["total_count"], 2)

        by_to = self.api.get(f"{LIST_URL}?to_location_id={self.to_loc_no_odoo.pk}").json()
        self.assertEqual(by_to["total_count"], 1)

        by_search = self.api.get(f"{LIST_URL}?search=Catatan").json()
        self.assertEqual(by_search["total_count"], 1)

        paged = self.api.get(f"{LIST_URL}?limit=1&offset=0").json()
        self.assertEqual(len(paged["rows"]), 1)
        self.assertTrue(paged["has_more"])

    def test_list_limit_tidak_valid_400_dan_anonim_403(self):
        self.assertEqual(self.api.get(f"{LIST_URL}?limit=0").status_code, 400)
        self.assertEqual(self.as_user(None).get(LIST_URL).status_code, 403)

    def test_detail_ok_dan_404(self):
        transfer = self.make_transfer()

        response = self.api.get(detail_url(transfer.pk))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["id"], transfer.pk)
        self.assertIsNone(body["sync"]["status"])
        self.assertEqual(body["product_code"], self.product.code)
        self.assertEqual(body["qty"], "5.00")

        self.assertEqual(self.api.get(detail_url(999_999)).status_code, 404)

    def test_commit_ok_enqueue_dan_ledger_pending(self):
        transfer = self.make_transfer()

        with (
            mock.patch(FETCH_TRACKING, return_value="none"),
            mock.patch(ENQUEUE, return_value="task-commit-trf-1") as enqueue,
        ):
            response = self.api.post(commit_url(transfer.pk), {}, format="json")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["state"], "COMMITTED")
        self.assertEqual(body["task_id"], "task-commit-trf-1")
        self.assertTrue(body["queued"])
        enqueue.assert_called_once()

        record = SyncRecord.objects.get(**LEDGER)
        self.assertEqual(record.status, SyncStatus.PENDING)
        self.assertEqual(record.payload["qty"], "5.00")
        self.assertEqual(record.payload["origin"], "TRF-TEST-1")

    def test_commit_guard_odoo_id_wajib_3_sisi(self):
        tanpa_produk = self.make_transfer(product=self.product_no_odoo, code="TRF-P")
        tanpa_asal = self.make_transfer(from_location=self.to_loc_no_odoo, code="TRF-A")
        tanpa_tujuan = self.make_transfer(to_location=self.to_loc_no_odoo, code="TRF-T")

        response_produk = self.api.post(commit_url(tanpa_produk.pk), {}, format="json")
        response_asal = self.api.post(commit_url(tanpa_asal.pk), {}, format="json")
        response_tujuan = self.api.post(commit_url(tanpa_tujuan.pk), {}, format="json")

        self.assertEqual(response_produk.status_code, 400)
        self.assertIn("odoo_id", response_produk.json()["detail"])
        self.assertEqual(response_asal.status_code, 400)
        self.assertIn("Lokasi asal", response_asal.json()["detail"])
        self.assertEqual(response_tujuan.status_code, 400)
        self.assertIn("Lokasi tujuan", response_tujuan.json()["detail"])
        self.assertEqual(StockTransfer.objects.get(pk=tanpa_produk.pk).state, "DRAFT")
        self.assertFalse(SyncRecord.objects.filter(**LEDGER).exists())

    def test_commit_tracking_lot_ditolak_400(self):
        transfer = self.make_transfer()

        with mock.patch(FETCH_TRACKING, return_value="lot"):
            response = self.api.post(commit_url(transfer.pk), {}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("lot/serial", response.json()["detail"])
        self.assertEqual(StockTransfer.objects.get(pk=transfer.pk).state, "DRAFT")

    def test_commit_dobel_409_dan_tidak_ada_404_dan_anonim_403(self):
        transfer = self.make_transfer(state=StockTransfer.State.SYNCED)

        dobel = self.api.post(commit_url(transfer.pk), {}, format="json")
        hilang = self.api.post(commit_url(999_999), {}, format="json")
        anonim = self.as_user(None).post(commit_url(transfer.pk), {})

        self.assertEqual(dobel.status_code, 409)
        self.assertIn("SYNCED", dobel.json()["detail"])
        self.assertEqual(hilang.status_code, 404)
        self.assertEqual(anonim.status_code, 403)


class StockTransferAdapterTests(TestCase):
    """`OdooAdapter.push_stock_transfer_wo` — picking path (klien Odoo di-mock)."""

    def test_push_sukses_create_picking_lalu_button_validate(self):
        client = FakeOdooClient()
        response = OdooAdapter(client=client).push_stock_transfer_wo(transfer_payload())

        self.assertTrue(response.ok)
        self.assertEqual(response.stage, "STOCK_TRANSFER")
        self.assertEqual(response.ref, "TRF-2026-0001")
        self.assertEqual(response.erp_id, "77")
        self.assertEqual(response.raw["picking_id"], 77)
        self.assertEqual(response.raw["picking_name"], "WH/INT/00003")
        self.assertEqual(response.raw["state"], "done")

        calls = [(model, method) for model, method, _a, _k in client.calls]
        self.assertEqual(
            calls,
            [
                ("stock.picking.type", "search_read"),
                ("stock.picking", "create"),
                ("stock.picking", "button_validate"),
                ("stock.picking", "search_read"),
            ],
        )
        values = client.calls[1][2][0][0]
        self.assertEqual(values["picking_type_id"], 5)
        self.assertEqual(values["location_id"], 8)
        self.assertEqual(values["location_dest_id"], 50)
        self.assertEqual(values["origin"], "TRF-2026-0001")
        move = values["move_ids"][0][2]
        self.assertEqual(move["product_id"], 89)
        self.assertEqual(move["product_uom_qty"], 5.0)
        self.assertEqual(move["location_id"], 8)
        self.assertEqual(move["location_dest_id"], 50)
        self.assertEqual(move["name"], "TRF-2026-0001 opname")

        ctx = client.calls[2][3]["context"]
        self.assertTrue(ctx["skip_backorder"])

    @override_settings(ODOO_PICKING_TYPE_INTERNAL_ID=42)
    def test_picking_type_dari_settings_tidak_hardcode(self):
        client = FakeOdooClient()
        response = OdooAdapter(client=client).push_stock_transfer_wo(transfer_payload())

        self.assertTrue(response.ok)
        calls = [(model, method) for model, method, _a, _k in client.calls]
        self.assertNotIn(("stock.picking.type", "search_read"), calls)
        self.assertEqual(client.calls[0][2][0][0]["picking_type_id"], 42)

    def test_picking_type_tidak_ditemukan_gagal_aman(self):
        client = FakeOdooClient(picking_types=[])

        response = OdooAdapter(client=client).push_stock_transfer_wo(transfer_payload())

        self.assertFalse(response.ok)
        self.assertIn("Tipe picking internal", response.error)

    def test_push_payload_kurang_field_ditolak(self):
        response = OdooAdapter(client=FakeOdooClient()).push_stock_transfer_wo({"ref": "TRF-1"})

        self.assertFalse(response.ok)
        self.assertIn("tidak lengkap", response.error)

    def test_push_qty_nol_atau_lokasi_sama_ditolak(self):
        client = FakeOdooClient()

        qty_nol = OdooAdapter(client=client).push_stock_transfer_wo(transfer_payload(qty="0"))
        asal_sama = OdooAdapter(client=client).push_stock_transfer_wo(
            transfer_payload(to_location_odoo_id=8)
        )

        self.assertFalse(qty_nol.ok)
        self.assertIn("> 0", qty_nol.error)
        self.assertFalse(asal_sama.ok)
        self.assertIn("sama", asal_sama.error)

    def test_push_tanpa_client_gagal_aman(self):
        from django.core.exceptions import ImproperlyConfigured

        with mock.patch(
            "integrations.erp_sync.client.get_odoo_rpc_client",
            side_effect=ImproperlyConfigured("credential kosong"),
        ):
            adapter = OdooAdapter()
            response = adapter.push_stock_transfer_wo(transfer_payload())

        self.assertIsNone(adapter.client)
        self.assertFalse(response.ok)
        self.assertIn("client", response.error)

    def test_push_wizard_atau_state_bukan_done_ditolak(self):
        wizard = OdooAdapter(client=FakeOdooClient(validate_result={"res_model": "wizard"})).push_stock_transfer_wo(
            transfer_payload()
        )
        belum_done = OdooAdapter(client=FakeOdooClient(picking_state="assigned")).push_stock_transfer_wo(
            transfer_payload()
        )

        self.assertFalse(wizard.ok)
        self.assertIn("wizard", wizard.error)
        self.assertFalse(belum_done.ok)
        self.assertIn("assigned", belum_done.error)


class FakeAdapter:
    """Adapter palsu untuk task push (hasil `ERPResponse` disiapkan test)."""

    name = "fake"

    def __init__(self, response: ERPResponse):
        self.response = response
        self.payloads: list = []

    def push_stock_transfer_wo(self, transfer: dict) -> ERPResponse:
        """Rekam payload & kembalikan respons yang sudah ditentukan."""
        self.payloads.append(dict(transfer))

        return self.response


class StockTransferTaskTests(TransferBase):
    """Task `erp_sync.push_stock_transfer` — SYNCED/FAILED/duplicate/no-op."""

    def make_committed(self, **overrides):
        """Transfer `COMMITTED` + ledger `PENDING` (siap di-push)."""
        from apps_industry.garment.services.stock_transfer_services import transfer_push_payload
        from integrations.erp_sync.idempotency import SyncIdempotency

        transfer = self.make_transfer(state=StockTransfer.State.COMMITTED, **overrides)
        record = SyncIdempotency().get_or_create_sync_record(
            SyncResource.STOCK_TRANSFER.value,
            transfer.pk,
            STAGE_STOCK_TRANSFER,
            transfer_push_payload(transfer),
        )

        return transfer, record

    def test_task_odoo_mode_sukses_menyimpan_picking(self):
        transfer, record = self.make_committed()
        adapter = FakeAdapter(
            ERPResponse(
                ok=True,
                erp_id="77",
                raw={"picking_id": 77, "picking_name": "WH/INT/00003", "state": "done"},
                stage="STOCK_TRANSFER",
                ref=transfer.code,
            )
        )

        with (
            mock.patch(f"{TASKS}.is_noop_mode", return_value=False),
            mock.patch(GET_ADAPTER, return_value=adapter),
        ):
            result = push_stock_transfer.apply(args=[transfer.pk, record.pk]).get()

        self.assertEqual(result["status"], "sent")
        transfer.refresh_from_db()
        self.assertEqual(transfer.state, "SYNCED")
        self.assertEqual(transfer.odoo_picking_id, 77)
        self.assertEqual(transfer.odoo_picking_name, "WH/INT/00003")
        self.assertEqual(transfer.last_error, "")
        self.assertEqual(adapter.payloads[0]["origin"], transfer.code)

        record.refresh_from_db()
        self.assertEqual(record.status, SyncStatus.SENT)
        self.assertEqual(record.erp_id, "77")

    def test_task_odoo_mode_gagal_menyimpan_error(self):
        transfer, record = self.make_committed()
        adapter = FakeAdapter(
            ERPResponse(
                ok=False,
                error="Picking WH/INT/00004 berstatus 'assigned' (bukan 'done').",
                stage="STOCK_TRANSFER",
                ref=transfer.code,
            )
        )

        with (
            mock.patch(f"{TASKS}.is_noop_mode", return_value=False),
            mock.patch(GET_ADAPTER, return_value=adapter),
        ):
            result = push_stock_transfer.apply(args=[transfer.pk, record.pk]).get()

        self.assertEqual(result["status"], "failed")
        transfer.refresh_from_db()
        self.assertEqual(transfer.state, "FAILED")
        self.assertIn("bukan 'done'", transfer.last_error)
        record.refresh_from_db()
        self.assertEqual(record.status, SyncStatus.FAILED)

    def test_task_noop_mode_sukses_tanpa_picking(self):
        transfer, record = self.make_committed()

        with mock.patch(f"{TASKS}.is_noop_mode", return_value=True):
            result = push_stock_transfer.apply(args=[transfer.pk, record.pk]).get()

        self.assertEqual(result["status"], "sent")
        self.assertTrue(str(result["erp_id"]).startswith("NULL-"))
        transfer.refresh_from_db()
        self.assertEqual(transfer.state, "SYNCED")
        self.assertIsNone(transfer.odoo_picking_id)

    def test_task_duplicate_ignored(self):
        from integrations.erp_sync.idempotency import SyncIdempotency

        transfer, record = self.make_committed()
        SyncIdempotency().mark_sent(record, "77")

        with (
            mock.patch(f"{TASKS}.is_noop_mode", return_value=False),
            mock.patch(GET_ADAPTER) as adapter,
        ):
            result = push_stock_transfer.apply(args=[transfer.pk, record.pk]).get()

        self.assertEqual(result["status"], "duplicate-ignored")
        adapter.assert_not_called()
        transfer.refresh_from_db()
        self.assertEqual(transfer.state, "COMMITTED")

    def test_task_transfer_tidak_ada(self):
        result = push_stock_transfer.apply(args=[999_999]).get()

        self.assertEqual(result["status"], "not-found")

    def test_task_transport_error_dicatat_lalu_raise(self):
        transfer, record = self.make_committed()

        class Boom:
            """Adapter yang selalu gagal (mensimulasikan koneksi Odoo putus)."""

            name = "boom"

            def push_stock_transfer_wo(self, payload):
                raise RuntimeError("koneksi Odoo putus")

        with (
            mock.patch(f"{TASKS}.is_noop_mode", return_value=False),
            mock.patch(GET_ADAPTER, return_value=Boom()),
            self.assertRaises(RuntimeError),
        ):
            push_stock_transfer.apply(args=[transfer.pk, record.pk]).get()

        record.refresh_from_db()
        self.assertEqual(record.status, SyncStatus.FAILED)
        transfer.refresh_from_db()
        self.assertEqual(transfer.state, "COMMITTED")


class StockTransferNonBreakingTests(TransferBase):
    """B7/B8/B30 + I4/I7 + H2.5 tetap hidup (tidak disentuh H2.6)."""

    def test_b7_b8_b30_masih_200(self):
        for url in (
            "/api/v1/inventory/products/",
            "/api/v1/inventory/operations/",
            "/api/v1/inventory/reporting/",
        ):
            with self.subTest(url=url):
                self.assertEqual(self.api.get(url).status_code, 200)

    def test_h2_5_adjustment_endpoints_masih_hidup(self):
        listing = self.api.get("/api/v1/inventory/adjustments/")

        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()["resource"], "inventory_adjustments")
        self.assertEqual(listing.json()["total_count"], 0)

    def test_i4_i7_masih_importable(self):
        from integrations.erp_sync.services.reconciliation import ReconciliationService
        from integrations.erp_sync.services.scrap_sync import ScrapSyncService

        self.assertTrue(callable(ReconciliationService().compare))
        self.assertIsNotNone(ScrapSyncService(adapter=None))

    def test_stage_dan_resource_baru_terdaftar(self):
        from integrations.erp_sync.idempotency import VALID_STAGES
        from integrations.erp_sync.models import SyncStage

        self.assertIn(STAGE_STOCK_TRANSFER, VALID_STAGES)
        self.assertEqual(SyncStage.STOCK_TRANSFER.value, STAGE_STOCK_TRANSFER)
        self.assertEqual(SyncResource.STOCK_TRANSFER.value, "stock_transfer")
        # H2.5 tetap terdaftar (tidak terbawa perubahan H2.6).
        self.assertIn("INVENTORY_ADJUST", VALID_STAGES)



