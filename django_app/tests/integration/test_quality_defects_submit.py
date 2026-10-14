"""Test POST defect dari form QC (F3A.3 / B7b) — ``POST /api/v1/quality/defects/``.

* ``action="scrap"``  → delegasi ke action endpoint ``BUNDLE_SCRAP`` (reuse
  `ActionExecutor`, **tanpa** duplikasi logika scrap);
* ``action="rework"`` → ``BundleEvent(BUNDLE_QC_REWORK)`` + 1 iterasi siklus
  ``QC_REWORK`` via `ReworkLoopHandler`.

Jalankan (SERIAL):

    docker compose exec django python -m pytest tests/integration/test_quality_defects_submit.py -q
"""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.models import Bundle, BundleEvent, WorkCenter
from apps_industry.garment.tests.factories import make_bundle, make_work_order
from core.auth.models import User
from core.cycle_handler.models import CycleInstance

URL = "/api/v1/quality/defects/"


class QualityDefectSubmitAuthTests(TestCase):
    def test_anonim_post_403(self):
        response = APIClient().post(URL, {"bundle_id": 1}, format="json")

        self.assertEqual(response.status_code, 403)


class QualityDefectSubmitTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="q-defect", password="x")

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)
        self.work_center = WorkCenter.objects.create(code="SEW-01", name="Sewing 1")
        self.bundle = make_bundle(
            work_order=make_work_order(),
            code="B-DEF",
            qty=10,
            state="SEWING",
            current_work_center=self.work_center,
        )

    def _payload(self, **overrides):
        payload = {
            "bundle_id": self.bundle.pk,
            "defect_type": "jahitan",
            "qty": 3,
            "reason": "meleset",
            "action": "rework",
        }
        payload.update(overrides)
        return payload

    def test_submit_scrap_200_reuse_action_endpoint(self):
        response = self.api.post(URL, self._payload(action="scrap"), format="json")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertIsNotNone(body["bundle_event_id"])
        self.assertNotIn("cycle_instance_id", body)

        # Delegasi ke BUNDLE_SCRAP -> state bundle jadi DONE.
        self.bundle.refresh_from_db()
        self.assertEqual(self.bundle.state, "DONE")

        event = BundleEvent.objects.get(pk=body["bundle_event_id"])
        self.assertEqual(event.event_type, "BUNDLE_SCRAP")
        self.assertEqual(event.payload.get("scrap_qty"), 3)
        self.assertEqual(event.payload.get("defect_type"), "jahitan")

        # Terlihat di GET /quality/defects/ (reuse endpoint existing).
        rows = self.api.get(URL).json()["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["action"], "scrap")
        self.assertEqual(rows[0]["qty"], 3)

    def test_submit_rework_200_dan_cycle(self):
        response = self.api.post(URL, self._payload(), format="json")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertIsNotNone(body["cycle_instance_id"])

        event = BundleEvent.objects.get(pk=body["bundle_event_id"])
        self.assertEqual(event.event_type, "BUNDLE_QC_REWORK")
        self.assertEqual(event.payload.get("action"), "rework")
        self.assertEqual(event.payload.get("scrap_qty"), 3)

        instance = CycleInstance.objects.get(pk=body["cycle_instance_id"])
        self.assertEqual(instance.definition.code, "QC_REWORK")
        self.assertEqual(instance.ref_type, "bundle")
        self.assertEqual(instance.ref_id, str(self.bundle.pk))
        self.assertEqual(instance.iteration_count, 1)
        self.assertEqual(instance.status, CycleInstance.Status.ACTIVE)

        # Bundle.state TIDAK diubah oleh rework (hanya jejak + siklus).
        self.bundle.refresh_from_db()
        self.assertEqual(self.bundle.state, "SEWING")

    def test_bundle_invalid_404(self):
        response = self.api.post(URL, self._payload(bundle_id=999999), format="json")

        self.assertEqual(response.status_code, 404)

    def test_qty_tidak_valid_400(self):
        for qty in (0, -1, "3", 1.5):
            with self.subTest(qty=qty):
                response = self.api.post(URL, self._payload(qty=qty), format="json")

                self.assertEqual(response.status_code, 400)

    def test_action_invalid_400(self):
        response = self.api.post(URL, self._payload(action="cancel"), format="json")

        self.assertEqual(response.status_code, 400)

    def test_defect_type_kosong_400(self):
        response = self.api.post(URL, self._payload(defect_type="   "), format="json")

        self.assertEqual(response.status_code, 400)

    def test_bundle_id_non_integer_400(self):
        response = self.api.post(URL, self._payload(bundle_id="abc"), format="json")

        self.assertEqual(response.status_code, 400)

    def test_scrap_bundle_sudah_done_400(self):
        Bundle.objects.filter(pk=self.bundle.pk).update(state="DONE")
        self.bundle.refresh_from_db()

        response = self.api.post(URL, self._payload(action="scrap"), format="json")

        # Fail-closed: status dari action endpoint diteruskan apa adanya.
        self.assertEqual(response.status_code, 400)
