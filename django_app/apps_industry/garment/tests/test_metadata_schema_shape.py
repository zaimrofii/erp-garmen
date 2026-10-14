"""Test bentuk metadata Fase B.1 — mirror `ResourceMetadataSchema` Zod frontend.

Backend tidak menjalankan Zod (frontend tidak diubah), jadi aturan schema
frontend disalin di sini sebagai assertion eksplisit lalu dijalankan untuk
`bundles`, `work-orders`, dan `qc`.

Schema acuan (`frontend_app/src/lib/schemas/`):

  * ``metadata.schema.ts`` — ResourceMetadata, ResourceRef, VIEW_TYPES, DEVICE_HINTS;
  * ``layout.schema.ts`` — LayoutMeta {sections}, LayoutSection, LAYOUT_FIELD_TYPES;
  * ``state-machine.schema.ts`` — StateMachineMeta, StateEntry {id,label,kind}, STATE_KINDS;
  * ``action.schema.ts`` — AllowedAction {id,label,mode?,endpoint?}, ACTION_MODES;
  * ``chatter.schema.ts`` — ChatterPage {preview,total_count,has_more,next_cursor}.
"""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.api.schema.builder import FIELD_TYPES, STATE_KINDS
from apps_industry.garment.models import Bundle, BundleEvent
from apps_industry.garment.tests.auth import authenticate
from apps_industry.garment.tests.factories import (
    make_bundle,
    make_scrap_accumulator,
    make_work_center,
    make_work_order,
)

# --- salinan enum/literal kontrak frontend --------------------------------- #
SCHEMA_VERSION = "1.0"
VIEW_TYPES = {"list", "form", "kanban", "telemetry"}
DEVICE_HINTS = {"OPERATOR_HP", "KIOSK_TABLET", "SCANNER_USB", "DESKTOP"}
ACTION_MODES = {"optimistic", "pessimistic"}
CHATTER_PREVIEW_LIMIT = 5


