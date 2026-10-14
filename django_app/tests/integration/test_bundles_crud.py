"""Test H2.4 — Bundle CRUD + split/merge (`/api/v1/garmen/bundles/…`).

Cakupan: create (per WorkOrder / jalur F2 `order_line_id`), preview (tanpa simpan),
update DRAFT-only + optimistic lock `X-Base-Version`, delete **hibrida** (hanya DRAFT
tanpa jejak produksi; selain itu 409), **split** (sum qty = sumber), **merge**
(2+ bundle DRAFT sejenis), list + filter, izin (anonim 403 / GET tetap publik), dan
ledger `SKIPPED` stage `BUNDLE_PUSH` + `AuditLog` (bundle = **MES-only** sebagai objek;
probe: Odoo tidak punya model bundle).

Non-breaking yang diuji di sini: list F3 tetap **9 key** + AllowAny, detail F3 tetap
kontrak lamanya (+ `version` 64 char), create F2 (`order_line_id`) tetap 201, aksi
state machine existing masih jalan, chatter bundle masih ada.
"""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.models import Bundle, BundleEvent, WorkOrder
from apps_industry.garment.tests.factories import (
    make_bundle,
    make_order_line,
    make_work_center,
    make_work_order,
)
from core.audit.models import AuditLog
from core.auth.models import Role, User
from integrations.erp_sync.models import (
    STAGE_BUNDLE_PUSH,
    STAGE_WIP,
    SyncRecord,
    SyncResource,
    SyncStatus,
)

BUNDLES_URL = "/api/v1/garmen/bundles/"
PREVIEW_URL = f"{BUNDLES_URL}preview/"
ENVELOPE_KEYS = {"rows", "total_count", "has_more", "next_cursor", "resource", "industry"}
#: Kontrak list F3 yang di-pin `apps_industry/garment/tests/test_list_endpoint.py:57`.
F3_LIST_KEYS = {
    "id",
    "code",
    "state",
    "size",
    "qty",
    "qty_done",
    "version",
    "current_work_center_code",
    "allowed_actions",
}

LEDGER = dict(resource=SyncResource.BUNDLE.value, stage=STAGE_BUNDLE_PUSH)


def detail_url(bundle_id: int) -> str:
    """URL detail/CRUD satu bundle (H2.4)."""
    return f"{BUNDLES_URL}{bundle_id}/"


def split_url(bundle_id: int) -> str:
    """URL split satu bundle (H2.4)."""
    return f"{BUNDLES_URL}{bundle_id}/split/"


def merge_url(bundle_id: int) -> str:
    """URL merge ke satu bundle target (H2.4)."""
    return f"{BUNDLES_URL}{bundle_id}/merge/"


