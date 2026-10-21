"""Test FASE K2 — endpoint kanban `/api/v1/garmen/<resource>/kanban/`.

Cakupan: kolom datang dari `core.state_machine` (label & urutan = baris DB, bukan
hardcode kode), transisi dari tabel `Transition`, filter `state`/`search`/
`work_center_id`/`line_id`, batas kartu per kolom (`limit` + `count` + `truncated`),
izin (anonim 403), resource di luar daftar (404), papan kosong, dan bentuk kartu
yang konsisten dengan endpoint list H2.4 (`allowed_actions`).

Non-breaking yang ikut dipin: endpoint list/detail/aksi F3 & H2.3/H2.4 tidak
disentuh (test ini tidak mengubah kontraknya).
"""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.models import Bundle, WorkOrder
from apps_industry.garment.services import kanban_services
from apps_industry.garment.tests.factories import (
    make_bundle,
    make_line,
    make_work_center,
    make_work_order,
)
from core.auth.models import User
from core.state_machine.models import State, Transition

BUNDLES_KANBAN = "/api/v1/garmen/bundles/kanban/"
WORK_ORDERS_KANBAN = "/api/v1/garmen/work-orders/kanban/"
BUNDLES_LIST = "/api/v1/garmen/bundles/"
BUNDLE_MACHINE = "garment.bundle"
WO_MACHINE = "garment.work_order"
CARD_KEYS = {
    "id",
    "code",
    "work_order_code",
    "size",
    "qty",
    "state",
    "allowed_actions",
}
TRANSITION_KEYS = {"from", "to", "action_id", "label"}


def column(body: dict, state: str) -> dict:
    """Kolom `state` dari response kanban (gagal keras kalau tidak ada)."""
    for item in body["columns"]:
        if item["state"] == state:
            return item

    raise AssertionError(f"kolom {state} tidak ada di response kanban")


class KanbanTestCase(TestCase):
    """Data: 2 bundle DRAFT + 1 CUTTING (2 WC, 2 memakai line), 1 WO DRAFT."""

    @classmethod
    def setUpTestData(cls):
        cls.wc_a = make_work_center(code="WC-KB-A")
        cls.wc_b = make_work_center(code="WC-KB-B")
        cls.line = make_line(code="LINE-KB", work_centers=[cls.wc_a])
        cls.wo = make_work_order(code="WO-KB-1", qty_planned=40)

        cls.bundle_a = make_bundle(
            work_order=cls.wo,
            code="BND-KB-1",
            state="DRAFT",
            size="L",
            qty=5,
            current_work_center=cls.wc_a,
            production_line=cls.line,
        )
        cls.bundle_b = make_bundle(
            work_order=cls.wo,
            code="BND-KB-2",
            state="DRAFT",
            size="M",
            qty=7,
            current_work_center=cls.wc_b,
        )
        cls.bundle_c = make_bundle(
            work_order=cls.wo,
            code="BND-KB-3",
            state="CUTTING",
            size="L",
            qty=9,
            current_work_center=cls.wc_a,
            production_line=cls.line,
        )
        # Kredensial test (bukan rahasia produksi).
        cls.user = User.objects.create_user(  # noqa: S106 - kredensial test
            username="kanban-k2", password="x"
        )

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def as_user(self, user):
        """Client terautentikasi (anonim bila ``user`` None)."""
        client = APIClient()
        if user is not None:
            client.force_authenticate(user)

        return client


class KanbanColumnTests(KanbanTestCase):
    """Kolom = data `core.state_machine` (4 test)."""

    def test_kolom_bundle_dari_state_machine_db(self):
        body = self.api.get(BUNDLES_KANBAN).json()

        self.assertEqual(body["machine"], BUNDLE_MACHINE)
        self.assertEqual(
            [item["state"] for item in body["columns"]],
            ["DRAFT", "CUTTING", "SEWING", "QC", "DONE"],
        )
        self.assertEqual(
            [item["label"] for item in body["columns"]],
            ["Draft", "Cutting", "Sewing", "QC", "Done"],
        )

    def test_kolom_work_order_dari_state_machine_db(self):
        body = self.api.get(WORK_ORDERS_KANBAN).json()

        self.assertEqual(body["machine"], WO_MACHINE)
        self.assertEqual(
            [item["state"] for item in body["columns"]],
            ["DRAFT", "IN_PROGRESS", "DONE", "CANCELLED"],
        )
        self.assertEqual(column(body, "IN_PROGRESS")["label"], "In Progress")
        self.assertEqual(column(body, "DRAFT")["count"], 1)

    def test_kolom_label_ikut_db_bukan_hardcode(self):
        State.objects.filter(machine__code=BUNDLE_MACHINE, code="CUTTING").update(
            label="Potong"
        )

        body = self.api.get(BUNDLES_KANBAN).json()

        self.assertEqual(column(body, "CUTTING")["label"], "Potong")
        self.assertEqual(column(body, "DRAFT")["label"], "Draft")

    def test_kolom_count_dan_limit_per_kolom(self):
        body = self.api.get(BUNDLES_KANBAN).json()

        self.assertEqual(column(body, "DRAFT")["count"], 2)
        self.assertEqual(column(body, "CUTTING")["count"], 1)
        self.assertEqual(column(body, "SEWING")["count"], 0)
        self.assertEqual(column(body, "SEWING")["cards"], [])
        self.assertEqual(body["total_count"], 3)
        self.assertEqual(body["limit"], kanban_services.DEFAULT_LIMIT_PER_COLUMN)
        self.assertFalse(body["truncated"])

        limited = self.api.get(BUNDLES_KANBAN, {"limit": 1}).json()

        self.assertEqual(limited["limit"], 1)
        self.assertEqual(column(limited, "DRAFT")["count"], 2)
        self.assertEqual(
            [card["code"] for card in column(limited, "DRAFT")["cards"]], ["BND-KB-1"]
        )
        self.assertTrue(column(limited, "DRAFT")["truncated"])
        self.assertTrue(limited["truncated"])
        self.assertEqual(limited["total_count"], 3)


