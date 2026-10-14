"""Test CRUD master Routing DAG — extend B22 ``/api/v1/settings/routing/`` (H1.9).

Cakupan (32 test): list B22 (**shape TIDAK berubah** — 16 test F3A tetap hijau),
detail baru (``capability_tags``/``steps_count``/``nodes[]``/``edges[]``), PUT header,
DELETE soft delete **+ guard rule tag-router aktif**, POST/PUT/DELETE step (node DAG)
dengan validasi **siklus** (DFS, ``MAX_DAG_DEPTH``), self-reference, referensi lintas
routing, ``order`` duplikat (400 — bukan 500 constraint), izin (anonim 403; tulis
endpoint H1.9 **ADMIN/OWNER**), serta kewajiban H1.9: ``SyncRecord``
``master.process_routing``/``MASTER_PUSH`` ber-status **``SKIPPED``** (MES-only) +
``AuditLog`` tiap tulis.

Keputusan H1.9 (STEP 0 — probe Odoo 17 + recon B22):
  * **MES-only** — ``mrp.routing`` tidak ada di Odoo 17; ``mrp.routing.workcenter`` =
    Operation per-BoM (wajib ``bom_id``+``workcenter_id``) ⇒ tanpa push/pull, tanpa
    ``odoo_id``;
  * **extend B22 di tempat** (tanpa endpoint paralel ``/master/routings/``): halaman
    master frontend memakai endpoint yang sama;
  * izin tulis lama (POST B22) dibiarkan ``IsAuthenticated``; endpoint **baru**
    (PUT/DELETE header + POST/PUT/DELETE step) **ADMIN/OWNER** — inkonsistensi
    disengaja, dicatat di ``decisions[]`` JSON;
  * ``DELETE`` step = **structural** (hapus baris): ``RoutingStep`` tidak punya
    ``is_active`` dan menambahkannya membuat konsumen membaca step nonaktif.

Non-breaking: `TagRouter`, `CapabilityAllocator`, dan monitoring
``_routing_nodes_edges`` diuji ulang di kelas terakhir memakai routing hasil API.

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_master_routings_crud.py -q
"""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.models import ProcessRouting, RoutingStep
from apps_industry.garment.services.capability_allocator import CapabilityAllocator
from apps_industry.garment.services.tag_router import TagRouter
from apps_industry.garment.tests.factories import (
    make_routing,
    make_step,
    make_tag_rule,
    make_work_center,
)
from core.audit.models import AuditLog
from core.auth.models import Role, User
from integrations.erp_sync import monitoring
from integrations.erp_sync.models import SyncRecord, SyncResource, SyncStage, SyncStatus
from master.routing_services import MES_ONLY_REASON

LIST_URL = "/api/v1/settings/routing/"
ENVELOPE_KEYS = {"rows", "total_count", "has_more", "next_cursor"}
#: Shape B22 (F3A) — dipin **eksak** supaya H1.9 tidak menyentuh list.
ROW_KEYS = {"id", "code", "name", "description", "is_active", "steps"}
STEP_KEYS = {
    "id",
    "step_no",
    "wc_type",
    "depends_on",
    "rework_target_step",
    "is_initial",
    "is_terminal",
}
#: Field BARU H1.9 — hanya di endpoint detail (bukan list B22).
DETAIL_KEYS = ROW_KEYS | {
    "capability_tags",
    "steps_count",
    "nodes",
    "edges",
    "created_at",
    "updated_at",
}


def detail_url(pk: int) -> str:
    """URL detail/ubah/nonaktifkan satu routing."""
    return f"{LIST_URL}{pk}/"


def steps_url(pk: int) -> str:
    """URL koleksi step routing."""
    return f"{LIST_URL}{pk}/steps/"


def step_url(pk: int, step_id: int) -> str:
    """URL satu step routing."""
    return f"{LIST_URL}{pk}/steps/{step_id}/"