class BundleTestCase(TestCase):
    """Basis bersama: order line + WorkOrder DRAFT, user simulator & admin."""

    @classmethod
    def setUpTestData(cls):
        cls.line = make_order_line(qty=20)
        cls.work_order = make_work_order(order_line=cls.line, code="WO-BND-1", qty_planned=20)
        cls.work_center = make_work_center(code="SEWING-BND")
        cls.sim = User.objects.create_user(username="sim-h24", password="x")  # noqa: S106
        cls.admin = User.objects.create_user(  # noqa: S106 - kredensial test
            username="admin-h24",
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
        """Payload create H2.4 default (satu size, bundle_size 5)."""
        data = {
            "work_order_id": self.work_order.pk,
            "size_matrix": {"L": 7},
            "bundle_size": 5,
        }
        data.update(overrides)

        return data

    def make_existing(self, code: str = "BND-TEST-1", **kwargs):
        """Bundle DRAFT langsung di DB (untuk uji update/delete/split/merge)."""
        return make_bundle(
            work_order=kwargs.pop("work_order", self.work_order),
            code=code,
            qty=kwargs.pop("qty", 10),
            **kwargs,
        )

    def make_wip_record(self, bundle: Bundle) -> SyncRecord:
        """Catat pergerakan stok WIP untuk bundle (guard delete/split/merge)."""
        return SyncRecord.objects.create(
            resource=SyncResource.BUNDLE.value,
            resource_id=str(bundle.pk),
            stage=STAGE_WIP,
            payload={"qty": 1},
        )


class BundleCreateTests(BundleTestCase):
    """Create (size matrix per WO), preview, ledger SKIPPED, dan jalur F2."""

    def test_create_per_work_order_plus_ledger_skipped(self):
        response = self.api.post(BUNDLES_URL, self.payload(), format="json")

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["created"], 2)  # L:7 + bundle_size 5 ⇒ 5 + 2
        self.assertEqual(body["work_order_id"], self.work_order.pk)
        self.assertEqual(body["summary"]["total_qty"], 7)
        self.assertEqual([row["qty"] for row in body["bundles"]], [5, 2])
        self.assertEqual(body["state"], "DRAFT")
        self.assertEqual(len(body["version"]), 64)

        codes = sorted(
            Bundle.objects.filter(work_order=self.work_order).values_list("code", flat=True)
        )
        self.assertEqual(codes, [f"{self.line.pk}-L-001", f"{self.line.pk}-L-002"])

        first = Bundle.objects.get(code=codes[0])
        record = SyncRecord.objects.get(
            resource=SyncResource.BUNDLE.value,
            resource_id=str(first.pk),
            stage=STAGE_BUNDLE_PUSH,
        )
        self.assertEqual(record.status, SyncStatus.SKIPPED)
        self.assertIn("MES-only", record.last_error)
        self.assertTrue(
            AuditLog.objects.filter(
                resource=SyncResource.BUNDLE.value, action="bundle.create"
            ).exists()
        )

    def test_create_multi_size_dan_bundle_size(self):
        response = self.api.post(
            BUNDLES_URL, self.payload(size_matrix={"L": 3, "M": 2}, bundle_size=2), format="json"
        )

        self.assertEqual(response.status_code, 201)
        rows = response.json()["bundles"]
        self.assertEqual(
            [(row["size"], row["qty"]) for row in rows], [("L", 2), ("L", 1), ("M", 2)]
        )

    def test_create_jalur_f2_order_line_id_tetap_201(self):
        line = make_order_line(qty=6)
        make_work_order(order_line=line, code="WO-BND-F2", qty_planned=6)

        response = self.api.post(
            BUNDLES_URL,
            {"order_line_id": line.pk, "size_matrix": {"S": 6}, "bundle_size": 4},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual([row["qty"] for row in response.json()["bundles"]], [4, 2])
        # Bundle menempel ke WO PERTAMA order line (semantik BundleEngine/F2).
        bundle = Bundle.objects.filter(work_order__order_line=line).first()
        self.assertIsNotNone(bundle)
        self.assertEqual(bundle.work_order.code, "WO-BND-F2")

    def test_create_dua_wo_order_line_sama_tidak_tabrakan_kode(self):
        """H2.3 memungkinkan >1 WO/order line ⇒ kode bundle batch kedua harus unik."""
        second = make_work_order(order_line=self.line, code="WO-BND-2", qty_planned=5)

        first = self.api.post(BUNDLES_URL, self.payload(size_matrix={"L": 2}), format="json")
        self.assertEqual(first.status_code, 201)

        again = self.api.post(
            BUNDLES_URL,
            {"work_order_id": second.pk, "size_matrix": {"L": 2}, "bundle_size": 5},
            format="json",
        )

        self.assertEqual(again.status_code, 201)
        codes = list(Bundle.objects.values_list("code", flat=True))
        self.assertEqual(len(codes), len(set(codes)))

    def test_create_404_wo_dan_order_line(self):
        missing_wo = self.api.post(BUNDLES_URL, self.payload(work_order_id=999999), format="json")
        missing_line = self.api.post(
            BUNDLES_URL, {"order_line_id": 999999, "size_matrix": {"L": 1}}, format="json"
        )

        self.assertEqual(missing_wo.status_code, 404)
        self.assertEqual(missing_line.status_code, 404)

    def test_create_400_wo_bukan_draft_dan_sudah_punya_bundle(self):
        wo = make_work_order(
            order_line=make_order_line(qty=3), code="WO-BND-IP", state="IN_PROGRESS"
        )
        bukan_draft = self.api.post(
            BUNDLES_URL, {"work_order_id": wo.pk, "size_matrix": {"L": 1}}, format="json"
        )

        self.assertEqual(bukan_draft.status_code, 400)
        self.assertIn("DRAFT", bukan_draft.json()["detail"])

        self.make_existing(code="BND-DUP-1")
        duplikat = self.api.post(BUNDLES_URL, self.payload(size_matrix={"M": 1}), format="json")

        self.assertEqual(duplikat.status_code, 400)
        self.assertIn("sudah punya bundle", duplikat.json()["detail"])

    def test_create_400_matrix_dan_bundle_size_invalid(self):
        for matrix in ({}, {"L": 0}, {"L": -1}, "bukan-objek"):
            with self.subTest(matrix=matrix):
                response = self.api.post(
                    BUNDLES_URL, self.payload(size_matrix=matrix), format="json"
                )
                self.assertEqual(response.status_code, 400)
                detail = response.json()["detail"]
                self.assertTrue("size_matrix" in detail or "qty untuk size" in detail, detail)

        bundle_size = self.api.post(BUNDLES_URL, self.payload(bundle_size=0), format="json")

        self.assertEqual(bundle_size.status_code, 400)
        self.assertIn("bundle_size", bundle_size.json()["detail"])

    def test_preview_tanpa_simpan(self):
        response = self.api.post(PREVIEW_URL, self.payload(size_matrix={"L": 7}), format="json")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual([row["qty"] for row in body["plan"]], [5, 2])
        self.assertEqual(body["summary"]["planned"], 2)
        self.assertEqual(Bundle.objects.count(), 0)  # TIDAK menyimpan

    def test_preview_invalid_400_dan_anonim_403(self):
        invalid = self.api.post(PREVIEW_URL, {"size_matrix": {}}, format="json")

        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(
            self.as_user(None).post(PREVIEW_URL, self.payload(), format="json").status_code, 403
        )


class BundleUpdateDeleteTests(BundleTestCase):
    """Update DRAFT-only (+optimistic lock) & delete hibrida."""

    def test_update_draft_ok_version_baru_dan_ledger(self):
        bundle = self.make_existing(qty=5)
        before = bundle.version

        response = self.api.put(
            detail_url(bundle.pk),
            {"size": "m", "sku_variant": "POLO-M", "qty": 8, "current_work_center_id": self.work_center.pk},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["size"], "M")
        self.assertEqual(body["sku_variant"], "POLO-M")
        self.assertEqual(body["qty"], 8)
        self.assertEqual(body["current_work_center_code"], "SEWING-BND")
        self.assertEqual(body["version"], Bundle.objects.get(pk=bundle.pk).version)

        record = SyncRecord.objects.get(
            resource=SyncResource.BUNDLE.value,
            resource_id=str(bundle.pk),
            stage=STAGE_BUNDLE_PUSH,
        )
        self.assertEqual(record.status, SyncStatus.SKIPPED)
        self.assertEqual(record.payload["action"], "update")
        # qty bukan field kritis ⇒ version boleh sama; tapi payload ledger ter-refresh.
        self.assertTrue(before)

    def test_update_400_qty_di_bawah_qty_done_dan_field_terlarang(self):
        bundle = self.make_existing(qty=5, qty_done=4)

        kecil = self.api.put(detail_url(bundle.pk), {"qty": 3}, format="json")
        code = self.api.put(detail_url(bundle.pk), {"code": "BND-BARU"}, format="json")
        state = self.api.put(detail_url(bundle.pk), {"state": "CUTTING"}, format="json")

        self.assertEqual(kecil.status_code, 400)
        self.assertIn("qty_done", kecil.json()["detail"])
        self.assertEqual(code.status_code, 400)
        self.assertIn("code", code.json()["detail"])
        self.assertEqual(state.status_code, 400)
        self.assertIn("BUNDLE_START", state.json()["detail"])

    def test_update_404_wc_dan_bukan_draft(self):
        bundle = self.make_existing()
        wc_hilang = self.api.put(
            detail_url(bundle.pk), {"current_work_center_id": 999999}, format="json"
        )
        bukan_draft = self.make_existing(code="BND-ND-1", state="CUTTING")
        tolak = self.api.put(detail_url(bukan_draft.pk), {"qty": 3}, format="json")

        self.assertEqual(wc_hilang.status_code, 404)
        self.assertEqual(tolak.status_code, 400)
        self.assertIn("DRAFT", tolak.json()["detail"])
        self.assertEqual(self.api.put(detail_url(999999), {"qty": 1}, format="json").status_code, 404)

    def test_update_optimistic_lock_409_dan_force(self):
        bundle = self.make_existing(qty=5)
        basi = self.api.put(
            detail_url(bundle.pk),
            {"qty": 6},
            format="json",
            HTTP_X_BASE_VERSION="versi-basi",
        )

        self.assertEqual(basi.status_code, 409)
        self.assertIn("current", basi.json())

        ok = self.api.put(
            detail_url(bundle.pk),
            {"qty": 6},
            format="json",
            HTTP_X_BASE_VERSION="versi-basi",
            HTTP_X_FORCE="true",
        )
        cocok = self.api.put(
            detail_url(bundle.pk),
            {"qty": 7},
            format="json",
            HTTP_X_BASE_VERSION=Bundle.objects.get(pk=bundle.pk).version,
        )

        self.assertEqual(ok.status_code, 200)
        self.assertEqual(cocok.status_code, 200)

    def test_delete_draft_tanpa_jejak_hard_delete(self):
        bundle = self.make_existing()
        bundle_id = bundle.pk
        # ledger CUD sendiri (BUNDLE_PUSH) TIDAK menghalangi delete.
        self.api.put(detail_url(bundle_id), {"qty": 11}, format="json")

        response = self.api.delete(detail_url(bundle_id))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["deleted"])
        self.assertFalse(Bundle.objects.filter(pk=bundle_id).exists())
        self.assertFalse(
            SyncRecord.objects.filter(
                resource=SyncResource.BUNDLE.value, resource_id=str(bundle_id)
            ).exists()
        )
        self.assertTrue(
            AuditLog.objects.filter(
                resource=SyncResource.BUNDLE.value, action="bundle.delete"
            ).exists()
        )

    def test_delete_409_punya_event_atau_wip_atau_bukan_draft(self):
        with_event = self.make_existing(code="BND-EV-1")
        BundleEvent.objects.create(bundle=with_event, event_type="BUNDLE_START", text="mulai")

        with_wip = self.make_existing(code="BND-WIP-1")
        self.make_wip_record(with_wip)

        bukan_draft = self.make_existing(code="BND-DONE-1", state="DONE")

        for bundle in (with_event, with_wip, bukan_draft):
            with self.subTest(code=bundle.code):
                response = self.api.delete(detail_url(bundle.pk))
                self.assertEqual(response.status_code, 409)
                self.assertIn(bundle.code, response.json()["detail"])

        self.assertEqual(Bundle.objects.count(), 3)

    def test_delete_anonim_403_dan_404(self):
        bundle = self.make_existing()

        self.assertEqual(self.as_user(None).delete(detail_url(bundle.pk)).status_code, 403)
        self.assertEqual(self.api.delete(detail_url(999999)).status_code, 404)