class KanbanOrderTests(KanbanTestCase):
    """Urutan kolom = `State.order` (2 test)."""

    def test_urutan_kolom_by_state_order(self):
        body = self.api.get(BUNDLES_KANBAN).json()

        expected = list(
            State.objects.filter(machine__code=BUNDLE_MACHINE)
            .order_by("order", "code")
            .values_list("code", "order")
        )
        self.assertEqual(
            [(item["state"], item["order"]) for item in body["columns"]], expected
        )
        orders = [item["order"] for item in body["columns"]]
        self.assertEqual(orders, sorted(orders))

    def test_urutan_kolom_ikut_perubahan_order(self):
        State.objects.filter(machine__code=BUNDLE_MACHINE, code="DRAFT").update(order=60)

        body = self.api.get(BUNDLES_KANBAN).json()

        self.assertEqual(
            [item["state"] for item in body["columns"]],
            ["CUTTING", "SEWING", "QC", "DONE", "DRAFT"],
        )
        self.assertEqual(column(body, "DRAFT")["order"], 60)


class KanbanTransitionTests(KanbanTestCase):
    """Transisi = tabel `Transition` (2 test)."""

    def test_transisi_bundle_dari_tabel_transition(self):
        body = self.api.get(BUNDLES_KANBAN).json()
        transitions = body["transitions"]

        self.assertTrue(transitions)
        self.assertEqual(set(transitions[0]), TRANSITION_KEYS)
        pairs = {(item["from"], item["to"], item["action_id"]) for item in transitions}
        self.assertIn(("DRAFT", "CUTTING", "BUNDLE_START"), pairs)
        self.assertIn(("QC", "DONE", "BUNDLE_FINISH"), pairs)
        self.assertEqual(
            [item["from"] for item in transitions if item["action_id"] == "BUNDLE_SCRAP"],
            ["DRAFT", "CUTTING", "SEWING", "QC"],
        )
        self.assertTrue(all(item["label"] for item in transitions))
        self.assertEqual(
            len(transitions),
            Transition.objects.filter(
                machine__code=BUNDLE_MACHINE, is_active=True
            ).count(),
        )

    def test_transisi_wo_dari_tabel_transition(self):
        body = self.api.get(WORK_ORDERS_KANBAN).json()
        transitions = body["transitions"]
        pairs = {(item["from"], item["to"], item["action_id"]) for item in transitions}

        self.assertIn(("DRAFT", "IN_PROGRESS", "WO_START"), pairs)
        self.assertIn(("IN_PROGRESS", "DONE", "WO_CLOSE"), pairs)
        self.assertEqual(
            sum(1 for item in transitions if item["action_id"] == "WO_CANCEL"), 2
        )
        self.assertFalse(
            [item for item in transitions if item["action_id"].startswith("BUNDLE_")]
        )
        self.assertEqual(
            len(transitions),
            Transition.objects.filter(machine__code=WO_MACHINE, is_active=True).count(),
        )


