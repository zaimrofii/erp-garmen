"""Test endpoint settings routing (F3A.2 / B22).

``GET|POST /api/v1/settings/routing/`` — list ``ProcessRouting`` + step, dan
buat routing baru (``ProcessRouting`` + ``RoutingStep``). ``IsAuthenticated``
untuk GET & POST → anonim 403.

Jalankan (SERIAL):

    docker compose exec django python -m pytest tests/integration/test_settings_routing.py -q
"""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.models import ProcessRouting, RoutingStep
from core.auth.models import User

URL = "/api/v1/settings/routing/"

TOP_KEYS = {"rows", "total_count", "has_more", "next_cursor"}
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


class SettingsRoutingAuthTests(TestCase):
    def test_anonim_get_403(self):
        self.assertEqual(APIClient().get(URL).status_code, 403)

    def test_anonim_post_403(self):
        response = APIClient().post(URL, {"name": "X", "steps": []}, format="json")

        self.assertEqual(response.status_code, 403)


class SettingsRoutingGetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="set-rt-get", password="x")

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    @staticmethod
    def _seed_routing(code="RT-1", name="Routing 1"):
        routing = ProcessRouting.objects.create(code=code, name=name)
        step1 = RoutingStep.objects.create(
            routing=routing, code="STEP-1", label="CUTTING", order=1, is_initial=True
        )
        step2 = RoutingStep.objects.create(
            routing=routing, code="STEP-2", label="SEWING", order=2, is_terminal=True
        )
        step1.allowed_next_steps.add(step2)
        return routing

    def test_shape_listpage_kosong(self):
        body = self.api.get(URL).json()

        self.assertEqual(set(body), TOP_KEYS)
        self.assertEqual(body["rows"], [])
        self.assertEqual(body["total_count"], 0)
        self.assertFalse(body["has_more"])
        self.assertIsNone(body["next_cursor"])

    def test_list_routing_dengan_steps(self):
        self._seed_routing()

        body = self.api.get(URL).json()

        row = body["rows"][0]
        self.assertEqual(set(row), ROW_KEYS)
        self.assertEqual(row["code"], "RT-1")
        self.assertEqual(len(row["steps"]), 2)
        self.assertEqual(set(row["steps"][0]), STEP_KEYS)

    def test_depends_on_initial_terminal(self):
        self._seed_routing()

        steps = self.api.get(URL).json()["rows"][0]["steps"]

        self.assertTrue(steps[0]["is_initial"])
        self.assertEqual(steps[0]["depends_on"], [])
        self.assertEqual(steps[1]["depends_on"], [1])
        self.assertEqual(steps[1]["wc_type"], "SEWING")
        self.assertTrue(steps[1]["is_terminal"])
        self.assertIsNone(steps[1]["rework_target_step"])

    def test_pagination_limit_dan_cursor(self):
        self._seed_routing(code="RT-1", name="Routing 1")
        self._seed_routing(code="RT-2", name="Routing 2")

        page1 = self.api.get(URL, {"limit": 1}).json()

        self.assertEqual(page1["total_count"], 2)
        self.assertTrue(page1["has_more"])
        self.assertEqual(page1["next_cursor"], 1)

        page2 = self.api.get(URL, {"limit": 1, "cursor": page1["next_cursor"]}).json()

        self.assertEqual(len(page2["rows"]), 1)
        self.assertFalse(page2["has_more"])
        self.assertIsNone(page2["next_cursor"])

    def test_limit_invalid_400(self):
        self.assertEqual(self.api.get(URL, {"limit": "abc"}).status_code, 400)
        self.assertEqual(self.api.get(URL, {"limit": 9999}).status_code, 400)


class SettingsRoutingPostTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="set-rt-post", password="x")

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    @staticmethod
    def _payload(name="Routing Baru"):
        return {
            "name": name,
            "description": "dari test",
            "steps": [
                {"step_no": 1, "wc_type": "CUTTING", "depends_on": []},
                {"step_no": 2, "wc_type": "SEWING", "depends_on": [1]},
                {
                    "step_no": 3,
                    "wc_type": "QC",
                    "depends_on": [2],
                    "rework_target_step": 2,
                },
            ],
        }

    def test_post_sukses_201_dan_persist(self):
        response = self.api.post(URL, self._payload(), format="json")

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(set(body), ROW_KEYS)
        self.assertEqual(body["name"], "Routing Baru")
        self.assertEqual(len(body["steps"]), 3)
        # code diturunkan dari name (slug uppercase)
        self.assertEqual(body["code"], "ROUTING-BARU")

        routing = ProcessRouting.objects.get(pk=body["id"])
        self.assertEqual(routing.steps.count(), 3)
        step3 = routing.steps.get(order=3)
        self.assertEqual(step3.label, "QC")
        self.assertEqual(step3.rework_target_step.order, 2)
        self.assertTrue(routing.steps.get(order=1).is_initial)
        self.assertTrue(step3.is_terminal)

    def test_post_mengisi_edge_depends_on(self):
        body = self.api.post(URL, self._payload(), format="json").json()

        steps = {step["step_no"]: step for step in body["steps"]}
        self.assertEqual(steps[2]["depends_on"], [1])
        self.assertEqual(steps[3]["depends_on"], [2])

    def test_post_code_unik_bila_nama_sama(self):
        first = self.api.post(URL, self._payload(name="Sama"), format="json").json()
        second = self.api.post(URL, self._payload(name="Sama"), format="json").json()

        self.assertEqual(first["code"], "SAMA")
        self.assertEqual(second["code"], "SAMA-2")

    def test_post_product_id_non_integer_400(self):
        payload = self._payload()
        payload["product_id"] = "bukan-angka"

        response = self.api.post(URL, payload, format="json")

        self.assertEqual(response.status_code, 400)


class SettingsRoutingValidationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="set-rt-val", password="x")

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def test_name_kosong_400(self):
        response = self.api.post(
            URL,
            {"name": "  ", "steps": [{"step_no": 1, "wc_type": "X"}]},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_steps_kosong_400(self):
        response = self.api.post(URL, {"name": "X", "steps": []}, format="json")

        self.assertEqual(response.status_code, 400)

    def test_step_no_duplikat_400(self):
        payload = {
            "name": "Dup",
            "steps": [
                {"step_no": 1, "wc_type": "A", "depends_on": []},
                {"step_no": 1, "wc_type": "B", "depends_on": []},
            ],
        }

        self.assertEqual(self.api.post(URL, payload, format="json").status_code, 400)

    def test_depends_on_tak_dikenal_400(self):
        payload = {
            "name": "Bad Dep",
            "steps": [{"step_no": 1, "wc_type": "A", "depends_on": [9]}],
        }

        self.assertEqual(self.api.post(URL, payload, format="json").status_code, 400)

    def test_rework_target_lebih_besar_dari_step_no_400(self):
        payload = {
            "name": "Bad Rework",
            "steps": [
                {"step_no": 1, "wc_type": "A", "depends_on": []},
                {
                    "step_no": 2,
                    "wc_type": "B",
                    "depends_on": [1],
                    "rework_target_step": 3,
                },
            ],
        }

        self.assertEqual(self.api.post(URL, payload, format="json").status_code, 400)