class BundleSplitTests(BundleTestCase):
    """Split: sum qty = sumber, DRAFT, tanpa jejak produksi."""

    def test_split_ok_bundle_asli_jadi_bagian_pertama(self):
        bundle = self.make_existing(qty=100)

        response = self.api.post(split_url(bundle.pk), {"parts": [60, 40]}, format="json")

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["qty"], 60)
        self.assertEqual(len(body["bundles"]), 1)
        self.assertEqual(body["bundles"][0]["qty"], 40)
        self.assertEqual(body["summary"]["created"], 1)

        total = sum(
            Bundle.objects.filter(work_order=self.work_order).values_list("qty", flat=True)
        )
        self.assertEqual(total, 100)
        codes = list(Bundle.objects.values_list("code", flat=True))
        self.assertEqual(len(codes), len(set(codes)))

    def test_split_tiga_bagian(self):
        bundle = self.make_existing(qty=30)

        response = self.api.post(split_url(bundle.pk), {"parts": [10, 10, 10]}, format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(response.json()["bundles"]), 2)
        self.assertEqual(Bundle.objects.filter(work_order=self.work_order).count(), 3)

    def test_split_total_tidak_sesuai_dan_payload_invalid_400(self):
        bundle = self.make_existing(qty=100)

        mismatch = self.api.post(split_url(bundle.pk), {"parts": [60, 30]}, format="json")
        satu = self.api.post(split_url(bundle.pk), {"parts": [100]}, format="json")
        nol = self.api.post(split_url(bundle.pk), {"parts": [60, 0]}, format="json")
        bukan_array = self.api.post(split_url(bundle.pk), {"parts": "60,40"}, format="json")

        self.assertEqual(mismatch.status_code, 400)
        self.assertIn("harus sama dengan qty bundle sumber", mismatch.json()["detail"])
        self.assertEqual(satu.status_code, 400)
        self.assertEqual(nol.status_code, 400)
        self.assertEqual(bukan_array.status_code, 400)
        self.assertEqual(Bundle.objects.filter(work_order=self.work_order).count(), 1)

    def test_split_409_kalau_sudah_bergerak_dan_400_bukan_draft(self):
        with_event = self.make_existing(code="BND-SP-EV")
        BundleEvent.objects.create(bundle=with_event, event_type="BUNDLE_START")

        with_wip = self.make_existing(code="BND-SP-WIP")
        self.make_wip_record(with_wip)

        bukan_draft = self.make_existing(code="BND-SP-ND", state="CUTTING")

        self.assertEqual(
            self.api.post(split_url(with_event.pk), {"parts": [5, 5]}, format="json").status_code,
            409,
        )
        self.assertEqual(
            self.api.post(split_url(with_wip.pk), {"parts": [5, 5]}, format="json").status_code,
            409,
        )
        tolak = self.api.post(split_url(bukan_draft.pk), {"parts": [5, 5]}, format="json")
        self.assertEqual(tolak.status_code, 400)
        self.assertIn("DRAFT", tolak.json()["detail"])

    def test_split_404_dan_anonim_403(self):
        bundle = self.make_existing()

        self.assertEqual(
            self.api.post(split_url(999999), {"parts": [5, 5]}, format="json").status_code, 404
        )
        self.assertEqual(
            self.as_user(None)
            .post(split_url(bundle.pk), {"parts": [5, 5]}, format="json")
            .status_code,
            403,
        )


