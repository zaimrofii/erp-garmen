"""Test H2.5 — Inventory Adjustment (`/api/v1/inventory/…`) MES → Odoo.

Cakupan: validasi create (`reason`/`qty_delta`/`usage='internal'`), create `DRAFT`
(+snapshot `qty_before`), `?commit=true`, list + filter + pagination, detail, commit
(`DRAFT → COMMITTED` + ledger `PENDING` + enqueue), guard commit (`odoo_id`,
tracking lot/serial), on-demand `stock-qty` (read-only, transport di-mock), adapter
`push_inventory_adjustment` (klien Odoo di-mock: quant → apply → move), task push
(`SYNCED`/`FAILED` + hint grup `stock.group_stock_manager`), dan non-breaking
B7/B8/B30 + I4/I7.

Prinsip yang di-pin: **MES tidak menyimpan stok** (`docs/CHANGES-DETAIL-H1H5.md` §4) —
tidak ada tabel/kolom stok di MES; semua nilai on-hand dibaca on-demand dari Odoo.
"""

from __future__ import annotations

from decimal import Decimal
from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.models import InventoryAdjustment
from core.audit.models import AuditLog
from core.auth.models import Role, User
from integrations.erp_sync.adapters.base import ERPResponse
from integrations.erp_sync.adapters.odoo import OdooAdapter
from integrations.erp_sync.models import (
    STAGE_INVENTORY_ADJUST,
    SyncRecord,
    SyncResource,
    SyncStatus,
)
from integrations.erp_sync.tasks_inventory_adjustment_push import (
    GROUP_REQUIRED_HINT,
    push_inventory_adjustment,
)
from master.models import Location, Product

ADJUST_URL = "/api/v1/inventory/adjust/"
LIST_URL = "/api/v1/inventory/adjustments/"
STOCK_QTY_URL = "/api/v1/inventory/stock-qty/"

SERVICES = "apps_industry.garment.services.inventory_adjustment_services"
FETCH_QTY = f"{SERVICES}.fetch_stock_qty"
FETCH_TRACKING = f"{SERVICES}.fetch_product_tracking"
GET_TRANSPORT = f"{SERVICES}.get_transport"
ENQUEUE = f"{SERVICES}._enqueue_push"
TASKS = "integrations.erp_sync.tasks_inventory_adjustment_push"
GET_ADAPTER = f"{TASKS}.get_adapter"

LEDGER = dict(resource=SyncResource.INVENTORY_ADJUSTMENT.value, stage=STAGE_INVENTORY_ADJUST)


def detail_url(adjustment_id: int) -> str:
    """URL detail satu adjustment (H2.5)."""
    return f"{LIST_URL}{adjustment_id}/"


def commit_url(adjustment_id: int) -> str:
    """URL commit satu adjustment (H2.5)."""
    return f"{LIST_URL}{adjustment_id}/commit/"


class FakeQuantTransport:
    """Transport palsu untuk pembacaan `stock.quant` (tanpa jaringan)."""

    def __init__(self, rows=None):
        self.rows = rows if rows is not None else []
        self.closed = False
        self.calls: list = []

    def fetch_stock_quants(self, location_ids, since=None, child_of=False):
        """Kembalikan baris quant yang sudah disiapkan test."""
        self.calls.append((list(location_ids), child_of))

        return list(self.rows)

    def search_read(self, model, domain=None, fields=None, limit=None, offset=0, order=None):
        """Guard tracking (dipakai hanya di test yang menyiapkannya)."""
        self.calls.append((model, domain))

        return []

    def fetch_internal_locations(self):
        """Dipakai `ReconciliationService` (I7) — kosong = tidak ada lokasi internal."""
        self.calls.append(("fetch_internal_locations",))

        return []

    def close(self):
        """Tandai transport ditutup (dipanggil `fetch_stock_qty`)."""
        self.closed = True


