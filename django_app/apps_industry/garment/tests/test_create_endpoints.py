"""Test endpoint CREATE (FASE 3.4, D1): ``POST .../work-orders/`` & ``.../bundles/``.

Menutup celah: sebelumnya tidak ada jalur HTTP untuk membuat WorkOrder/Bundle
(``BundleEngine.create_bundles`` tak punya pemanggil). Yang diuji:

* ``POST`` butuh auth (``IsAuthenticated``) — anonim **403**;
* ``GET`` pada path yang sama tetap **list** kontrak §3 (anonim **200**) — tidak
  ada regresi pada bootstrap simulator;
* WorkOrder: 201 + ``state="DRAFT"`` + ``qty_planned = order_line.qty``; 404
  order line tak ada; 400 untuk body invalid / qty <= 0;
* Bundle: 201 + bundle dibuat lewat ``BundleEngine``; 404 WO tak ada; 400 untuk
  WO bukan DRAFT, duplikat (idempoten), dan ``size_matrix``/``bundle_size`` invalid.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.models import Bundle, WorkOrder
from apps_industry.garment.tests.factories import make_order_line, make_work_order

WO_URL = "/api/v1/garmen/work-orders/"
BUNDLE_URL = "/api/v1/garmen/bundles/"


class CreateEndpointAuthTests(TestCase):
    """``POST`` terproteksi; ``GET`` list tetap publik (perilaku lama)."""

    def setUp(self):
        self.client = APIClient()

    def test_post_work_order_anonim_403(self):
        response = self.client.post(WO_URL, {"order_line_id": 1}, format="json")

        self.assertEqual(response.status_code, 403)

    def test_post_bundle_anonim_403(self):
        response = self.client.post(BUNDLE_URL, {"work_order_id": 1}, format="json")

        self.assertEqual(response.status_code, 403)

    def test_get_list_tetap_anonim_200(self):
        self.assertEqual(self.client.get(BUNDLE_URL).status_code, 200)
        self.assertEqual(self.client.get(WO_URL).status_code, 200)

    def test_industri_tidak_dikenal_404(self):
        response = self.client.get("/api/v1/ngawur/bundles/")

        self.assertEqual(response.status_code, 404)


class CreateWorkOrderTests(TestCase):
    """``POST /api/v1/garmen/work-orders/``."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="sim-wo", password="x")
        cls.order_line = make_order_line(qty=20)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _post(self, payload):
        return self.client.post(WO_URL, payload, format="json")

    def test_create_work_order(self):
        response = self._post({"order_line_id": self.order_line.pk})

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["order_line_id"], self.order_line.pk)
        self.assertEqual(body["state"], "DRAFT")
        self.assertEqual(body["qty_planned"], 20)
        work_order = WorkOrder.objects.get(pk=body["id"])
        self.assertEqual(work_order.order_line_id, self.order_line.pk)
        self.assertEqual(work_order.qty_planned, 20)
        self.assertEqual(work_order.state, "DRAFT")
        self.assertTrue(work_order.code.startswith("WO-"))

    def test_create_work_order_invalid_404(self):
        response = self._post({"order_line_id": 999999})

        self.assertEqual(response.status_code, 404)

    def test_create_work_order_body_invalid_400(self):
        self.assertEqual(self._post({}).status_code, 400)
        self.assertEqual(self._post({"order_line_id": "abc"}).status_code, 400)

    def test_create_work_order_qty_nol_400(self):
        kosong = make_order_line(qty=0)

        self.assertEqual(self._post({"order_line_id": kosong.pk}).status_code, 400)

    def test_kode_wo_unik_saat_create_dua_kali(self):
        pertama = self._post({"order_line_id": self.order_line.pk})
        kedua = self._post({"order_line_id": self.order_line.pk})

        self.assertEqual(pertama.status_code, 201)
        self.assertEqual(kedua.status_code, 201)
        self.assertNotEqual(pertama.json()["code"], kedua.json()["code"])
        self.assertEqual(
            WorkOrder.objects.filter(order_line=self.order_line).count(), 2
        )


class CreateBundleTests(TestCase):
    """``POST /api/v1/garmen/bundles/`` (delegasi ke ``BundleEngine``)."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="sim-bnd", password="x"
        )
        cls.order_line = make_order_line(qty=20)
        cls.work_order = make_work_order(order_line=cls.order_line)  # DRAFT

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _post(self, payload):
        return self.client.post(BUNDLE_URL, payload, format="json")

    def _payload(self, **overrides):
        data = {
            "work_order_id": self.work_order.pk,
            "size_matrix": {"L": 7, "M": 3},
            "bundle_size": 5,
        }
        data.update(overrides)
        return data

    def test_create_bundle(self):
        # L=7 -> 5 + 2 ; M=3 -> 3  => 3 bundle
        response = self._post(self._payload())

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["created"], 3)
        self.assertEqual(body["work_order_id"], self.work_order.pk)
        self.assertEqual(len(body["bundles"]), 3)
        self.assertEqual(
            Bundle.objects.filter(work_order=self.work_order).count(), 3
        )
        self.assertEqual(
            sorted(b["code"] for b in body["bundles"]),
            sorted(
                [
                    f"{self.order_line.pk}-L-001",
                    f"{self.order_line.pk}-L-002",
                    f"{self.order_line.pk}-M-001",
                ]
            ),
        )
        self.assertEqual(
            sorted(b["qty"] for b in body["bundles"]), [2, 3, 5]
        )

    def test_create_bundle_duplicate_400(self):
        pertama = self._post(self._payload())
        kedua = self._post(self._payload())

        self.assertEqual(pertama.status_code, 201)
        self.assertEqual(kedua.status_code, 400)
        self.assertIn("sudah punya bundle", kedua.json()["detail"])
        self.assertEqual(
            Bundle.objects.filter(work_order=self.work_order).count(), 3
        )

    def test_create_bundle_work_order_tidak_ada_404(self):
        response = self._post(self._payload(work_order_id=999999))

        self.assertEqual(response.status_code, 404)

    def test_create_bundle_work_order_bukan_draft_400(self):
        bukan_draft = make_work_order(
            order_line=make_order_line(qty=5), state="IN_PROGRESS"
        )

        response = self._post(self._payload(work_order_id=bukan_draft.pk))

        self.assertEqual(response.status_code, 400)
        self.assertIn("DRAFT", response.json()["detail"])

    def test_create_bundle_size_matrix_invalid_400(self):
        self.assertEqual(self._post(self._payload(size_matrix={})).status_code, 400)
        self.assertEqual(
            self._post(self._payload(size_matrix="bukan-objek")).status_code, 400
        )

    def test_create_bundle_size_invalid_400(self):
        response = self._post(self._payload(bundle_size=0))

        self.assertEqual(response.status_code, 400)

    def test_create_bundle_body_invalid_400(self):
        self.assertEqual(self._post({}).status_code, 400)