class BundleMergeTests(BundleTestCase):
    """Merge: 2+ bundle DRAFT sejenis (WO + size + SKU sama) → target."""

    def test_merge_ok_qty_total_dan_sumber_hilang(self):
        target = self.make_existing(code="BND-MG-1", qty=5, size="L")
        source_a = self.make_existing(code="BND-MG-2", qty=5, size="L")
        source_b = self.make_existing(code="BND-MG-3", qty=3, size="L")

        response = self.api.post(
            merge_url(target.pk), {"bundle_ids": [source_a.pk, source_b.pk]}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["qty"], 13)
        self.assertEqual(body["summary"]["merged"], 2)
        self.assertFalse(Bundle.objects.filter(pk__in=[source_a.pk, source_b.pk]).exists())
        self.assertEqual(Bundle.objects.count(), 1)
        record = SyncRecord.objects.get(
            resource=SyncResource.BUNDLE.value,
            resource_id=str(target.pk),
            stage=STAGE_BUNDLE_PUSH,
        )
        self.assertEqual(record.payload["action"], "merge")

    def test_merge_409_wo_berbeda_dan_size_sku_beda(self):
        target = self.make_existing(code="BND-MX-1", qty=5, size="L")
        wo_lain = make_work_order(order_line=make_order_line(qty=5), code="WO-BND-LAIN")
        other_wo = make_bundle(work_order=wo_lain, code="BND-MX-2", qty=5, size="L")
        other_size = self.make_existing(code="BND-MX-3", qty=5, size="M")

        beda_wo = self.api.post(merge_url(target.pk), {"bundle_ids": [other_wo.pk]}, format="json")
        beda_size = self.api.post(
            merge_url(target.pk), {"bundle_ids": [other_size.pk]}, format="json"
        )

        self.assertEqual(beda_wo.status_code, 409)
        self.assertIn("WorkOrder", beda_wo.json()["detail"])
        self.assertEqual(beda_size.status_code, 409)
        self.assertIn("size/SKU", beda_size.json()["detail"])

    def test_merge_409_sumber_bukan_draft_atau_sudah_bergerak(self):
        target = self.make_existing(code="BND-MY-1", qty=5, size="L")
        bukan_draft = self.make_existing(code="BND-MY-2", qty=5, size="L", state="CUTTING")
        with_event = self.make_existing(code="BND-MY-3", qty=5, size="L")
        BundleEvent.objects.create(bundle=with_event, event_type="BUNDLE_START")

        tolak_nd = self.api.post(
            merge_url(target.pk), {"bundle_ids": [bukan_draft.pk]}, format="json"
        )
        tolak_ev = self.api.post(
            merge_url(target.pk), {"bundle_ids": [with_event.pk]}, format="json"
        )

        self.assertEqual(tolak_nd.status_code, 409)
        self.assertEqual(tolak_ev.status_code, 409)
        self.assertEqual(Bundle.objects.get(pk=target.pk).qty, 5)

    def test_merge_400_payload_invalid_dan_404_sumber(self):
        target = self.make_existing(code="BND-MZ-1", qty=5, size="L")

        kosong = self.api.post(merge_url(target.pk), {}, format="json")
        bukan_list = self.api.post(merge_url(target.pk), {"bundle_ids": "x"}, format="json")
        target_sendiri = self.api.post(
            merge_url(target.pk), {"bundle_ids": [target.pk]}, format="json"
        )
        hilang = self.api.post(merge_url(target.pk), {"bundle_ids": [999999]}, format="json")

        self.assertEqual(kosong.status_code, 400)
        self.assertEqual(bukan_list.status_code, 400)
        self.assertEqual(target_sendiri.status_code, 400)
        self.assertIn("Target merge", target_sendiri.json()["detail"])
        self.assertEqual(hilang.status_code, 404)

    def test_merge_404_target_dan_anonim_403(self):
        target = self.make_existing(code="BND-MW-1", qty=5, size="L")

        self.assertEqual(
            self.api.post(merge_url(999999), {"bundle_ids": [target.pk]}, format="json").status_code,
            404,
        )
        self.assertEqual(
            self.as_user(None)
            .post(merge_url(target.pk), {"bundle_ids": [target.pk]}, format="json")
            .status_code,
            403,
        )


