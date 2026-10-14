"""Fase C.5 — `Bundle.version` (optimistic lock) regenerate.

Kontrak: `version` = SHA-256 dari `code|state|qty_done|wc_id|timestamp`, dihitung
di `save()`; regenerate HANYA kalau state kritis berubah (`state`, `qty_done`,
`current_work_center`). Frontend memakai token ini sebagai `X-Base-Version`.
"""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from apps_industry.garment.models import Bundle
from apps_industry.garment.services.wc_queue import WCQueue
from apps_industry.garment.tests.auth import authenticate
from apps_industry.garment.tests.factories import make_bundle, make_work_center

HEX = set("0123456789abcdef")


class BundleVersionRegenerateTests(TestCase):
    """Model-level: kapan `version` berubah / tidak berubah."""

    def test_bundle_baru_punya_version_sha256(self):
        bundle = make_bundle(code="BND-V-001")

        self.assertEqual(len(bundle.version), 64)
        self.assertTrue(set(bundle.version) <= HEX)
        self.assertEqual(Bundle.objects.get(pk=bundle.pk).version, bundle.version)

    def test_version_stabil_tanpa_perubahan_kritis(self):
        bundle = make_bundle(code="BND-V-002")
        versi = bundle.version

        bundle.save()  # tanpa perubahan apa pun

        self.assertEqual(Bundle.objects.get(pk=bundle.pk).version, versi)

    def test_state_berubah_version_wajib_berubah(self):
        bundle = make_bundle(code="BND-V-003", state="DRAFT")
        versi = bundle.version

        bundle.state = "CUTTING"
        bundle.save()

        baru = Bundle.objects.get(pk=bundle.pk).version
        self.assertNotEqual(baru, versi)
        self.assertEqual(baru, bundle.version)

    def test_qty_done_berubah_version_berubah(self):
        bundle = make_bundle(code="BND-V-004", qty=10)
        versi = bundle.version

        bundle.qty_done = 3
        bundle.save()

        self.assertNotEqual(Bundle.objects.get(pk=bundle.pk).version, versi)

    def test_work_center_berubah_version_berubah(self):
        bundle = make_bundle(code="BND-V-005")
        versi = bundle.version

        bundle.current_work_center = make_work_center(code="SEWING-V5")
        bundle.save()

        self.assertNotEqual(Bundle.objects.get(pk=bundle.pk).version, versi)

    def test_field_non_kritis_tidak_mengubah_version(self):
        """`qty`/`size` bukan state kritis → token tetap valid."""
        bundle = make_bundle(code="BND-V-006", qty=5, size="L")
        versi = bundle.version

        bundle.qty = 9
        bundle.size = "XL"
        bundle.save()

        self.assertEqual(Bundle.objects.get(pk=bundle.pk).version, versi)

    def test_dua_perubahan_state_berturut_turut_version_selalu_beda(self):
        bundle = make_bundle(code="BND-V-007")
        versi_1 = bundle.version

        bundle.state = "CUTTING"
        bundle.save()
        versi_2 = bundle.version

        bundle.state = "SEWING"
        bundle.save()
        versi_3 = bundle.version

        self.assertEqual(len({versi_1, versi_2, versi_3}), 3)

    def test_save_update_fields_yang_memuat_field_kritis_ikut_menyimpan_version(self):
        """Hardening Fase C: kalau tidak, baris DB bisa basi walau state berubah."""
        bundle = make_bundle(code="BND-V-008")
        versi = bundle.version

        bundle.state = "CUTTING"
        bundle.save(update_fields=["state", "updated_at"])

        self.assertNotEqual(Bundle.objects.get(pk=bundle.pk).version, versi)

    def test_save_update_fields_non_kritis_tidak_menyentuh_version(self):
        bundle = make_bundle(code="BND-V-009")
        versi = bundle.version

        bundle.state = "CUTTING"  # sengaja TIDAK ikut disimpan
        bundle.qty = 99
        bundle.save(update_fields=["qty"])

        di_db = Bundle.objects.get(pk=bundle.pk)
        self.assertEqual(di_db.version, versi)
        self.assertEqual(di_db.state, "DRAFT")  # konsisten: state & version sama-sama lama

    def test_wc_queue_enqueue_dequeue_mengubah_version(self):
        """Regresi: enqueue/dequeue menyentuh `current_work_center` (state kritis)."""
        queue = WCQueue()
        work_center = make_work_center(code="WC-V-010")
        bundle = make_bundle(code="BND-V-010")
        versi_awal = bundle.version

        queue.enqueue(bundle, work_center)
        versi_enqueue = Bundle.objects.get(pk=bundle.pk).version
        self.assertNotEqual(versi_enqueue, versi_awal)

        queue.dequeue(bundle)
        versi_dequeue = Bundle.objects.get(pk=bundle.pk).version
        self.assertNotEqual(versi_dequeue, versi_enqueue)


class BundleVersionEndpointTests(TestCase):
    """Version di metadata == version di DB == version yang dipakai conflict check."""

    @classmethod
    def setUpTestData(cls):
        cls.bundle = make_bundle(code="BND-V-020")

    def setUp(self):
        self.client = APIClient()
        # FASE 4.1: ActionView kini `IsAuthenticated`.
        authenticate(self.client)

    def _metadata(self):
        return self.client.get(
            "/api/v1/metadata/bundles/", {"id": self.bundle.pk}
        ).json()

    def test_metadata_version_sama_dengan_db(self):
        body = self._metadata()

        self.assertEqual(body["version"], Bundle.objects.get(pk=self.bundle.pk).version)
        self.assertEqual(body["resource"]["version"], body["version"])

    def test_aksi_mengubah_version_dan_cocok_dengan_db(self):
        versi_lama = self._metadata()["version"]

        response = self.client.post(
            f"/api/v1/garmen/bundles/{self.bundle.pk}/BUNDLE_START/", {}, format="json"
        )

        versi_db = Bundle.objects.get(pk=self.bundle.pk).version
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(versi_db, versi_lama)
        self.assertEqual(response.json()["version"], versi_db)

    def test_base_version_dari_metadata_langsung_diterima(self):
        """Alur frontend: `resource.version` dari metadata → `X-Base-Version`."""
        versi = self._metadata()["version"]

        response = self.client.post(
            f"/api/v1/garmen/bundles/{self.bundle.pk}/BUNDLE_START/",
            {},
            format="json",
            headers={"X-Base-Version": versi},
        )

        self.assertEqual(response.status_code, 200)