class MetadataShapeContractTests(TestCase):
    """`build()` harus lolos `ResourceMetadataSchema` — dicek struktural."""

    @classmethod
    def setUpTestData(cls):
        cls.work_center = make_work_center(code="SEWING-1")
        cls.work_order = make_work_order(code="WO-001")
        cls.bundle = make_bundle(
            work_order=cls.work_order,
            code="BND-001",
            size="L",
            qty=5,
            state="SEWING",
            current_work_center=cls.work_center,
        )
        cls.scrap = make_scrap_accumulator(
            work_center=cls.work_center, bundle=cls.bundle, qty=3, reason="sobek"
        )
        for index in range(3):
            BundleEvent.objects.create(
                bundle=cls.bundle, event_type=f"EVENT_{index}", text=f"e{index}"
            )

    def setUp(self):
        self.client = APIClient()
        # FASE 4.1: ActionView kini `IsAuthenticated`.
        authenticate(self.client)

    # --------------------------------------------------------------- assertion
    def assert_matches_frontend_contract(self, body: dict) -> None:
        """Salinan aturan `ResourceMetadataSchema` + sub-schema-nya."""
        # --- metadata.schema.ts -------------------------------------------------
        self.assertEqual(body["schema_version"], SCHEMA_VERSION)
        self.assertIn(body["view_type"], VIEW_TYPES)
        self.assertIsInstance(body["resource"], dict)
        self.assertEqual(set(body["resource"]), {"name", "label", "id", "version"})
        for key in ("name", "id", "version"):
            self.assertIsInstance(body["resource"][key], str)
            self.assertTrue(body["resource"][key])  # Zod `min(1)`
        self.assertIsInstance(body["resource"]["label"], str)
        self.assertIn(body["device_hint"], DEVICE_HINTS)

        # --- state-machine.schema.ts -------------------------------------------
        machine = body["state_machine"]
        self.assertIsInstance(machine["current_state"], str)
        self.assertTrue(machine["current_state"])
        for state in machine["possible_states"]:
            self.assertEqual(set(state), {"id", "label", "kind"})
            self.assertTrue(state["id"])
            self.assertIsInstance(state["label"], str)
            self.assertIn(state["kind"], STATE_KINDS)
        for action in machine["allowed_actions"]:
            self.assertTrue(action["id"])
            self.assertIsInstance(action["label"], str)
            self.assertIn(action["mode"], ACTION_MODES)
            self.assertTrue(action["endpoint"].startswith("/"))

        # --- layout.schema.ts ---------------------------------------------------
        layout = body["layout"]
        self.assertEqual(set(layout), {"sections"})
        self.assertIsInstance(layout["sections"], list)
        for section in layout["sections"]:
            self.assertTrue(section["id"])
            self.assertIsInstance(section["label"], str)
            for field in section["fields"]:
                self.assertTrue(field["name"])
                self.assertIn(field["type"], FIELD_TYPES)  # enum kontrak, bukan "text"
                self.assertIsInstance(field["label"], str)
                self.assertIn("value", field)
                self.assertIsInstance(field["read_only"], bool)
                if "widget" in field:
                    self.assertIsInstance(field["widget"], str)

        # --- chatter.schema.ts --------------------------------------------------
        chatter = body["chatter"]
        self.assertEqual(
            set(chatter), {"preview", "total_count", "has_more", "next_cursor"}
        )
        self.assertLessEqual(len(chatter["preview"]), CHATTER_PREVIEW_LIMIT)
        self.assertIsInstance(chatter["total_count"], int)
        self.assertIsInstance(chatter["has_more"], bool)
        self.assertTrue(
            chatter["next_cursor"] is None or isinstance(chatter["next_cursor"], str)
        )
        for event in chatter["preview"]:
            self.assertTrue(event["id"])
            self.assertIsInstance(event["actor"], dict)
            self.assertTrue(event["actor"]["id"])
            self.assertIsInstance(event["actor"]["name"], str)
            self.assertIsInstance(event["type"], str)
            self.assertIsInstance(event["summary"], str)
            self.assertIsInstance(event["payload"], dict)
            self.assertIsInstance(event["created_at"], str)

    # --------------------------------------------------------------- jalur HTTP
    def test_metadata_bundles_id_eksplisit_lolos_kontrak(self):
        response = self.client.get("/api/v1/metadata/bundles/", {"id": self.bundle.pk})

        self.assertEqual(response.status_code, 200)
        self.assert_matches_frontend_contract(response.json())

    def test_metadata_work_orders_lolos_kontrak(self):
        response = self.client.get("/api/v1/metadata/work-orders/")

        self.assertEqual(response.status_code, 200)
        self.assert_matches_frontend_contract(response.json())

    def test_metadata_qc_lolos_kontrak(self):
        response = self.client.get("/api/v1/metadata/qc/")

        self.assertEqual(response.status_code, 200)
        self.assert_matches_frontend_contract(response.json())

    def test_schema_instance_lolos_kontrak(self):
        response = self.client.get(f"/api/v1/garmen/bundles/{self.bundle.pk}/schema/")

        self.assertEqual(response.status_code, 200)
        self.assert_matches_frontend_contract(response.json())

    # ------------------------------------------------------------------- B.1.1
    def test_resource_id_dan_version_dari_instance(self):
        body = self.client.get(
            "/api/v1/metadata/bundles/", {"id": self.bundle.pk}
        ).json()

        self.assertEqual(body["resource"]["id"], str(self.bundle.pk))
        self.assertEqual(
            body["resource"]["version"], Bundle.objects.get(pk=self.bundle.pk).version
        )
        # Versi identik dengan yang dipakai conflict detection (§2.3).
        self.assertEqual(body["resource"]["version"], body["version"])

    def test_resource_label_tiap_resource(self):
        for resource, label in (
            ("bundles", "Bundle"),
            ("work-orders", "Work Order"),
            ("qc", "Catatan QC"),
        ):
            with self.subTest(resource=resource):
                body = self.client.get(f"/api/v1/metadata/{resource}/").json()
                self.assertEqual(body["resource"]["label"], label)

    # ------------------------------------------------------------------- B.1.2
    def test_possible_states_kind_dari_posisi(self):
        states = self.client.get("/api/v1/metadata/bundles/").json()["state_machine"][
            "possible_states"
        ]

        self.assertEqual(
            [(state["id"], state["kind"]) for state in states],
            [
                ("DRAFT", "past"),
                ("CUTTING", "past"),
                ("SEWING", "current"),
                ("QC", "future"),
                ("DONE", "future"),
            ],
        )

    def test_state_di_luar_mesin_semua_future(self):
        bundle_nyasar = make_bundle(code="BND-NYASAR", state="NGAWUR")

        states = self.client.get(
            "/api/v1/metadata/bundles/", {"id": bundle_nyasar.pk}
        ).json()["state_machine"]["possible_states"]

        self.assertTrue(states)
        self.assertEqual({state["kind"] for state in states}, {"future"})

    # ------------------------------------------------------------------- B.1.3
    def test_layout_section_id_stabil_antar_build(self):
        pertama = self.client.get("/api/v1/metadata/bundles/").json()["layout"]
        kedua = self.client.get("/api/v1/metadata/bundles/").json()["layout"]

        self.assertEqual(pertama, kedua)
        # id = slug dari label (deterministik, tidak berubah antar build).
        self.assertEqual(pertama["sections"][0]["id"], "info-bundle")

    # ------------------------------------------------------------------- B.1.4
    def test_tipe_field_enum_dan_widget_terpisah(self):
        fields = self.client.get("/api/v1/metadata/bundles/").json()["layout"][
            "sections"
        ][0]["fields"]

        self.assertTrue(all(field["type"] in FIELD_TYPES for field in fields))
        qr = next(field for field in fields if field["name"] == "qr_scan")
        self.assertEqual(qr["type"], "string")
        # Nama widget = yang terdaftar di `modules/garmen/register.ts`.
        self.assertEqual(qr["widget"], "garmen-qr-bundle")
        self.assertEqual(qr["value"], "BND-001")

    def test_field_tanpa_widget_tidak_punya_key_widget(self):
        fields = self.client.get("/api/v1/metadata/qc/").json()["layout"]["sections"][
            0
        ]["fields"]

        self.assertTrue(all("widget" not in field for field in fields))

    # ------------------------------------------------------------------- B.1.5
    def test_allowed_actions_endpoint_pakai_action_id_asli(self):
        actions = self.client.get("/api/v1/metadata/bundles/").json()["state_machine"][
            "allowed_actions"
        ]

        self.assertTrue(actions)
        for action in actions:
            # Path RELATIF baseUrl frontend: `VITE_API_BASE_URL` sudah `/api/v1`,
            # jadi endpoint TIDAK boleh ikut membawa prefix itu (jadi dobel).
            self.assertFalse(action["endpoint"].startswith("/api/v1"))
            self.assertTrue(action["endpoint"].endswith(f"/{action['id']}/"))
            self.assertEqual(
                action["endpoint"],
                f"/garmen/bundles/{self.bundle.pk}/{action['id']}/",
            )

    def test_action_endpoint_dari_metadata_benar_benar_dapat_dipanggil(self):
        """Bukti gap #3/#4/#5 tertutup: path dari metadata → 200, bukan 404."""
        action = self.client.get("/api/v1/metadata/work-orders/").json()[
            "state_machine"
        ]["allowed_actions"][0]

        response = self.client.post(f"/api/v1{action['endpoint']}", {}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["action"], action["id"])

    # -------------------------------------------------------------- batas B.1/B.2
    def test_chatter_preview_metadata_bentuk_kontrak(self):
        preview = self.client.get("/api/v1/metadata/bundles/").json()["chatter"][
            "preview"
        ]

        self.assertTrue(preview)
        self.assertEqual(
            set(preview[0]),
            {"id", "actor", "type", "summary", "payload", "created_at"},
        )

    def test_endpoint_chatter_bentuk_kontrak_sama_dengan_metadata(self):
        """Fase B.2: endpoint chatter & blok `chatter` metadata memakai bentuk identik."""
        page = self.client.get(f"/api/v1/chatter/bundles/{self.bundle.pk}").json()

        self.assertEqual(
            set(page), {"preview", "total_count", "has_more", "next_cursor"}
        )
        self.assertEqual(
            set(page["preview"][0]),
            {"id", "actor", "type", "summary", "payload", "created_at"},
        )

        metadata_preview = self.client.get(
            "/api/v1/metadata/bundles/", {"id": self.bundle.pk}
        ).json()["chatter"]["preview"]
        self.assertEqual(
            [event["id"] for event in page["preview"]],
            [event["id"] for event in metadata_preview],
        )