class InventoryBase(TestCase):
    """Basis bersama: produk/lokasi master + user simulator."""

    @classmethod
    def setUpTestData(cls):
        cls.product = Product.objects.create(code="KAIN-COTTON", name="Kain Cotton", odoo_id=89)
        cls.product_no_odoo = Product.objects.create(code="KAIN-BARU", name="Kain Baru")
        cls.location = Location.objects.create(
            code="WH/STOK", name="Stok", usage=Location.Usage.INTERNAL, odoo_id=8
        )
        cls.location_no_odoo = Location.objects.create(
            code="WH/LOKAL", name="Lokal", usage=Location.Usage.INTERNAL
        )
        cls.location_production = Location.objects.create(
            code="WH/PROD", name="Produksi", usage=Location.Usage.PRODUCTION, odoo_id=24
        )
        cls.sim = User.objects.create_user(username="sim-h25", password="x")  # noqa: S106
        cls.admin = User.objects.create_user(  # noqa: S106 - kredensial test
            username="admin-h25",
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
        """Payload create H2.5 default (delta +5, alasan jelas)."""
        data = {
            "product_id": self.product.pk,
            "location_id": self.location.pk,
            "qty_delta": "5",
            "reason": "Hasil hitung ulang gudang",
        }
        data.update(overrides)

        return data

    def make_adjustment(self, **overrides):
        """Baris `InventoryAdjustment` langsung di DB (bikin test commit ringkas)."""
        data = {
            "code": "ADJ-TEST-1",
            "product": self.product,
            "location": self.location,
            "qty_delta": Decimal("5.00"),
            "qty_before": Decimal("10.00"),
            "reason": "Koreksi opname",
            "state": InventoryAdjustment.State.DRAFT,
        }
        data.update(overrides)

        return InventoryAdjustment.objects.create(**data)


class InventoryAdjustmentCreateTests(InventoryBase):
    """`POST /api/v1/inventory/adjust/` — validasi + create DRAFT."""

    def test_create_ok_draft_dengan_snapshot_qty_before(self):
        with mock.patch(FETCH_QTY, return_value=Decimal("12.00")):
            response = self.api.post(ADJUST_URL, self.payload(), format="json")

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["state"], "DRAFT")
        self.assertTrue(body["code"].startswith("ADJ-"))
        self.assertEqual(body["qty_delta"], "5.00")
        self.assertEqual(body["qty_before"], "12.00")
        self.assertIsNone(body["qty_after"])
        self.assertIsNone(body["odoo_move_id"])
        self.assertEqual(body["reason"], "Hasil hitung ulang gudang")
        self.assertEqual(body["location_usage"], "internal")
        self.assertEqual(body["industry"], "garmen")
        self.assertEqual(InventoryAdjustment.objects.count(), 1)

    def test_create_delta_negatif_ok(self):
        with mock.patch(FETCH_QTY, return_value=Decimal("3.00")):
            response = self.api.post(ADJUST_URL, self.payload(qty_delta="-2.50"), format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["qty_delta"], "-2.50")

    def test_create_reason_kosong_400(self):
        response = self.api.post(ADJUST_URL, self.payload(reason="   "), format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("reason", response.json()["detail"])
        self.assertEqual(InventoryAdjustment.objects.count(), 0)

    def test_create_qty_delta_nol_400(self):
        response = self.api.post(ADJUST_URL, self.payload(qty_delta="0"), format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("tidak boleh 0", response.json()["detail"])

    def test_create_qty_delta_bukan_angka_400(self):
        response = self.api.post(ADJUST_URL, self.payload(qty_delta="banyak"), format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("angka", response.json()["detail"])

    def test_create_qty_delta_terlalu_besar_400(self):
        response = self.api.post(ADJUST_URL, self.payload(qty_delta="1000001"), format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("maksimal", response.json()["detail"])

    def test_create_location_usage_production_400(self):
        response = self.api.post(
            ADJUST_URL, self.payload(location_id=self.location_production.pk), format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("internal", response.json()["detail"])

    def test_create_produk_tidak_ada_404(self):
        response = self.api.post(ADJUST_URL, self.payload(product_id=999_999), format="json")

        self.assertEqual(response.status_code, 404)
        self.assertIn("tidak ditemukan", response.json()["detail"])

    def test_create_lokasi_tidak_ada_404(self):
        response = self.api.post(ADJUST_URL, self.payload(location_id=999_999), format="json")

        self.assertEqual(response.status_code, 404)

    def test_create_field_wajib_kosong_400(self):
        response = self.api.post(ADJUST_URL, {"reason": "x"}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("product_id", response.json()["detail"])

    def test_create_anonim_403(self):
        response = self.as_user(None).post(ADJUST_URL, self.payload(), format="json")

        self.assertEqual(response.status_code, 403)

    def test_create_menulis_audit_log(self):
        with mock.patch(FETCH_QTY, return_value=Decimal("1.00")):
            self.api.post(ADJUST_URL, self.payload(), format="json")

        log = AuditLog.objects.filter(resource=SyncResource.INVENTORY_ADJUSTMENT.value).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.action, "inventory_adjustment.create")

    def test_create_qty_before_none_kalau_odoo_tidak_terbaca(self):
        with mock.patch(FETCH_QTY, return_value=None):
            response = self.api.post(ADJUST_URL, self.payload(), format="json")

        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.json()["qty_before"])

    def test_create_commit_true_langsung_committed(self):
        with (
            mock.patch(FETCH_QTY, return_value=Decimal("7.00")),
            mock.patch(FETCH_TRACKING, return_value="none"),
            mock.patch(ENQUEUE, return_value="task-adj-1") as enqueue,
        ):
            response = self.api.post(f"{ADJUST_URL}?commit=true", self.payload(), format="json")

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["state"], "COMMITTED")
        self.assertTrue(body["commit"]["ok"])
        self.assertEqual(body["commit"]["task_id"], "task-adj-1")
        enqueue.assert_called_once()

        record = SyncRecord.objects.get(**LEDGER)
        self.assertEqual(record.status, SyncStatus.PENDING)
        self.assertEqual(record.resource_id, str(body["id"]))


class InventoryAdjustmentReadTests(InventoryBase):
    """List/detail/commit — envelope §3, guard, dan on-demand `stock-qty`."""

    def test_list_envelope_dan_filter(self):
        self.make_adjustment(code="ADJ-1", product=self.product, location=self.location)
        self.make_adjustment(
            code="ADJ-2",
            product=self.product,
            location=self.location_production,
            state=InventoryAdjustment.State.COMMITTED,
            reason="Alasan lain",
        )

        all_rows = self.api.get(LIST_URL).json()
        self.assertEqual(
            set(all_rows),
            {"rows", "total_count", "has_more", "next_cursor", "resource", "industry"},
        )
        self.assertEqual(all_rows["total_count"], 2)
        self.assertEqual(all_rows["resource"], "inventory_adjustments")

        by_state = self.api.get(f"{LIST_URL}?state=committed").json()
        self.assertEqual(by_state["total_count"], 1)
        self.assertEqual(by_state["rows"][0]["code"], "ADJ-2")

        by_location = self.api.get(f"{LIST_URL}?location_id={self.location.pk}").json()
        self.assertEqual(by_location["total_count"], 1)

        by_search = self.api.get(f"{LIST_URL}?search=Alasan").json()
        self.assertEqual(by_search["total_count"], 1)

        paged = self.api.get(f"{LIST_URL}?limit=1&offset=0").json()
        self.assertEqual(len(paged["rows"]), 1)
        self.assertTrue(paged["has_more"])

    def test_list_limit_tidak_valid_400(self):
        self.assertEqual(self.api.get(f"{LIST_URL}?limit=0").status_code, 400)

    def test_list_anonim_403(self):
        self.assertEqual(self.as_user(None).get(LIST_URL).status_code, 403)

    def test_detail_ok_dan_404(self):
        adj = self.make_adjustment()

        response = self.api.get(detail_url(adj.pk))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["id"], adj.pk)
        self.assertIsNone(body["sync"]["status"])
        self.assertEqual(body["product_code"], self.product.code)
        self.assertEqual(body["location_code"], self.location.code)

        self.assertEqual(self.api.get(detail_url(999_999)).status_code, 404)

    def test_commit_ok_enqueue_dan_ledger_pending(self):
        adj = self.make_adjustment()

        with (
            mock.patch(FETCH_TRACKING, return_value="none"),
            mock.patch(ENQUEUE, return_value="task-commit-1") as enqueue,
        ):
            response = self.api.post(commit_url(adj.pk), {}, format="json")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["state"], "COMMITTED")
        self.assertEqual(body["task_id"], "task-commit-1")
        self.assertTrue(body["queued"])
        enqueue.assert_called_once()

        record = SyncRecord.objects.get(**LEDGER)
        self.assertEqual(record.status, SyncStatus.PENDING)
        self.assertEqual(record.payload["qty_delta"], "5.00")

    def test_commit_produk_tanpa_odoo_id_400(self):
        adj = self.make_adjustment(product=self.product_no_odoo)

        response = self.api.post(commit_url(adj.pk), {}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("odoo_id", response.json()["detail"])
        self.assertEqual(InventoryAdjustment.objects.get(pk=adj.pk).state, "DRAFT")
        self.assertFalse(SyncRecord.objects.filter(**LEDGER).exists())

    def test_commit_lokasi_tanpa_odoo_id_400(self):
        adj = self.make_adjustment(location=self.location_no_odoo)

        response = self.api.post(commit_url(adj.pk), {}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("Location", response.json()["detail"])

    def test_commit_tracking_lot_ditolak_400(self):
        adj = self.make_adjustment()

        with mock.patch(FETCH_TRACKING, return_value="lot"):
            response = self.api.post(commit_url(adj.pk), {}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("lot/serial", response.json()["detail"])
        self.assertEqual(InventoryAdjustment.objects.get(pk=adj.pk).state, "DRAFT")

    def test_commit_dobel_409(self):
        adj = self.make_adjustment(state=InventoryAdjustment.State.SYNCED)

        response = self.api.post(commit_url(adj.pk), {}, format="json")

        self.assertEqual(response.status_code, 409)
        self.assertIn("SYNCED", response.json()["detail"])

    def test_commit_tidak_ada_404(self):
        self.assertEqual(self.api.post(commit_url(999_999), {}, format="json").status_code, 404)

    def test_commit_anonim_403(self):
        adj = self.make_adjustment()

        self.assertEqual(self.as_user(None).post(commit_url(adj.pk), {}).status_code, 403)

    def test_stock_qty_on_demand_dari_odoo(self):
        transport = FakeQuantTransport(
            rows=[{"product_id": [89, "Kain"], "location_id": [8, "Stok"], "quantity": 60.0}]
        )

        with mock.patch(GET_TRANSPORT, return_value=transport):
            response = self.api.get(
                f"{STOCK_QTY_URL}?product_id={self.product.pk}&location_id={self.location.pk}"
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["qty"], "60.00")
        self.assertEqual(body["source"], "odoo")
        self.assertEqual(body["stock_owner"], "odoo")
        self.assertEqual(body["product_odoo_id"], 89)
        self.assertTrue(transport.closed)
        self.assertFalse(InventoryAdjustment.objects.exists())

    def test_stock_qty_quant_kosong_jadi_nol(self):
        transport = FakeQuantTransport(rows=[])

        with mock.patch(GET_TRANSPORT, return_value=transport):
            response = self.api.get(
                f"{STOCK_QTY_URL}?product_id={self.product.pk}&location_id={self.location.pk}"
            )

        self.assertEqual(response.json()["qty"], "0.00")

    def test_stock_qty_quant_produk_lain_diabaikan(self):
        transport = FakeQuantTransport(
            rows=[{"product_id": [99, "Lain"], "location_id": [8, "Stok"], "quantity": 40.0}]
        )

        with mock.patch(GET_TRANSPORT, return_value=transport):
            response = self.api.get(
                f"{STOCK_QTY_URL}?product_id={self.product.pk}&location_id={self.location.pk}"
            )

        self.assertEqual(response.json()["qty"], "0.00")

    def test_stock_qty_tanpa_odoo_id_null(self):
        transport = FakeQuantTransport(rows=[{"product_id": [89, "Kain"], "quantity": 5.0}])

        with mock.patch(GET_TRANSPORT, return_value=transport):
            response = self.api.get(
                f"{STOCK_QTY_URL}?product_id={self.product_no_odoo.pk}"
                f"&location_id={self.location.pk}"
            )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["qty"])

    def test_stock_qty_param_kurang_400(self):
        self.assertEqual(self.api.get(STOCK_QTY_URL).status_code, 400)

    def test_stock_qty_lokasi_non_internal_400(self):
        response = self.api.get(
            f"{STOCK_QTY_URL}?product_id={self.product.pk}"
            f"&location_id={self.location_production.pk}"
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("internal", response.json()["detail"])

    def test_stock_qty_produk_tidak_ada_404(self):
        response = self.api.get(
            f"{STOCK_QTY_URL}?product_id=999999&location_id={self.location.pk}"
        )

        self.assertEqual(response.status_code, 404)


class FakeOdooClient:
    """Klien Odoo palsu untuk adapter (merekam `execute_kw`, tanpa jaringan)."""

    def __init__(self, quants=None, moves=None, fail_on=None):
        self.quants = (
            quants if quants is not None else [{"id": 11, "quantity": 60.0}]
        )
        self.moves = (
            moves if moves is not None else [{"id": 231, "name": "ADJ-2026-0001 opname"}]
        )
        self.fail_on = fail_on
        self.calls: list = []

    def execute_kw(self, model, method, args=None, kwargs=None):
        """Tiru `execute_kw` Odoo untuk 4 panggilan yang dipakai adapter."""
        if self.fail_on == (model, method):
            raise RuntimeError("Only a stock manager can validate an inventory adjustment.")

        self.calls.append((model, method, args, kwargs))
        if (model, method) == ("stock.quant", "search_read"):
            return list(self.quants)
        if (model, method) == ("stock.quant", "create"):
            return [12]
        if (model, method) == ("stock.quant", "write"):
            return True
        if (model, method) == ("stock.quant", "action_apply_inventory"):
            return None
        if (model, method) == ("stock.move", "search_read"):
            return list(self.moves)

        return None


def adapter_payload(**overrides) -> dict:
    """Payload adapter default (hasil `adjustment_values` task)."""
    data = {
        "ref": "ADJ-2026-0001",
        "product_odoo_id": 89,
        "location_odoo_id": 8,
        "qty_delta": "5",
        "inventory_name": "ADJ-2026-0001 opname",
    }
    data.update(overrides)

    return data


class InventoryAdjustmentAdapterTests(TestCase):
    """`OdooAdapter.push_inventory_adjustment` — jalur quant Odoo (klien di-mock)."""

    def test_push_sukses_tulis_quant_apply_dan_cari_move(self):
        client = FakeOdooClient()
        response = OdooAdapter(client=client).push_inventory_adjustment(adapter_payload())

        self.assertTrue(response.ok)
        self.assertEqual(response.stage, "INVENTORY_ADJUST")
        self.assertEqual(response.ref, "ADJ-2026-0001")
        self.assertEqual(response.erp_id, "231")
        self.assertEqual(response.raw["before"], 60.0)
        self.assertEqual(response.raw["target"], 65.0)
        self.assertEqual(response.raw["move_id"], 231)

        calls = [(model, method) for model, method, _args, _kwargs in client.calls]
        self.assertEqual(
            calls,
            [
                ("stock.quant", "search_read"),
                ("stock.quant", "write"),
                ("stock.quant", "action_apply_inventory"),
                ("stock.move", "search_read"),
            ],
        )
        write_args = client.calls[1][2]
        self.assertEqual(write_args[0], [11])
        self.assertEqual(write_args[1]["inventory_quantity"], 65.0)
        ctx = client.calls[1][3]["context"]
        self.assertTrue(ctx["inventory_mode"])
        self.assertEqual(ctx["inventory_name"], "ADJ-2026-0001 opname")

    def test_push_buat_quant_baru_kalau_belum_ada(self):
        client = FakeOdooClient(quants=[])

        response = OdooAdapter(client=client).push_inventory_adjustment(adapter_payload())

        self.assertTrue(response.ok)
        self.assertEqual(response.raw["before"], 0.0)
        self.assertEqual(response.raw["target"], 5.0)
        self.assertEqual(response.raw["quant_id"], 12)
        calls = [(model, method) for model, method, _a, _k in client.calls]
        self.assertIn(("stock.quant", "create"), calls)

    def test_push_payload_kurang_field_ditolak(self):
        response = OdooAdapter(client=FakeOdooClient()).push_inventory_adjustment(
            {"ref": "ADJ-1"}
        )

        self.assertFalse(response.ok)
        self.assertIn("tidak lengkap", response.error)

    def test_push_tanpa_client_gagal_aman(self):
        # `client=None` → adapter membangun klien dari settings; di test kredensial
        # dipaksa tidak siap (`ImproperlyConfigured`) supaya **tidak** ada panggilan
        # jaringan ke Odoo nyata.
        from django.core.exceptions import ImproperlyConfigured

        with mock.patch(
            "integrations.erp_sync.client.get_odoo_rpc_client",
            side_effect=ImproperlyConfigured("credential kosong"),
        ):
            adapter = OdooAdapter()
            response = adapter.push_inventory_adjustment(adapter_payload())

        self.assertIsNone(adapter.client)
        self.assertFalse(response.ok)
        self.assertIn("client", response.error)

    def test_push_error_odoo_diteruskan(self):
        client = FakeOdooClient(fail_on=("stock.quant", "write"))

        response = OdooAdapter(client=client).push_inventory_adjustment(adapter_payload())

        self.assertFalse(response.ok)
        self.assertIn("stock manager", response.error)


class FakeAdapter:
    """Adapter palsu untuk task push (hasil `ERPResponse` disiapkan test)."""

    name = "fake"

    def __init__(self, response: ERPResponse):
        self.response = response
        self.payloads: list = []

    def push_inventory_adjustment(self, payload: dict) -> ERPResponse:
        """Rekam payload & kembalikan respons yang sudah ditentukan."""
        self.payloads.append(dict(payload))

        return self.response


class InventoryAdjustmentTaskTests(InventoryBase):
    """Task `erp_sync.push_inventory_adjustment` — SYNCED/FAILED/duplicate/no-op."""

    def make_committed(self, **overrides):
        """Adjustment `COMMITTED` + ledger `PENDING` (siap di-push)."""
        from apps_industry.garment.services.inventory_adjustment_services import (
            adjustment_push_payload,
        )
        from integrations.erp_sync.idempotency import SyncIdempotency

        adj = self.make_adjustment(state=InventoryAdjustment.State.COMMITTED, **overrides)
        record = SyncIdempotency().get_or_create_sync_record(
            SyncResource.INVENTORY_ADJUSTMENT.value,
            adj.pk,
            STAGE_INVENTORY_ADJUST,
            adjustment_push_payload(adj),
        )

        return adj, record

    def test_task_odoo_mode_sukses_menyimpan_move_id(self):
        adj, record = self.make_committed()
        adapter = FakeAdapter(
            ERPResponse(
                ok=True,
                erp_id="231",
                raw={"quant_id": 11, "before": 60.0, "target": 65.0, "move_id": 231},
                stage="INVENTORY_ADJUST",
                ref=adj.code,
            )
        )

        with (
            mock.patch(f"{TASKS}.is_noop_mode", return_value=False),
            mock.patch(GET_ADAPTER, return_value=adapter),
        ):
            result = push_inventory_adjustment.apply(args=[adj.pk, record.pk]).get()

        self.assertEqual(result["status"], "sent")
        adj.refresh_from_db()
        self.assertEqual(adj.state, "SYNCED")
        self.assertEqual(adj.odoo_move_id, 231)
        self.assertEqual(str(adj.qty_after), "65.00")
        self.assertEqual(adj.last_error, "")
        self.assertEqual(adapter.payloads[0]["inventory_name"], f"{adj.code} Koreksi opname")

        record.refresh_from_db()
        self.assertEqual(record.status, SyncStatus.SENT)
        self.assertEqual(record.erp_id, "231")

    def test_task_odoo_mode_gagal_menyimpan_hint_grup(self):
        adj, record = self.make_committed()
        adapter = FakeAdapter(
            ERPResponse(
                ok=False,
                error="Only a stock manager can validate an inventory adjustment.",
                stage="INVENTORY_ADJUST",
                ref=adj.code,
            )
        )

        with (
            mock.patch(f"{TASKS}.is_noop_mode", return_value=False),
            mock.patch(GET_ADAPTER, return_value=adapter),
        ):
            result = push_inventory_adjustment.apply(args=[adj.pk, record.pk]).get()

        self.assertEqual(result["status"], "failed")
        adj.refresh_from_db()
        self.assertEqual(adj.state, "FAILED")
        self.assertEqual(adj.last_error, GROUP_REQUIRED_HINT)
        self.assertIn("stock.group_stock_manager", adj.last_error)
        record.refresh_from_db()
        self.assertEqual(record.status, SyncStatus.FAILED)

    def test_task_noop_mode_sukses_tanpa_move(self):
        adj, record = self.make_committed()

        with mock.patch(f"{TASKS}.is_noop_mode", return_value=True):
            result = push_inventory_adjustment.apply(args=[adj.pk, record.pk]).get()

        self.assertEqual(result["status"], "sent")
        self.assertTrue(str(result["erp_id"]).startswith("NULL-"))
        adj.refresh_from_db()
        self.assertEqual(adj.state, "SYNCED")
        self.assertIsNone(adj.odoo_move_id)

    def test_task_duplicate_ignored(self):
        from integrations.erp_sync.idempotency import SyncIdempotency

        adj, record = self.make_committed()
        SyncIdempotency().mark_sent(record, "231")

        with (
            mock.patch(f"{TASKS}.is_noop_mode", return_value=False),
            mock.patch(GET_ADAPTER) as adapter,
        ):
            result = push_inventory_adjustment.apply(args=[adj.pk, record.pk]).get()

        self.assertEqual(result["status"], "duplicate-ignored")
        adapter.assert_not_called()
        adj.refresh_from_db()
        self.assertEqual(adj.state, "COMMITTED")

    def test_task_adjustment_tidak_ada(self):
        result = push_inventory_adjustment.apply(args=[999_999]).get()

        self.assertEqual(result["status"], "not-found")

    def test_task_transport_error_dicatat_lalu_raise(self):
        adj, record = self.make_committed()

        class Boom:
            """Adapter yang selalu gagal (mensimulasikan koneksi Odoo putus)."""

            name = "boom"

            def push_inventory_adjustment(self, payload):
                raise RuntimeError("koneksi Odoo putus")

        with (
            mock.patch(f"{TASKS}.is_noop_mode", return_value=False),
            mock.patch(GET_ADAPTER, return_value=Boom()),
            self.assertRaises(RuntimeError),
        ):
            push_inventory_adjustment.apply(args=[adj.pk, record.pk]).get()

        record.refresh_from_db()
        self.assertEqual(record.status, SyncStatus.FAILED)
        adj.refresh_from_db()
        self.assertEqual(adj.state, "COMMITTED")


class InventoryAdjustmentNonBreakingTests(InventoryBase):
    """B7/B8/B30 + I4/I7 tetap hidup (tidak disentuh H2.5)."""

    def test_b7_b8_b30_masih_200(self):
        for url in (
            "/api/v1/inventory/products/",
            "/api/v1/inventory/operations/",
            "/api/v1/inventory/reporting/",
        ):
            with self.subTest(url=url):
                self.assertEqual(self.api.get(url).status_code, 200)

    def test_i4_scrap_sync_masih_importable(self):
        from integrations.erp_sync.services.scrap_sync import ScrapSyncService

        self.assertIsNotNone(ScrapSyncService(adapter=None))

    def test_i7_reconciliation_masih_importable(self):
        from integrations.erp_sync.services.reconciliation import ReconciliationService

        service = ReconciliationService(transport=FakeQuantTransport(rows=[]))
        result = service.compare()

        self.assertIn("total_products", result)
        self.assertEqual(result["total_products"], 0)

    def test_stage_dan_resource_baru_terdaftar(self):
        from integrations.erp_sync.idempotency import VALID_STAGES
        from integrations.erp_sync.models import SyncStage

        self.assertIn(STAGE_INVENTORY_ADJUST, VALID_STAGES)
        self.assertEqual(SyncStage.INVENTORY_ADJUST.value, STAGE_INVENTORY_ADJUST)
        self.assertEqual(SyncResource.INVENTORY_ADJUSTMENT.value, "inventory_adjustment")