class RoutingCrudTestCase(TestCase):
    """Basis bersama: user admin/operator/qc + client admin siap pakai."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="admin-route",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.ADMIN),
        )
        cls.operator = User.objects.create_user(
            username="op-route",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.OPERATOR),
        )
        cls.qc = User.objects.create_user(
            username="qc-route",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.QC),
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

    @staticmethod
    def seed_routing(code="RT-H19", name="Routing H1.9"):
        """Routing 2 step (1 → 2) — bentuk seed sama dengan test F3A."""
        routing = make_routing(code=code)
        routing.name = name
        routing.save(update_fields=("name",))
        step1 = make_step(routing, "STEP-1", 1, label="CUTTING", is_initial=True)
        step2 = make_step(routing, "STEP-2", 2, label="SEWING", is_terminal=True)
        step1.allowed_next_steps.add(step2)
        return routing


class RoutingPermissionTests(RoutingCrudTestCase):
    """Anonim 403; tulis endpoint H1.9 hanya ADMIN/OWNER (POST B22 tetap seperti F3A)."""

    def test_anonim_list_dan_detail_403(self):
        routing = self.seed_routing()

        self.assertEqual(self.as_user(None).get(LIST_URL).status_code, 403)
        self.assertEqual(self.as_user(None).get(detail_url(routing.pk)).status_code, 403)

    def test_anonim_put_detail_403(self):
        routing = self.seed_routing()

        response = self.as_user(None).put(
            detail_url(routing.pk), {"name": "X"}, format="json"
        )

        self.assertEqual(response.status_code, 403)

    def test_anonim_post_step_403(self):
        routing = self.seed_routing()

        response = self.as_user(None).post(
            steps_url(routing.pk), {"label": "QC"}, format="json"
        )

        self.assertEqual(response.status_code, 403)

    def test_non_admin_put_detail_403(self):
        routing = self.seed_routing()

        response = self.as_user(self.operator).put(
            detail_url(routing.pk), {"name": "Diubah operator"}, format="json"
        )

        self.assertEqual(response.status_code, 403)
        routing.refresh_from_db()
        self.assertEqual(routing.name, "Routing H1.9")

    def test_non_admin_delete_routing_dan_post_step_403(self):
        routing = self.seed_routing()

        self.assertEqual(
            self.as_user(self.qc).delete(detail_url(routing.pk)).status_code, 403
        )
        self.assertEqual(
            self.as_user(self.qc)
            .post(steps_url(routing.pk), {"label": "QC"}, format="json")
            .status_code,
            403,
        )
        self.assertEqual(routing.steps.count(), 2)


class RoutingDetailGetTests(RoutingCrudTestCase):
    """Detail baru: field B22 + field H1.9 (list B22 tidak tersentuh)."""

    def test_list_b22_shape_tetap(self):
        self.seed_routing()

        body = self.api.get(LIST_URL).json()

        self.assertEqual(set(body), ENVELOPE_KEYS)
        row = body["rows"][0]
        self.assertEqual(set(row), ROW_KEYS)
        self.assertEqual(set(row["steps"][0]), STEP_KEYS)

    def test_detail_shape_dan_field_h19(self):
        routing = self.seed_routing()

        body = self.api.get(detail_url(routing.pk)).json()

        self.assertEqual(set(body), DETAIL_KEYS)
        self.assertEqual(body["code"], "RT-H19")
        self.assertEqual(body["steps_count"], 2)
        self.assertEqual(body["capability_tags"], [])
        self.assertEqual(set(body["steps"][0]), STEP_KEYS)
        self.assertTrue(body["is_active"])

    def test_detail_nodes_edges_shape_routing_graph(self):
        routing = self.seed_routing()
        step1 = routing.steps.get(order=1)
        step2 = routing.steps.get(order=2)

        body = self.api.get(detail_url(routing.pk)).json()

        self.assertEqual(
            body["nodes"],
            [
                {"id": step1.pk, "label": "CUTTING", "step_no": 1},
                {"id": step2.pk, "label": "SEWING", "step_no": 2},
            ],
        )
        self.assertEqual(
            body["edges"],
            [
                {
                    "from": step1.pk,
                    "to": step2.pk,
                    "overlap_pct": 0,
                    "is_rework": False,
                }
            ],
        )

        # edge rework (QC → SEWING) ditandai is_rework — routing terpisah
        rework = make_routing(code="RT-REWORK")
        r1 = make_step(rework, "STEP-1", 1, label="SEWING", is_initial=True)
        r2 = make_step(
            rework, "STEP-2", 2, label="QC", is_terminal=True, rework_target_step=r1
        )
        r1.allowed_next_steps.add(r2)

        edges = self.api.get(detail_url(rework.pk)).json()["edges"]

        self.assertEqual(
            [edge for edge in edges if edge["is_rework"]],
            [{"from": r2.pk, "to": r1.pk, "overlap_pct": 0, "is_rework": True}],
        )

    def test_detail_capability_tags_dan_404(self):
        routing = self.seed_routing()
        routing.capability_tags = ["JAHIT", "obras"]
        routing.save(update_fields=("capability_tags",))

        body = self.api.get(detail_url(routing.pk)).json()

        self.assertEqual(body["capability_tags"], ["JAHIT", "obras"])
        self.assertEqual(self.api.get(detail_url(999999)).status_code, 404)


class RoutingStepCreateTests(RoutingCrudTestCase):
    """POST /routing/<id>/steps/ — node DAG baru + edge + validasi."""

    def test_post_step_sukses_201_order_dan_wc(self):
        routing = self.seed_routing()
        step2 = routing.steps.get(order=2)
        work_center = make_work_center("WC-SEWING")

        response = self.api.post(
            steps_url(routing.pk),
            {
                "label": "QC",
                "work_center_id": work_center.pk,
                "depends_on_step_ids": [step2.pk],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(set(body), DETAIL_KEYS)
        self.assertEqual(body["steps_count"], 3)
        baru = body["steps"][-1]
        # order otomatis = max(2) + 10
        self.assertEqual(baru["step_no"], 12)
        self.assertEqual(baru["wc_type"], "QC")
        self.assertEqual(baru["depends_on"], [2])
        self.assertFalse(baru["is_initial"])
        self.assertTrue(baru["is_terminal"])

        step = RoutingStep.objects.get(pk=baru["id"])
        self.assertEqual(step.work_center_id, work_center.pk)
        self.assertEqual(step.code, "STEP-12")

    def test_post_step_mengisi_edge_keluar(self):
        routing = self.seed_routing()
        step2 = routing.steps.get(order=2)

        response = self.api.post(
            steps_url(routing.pk),
            {"label": "PACKING", "order": 5, "next_step_ids": [step2.pk]},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        baru = RoutingStep.objects.get(pk=response.json()["steps"][-1]["id"])
        self.assertEqual(list(baru.allowed_next_steps.values_list("pk", flat=True)), [step2.pk])
        # edge masuk hanya dari depends_on → step baru ini step awal
        self.assertEqual(list(baru.allowed_from.values_list("pk", flat=True)), [])
        self.assertTrue(baru.is_initial)
        self.assertFalse(baru.is_terminal)

    def test_post_step_order_duplikat_dan_label_kosong_400(self):
        routing = self.seed_routing()

        duplikat = self.api.post(
            steps_url(routing.pk), {"label": "X", "order": 1}, format="json"
        )
        kosong = self.api.post(steps_url(routing.pk), {"label": "   "}, format="json")

        self.assertEqual(duplikat.status_code, 400)
        self.assertEqual(kosong.status_code, 400)
        self.assertEqual(routing.steps.count(), 2)

    def test_post_step_work_center_tidak_dikenal_400(self):
        routing = self.seed_routing()

        response = self.api.post(
            steps_url(routing.pk), {"label": "X", "work_center_id": 999999}, format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("tidak ditemukan", response.json()["detail"])
        self.assertEqual(routing.steps.count(), 2)

    def test_post_step_lintas_routing_400(self):
        routing = self.seed_routing()
        lain = self.seed_routing(code="RT-LAIN", name="Routing lain")
        step_lain = lain.steps.get(order=1)

        depends = self.api.post(
            steps_url(routing.pk),
            {"label": "X", "depends_on_step_ids": [step_lain.pk]},
            format="json",
        )
        rework = self.api.post(
            steps_url(routing.pk),
            {"label": "Y", "rework_target_step_id": step_lain.pk},
            format="json",
        )

        self.assertEqual(depends.status_code, 400)
        self.assertIn("bukan bagian routing", depends.json()["detail"])
        self.assertEqual(rework.status_code, 400)
        self.assertEqual(routing.steps.count(), 2)

    def test_post_step_siklus_400_dan_rollback(self):
        routing = self.seed_routing()
        step1 = routing.steps.get(order=1)
        step2 = routing.steps.get(order=2)

        # B → C → A akan menutup siklus A → B → C → A
        response = self.api.post(
            steps_url(routing.pk),
            {
                "label": "QC",
                "depends_on_step_ids": [step2.pk],
                "next_step_ids": [step1.pk],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("siklus", response.json()["detail"])
        self.assertEqual(routing.steps.count(), 2)


class RoutingHeaderUpdateTests(RoutingCrudTestCase):
    """PUT /routing/<id>/ — ubah header (name/code/description/tags/active)."""

    def test_put_update_header_ok(self):
        routing = self.seed_routing()

        response = self.api.put(
            detail_url(routing.pk),
            {
                "name": "Routing Baru",
                "description": "dari test",
                "capability_tags": ["jahit", "JAHIT", "obras"],
                "active": False,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["name"], "Routing Baru")
        self.assertEqual(body["capability_tags"], ["jahit", "obras"])
        self.assertFalse(body["is_active"])

        routing.refresh_from_db()
        self.assertEqual(routing.description, "dari test")
        self.assertFalse(routing.is_active)

    def test_put_reactivate_ok(self):
        routing = self.seed_routing()
        ProcessRouting.objects.filter(pk=routing.pk).update(is_active=False)

        body = self.api.put(detail_url(routing.pk), {"active": True}, format="json").json()

        self.assertTrue(body["is_active"])

    def test_put_code_duplikat_400(self):
        routing = self.seed_routing()
        self.seed_routing(code="RT-PAKAI", name="Routing pakai")

        response = self.api.put(detail_url(routing.pk), {"code": "rt-pakai"}, format="json")

        self.assertEqual(response.status_code, 400)
        routing.refresh_from_db()
        self.assertEqual(routing.code, "RT-H19")

    def test_put_name_kosong_dan_tags_bukan_array_400(self):
        routing = self.seed_routing()

        kosong = self.api.put(detail_url(routing.pk), {"name": "   "}, format="json")
        tags = self.api.put(
            detail_url(routing.pk), {"capability_tags": "JAHIT"}, format="json"
        )

        self.assertEqual(kosong.status_code, 400)
        self.assertEqual(tags.status_code, 400)


class RoutingStepUpdateDeleteTests(RoutingCrudTestCase):
    """PUT/DELETE /routing/<id>/steps/<step_id>/ — replace edge atomic + rollback."""

    def test_put_step_ganti_depends_on_atomik(self):
        routing = self.seed_routing()
        step1 = routing.steps.get(order=1)
        step2 = routing.steps.get(order=2)

        response = self.api.put(
            step_url(routing.pk, step2.pk), {"depends_on_step_ids": []}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        step1.refresh_from_db()
        step2.refresh_from_db()
        self.assertEqual(list(step2.allowed_from.values_list("pk", flat=True)), [])
        self.assertEqual(list(step1.allowed_next_steps.values_list("pk", flat=True)), [])
        self.assertTrue(step2.is_initial)
        self.assertTrue(step1.is_terminal)
        self.assertEqual(response.json()["steps"][1]["depends_on"], [])

    def test_put_step_label_order_ok_dan_duplikat_400(self):
        routing = self.seed_routing()
        step2 = routing.steps.get(order=2)

        response = self.api.put(
            step_url(routing.pk, step2.pk),
            {"label": "FINISHING", "order": 7},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        step2.refresh_from_db()
        self.assertEqual(step2.label, "FINISHING")
        self.assertEqual(step2.order, 7)
        self.assertEqual(response.json()["steps"][-1]["step_no"], 7)

        duplikat = self.api.put(step_url(routing.pk, step2.pk), {"order": 1}, format="json")

        self.assertEqual(duplikat.status_code, 400)
        step2.refresh_from_db()
        self.assertEqual(step2.order, 7)

    def test_put_step_siklus_400_dan_rollback(self):
        routing = self.seed_routing()
        step1 = routing.steps.get(order=1)
        step2 = routing.steps.get(order=2)

        # step1 depends_on step2 → edge step2 → step1 menutup siklus 1 → 2 → 1
        response = self.api.put(
            step_url(routing.pk, step1.pk),
            {"depends_on_step_ids": [step2.pk]},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("siklus", response.json()["detail"])
        step1.refresh_from_db()
        step2.refresh_from_db()
        self.assertEqual(list(step1.allowed_from.values_list("pk", flat=True)), [])
        self.assertEqual(
            list(step1.allowed_next_steps.values_list("pk", flat=True)), [step2.pk]
        )

    def test_put_step_self_reference_lintas_dan_404(self):
        routing = self.seed_routing()
        lain = self.seed_routing(code="RT-LAIN3", name="Routing lain 3")
        step1 = routing.steps.get(order=1)

        sendiri = self.api.put(
            step_url(routing.pk, step1.pk),
            {"depends_on_step_ids": [step1.pk]},
            format="json",
        )
        lintas = self.api.put(
            step_url(routing.pk, step1.pk),
            {"depends_on_step_ids": [lain.steps.get(order=1).pk]},
            format="json",
        )
        asing = self.api.put(
            step_url(routing.pk, lain.steps.get(order=1).pk), {"label": "X"}, format="json"
        )

        self.assertEqual(sendiri.status_code, 400)
        self.assertIn("dirinya sendiri", sendiri.json()["detail"])
        self.assertEqual(lintas.status_code, 400)
        self.assertEqual(asing.status_code, 404)

    def test_delete_step_ok_dan_recompute(self):
        routing = self.seed_routing()
        step1 = routing.steps.get(order=1)
        step2 = routing.steps.get(order=2)

        response = self.api.delete(step_url(routing.pk, step2.pk))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["steps_count"], 1)
        self.assertFalse(RoutingStep.objects.filter(pk=step2.pk).exists())
        step1.refresh_from_db()
        self.assertTrue(step1.is_initial)
        self.assertTrue(step1.is_terminal)
        self.assertEqual(self.api.delete(step_url(routing.pk, 999999)).status_code, 404)

    def test_delete_step_menullkan_rework_target_step_lain(self):
        routing = make_routing(code="RT-RW2")
        step1 = make_step(routing, "STEP-1", 1, label="SEWING", is_initial=True)
        step2 = make_step(
            routing, "STEP-2", 2, label="QC", is_terminal=True, rework_target_step=step1
        )
        step1.allowed_next_steps.add(step2)

        response = self.api.delete(step_url(routing.pk, step1.pk))

        self.assertEqual(response.status_code, 200)
        step2.refresh_from_db()
        self.assertIsNone(step2.rework_target_step)


class RoutingDeleteTests(RoutingCrudTestCase):
    """DELETE /routing/<id>/ — soft delete + guard rule tag-router aktif."""

    def test_delete_routing_soft_delete(self):
        routing = self.seed_routing()

        response = self.api.delete(detail_url(routing.pk))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["is_active"])
        routing.refresh_from_db()
        self.assertTrue(ProcessRouting.objects.filter(pk=routing.pk).exists())
        self.assertFalse(routing.is_active)
        # masih tampil di list (soft delete) dengan step utuh
        rows = self.api.get(LIST_URL).json()["rows"]
        self.assertEqual([row["code"] for row in rows], ["RT-H19"])
        self.assertEqual(len(rows[0]["steps"]), 2)

    def test_delete_routing_diblokir_rule_tag_router_aktif(self):
        routing = self.seed_routing()
        make_tag_rule("blokir-h19", routing_code=routing.code)

        response = self.api.delete(detail_url(routing.pk))

        self.assertEqual(response.status_code, 400)
        self.assertIn("rule tag-router aktif", response.json()["detail"])
        routing.refresh_from_db()
        self.assertTrue(routing.is_active)

    def test_delete_routing_ok_setelah_rule_nonaktif(self):
        routing = self.seed_routing()
        make_tag_rule("nonaktif-h19", routing_code=routing.code, is_active=False)

        response = self.api.delete(detail_url(routing.pk))

        self.assertEqual(response.status_code, 200)
        routing.refresh_from_db()
        self.assertFalse(routing.is_active)

    def test_delete_routing_404(self):
        self.assertEqual(self.api.delete(detail_url(999999)).status_code, 404)


class RoutingLedgerDanNonBreakingTests(RoutingCrudTestCase):
    """Kewajiban H1.9 (SyncRecord SKIPPED + AuditLog) dan konsumen lama tetap hijau."""

    def test_tulis_step_menulis_sync_record_skipped(self):
        routing = self.seed_routing()
        step2 = routing.steps.get(order=2)

        response = self.api.post(
            steps_url(routing.pk),
            {"label": "QC", "depends_on_step_ids": [step2.pk]},
            format="json",
        )
        self.assertEqual(response.status_code, 201)

        record = SyncRecord.objects.get(
            resource=SyncResource.MASTER_PROCESS_ROUTING.value,
            resource_id=str(routing.pk),
            stage=SyncStage.MASTER_PUSH.value,
        )
        self.assertEqual(record.status, SyncStatus.SKIPPED)
        self.assertEqual(record.last_error, MES_ONLY_REASON)
        self.assertEqual(record.payload["code"], "RT-H19")
        self.assertEqual([step["step_no"] for step in record.payload["steps"]], [1, 2, 12])

    def test_put_dan_delete_step_menulis_audit_log(self):
        routing = self.seed_routing()
        step2 = routing.steps.get(order=2)

        self.api.put(
            step_url(routing.pk, step2.pk), {"label": "FINISHING"}, format="json"
        )
        self.api.delete(step_url(routing.pk, step2.pk))

        actions = sorted(
            AuditLog.objects.filter(
                resource=SyncResource.MASTER_PROCESS_ROUTING.value,
                resource_id=str(routing.pk),
            ).values_list("action", flat=True)
        )
        self.assertEqual(actions, ["master.delete", "master.update"])
        self.assertTrue(
            AuditLog.objects.filter(resource_id=str(routing.pk)).first().metadata["mes_only"]
        )

    def test_consume_lama_tag_router_allocator_dan_monitoring(self):
        work_center = make_work_center("WC-B22")
        created = self.api.post(
            LIST_URL,
            {
                "name": "Routing B22 H1.9",
                "steps": [
                    {"step_no": 1, "wc_type": "CUTTING", "depends_on": []},
                    {"step_no": 2, "wc_type": "SEWING", "depends_on": [1]},
                ],
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        routing = ProcessRouting.objects.get(pk=created.json()["id"])
        step2 = routing.steps.get(order=2)

        updated = self.api.put(
            step_url(routing.pk, step2.pk), {"work_center_id": work_center.pk}, format="json"
        )
        self.assertEqual(updated.status_code, 200)

        # konsumen lama: TagRouter (by code), allocator (WC dari step), monitoring (nodes/edges)
        self.assertEqual(TagRouter._resolve_routing(routing.code).pk, routing.pk)
        self.assertEqual(CapabilityAllocator.required_work_centers(routing), {work_center.pk})
        detail = self.api.get(detail_url(routing.pk)).json()
        nodes, edges = monitoring._routing_nodes_edges(routing)
        self.assertEqual(detail["nodes"], nodes)
        self.assertEqual(detail["edges"], edges)
        self.assertTrue(routing.steps.get(order=1).is_initial)
        self.assertTrue(step2.is_terminal)




