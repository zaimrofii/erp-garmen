"""Test model inti garmen (Sprint 2.1).

Fokus: `Bundle.version` (recompute strategy), `BundleEvent` (PK UUID),
constraint unik `ScrapAccumulator`, DAG routing (`allowed_next_steps` +
`rework_target_step`), M2M line produksi, dan extension OneToOne device profile.
"""

from __future__ import annotations

import re

from django.db import IntegrityError, transaction
from django.test import TestCase

from apps_industry.garment.models import (
    Bundle,
    BundleEvent,
    GarmentDeviceProfile,
    Order,
    OrderLine,
    ProcessRouting,
    ProductionLine,
    RoutingStep,
    ScrapAccumulator,
    WorkCenter,
    WorkOrder,
)
from core.device_profile.models import DeviceProfile
from master.models import Partner, Product

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class GarmentModelTestCase(TestCase):
    """Data minimum: partner/product (master) -> order -> line -> WO + work center."""

    @classmethod
    def setUpTestData(cls):
        cls.customer = Partner.objects.create(code="CUST-01", name="PT Klien")
        cls.product = Product.objects.create(code="TS-001", name="Kaos Polos")
        cls.order = Order.objects.create(
            code="ORD-0001",
            customer=cls.customer,
            order_type=Order.OrderType.EXPORT,
        )
        cls.line = OrderLine.objects.create(
            order=cls.order,
            product=cls.product,
            tag="FAST_TRACK",
            ticket_code="TKT-0001",
            qty=100,
        )
        cls.work_order = WorkOrder.objects.create(
            code="WO-0001", order_line=cls.line, qty_planned=100
        )
        cls.wc_sewing = WorkCenter.objects.create(code="SEWING-1", name="Sewing 1")
        cls.wc_qc = WorkCenter.objects.create(code="QC-1", name="QC 1")

    def make_bundle(self, code="BND-0001", **kwargs):
        defaults = {"work_order": self.work_order, "size": "L", "qty": 5}
        defaults.update(kwargs)
        return Bundle.objects.create(code=code, **defaults)


class BundleVersionTests(GarmentModelTestCase):
    """`Bundle.version` = SHA-256 state kritis, dihitung di save()."""

    def test_version_dibuat_saat_save_pertama(self):
        bundle = self.make_bundle()

        self.assertTrue(SHA256_RE.match(bundle.version), bundle.version)
        self.assertEqual(len(bundle.version), 64)

    def test_version_berubah_saat_state_berubah(self):
        bundle = self.make_bundle()
        version_awal = bundle.version

        bundle.state = "SEWING"
        bundle.save()

        self.assertNotEqual(bundle.version, version_awal)
        self.assertTrue(SHA256_RE.match(bundle.version))

    def test_version_berubah_saat_qty_done_berubah(self):
        bundle = self.make_bundle()
        version_awal = bundle.version

        bundle.qty_done = 3
        bundle.save()

        self.assertNotEqual(bundle.version, version_awal)

    def test_version_berubah_saat_current_work_center_berubah(self):
        bundle = self.make_bundle()
        version_awal = bundle.version

        bundle.current_work_center = self.wc_sewing
        bundle.save()

        self.assertNotEqual(bundle.version, version_awal)

    def test_version_stabil_saat_field_non_kritis_berubah(self):
        production_line = ProductionLine.objects.create(code="LINE-1", name="Line 1")
        bundle = self.make_bundle()
        version_awal = bundle.version

        bundle.size = "XL"
        bundle.sku_variant = "MERAH"
        bundle.production_line = production_line
        bundle.save()

        # `version` hanya melacak state kritis (state/qty_done/work center).
        self.assertEqual(bundle.version, version_awal)

    def test_version_berubah_untuk_instance_hasil_baca_ulang(self):
        bundle = self.make_bundle()
        segar = Bundle.objects.get(pk=bundle.pk)  # lewat from_db (tracking aktif)

        segar.qty_done = 2
        segar.save()

        self.assertNotEqual(segar.version, bundle.version)

    def test_version_berbeda_antar_bundle(self):
        satu = self.make_bundle(code="BND-0001")
        dua = self.make_bundle(code="BND-0002")

        self.assertNotEqual(satu.version, dua.version)


class BundleEventTests(GarmentModelTestCase):
    """`BundleEvent`: PK UUID (siap dibuat offline di Fase 2) + relasi bundle."""

    def test_id_uuid_unik_untuk_dua_event(self):
        bundle = self.make_bundle()

        event_satu = BundleEvent.objects.create(
            bundle=bundle, event_type="BUNDLE_START", text="mulai"
        )
        event_dua = BundleEvent.objects.create(
            bundle=bundle, event_type="BUNDLE_FINISH", text="selesai"
        )

        self.assertNotEqual(event_satu.pk, event_dua.pk)
        self.assertEqual(event_satu.pk.version, 4)  # uuid4
        self.assertIsNotNone(event_satu.ts)

    def test_related_name_events_dan_payload(self):
        bundle = self.make_bundle()
        BundleEvent.objects.create(bundle=bundle, event_type="SCRAP", payload={"qty": 2})

        self.assertEqual(bundle.events.count(), 1)
        self.assertEqual(bundle.events.first().payload, {"qty": 2})

    def test_event_ikut_terhapus_kalau_bundle_dihapus(self):
        bundle = self.make_bundle()
        BundleEvent.objects.create(bundle=bundle, event_type="BUNDLE_START")

        bundle.delete()

        self.assertEqual(BundleEvent.objects.count(), 0)