class KanbanFilterTests(KanbanTestCase):
    """Filter `search`/`state`/`work_center_id`/`line_id` (3 test)."""

    def test_filter_search(self):
        response = self.api.get(BUNDLES_KANBAN, {"search": "KB-3"})

        self.assertEqual(response.status_code, 200)
        body = response.json()

        self.assertEqual(column(body, "DRAFT")["count"], 0)
        self.assertEqual(column(body, "CUTTING")["count"], 1)
        self.assertEqual(
            [card["code"] for card in column(body, "CUTTING")["cards"]], ["BND-KB-3"]
        )
        self.assertEqual(body["total_count"], 1)
        self.assertEqual(body["filters"]["applied"]["search"], "KB-3")

    def test_filter_state(self):
        body = self.api.get(BUNDLES_KANBAN, {"state": "cutting"}).json()

        self.assertEqual(column(body, "CUTTING")["count"], 1)
        self.assertEqual(column(body, "DRAFT")["count"], 0)
        self.assertEqual(column(body, "DRAFT")["cards"], [])
        self.assertEqual(body["total_count"], 1)
        self.assertEqual(body["filters"]["applied"]["state"], "cutting")
        # kolom tetap lengkap (state machine tidak ikut terfilter)
        self.assertEqual(len(body["columns"]), 5)

    def test_filter_work_center_dan_line_id(self):
        by_wc = self.api.get(BUNDLES_KANBAN, {"work_center_id": self.wc_a.pk}).json()

        self.assertEqual(by_wc["total_count"], 2)
        self.assertEqual(column(by_wc, "DRAFT")["count"], 1)
        self.assertEqual(column(by_wc, "CUTTING")["count"], 1)
        self.assertEqual(by_wc["filters"]["applied"]["work_center_id"], self.wc_a.pk)

        by_line = self.api.get(BUNDLES_KANBAN, {"line_id": self.line.pk}).json()
        self.assertEqual(by_line["total_count"], 2)
        self.assertEqual(by_line["filters"]["applied"]["line_id"], self.line.pk)

        # id bukan angka -> "tidak ada yang cocok" (bukan 500)
        invalid = self.api.get(BUNDLES_KANBAN, {"work_center_id": "abc"})
        self.assertEqual(invalid.status_code, 200)
        self.assertEqual(invalid.json()["total_count"], 0)

        # WorkOrder tidak punya FK work center -> param dilaporkan `ignored`
        wo_body = self.api.get(WORK_ORDERS_KANBAN, {"work_center_id": self.wc_a.pk}).json()
        self.assertEqual(wo_body["filters"]["applied"], {})
        self.assertEqual(wo_body["filters"]["ignored"], ["work_center_id"])
        self.assertEqual(wo_body["total_count"], 1)


class KanbanGuardTests(KanbanTestCase):
    """Izin, resource tak dikenal, papan kosong, bentuk kartu (4 test)."""

    def test_anonim_403(self):
        anon = self.as_user(None)

        self.assertEqual(anon.get(BUNDLES_KANBAN).status_code, 403)
        self.assertEqual(anon.get(WORK_ORDERS_KANBAN).status_code, 403)

    def test_resource_tidak_dikenal_404(self):
        self.assertEqual(self.api.get("/api/v1/garmen/qc/kanban/").status_code, 404)

        with self.assertRaises(kanban_services.UnknownKanbanResource):
            kanban_services.get_state_machine_for_resource("qc")

        with self.assertRaises(kanban_services.UnknownKanbanResource):
            kanban_services.get_kanban_queryset("nope")

    def test_empty_state_tetap_200(self):
        Bundle.objects.all().delete()
        WorkOrder.objects.all().delete()

        response = self.api.get(BUNDLES_KANBAN)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["columns"]), 5)
        self.assertTrue(
            all(item["count"] == 0 and item["cards"] == [] for item in body["columns"])
        )
        self.assertEqual(body["total_count"], 0)
        self.assertFalse(body["truncated"])
        self.assertTrue(body["transitions"])  # mesin tetap dibaca dari DB
        self.assertEqual(body["unknown_states"], {})

    def test_card_field_lengkap_dan_sama_dengan_list(self):
        body = self.api.get(BUNDLES_KANBAN).json()
        card = column(body, "DRAFT")["cards"][0]

        self.assertEqual(set(card), CARD_KEYS)
        self.assertEqual(card["id"], self.bundle_a.pk)
        self.assertEqual(card["code"], "BND-KB-1")
        self.assertEqual(card["work_order_code"], "WO-KB-1")
        self.assertEqual(card["size"], "L")
        self.assertEqual(card["qty"], 5)
        self.assertEqual(card["state"], "DRAFT")
        self.assertIn(
            {
                "id": "BUNDLE_START",
                "label": "Mulai Bundle",
                "mode": "optimistic",
                "endpoint": f"/garmen/bundles/{self.bundle_a.pk}/BUNDLE_START/",
            },
            card["allowed_actions"],
        )

        # Paritas kontrak: `allowed_actions` kanban == baris list H2.4 (reuse).
        rows = self.api.get(BUNDLES_LIST, {"search": "BND-KB-1"}).json()["rows"]
        self.assertEqual(rows[0]["allowed_actions"], card["allowed_actions"])
