"""Test endpoint schema work-order: `GET /api/v1/garmen/work-orders/<id>/schema/`."""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.tests.factories import make_work_order

URL_TEMPLATE = "/api/v1/garmen/work-orders/{id}/schema/"

KONTRAK_KEYS = {
    "resource",
    "industry",
    "view_type",
    "schema_version",
    "title",
    "version",
    "device_hint",
    "state_machine",
    "layout",
    "chatter",
}


class WorkOrderSchemaTests(TestCase):
    """Metadata WO: tombol/status/kolom datang dari backend (kontrak §1)."""

    @classmethod
    def setUpTestData(cls):
        cls.work_order = make_work_order(code="WO-001")

    def setUp(self):
        self.client = APIClient()

    def _get(self, work_order=None, industry="garmen"):
        work_order = work_order or self.work_order
        return self.client.get(
            f"/api/v1/{industry}/work-orders/{work_order.pk}/schema/"
        )

    def test_status_200_dan_key_persis_kontrak(self):
        response = self._get()

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), KONTRAK_KEYS)
        self.assertEqual(body["schema_version"], "1.0")
        self.assertEqual(body["view_type"], "form")
        # Fase B.1.1: `resource` = objek {name, label, id, version}.
        self.assertEqual(
            body["resource"],
            {
                "name": "work-orders",
                "label": "Work Order",
                "id": str(self.work_order.pk),
                "version": body["version"],
            },
        )
        self.assertEqual(body["industry"], "garmen")
        self.assertEqual(response["X-Schema-Version"], "1.0")

    def test_title_device_hint_dan_version(self):
        body = self._get().json()

        self.assertEqual(body["title"], "Work Order #WO-001")
        self.assertEqual(body["device_hint"], "OPERATOR_HP")
        self.assertRegex(body["version"], r"^[0-9a-f]{64}$")

    def test_version_berubah_kalau_state_berubah(self):
        versi_awal = self._get().json()["version"]

        self.work_order.state = "IN_PROGRESS"
        self.work_order.save()

        self.assertNotEqual(self._get().json()["version"], versi_awal)

    def test_state_machine_possible_states_dan_allowed_actions(self):
        machine = self._get().json()["state_machine"]

        self.assertEqual(machine["current_state"], "DRAFT")
        self.assertEqual(
            [state["id"] for state in machine["possible_states"]],
            ["DRAFT", "IN_PROGRESS", "DONE", "CANCELLED"],
        )
        # Fase B.1.2: `kind` diturunkan dari posisi (DRAFT = current).
        self.assertEqual(
            [state["kind"] for state in machine["possible_states"]],
            ["current", "future", "future", "future"],
        )
        # Dari DRAFT: WO_CANCEL (pessimistic) & WO_START (optimistic), urut action_id.
        self.assertEqual(
            [action["id"] for action in machine["allowed_actions"]],
            ["WO_CANCEL", "WO_START"],
        )
        self.assertEqual(machine["allowed_actions"][0]["mode"], "pessimistic")
        self.assertEqual(machine["allowed_actions"][1]["mode"], "optimistic")
        # Fase B.1.5: endpoint path dari backend (aksi pakai `action_id` asli).
        self.assertEqual(
            [action["endpoint"] for action in machine["allowed_actions"]],
            [
                f"/garmen/work-orders/{self.work_order.pk}/WO_CANCEL/",
                f"/garmen/work-orders/{self.work_order.pk}/WO_START/",
            ],
        )

    def test_layout_section_dan_field(self):
        layout = self._get().json()["layout"]

        # Fase B.1.3: `{sections: [{id, label, fields}]}`.
        self.assertEqual(set(layout), {"sections"})
        sections = layout["sections"]
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0]["id"], "info-wo")
        self.assertEqual(sections[0]["label"], "Info WO")
        fields = sections[0]["fields"]
        self.assertEqual(
            [field["name"] for field in fields],
            ["code", "state", "qty_planned", "qty_done"],
        )
        self.assertTrue(all(field["read_only"] for field in fields))
        # Fase B.1.4: tipe lama `text` dinormalkan jadi `string` (enum kontrak).
        self.assertEqual(fields[0]["type"], "string")
        self.assertEqual(fields[0]["value"], "WO-001")
        self.assertEqual(fields[2]["type"], "number")
        self.assertEqual(fields[2]["value"], self.work_order.qty_planned)

    def test_chatter_kosong_karena_wo_belum_punya_event_log(self):
        self.assertEqual(
            self._get().json()["chatter"],
            {
                "preview": [],
                "total_count": 0,
                "has_more": False,
                "next_cursor": None,
            },
        )

    def test_industry_valid_dinormalkan_dari_url(self):
        """Segment industri tetap diteruskan ke metadata (kanonik lowercase)."""
        body = self._get(industry="GARMEN").json()

        self.assertEqual(body["industry"], "garmen")
        self.assertEqual(body["resource"]["name"], "work-orders")

    def test_industry_tidak_dikenal_404(self):
        """Fase A: whitelist industri — dulu string apa pun diteruskan (200)."""
        response = self._get(industry="garmen-klien-a")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "industry tidak dikenal")
