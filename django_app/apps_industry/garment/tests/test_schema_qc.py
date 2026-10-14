"""Test resource `qc` (schema endpoint + perilaku aksi)."""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.tests.auth import authenticate
from apps_industry.garment.tests.factories import (
    make_bundle,
    make_scrap_accumulator,
    make_work_center,
)


class QCSchemaTests(TestCase):
    """Resource `qc` = catatan ScrapAccumulator (bukan tabel baru)."""

    @classmethod
    def setUpTestData(cls):
        cls.work_center = make_work_center(code="QC-1")
        cls.bundle = make_bundle(code="BND-001")
        cls.scrap = make_scrap_accumulator(
            work_center=cls.work_center,
            bundle=cls.bundle,
            qty=3,
            rework_qty=1,
            end_loss_qty=2,
            reason="kain sobek",
        )

    def setUp(self):
        self.client = APIClient()
        # FASE 4.1: ActionView kini `IsAuthenticated`.
        authenticate(self.client)

    def test_schema_qc_200_sesuai_kontrak(self):
        response = self.client.get(f"/api/v1/garmen/qc/{self.scrap.pk}/schema/")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["resource"]["name"], "qc")
        self.assertEqual(body["resource"]["label"], "Catatan QC")
        self.assertEqual(body["resource"]["id"], str(self.scrap.pk))
        self.assertEqual(body["schema_version"], "1.0")
        self.assertEqual(body["view_type"], "form")
        self.assertEqual(body["title"], f"QC #{self.scrap.pk}")
        # Fase B.1: `device_hint` WAJIB salah satu enum frontend (`DEVICE_HINTS`).
        self.assertEqual(body["device_hint"], "KIOSK_TABLET")
        self.assertEqual(len(body["version"]), 64)
        self.assertEqual(
            body["state_machine"],
            {
                "current_state": "RECORDED",
                "possible_states": [
                    {"id": "RECORDED", "label": "Recorded", "kind": "current"}
                ],
                "allowed_actions": [],
            },
        )
        # Fase B.1.3: layout dibungkus `{sections: [...]}`.
        section = body["layout"]["sections"][0]
        self.assertEqual(section["id"], "info-qc")
        self.assertEqual(section["label"], "Info QC")
        self.assertEqual(
            [field["name"] for field in section["fields"]],
            ["work_center", "qty", "rework_qty", "end_loss_qty", "reason"],
        )
        self.assertEqual(section["fields"][0]["value"], "QC-1")
        self.assertEqual(section["fields"][1]["value"], 3)
        self.assertEqual(
            body["chatter"],
            {"preview": [], "total_count": 0, "has_more": False, "next_cursor": None},
        )

    def test_qc_bisa_di_list_dan_detail(self):
        daftar = self.client.get("/api/v1/garmen/qc/")
        detail = self.client.get(f"/api/v1/garmen/qc/{self.scrap.pk}/")

        self.assertEqual(daftar.status_code, 200)
        self.assertEqual(daftar.json()["rows"][0]["work_center_code"], "QC-1")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["reason"], "kain sobek")
        self.assertEqual(len(detail.json()["version"]), 64)

    def test_qc_belum_mendukung_aksi(self):
        response = self.client.post(
            f"/api/v1/garmen/qc/{self.scrap.pk}/RECORD/", {}, format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("tidak mendukung aksi", response.json()["detail"])