class ScrapAccumulatorTests(GarmentModelTestCase):
    """Akumulasi scrap unik per (work_center, bundle)."""

    def test_unik_per_work_center_dan_bundle(self):
        bundle = self.make_bundle()
        ScrapAccumulator.objects.create(work_center=self.wc_sewing, bundle=bundle, qty=1)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ScrapAccumulator.objects.create(
                    work_center=self.wc_sewing, bundle=bundle, qty=2
                )

    def test_work_center_berbeda_boleh_baris_terpisah(self):
        bundle = self.make_bundle()
        ScrapAccumulator.objects.create(work_center=self.wc_sewing, bundle=bundle, qty=1)
        ScrapAccumulator.objects.create(work_center=self.wc_qc, bundle=bundle, qty=2)

        self.assertEqual(ScrapAccumulator.objects.count(), 2)

    def test_bundle_null_boleh_lebih_dari_satu(self):
        # PostgreSQL menganggap NULL berbeda satu sama lain, jadi (wc, NULL)
        # boleh berulang: dipakai mencatat kehilangan umum per work center.
        ScrapAccumulator.objects.create(work_center=self.wc_sewing, bundle=None, qty=1)
        ScrapAccumulator.objects.create(work_center=self.wc_sewing, bundle=None, qty=1)

        self.assertEqual(ScrapAccumulator.objects.filter(bundle=None).count(), 2)


class RoutingStepTests(TestCase):
    """DAG routing: M2M step lanjutan, rework self-FK, dan constraint unik."""

    @classmethod
    def setUpTestData(cls):
        cls.routing = ProcessRouting.objects.create(
            code="ROUTE-STD", name="Routing Standar"
        )
        cls.wc = WorkCenter.objects.create(code="SABLON-1", name="Sablon 1")
        cls.step_sablon = RoutingStep.objects.create(
            routing=cls.routing,
            code="SABLON",
            order=10,
            is_initial=True,
            work_center=cls.wc,
        )
        cls.step_sewing = RoutingStep.objects.create(
            routing=cls.routing, code="SEWING", order=20, work_center=cls.wc
        )
        cls.step_qc = RoutingStep.objects.create(
            routing=cls.routing, code="QC", order=30
        )
        cls.step_packing = RoutingStep.objects.create(
            routing=cls.routing, code="PACKING", order=40, is_terminal=True
        )

    def test_allowed_next_steps_m2m_tidak_simetris(self):
        self.step_sablon.allowed_next_steps.add(self.step_sewing)

        self.assertEqual(
            list(self.step_sablon.allowed_next_steps.all()), [self.step_sewing]
        )
        self.assertIn(self.step_sablon, list(self.step_sewing.allowed_from.all()))
        # symmetrical=False: arah balik tidak otomatis dibuat.
        self.assertEqual(list(self.step_sewing.allowed_next_steps.all()), [])

    def test_rework_target_step_self_fk(self):
        self.step_qc.rework_target_step = self.step_sablon
        self.step_qc.save()

        self.assertEqual(self.step_qc.rework_target_step, self.step_sablon)
        self.assertIn(self.step_qc, list(self.step_sablon.rework_sources.all()))

    def test_unique_code_dan_order_per_routing(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                RoutingStep.objects.create(routing=self.routing, code="SABLON", order=99)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                RoutingStep.objects.create(routing=self.routing, code="LAIN", order=10)

    def test_work_center_dihapus_jadi_null(self):
        step = RoutingStep.objects.create(
            routing=self.routing, code="EXTRA", order=99, work_center=self.wc
        )

        self.wc.delete()

        step.refresh_from_db()
        self.assertIsNone(step.work_center)

    def test_step_ikut_terhapus_kalau_routing_dihapus(self):
        self.routing.delete()

        self.assertEqual(RoutingStep.objects.count(), 0)


class ProductionLineTests(TestCase):
    """M2M work center di line produksi."""

    def test_m2m_work_centers_dan_related_name(self):
        wc_a = WorkCenter.objects.create(code="WC-A", name="Work Center A")
        wc_b = WorkCenter.objects.create(code="WC-B", name="Work Center B")
        line = ProductionLine.objects.create(code="LINE-1", name="Line 1")

        line.work_centers.add(wc_a, wc_b)

        self.assertEqual(line.work_centers.count(), 2)
        self.assertIn(line, list(wc_a.production_lines.all()))


class GarmentDeviceProfileTests(TestCase):
    """Extension OneToOne: data utama tetap di core.device_profile."""

    def test_onetoone_ke_core_device_profile(self):
        # Profil device core dibuat migration 0002_seed_default_profiles.
        device = DeviceProfile.objects.get(code="KIOS")
        wc = WorkCenter.objects.create(code="KIOS-WC", name="Kios WC")

        garment_profile = GarmentDeviceProfile.objects.create(
            device_profile=device, work_center=wc, notes="kios di sewing"
        )

        self.assertEqual(device.garment_profile, garment_profile)
        self.assertEqual(garment_profile.work_center, wc)
        self.assertEqual(GarmentDeviceProfile._meta.db_table, "garment_device_profile")

    def test_profil_core_tidak_boleh_punya_dua_extension(self):
        device = DeviceProfile.objects.get(code="SCANNER_USB")
        GarmentDeviceProfile.objects.create(device_profile=device)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                GarmentDeviceProfile.objects.create(device_profile=device)

    def test_extension_ikut_terhapus_kalau_profil_core_dihapus(self):
        device = DeviceProfile.objects.create(code="TABLET-EXT", name="Tablet")
        GarmentDeviceProfile.objects.create(device_profile=device)

        device.delete()

        self.assertEqual(GarmentDeviceProfile.objects.count(), 0)
