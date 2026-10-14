"""Test sprint utang ``warehouse-create-mapping`` — create `stock.warehouse` (OPSI B).

Latar (STEP 0, bukti KONKLUSIF dari sumber Odoo 17 di container
``stock/models/stock_warehouse.py`` baris 109–126):

  * ``view_location_id`` & ``lot_stock_id`` memang ``required=True`` di
    ``fields_get``, TETAPI keduanya **dibuat sendiri oleh Odoo di dalam ``create()``**
    (``stock.location.create({'usage': 'view', ...})`` lalu semua sub-lokasi via
    ``_get_locations_values(vals)``) ⇒ create tanpa keduanya tetap sah;
  * ``company_id`` bahkan **``readonly=True``** (punya default dari company user di
    ``default_get``) ⇒ mengirimnya dari MES sia-sia;
  * MES **tidak punya** relasi Warehouse→Location (arah relasinya
    ``Location.warehouse``), jadi menurunkan ``view_location_id``/``lot_stock_id``
    dari MES = mengarang data.

⇒ Fix: **payload tidak berubah** (tetap 6 field) dan ``create`` diizinkan
(``odoo_id`` ada ⇒ ``write``, belum ada ⇒ ``create``). Klien Odoo di-patch dengan
``FakeOdooClient`` sehingga test TIDAK menyentuh jaringan/Odoo nyata.

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_push_warehouse_mapping.py -q
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.auth.models import Role, User
from integrations.erp_sync.models import SyncRecord, SyncResource, SyncStage, SyncStatus
from integrations.erp_sync.tasks_master_push import (
    MasterPushError,
    _push_warehouse_to_odoo,
    _warehouse_odoo_values,
    push_master_warehouse,
)
from master.models import Warehouse

WAREHOUSES_URL = "/api/v1/master/warehouses/"
#: Path patch klien Odoo di modul task (dipakai semua test jalur create/update).
CREATE_CLIENT = "integrations.erp_sync.tasks_master_push.get_odoo_rpc_client"
ENQUEUE = "master.warehouse_services.push_master_warehouse.apply_async"

VALID_BODY = {
    "code": "WH2",
    "name": "Gudang Kedua",
    "reception_steps": "one_step",
    "delivery_steps": "ship_only",
    "active": True,
}

#: Field yang HARUS tetap tidak dikirim (ditangani Odoo sendiri).
FORBIDDEN_FIELDS = ("view_location_id", "lot_stock_id", "company_id")


class FakeTransport:
    """Transport RPC palsu: mencatat ``create``/``write`` tanpa jaringan."""

    def __init__(self, created_id: int) -> None:
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

    def __init__(self, created_id: int = 999) -> None:
        self.transport = FakeTransport(created_id)
        self.closed = False

    #: Properti nyaman untuk assertion.
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


class PushWarehouseMappingTests(TestCase):
    """Create/update payload gudang tanpa 3 field lokasi/company + guard non-breaking."""

    @classmethod
    def setUpTestData(cls):
        """Satu user admin (create/update task tidak butuh role lain)."""
        cls.admin = User.objects.create_user(
            username="admin-wh-debt",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.ADMIN),
        )

    def setUp(self):
        """Klien API admin + gudang MES (lewat API supaya payload realistis)."""
        self.api = APIClient()
        self.api.force_authenticate(self.admin)

    # ------------------------------------------------------------------ helper
    def make_warehouse(self, **overrides) -> Warehouse:
        """Gudang tersimpan langsung (tanpa API) untuk test push task."""
        return Warehouse.objects.create(
            code=overrides.pop("code", "WH2"),
            name=overrides.pop("name", "Gudang Kedua"),
            **overrides,
        )

    def post_warehouse(self, body: dict | None = None) -> Warehouse:
        """POST gudang lewat API (enqueue di-patch) → objek Warehouse."""
        payload = dict(VALID_BODY if body is None else body)
        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-wh-debt")):
            response = self.api.post(WAREHOUSES_URL, payload, format="json")

        self.assertEqual(response.status_code, 201)

        return Warehouse.objects.get(pk=response.json()["id"])

    def push(self, warehouse: Warehouse, client: FakeOdooClient) -> dict:
        """Jalankan task ``push_master_warehouse`` dengan klien Odoo palsu."""
        with patch(CREATE_CLIENT, return_value=client):
            return push_master_warehouse.apply(args=[warehouse.pk]).get()

    # ------------------------------------------------- create (inti sprint utang)
    def test_create_warehouse_baru_memakai_create_dan_menyimpan_odoo_id(self):
        """Tanpa ``odoo_id`` → ``create`` dipanggil, ``odoo_id`` diisi hasil create."""
        warehouse = self.post_warehouse()
        self.assertIsNone(warehouse.odoo_id)

        fake = FakeOdooClient(created_id=77)
        result = self.push(warehouse, fake)

        self.assertEqual(result["status"], "sent")
        self.assertEqual(result["erp_id"], "77")
        self.assertEqual(len(fake.created), 1)
        self.assertEqual(fake.created[0][0], "stock.warehouse")
        self.assertEqual(fake.written, [])
        self.assertTrue(fake.closed)  # klien ditutup di finally

        warehouse.refresh_from_db()
        self.assertEqual(warehouse.odoo_id, 77)

    def test_payload_create_tanpa_view_location_lot_stock_company(self):
        """Payload create = 6 field MES; 3 field lokasi/company TIDAK dikirim (OPSI B)."""
        warehouse = self.post_warehouse()

        fake = FakeOdooClient(created_id=88)
        self.push(warehouse, fake)

        _, payload = fake.created[0]
        self.assertEqual(
            payload,
            {
                "name": "Gudang Kedua",
                "code": "WH2",
                "reception_steps": "one_step",
                "delivery_steps": "ship_only",
                "active": True,
            },
        )
        for forbidden in FORBIDDEN_FIELDS:
            self.assertNotIn(forbidden, payload)

    def test_helper_odoo_values_tidak_pernah_memuat_field_lokasi_company(self):
        """``_warehouse_odoo_values`` (dipakai create & update) bebas 3 field itu."""
        values = _warehouse_odoo_values(
            {
                "code": "WH2",
                "name": "Gudang Kedua",
                "reception_steps": "one_step",
                "delivery_steps": "ship_only",
            }
        )

        self.assertEqual(
            set(values), {"name", "code", "reception_steps", "delivery_steps", "active"}
        )
        for forbidden in FORBIDDEN_FIELDS:
            self.assertNotIn(forbidden, values)

    def test_push_task_create_dari_api_menyimpan_sync_record_sent(self):
        """Task create menandai ``SyncRecord`` SENT + ``erp_id`` (idempotensi tetap)."""
        warehouse = self.post_warehouse()
        record = SyncRecord.objects.get(
            resource=SyncResource.MASTER_WAREHOUSE.value, resource_id=str(warehouse.pk)
        )
        self.assertEqual(record.status, SyncStatus.PENDING)

        self.push(warehouse, FakeOdooClient(created_id=123))

        record.refresh_from_db()
        self.assertEqual(record.status, SyncStatus.SENT)
        self.assertEqual(record.erp_id, "123")
        self.assertIsNotNone(record.sent_at)
        self.assertEqual(record.stage, SyncStage.MASTER_PUSH.value)

        # Run kedua: sudah SENT & payload identik → diabaikan (tidak create lagi).
        again = FakeOdooClient(created_id=999)
        result = self.push(warehouse, again)
        self.assertEqual(result["status"], "duplicate-ignored")
        self.assertEqual(again.created, [])

    # -------------------------------------------------------------- update (write)
    def test_update_warehouse_memakai_write_bukan_create(self):
        """``odoo_id`` sudah ada → jalur ``write`` (tidak create ulang)."""
        warehouse = self.make_warehouse(odoo_id=55)

        fake = FakeOdooClient(created_id=999)
        result = self.push(warehouse, fake)

        self.assertEqual(result["status"], "sent")
        self.assertEqual(result["erp_id"], "55")
        self.assertEqual(fake.created, [])
        self.assertEqual(len(fake.written), 1)

        model, ids, values = fake.written[0]
        self.assertEqual(model, "stock.warehouse")
        self.assertEqual(ids, [55])
        for forbidden in FORBIDDEN_FIELDS:
            self.assertNotIn(forbidden, values)

        warehouse.refresh_from_db()
        self.assertEqual(warehouse.odoo_id, 55)  # tidak berubah

    def test_push_warehouse_to_odoo_langsung_create_dan_write(self):
        """Fungsi inti: belum ada ``odoo_id`` ⇒ create; sudah ada ⇒ write."""
        full_payload = {
            "code": "WH3",
            "name": "G3",
            "reception_steps": "one_step",
            "delivery_steps": "ship_only",
        }

        created = self.make_warehouse(code="WH3")
        with patch(CREATE_CLIENT, return_value=FakeOdooClient(created_id=404)):
            self.assertEqual(_push_warehouse_to_odoo(created, full_payload), "404")

        existing = self.make_warehouse(code="WH4", odoo_id=405)
        fake = FakeOdooClient()
        with patch(CREATE_CLIENT, return_value=fake):
            self.assertEqual(
                _push_warehouse_to_odoo(existing, {**full_payload, "code": "WH4", "name": "G4"}),
                "405",
            )
        self.assertEqual(fake.created, [])
        self.assertEqual(fake.written[0][1], [405])

    # ----------------------------------------------- guard non-breaking + pull utuh
    def test_guard_non_breaking_code_dan_steps(self):
        """Guard lama tetap: ``code`` kosong/>5 & steps invalid → ``MasterPushError``."""
        cases = (
            ({"code": ""}, "code (short_name)"),
            ({"code": "GUDANGPANJANG"}, "terlalu panjang"),
            ({"code": "WH2", "reception_steps": "dua_langkah"}, "reception_steps"),
            (
                {"code": "WH2", "reception_steps": "one_step", "delivery_steps": "kirim_saja"},
                "delivery_steps",
            ),
        )

        for payload, needle in cases:
            with self.subTest(payload=payload):
                with self.assertRaises(MasterPushError) as ctx:
                    _warehouse_odoo_values(payload)
                self.assertIn(needle, str(ctx.exception))

        # Task menandai FAILED (bukan SENT) & TIDAK memanggil Odoo sama sekali.
        warehouse = self.make_warehouse(code="WH2")
        warehouse.code = "GUDANGPANJANG"
        warehouse.save(update_fields=("code",))
        fake = FakeOdooClient()
        with patch(CREATE_CLIENT, return_value=fake):
            with self.assertRaises(MasterPushError):
                push_master_warehouse.apply(args=[warehouse.pk]).get()

        self.assertEqual(fake.created, [])
        self.assertEqual(fake.written, [])

        record = SyncRecord.objects.get(
            resource=SyncResource.MASTER_WAREHOUSE.value, resource_id=str(warehouse.pk)
        )
        self.assertEqual(record.status, SyncStatus.FAILED)
        self.assertIn("terlalu panjang", record.last_error)

    def test_pull_warehouse_tidak_berubah(self):
        """Pull Odoo→MES tetap ``_name_defaults(row, 'code')`` — hanya ``code`` + ``name``.

        Sprint utang ini **tidak** menyentuh pull: perilaku lama yang memang hanya
        memetakan kode natural ``code`` (+ ``name``) dipertahankan apa adanya, dan
        ``is_active`` **tidak** diturunkan dari ``active`` Odoo (seperti sebelumnya).
        """
        from integrations.erp_sync.tasks_master import (
            _warehouse_defaults,
            sync_master_warehouses,
        )

        with patch(
            "integrations.erp_sync.tasks_master.get_transport",
            return_value=FakeTransportFacade(
                warehouses=[
                    {"id": 9, "code": "WH9", "name": "Gudang Sembilan", "active": True},
                    {"id": 10, "code": "WH10", "name": "Gudang Sepuluh", "active": False},
                ]
            ),
        ):
            result = sync_master_warehouses.apply().get()

        self.assertEqual(result, {"created": 2, "updated": 0, "skipped": 0})

        pulled = Warehouse.objects.get(odoo_id=9)
        self.assertEqual(pulled.code, "WH9")
        self.assertEqual(pulled.name, "Gudang Sembilan")

        # Defaults pull = {code, name} saja (tanpa 3 field lokasi/company & tanpa active).
        self.assertEqual(
            _warehouse_defaults({"id": 9, "code": "WH9", "name": "X", "active": False}),
            {"code": "WH9", "name": "X"},
        )
        self.assertTrue(Warehouse.objects.get(odoo_id=10).is_active)  # perilaku lama


class FakeTransportFacade:
    """Facade transport palsu untuk pull (hanya ``fetch_warehouses`` + ``close``)."""

    def __init__(self, warehouses: list[dict]) -> None:
        self._warehouses = warehouses

    def fetch_warehouses(self, since=None):  # noqa: ARG002 - signature transport asli
        """Kembalikan baris gudang palsu (``since`` diabaikan seperti mode full)."""
        return list(self._warehouses)

    def close(self) -> None:
        """Tidak ada resource untuk ditutup."""
        return None