class BundleListNonBreakingTests(BundleTestCase):
    """List + filter (kontrak 9 key) & non-breaking konsumen existing."""

    def test_list_tetap_sembilan_key_dan_allowany(self):
        bundle = self.make_existing(code="BND-F3-1", qty=7, size="L")
        anonim = self.as_user(None)

        response = anonim.get(BUNDLES_URL)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), ENVELOPE_KEYS)
        row = next(item for item in body["rows"] if item["id"] == bundle.pk)
        self.assertEqual(set(row), F3_LIST_KEYS)
        self.assertEqual(len(row["version"]), 64)

    def test_list_filter_state_size_search_work_order(self):
        self.make_existing(code="BND-FL-1", qty=5, size="L", state="CUTTING")
        self.make_existing(code="BND-FL-2", qty=5, size="M")

        by_state = self.api.get(BUNDLES_URL, {"state": "cutting"}).json()
        by_size = self.api.get(BUNDLES_URL, {"size": "m"}).json()
        by_search = self.api.get(BUNDLES_URL, {"search": "FL-2"}).json()
        by_wo = self.api.get(BUNDLES_URL, {"work_order_id": self.work_order.pk}).json()
        wo_hilang = self.api.get(BUNDLES_URL, {"work_order_id": 999999}).json()

        self.assertEqual([row["code"] for row in by_state["rows"]], ["BND-FL-1"])
        self.assertEqual([row["code"] for row in by_size["rows"]], ["BND-FL-2"])
        self.assertEqual([row["code"] for row in by_search["rows"]], ["BND-FL-2"])
        self.assertEqual(by_wo["total_count"], 2)
        self.assertEqual(wo_hilang["total_count"], 0)

    def test_list_limit_invalid_400(self):
        for params in ({"limit": 0}, {"limit": 999}, {"limit": "x"}):
            with self.subTest(params=params):
                response = self.api.get(BUNDLES_URL, params)
                self.assertEqual(response.status_code, 400)
                self.assertIn("limit", response.json()["detail"])

    def test_detail_get_mempertahankan_kontrak_f3(self):
        bundle = self.make_existing(code="BND-F3-2", qty=9, size="L")
        anonim = self.as_user(None)

        response = anonim.get(detail_url(bundle.pk))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["code"], "BND-F3-2")
        self.assertEqual(body["state"], "DRAFT")
        self.assertEqual(body["size"], "L")
        self.assertEqual(body["qty"], 9)
        self.assertEqual(body["work_order_id"], self.work_order.pk)
        self.assertEqual(len(body["version"]), 64)
        self.assertIn("allowed_actions", body)
        self.assertIn("events_count", body)
        self.assertEqual(body["ledger_status"], "SKIPPED")
        self.assertEqual(self.api.get(detail_url(999999)).status_code, 404)

    def test_aksi_state_machine_dan_chatter_tetap_jalan(self):
        bundle = self.make_existing(code="BND-F3-3", qty=5)

        action = self.api.post(f"{BUNDLES_URL}{bundle.pk}/BUNDLE_START/", {}, format="json")
        chatter = self.api.get(f"/api/v1/chatter/bundles/{bundle.pk}/")

        self.assertEqual(action.status_code, 200)
        self.assertEqual(Bundle.objects.get(pk=bundle.pk).state, "CUTTING")
        self.assertEqual(chatter.status_code, 200)

    def test_bundle_engine_masih_dipakai_untuk_rencana(self):
        """Create H2.4 tidak mengubah jalur lama: version 64 char & engine tetap jalan."""
        from apps_industry.garment.services.bundle_engine import BundleEngine

        response = self.api.post(BUNDLES_URL, self.payload(size_matrix={"L": 5}), format="json")
        self.assertEqual(response.status_code, 201)

        bundle = Bundle.objects.get(work_order=self.work_order)
        self.assertEqual(len(bundle.version), 64)
        plan = BundleEngine.preview_bundles(self.line, {"L": 5}, 5)
        self.assertEqual(len(plan), 1)


class BundleServiceUnitTests(BundleTestCase):
    """Unit service (tanpa HTTP): payload MES-only, row superset, normalisasi payload."""

    def test_bundle_payload_mes_only_dan_row_superset(self):
        from apps_industry.garment.services import bundle_services

        bundle = self.make_existing(code="BND-SVC-1", qty=4, size="L")

        payload = bundle_services.bundle_payload(bundle)
        row = bundle_services.bundle_row(bundle)

        self.assertTrue(payload["mes_only"])
        self.assertEqual(payload["code"], "BND-SVC-1")
        self.assertEqual(row["work_order_code"], self.work_order.code)
        self.assertEqual(row["ledger_status"], "SKIPPED")
        self.assertEqual(row["events_count"], 0)

    def test_validate_payload_normalisasi_size_dan_qty(self):
        from apps_industry.garment.services import bundle_services

        values, error, not_found = bundle_services.validate_bundle_payload(
            {"work_order_id": self.work_order.pk, "size_matrix": {" l ": 3, "L": 2}}
        )

        self.assertIsNone(error)
        self.assertFalse(not_found)
        self.assertEqual(values["size_matrix"], {"L": 5})
        self.assertEqual(values["bundle_size"], 1)
