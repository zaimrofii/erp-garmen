"""Test CRUD master BOM — ``/api/v1/master/boms/`` (H1.5).

Cakupan: list (pagination/filter/search/annotate), detail (dengan ``lines[]``),
create (BOM + ``lines[]`` **atomic**), update (ganti baris: cocokkan ``id`` →
``odoo_id`` → baru; sisanya di-*soft-delete*), **soft delete** tanpa guard, izin
(anon 403, role non-admin 403), validasi 400 (produk/qty/output_qty/uom/kode
duplikat/``lines`` bukan array), guard hierarki (**komponen = produk BOM sendiri**
dan **siklus BOM**), serta kewajiban H1.5: ``SyncRecord`` (``master.bom``/
``MASTER_PUSH``) + ``AuditLog`` setiap POST/PUT/DELETE dan enqueue task
``erp_sync.push_master_bom``.

Catatan khusus H1.5 (probe ``fields_get`` Odoo 17 ``mrp.bom``):
  * header push memakai ``product_tmpl_id`` (**wajib**, = ``Product.odoo_tmpl_id``)
    + ``product_qty`` + ``product_uom_id`` + ``type``; guard-nya bukan ``odoo_id``;
  * baris push memakai ``product_id`` (varian, ``Product.odoo_id``) + ``product_qty``
    + ``product_uom_id`` + ``sequence``;
  * ``ERP_ADAPTER=null`` → no-op (``SENT`` + ``erp_id NULL-<uuid>``); ``ERP_ADAPTER=odoo``
    + produk belum punya ``odoo_tmpl_id`` → ``FAILED`` dengan pesan jelas (test tidak
    menyentuh jaringan karena ``MasterPushError`` dilempar sebelum transport dipakai).

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_master_boms_crud.py -q
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.audit.models import AuditLog
from core.auth.models import Role, User
from integrations.erp_sync.models import SyncRecord, SyncResource, SyncStage, SyncStatus
from integrations.erp_sync.tasks_master_push import (
    MasterPushError,
    _bom_line_odoo_values,
    _bom_odoo_values,
    bom_payload,
    push_master_bom,
)
from master.bom_services import create_bom
from master.models import BOM, BOMLine, Product, UoM

BOMS_URL = "/api/v1/master/boms/"
ENVELOPE_KEYS = {"rows", "total_count", "has_more", "next_cursor"}
ROW_KEYS = {
    "id",
    "code",
    "name",
    "product_id",
    "product_code",
    "product_name",
    "output_qty",
    "uom_id",
    "uom_code",
    "notes",
    "active",
    "odoo_id",
    "lines_count",
    "created_at",
    "updated_at",
}
LINE_KEYS = {
    "id",
    "product_id",
    "product_code",
    "product_name",
    "qty",
    "uom_id",
    "uom_code",
    "sequence",
    "notes",
    "active",
    "odoo_id",
}
#: Path patch enqueue task (service menulis SyncRecord lalu enqueue).
ENQUEUE = "master.bom_services.push_master_bom.apply_async"


def detail_url(pk: int) -> str:
    """URL detail BOM."""
    return f"{BOMS_URL}{pk}/"


class MasterBomsCrudTests(TestCase):
    """GET/POST/PUT/DELETE + baris inline + siklus + idempotensi + audit + push."""

    @classmethod
    def setUpTestData(cls):
        """4 user: admin, purchasing, operator, qc (uji 403 untuk 3 role terakhir)."""
        cls.admin = User.objects.create_user(
            username="admin-bom",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.ADMIN),
        )
        cls.purchasing = User.objects.create_user(
            username="beli-bom",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.PURCHASING),
        )
        cls.operator = User.objects.create_user(
            username="op-bom",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.OPERATOR),
        )
        cls.qc = User.objects.create_user(
            username="qc-bom",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.QC),
        )

    def setUp(self):
        """Klien admin (utama) + klien role lain (uji 403) + master pendukung."""
        self.api = APIClient()
        self.api.force_authenticate(self.admin)

        self.readonly_apis = {}
        for name, user in (
            ("purchasing", self.purchasing),
            ("operator", self.operator),
            ("qc", self.qc),
        ):
            client = APIClient()
            client.force_authenticate(user)
            self.readonly_apis[name] = client

        self.uom = UoM.objects.create(code="PCS", name="PCS", factor=1.0, rounding=0.01)
        self.oven = Product.objects.create(code="KTS-EXPORT-L", name="Kaos Export L")
        self.fabric = Product.objects.create(code="KAIN-COTTON", name="Kain Cotton")
        self.thread = Product.objects.create(code="BENANG-X", name="Benang X")

    # ------------------------------------------------------------------ helper
    def bom_body(self, **overrides) -> dict:
        """Body create/update BOM valid (default: 2 baris komponen)."""
        body = {
            "product_id": self.oven.pk,
            "output_qty": 1,
            "uom_id": self.uom.pk,
            "name": "BOM Kaos Export L",
            "active": True,
            "lines": [
                {"product_id": self.fabric.pk, "qty": 1.5, "uom_id": self.uom.pk},
                {"product_id": self.thread.pk, "qty": 0.5},
            ],
        }
        body.update(overrides)

        return body

    def post_bom(self, body: dict, client=None):
        """POST BOM dengan enqueue task di-patch → ``(response, mock)``."""
        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-bom-1")) as enqueue:
            response = (client or self.api).post(BOMS_URL, body, format="json")

        return response, enqueue

    def put_bom(self, pk: int, body: dict, client=None):
        """PUT BOM dengan enqueue task di-patch → ``(response, mock)``."""
        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-bom-2")) as enqueue:
            response = (client or self.api).put(detail_url(pk), body, format="json")

        return response, enqueue

    def delete_bom(self, pk: int, client=None):
        """DELETE BOM dengan enqueue task di-patch → ``(response, mock)``."""
        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-bom-3")) as enqueue:
            response = (client or self.api).delete(detail_url(pk))

        return response, enqueue

    def make_bom(self, code: str = "BOM-KTS-EXPORT-L", **overrides) -> BOM:
        """BOM tersimpan langsung (tanpa lewat API) untuk test non-create."""
        return BOM.objects.create(
            code=code,
            name=overrides.pop("name", "BOM Kaos Export L"),
            product=overrides.pop("product", self.oven),
            output_qty=overrides.pop("output_qty", 1),
            uom=overrides.pop("uom", self.uom),
            **overrides,
        )

    # ------------------------------------------------------------ POST / create
    def test_create_bom_ok(self):
        """POST → 201: BOM + 2 baris komponen + kode auto + info sync."""
        response, enqueue = self.post_bom(self.bom_body())

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertTrue(ROW_KEYS <= set(body))
        self.assertEqual(body["product_id"], self.oven.pk)
        self.assertEqual(body["product_code"], "KTS-EXPORT-L")
        self.assertEqual(body["output_qty"], 1.0)
        self.assertEqual(body["uom_code"], "PCS")
        self.assertEqual(body["code"], "BOM-KTS-EXPORT-L")  # auto-generate
        self.assertEqual(body["lines_count"], 2)
        self.assertEqual(len(body["lines"]), 2)

        first, second = body["lines"]
        self.assertTrue(LINE_KEYS <= set(first))
        self.assertEqual(first["product_code"], "KAIN-COTTON")
        self.assertEqual(first["qty"], 1.5)
        self.assertEqual(first["uom_id"], self.uom.pk)
        self.assertEqual(first["sequence"], 10)  # default baris #1
        self.assertEqual(second["product_code"], "BENANG-X")
        self.assertEqual(second["sequence"], 20)  # default baris #2
        self.assertIsNone(second["uom_id"])  # baris boleh tanpa satuan (warisi produk)

        self.assertIsNotNone(body["sync_record_id"])
        self.assertEqual(body["task_id"], "task-bom-1")
        self.assertIs(body["queued"], True)

        bom = BOM.objects.get(pk=body["id"])
        self.assertEqual(bom.lines.filter(is_active=True).count(), 2)
        enqueue.assert_called_once()
        self.assertEqual(enqueue.call_args.kwargs["args"], [bom.pk, body["sync_record_id"]])

    def test_create_bom_auto_code_suffix(self):
        """Kode auto unik: ``BOM-<kode produk>`` lalu ``-2`` bila sudah terpakai."""
        self.make_bom(code="BOM-KTS-EXPORT-L")

        response, _ = self.post_bom(self.bom_body())

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["code"], "BOM-KTS-EXPORT-L-2")

    def test_create_bom_explicit_code_duplicate_400(self):
        """Kode eksplisit duplikat → 400 tanpa baris baru."""
        self.make_bom(code="BOM-CUSTOM")

        response, enqueue = self.post_bom(self.bom_body(code="BOM-CUSTOM"))

        self.assertEqual(response.status_code, 400)
        self.assertIn("sudah dipakai", response.json()["detail"])
        self.assertEqual(BOM.objects.count(), 1)
        enqueue.assert_not_called()

    def test_create_bom_invalid_payload_400(self):
        """Validasi: produk/output_qty/uom/active/lines + qty baris."""
        cases = (
            ({"product_id": 999999}, "tidak ditemukan"),
            ({"product_id": None}, "wajib diisi"),
            ({"output_qty": 0}, "lebih besar dari 0"),
            ({"output_qty": -2}, "lebih besar dari 0"),
            ({"output_qty": "banyak"}, "berupa angka"),
            ({"uom_id": 999999}, "tidak ditemukan"),
            ({"active": "kadang"}, "active"),
            ({"lines": "bukan-array"}, "harus berupa array"),
            ({"lines": [{"product_id": self.fabric.pk, "qty": 0}]}, "lebih besar dari 0"),
            ({"lines": [{"qty": 1}]}, "product_id"),
        )

        for overrides, needle in cases:
            with self.subTest(overrides=overrides):
                response, _ = self.post_bom(self.bom_body(**overrides))
                self.assertEqual(response.status_code, 400)
                self.assertIn(needle, response.json()["detail"])

        self.assertEqual(BOM.objects.count(), 0)

    def test_create_bom_atomic_rollback(self):
        """Kegagalan menulis baris #2 → BOM & baris #1 ikut di-rollback (atomic)."""
        original_save = BOMLine.save
        calls = {"count": 0}

        def flaky_save(line, *args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 2:
                raise RuntimeError("gagal menyimpan baris #2")
            return original_save(line, *args, **kwargs)

        with patch.object(BOMLine, "save", flaky_save), self.assertRaises(RuntimeError):
            create_bom(self.bom_body())

        self.assertEqual(BOM.objects.count(), 0)
        self.assertEqual(BOMLine.objects.count(), 0)

    def test_create_bom_self_reference_400(self):
        """Komponen = produk BOM sendiri → 400 (self-reference langsung)."""
        response, _ = self.post_bom(
            self.bom_body(lines=[{"product_id": self.oven.pk, "qty": 1}])
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("tidak boleh menjadi komponen BOM-nya sendiri", response.json()["detail"])
        self.assertEqual(BOM.objects.count(), 0)

    def test_create_bom_cycle_400(self):
        """Siklus tidak langsung (A → B → A) → 400."""
        # BOM "Kain" memakai Kaos sebagai komponen.
        kain_bom = self.make_bom(code="BOM-KAIN", product=self.fabric)
        BOMLine.objects.create(bom=kain_bom, product=self.oven, product_qty=1)

        response, _ = self.post_bom(
            self.bom_body(lines=[{"product_id": self.fabric.pk, "qty": 2}])
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Siklus BOM terdeteksi", response.json()["detail"])

    # ------------------------------------------------------------ PUT / detail
    def test_update_bom_header_only(self):
        """PUT header saja (tanpa ``lines``) → 200, baris tidak diubah + audit."""
        bom = self.make_bom()
        BOMLine.objects.create(bom=bom, product=self.fabric, product_qty=1.5)

        response, enqueue = self.put_bom(
            bom.pk, {"name": "BOM Kaos (baru)", "output_qty": 2, "notes": "catatan"}
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["name"], "BOM Kaos (baru)")
        self.assertEqual(body["output_qty"], 2.0)
        self.assertEqual(body["notes"], "catatan")
        self.assertEqual(body["lines_count"], 1)  # baris tidak disentuh
        self.assertEqual(body["code"], bom.code)  # tidak dikirim -> tetap

        bom.refresh_from_db()
        self.assertEqual(bom.output_qty, 2)
        self.assertEqual(bom.lines.filter(is_active=True).count(), 1)

        enqueue.assert_called_once()
        self.assertTrue(
            AuditLog.objects.filter(
                action="master.update",
                resource="master.bom",
                resource_id=str(bom.pk),
            ).exists()
        )

    def test_update_bom_replaces_lines(self):
        """PUT ``lines``: baris lama (by ``id``) diperbarui, yang hilang soft-deleted.

        Pencocokan memakai ``id`` baris MES; baris yang tidak lagi dikirim
        di-*soft-delete* (baris tetap ada di DB supaya ``odoo_id`` tidak hilang).
        """
        bom = self.make_bom()
        keep = BOMLine.objects.create(bom=bom, product=self.fabric, product_qty=1.5)
        dropped = BOMLine.objects.create(bom=bom, product=self.thread, product_qty=0.5)

        response, _ = self.put_bom(
            bom.pk,
            {
                "lines": [
                    {"id": keep.pk, "product_id": self.fabric.pk, "qty": 2.5},
                    {"product_id": self.thread.pk, "qty": 3},
                ]
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["lines_count"], 2)

        keep.refresh_from_db()
        self.assertEqual(keep.product_qty, 2.5)  # baris yang sama diperbarui
        dropped.refresh_from_db()
        self.assertFalse(dropped.is_active)  # soft delete, bukan dihapus
        self.assertTrue(BOMLine.objects.filter(pk=dropped.pk).exists())
        self.assertEqual(BOMLine.objects.filter(bom=bom, is_active=True).count(), 2)

    def test_update_bom_matches_line_by_odoo_id(self):
        """Baris cocok lewat ``odoo_id`` walau ``id`` tidak dikirim (hasil pull Odoo)."""
        bom = self.make_bom()
        line = BOMLine.objects.create(bom=bom, product=self.fabric, product_qty=1, odoo_id=7001)

        response, _ = self.put_bom(
            bom.pk, {"lines": [{"odoo_id": 7001, "product_id": self.fabric.pk, "qty": 4}]}
        )

        self.assertEqual(response.status_code, 200)
        line.refresh_from_db()
        self.assertEqual(line.product_qty, 4)
        self.assertEqual(BOMLine.objects.filter(bom=bom).count(), 1)

    def test_update_bom_lines_empty_soft_deletes_all(self):
        """``lines: []`` → semua baris non-aktif (tanpa hard delete)."""
        bom = self.make_bom()
        line = BOMLine.objects.create(bom=bom, product=self.fabric, product_qty=1)

        response, _ = self.put_bom(bom.pk, {"lines": []})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["lines_count"], 0)
        self.assertEqual(response.json()["lines"], [])
        line.refresh_from_db()
        self.assertFalse(line.is_active)
        self.assertTrue(BOMLine.objects.filter(pk=line.pk).exists())

    def test_update_bom_cycle_400(self):
        """PUT yang menciptakan siklus → 400, baris lama tidak berubah."""
        kain_bom = self.make_bom(code="BOM-KAIN", product=self.fabric)
        BOMLine.objects.create(bom=kain_bom, product=self.oven, product_qty=1)
        bom = self.make_bom(code="BOM-KTS-EXPORT-L", product=self.oven)
        BOMLine.objects.create(bom=bom, product=self.thread, product_qty=1)

        response, _ = self.put_bom(bom.pk, {"lines": [{"product_id": self.fabric.pk, "qty": 1}]})

        self.assertEqual(response.status_code, 400)
        self.assertIn("Siklus", response.json()["detail"])
        active = bom.lines.filter(is_active=True)
        self.assertEqual(active.count(), 1)  # tetap baris lama
        self.assertEqual(active.first().product, self.thread)

    def test_update_bom_empty_body_no_syncrecord(self):
        """PUT tanpa satu pun field → 200 tanpa ``SyncRecord``/audit/push."""
        bom = self.make_bom()

        response, enqueue = self.put_bom(bom.pk, {})

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["sync_record_id"])
        self.assertIsNone(response.json()["task_id"])
        self.assertFalse(response.json()["queued"])
        enqueue.assert_not_called()
        self.assertFalse(
            SyncRecord.objects.filter(resource=SyncResource.MASTER_BOM.value).exists()
        )

    def test_detail_and_missing_bom_404(self):
        """GET detail → 200 (dengan ``lines[]``); id tak dikenal → 404 GET/PUT/DELETE."""
        bom = self.make_bom()
        BOMLine.objects.create(bom=bom, product=self.fabric, product_qty=1.5, sequence=5)
        BOMLine.objects.create(bom=bom, product=self.thread, product_qty=0.5, is_active=False)

        detail = self.api.get(detail_url(bom.pk))
        self.assertEqual(detail.status_code, 200)
        body = detail.json()
        self.assertTrue(ROW_KEYS <= set(body))
        self.assertEqual(body["id"], bom.pk)
        self.assertEqual(body["lines_count"], 1)  # hanya baris aktif
        self.assertEqual([line["product_code"] for line in body["lines"]], ["KAIN-COTTON"])

        self.assertEqual(self.api.get(detail_url(999999)).status_code, 404)
        with patch(ENQUEUE, return_value=SimpleNamespace(id="task-none")):
            self.assertEqual(
                self.api.put(detail_url(999999), {"name": "X"}, format="json").status_code,
                404,
            )
            self.assertEqual(self.api.delete(detail_url(999999)).status_code, 404)

    # ---------------------------------------------------------- DELETE (soft)
    def test_delete_bom_soft_delete(self):
        """DELETE → 200 soft delete: ``active=False``, BOM & baris MASIH ada di DB."""
        bom = self.make_bom()
        line = BOMLine.objects.create(bom=bom, product=self.fabric, product_qty=1.5)

        response, enqueue = self.delete_bom(bom.pk)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["id"], bom.pk)
        self.assertTrue(body["deleted"])
        self.assertFalse(body["active"])

        bom.refresh_from_db()
        self.assertFalse(bom.is_active)
        self.assertTrue(BOM.objects.filter(pk=bom.pk).exists())
        self.assertTrue(BOMLine.objects.filter(pk=line.pk).exists())  # baris utuh
        self.assertFalse(self.api.get(detail_url(bom.pk)).json()["active"])
        enqueue.assert_called_once()

    # ------------------------------------------------------------------- GET list
    def test_list_boms_pagination_and_envelope(self):
        """Envelope ListPage + pagination + ``lines_count`` (hanya baris aktif)."""
        for index in range(3):
            bom = self.make_bom(code=f"BOM-L{index}")
            BOMLine.objects.create(bom=bom, product=self.fabric, product_qty=1)
        BOMLine.objects.create(
            bom=BOM.objects.get(code="BOM-L0"), product=self.thread, product_qty=1, is_active=False
        )

        first = self.api.get(BOMS_URL, {"limit": 2}).json()
        self.assertEqual(set(first), ENVELOPE_KEYS)
        self.assertEqual(first["total_count"], 3)
        self.assertEqual(len(first["rows"]), 2)
        self.assertTrue(first["has_more"])
        self.assertEqual(first["next_cursor"], 2)
        self.assertTrue(ROW_KEYS <= set(first["rows"][0]))
        self.assertEqual(first["rows"][0]["lines_count"], 1)  # baris nonaktif tidak dihitung
        self.assertNotIn("lines", first["rows"][0])  # daftar tidak memuat baris (anti N+1)

        second = self.api.get(BOMS_URL, {"limit": 2, "cursor": 2}).json()
        self.assertEqual(len(second["rows"]), 1)
        self.assertFalse(second["has_more"])
        self.assertIsNone(second["next_cursor"])

    def test_list_boms_filters(self):
        """Filter ``search`` (BOM & produk), ``product_id``, ``active``."""
        self.make_bom(code="BOM-KTS-EXPORT-L", product=self.oven, name="BOM Kaos Export L")
        self.make_bom(code="BOM-KAIN", product=self.fabric, name="BOM Kain Cotton")
        self.make_bom(
            code="BOM-OFF", product=self.thread, name="BOM Benang X", is_active=False
        )

        by_code = self.api.get(BOMS_URL, {"search": "KAIN"}).json()
        self.assertEqual([row["code"] for row in by_code["rows"]], ["BOM-KAIN"])

        by_product_name = self.api.get(BOMS_URL, {"search": "kaos export"}).json()
        self.assertEqual([row["code"] for row in by_product_name["rows"]], ["BOM-KTS-EXPORT-L"])

        by_product = self.api.get(BOMS_URL, {"product_id": self.fabric.pk}).json()
        self.assertEqual([row["code"] for row in by_product["rows"]], ["BOM-KAIN"])

        by_active = self.api.get(BOMS_URL, {"active": "false"}).json()
        self.assertEqual([row["code"] for row in by_active["rows"]], ["BOM-OFF"])

    def test_list_boms_invalid_params_400(self):
        """Parameter list ngawur → 400 (bukan 500)."""
        cases = (
            {"limit": "nol"},
            {"limit": "0"},
            {"limit": "201"},
            {"cursor": "-1"},
            {"product_id": "kaos"},
            {"active": "kadang"},
        )

        for params in cases:
            with self.subTest(params=params):
                response = self.api.get(BOMS_URL, params)
                self.assertEqual(response.status_code, 400)
                self.assertIn("detail", response.json())

    # -------------------------------------------------------------------- izin
    def test_anonymous_forbidden(self):
        """Tanpa kredensial → 403 untuk semua metode (GET/POST/PUT/DELETE)."""
        bom = self.make_bom()
        client = APIClient()

        self.assertEqual(client.get(BOMS_URL).status_code, 403)
        self.assertEqual(client.post(BOMS_URL, self.bom_body(), format="json").status_code, 403)
        self.assertEqual(client.get(detail_url(bom.pk)).status_code, 403)
        self.assertEqual(
            client.put(detail_url(bom.pk), {"name": "X"}, format="json").status_code, 403
        )
        self.assertEqual(client.delete(detail_url(bom.pk)).status_code, 403)

    def test_non_admin_roles_read_only(self):
        """Role non-ADMIN/OWNER: GET 200, tapi POST/PUT/DELETE 403 (tanpa efek)."""
        bom = self.make_bom()

        for name, client in self.readonly_apis.items():
            with self.subTest(role=name):
                self.assertEqual(client.get(BOMS_URL).status_code, 200)
                self.assertEqual(
                    client.post(BOMS_URL, self.bom_body(), format="json").status_code, 403
                )
                self.assertEqual(
                    client.put(detail_url(bom.pk), {"name": "X"}, format="json").status_code, 403
                )
                self.assertEqual(client.delete(detail_url(bom.pk)).status_code, 403)

        self.assertEqual(BOM.objects.count(), 1)
        bom.refresh_from_db()
        self.assertEqual(bom.name, "BOM Kaos Export L")
        self.assertTrue(bom.is_active)

    # --------------------------------------------- idempotensi & audit (H1.5)
    def test_syncrecord_written_on_create(self):
        """POST → ``SyncRecord`` PENDING (``master.bom``/``MASTER_PUSH``) + payload baris."""
        response, _ = self.post_bom(self.bom_body())
        bom_id = response.json()["id"]

        record = SyncRecord.objects.get(
            resource=SyncResource.MASTER_BOM.value,
            resource_id=str(bom_id),
            stage=SyncStage.MASTER_PUSH.value,
        )
        self.assertEqual(record.status, SyncStatus.PENDING)
        self.assertEqual(record.payload["code"], "BOM-KTS-EXPORT-L")
        self.assertEqual(record.payload["output_qty"], 1.0)
        self.assertEqual(len(record.payload["lines"]), 2)
        self.assertEqual(record.payload["lines"][0]["qty"], 1.5)
        self.assertIsNone(record.erp_id)

    def test_auditlog_written_on_create(self):
        """POST → ``AuditLog`` ``master.create`` resource ``master.bom``."""
        response, _ = self.post_bom(self.bom_body())
        bom_id = response.json()["id"]

        log = AuditLog.objects.get(action="master.create", resource_id=str(bom_id))
        self.assertEqual(log.resource, "master.bom")
        self.assertEqual(log.result, AuditLog.Result.OK)
        self.assertEqual(log.user_id, self.admin.pk)
        self.assertEqual(log.payload["code"], "BOM-KTS-EXPORT-L")

    def test_update_and_delete_reuse_syncrecord_and_write_audit(self):
        """PUT lalu DELETE memakai SATU ``SyncRecord`` + audit keduanya."""
        bom = self.make_bom()

        self.put_bom(bom.pk, {"name": "BOM Kaos Baru"})
        response, _ = self.delete_bom(bom.pk)

        records = SyncRecord.objects.filter(
            resource=SyncResource.MASTER_BOM.value, resource_id=str(bom.pk)
        )
        self.assertEqual(records.count(), 1)

        record = records.get()
        self.assertEqual(record.stage, SyncStage.MASTER_PUSH.value)
        self.assertEqual(record.status, SyncStatus.PENDING)
        self.assertIs(record.payload["active"], False)  # payload terbaru = soft delete
        self.assertEqual(record.payload["name"], "BOM Kaos Baru")
        self.assertEqual(record.pk, response.json()["sync_record_id"])

        actions = set(
            AuditLog.objects.filter(resource_id=str(bom.pk)).values_list("action", flat=True)
        )
        self.assertEqual(actions, {"master.update", "master.delete"})

    # --------------------------------------------------------------- push task
    @override_settings(ERP_ADAPTER="null")
    def test_push_task_enqueued_and_null_mode_marks_sent(self):
        """Task ``erp_sync.push_master_bom``: no-op mode null → SENT + idempotent."""
        response, enqueue = self.post_bom(self.bom_body())
        body = response.json()
        enqueue.assert_called_once()

        result = push_master_bom.apply(args=[body["id"], body["sync_record_id"]]).get()

        self.assertEqual(result["status"], "sent")
        self.assertTrue(str(result["erp_id"]).startswith("NULL-"))
        self.assertEqual(result["lines_synced"], 0)  # no-op tidak menyentuh Odoo
        self.assertEqual(result["resource"], SyncResource.MASTER_BOM.value)

        record = SyncRecord.objects.get(pk=body["sync_record_id"])
        self.assertEqual(record.status, SyncStatus.SENT)
        self.assertIsNotNone(record.sent_at)
        self.assertTrue(
            AuditLog.objects.filter(
                action="erp_sync.push_master_bom", resource_id=str(body["id"])
            ).exists()
        )

        again = push_master_bom.apply(args=[body["id"], body["sync_record_id"]]).get()
        self.assertEqual(again["status"], "duplicate-ignored")

    @override_settings(ERP_ADAPTER="odoo")
    def test_push_task_odoo_mode_product_without_tmpl_id_marks_failed(self):
        """Produk belum punya ``odoo_tmpl_id`` → **FAILED** pesan jelas (tanpa jaringan).

        ``MasterPushError`` dilempar di ``_bom_odoo_values`` sebelum transport dipakai
        (klien Odoo dibuat lazy, tanpa login), jadi test tidak menyentuh Odoo nyata.
        """
        response, _ = self.post_bom(self.bom_body())
        body = response.json()

        with self.assertRaises(MasterPushError) as ctx:
            push_master_bom.apply(args=[body["id"], body["sync_record_id"]]).get()

        self.assertIn("odoo_tmpl_id", str(ctx.exception))

        record = SyncRecord.objects.get(pk=body["sync_record_id"])
        self.assertEqual(record.status, SyncStatus.FAILED)
        self.assertEqual(record.attempts, 1)
        self.assertIsNone(record.erp_id)

    def test_bom_push_values_mapping(self):
        """Pemetaan payload → ``mrp.bom``/``mrp.bom.line`` (header pakai ``product_tmpl_id``)."""
        self.oven.odoo_id = 100
        self.oven.odoo_tmpl_id = 10
        self.oven.uom = self.uom
        self.oven.save(update_fields=("odoo_id", "odoo_tmpl_id", "uom"))
        self.uom.odoo_id = 33
        self.uom.save(update_fields=("odoo_id",))

        bom = self.make_bom()
        line = BOMLine.objects.create(bom=bom, product=self.oven, product_qty=1.5, sequence=7)

        values = _bom_odoo_values(bom, bom_payload(bom))
        self.assertEqual(
            values,
            {
                "product_tmpl_id": 10,
                "product_qty": 1.0,
                "product_uom_id": 33,
                "type": "normal",
                "active": True,
                "product_id": 100,
                "code": "BOM-KTS-EXPORT-L",
            },
        )

        line_values = _bom_line_odoo_values(line, 55)
        self.assertEqual(
            line_values,
            {
                "bom_id": 55,
                "product_id": 100,
                "product_qty": 1.5,
                "product_uom_id": 33,  # baris tanpa uom → warisi satuan produk
                "sequence": 7,
            },
        )

        # Komponen belum tersinkron → MasterPushError (bukan mengarang id).
        self.oven.odoo_id = None
        self.oven.save(update_fields=("odoo_id",))
        with self.assertRaises(MasterPushError):
            _bom_line_odoo_values(line, 55)

        # Produk BOM tanpa odoo_tmpl_id → header juga menolak.
        self.oven.odoo_tmpl_id = None
        self.oven.save(update_fields=("odoo_tmpl_id",))
        with self.assertRaises(MasterPushError):
            _bom_odoo_values(bom, bom_payload(bom))






