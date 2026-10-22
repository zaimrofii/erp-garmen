"""Test S.6 — OEE, WIP flow, alert wc_idle/buffer_overflow."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps_industry.garment.tests.factories import make_bundle, make_work_center
from integrations.analytics.core import event_listener
from integrations.analytics.plugins.garment.metrics import oee, wip_flow
from integrations.analytics.plugins.garment.streams import buffer_overflow, wc_idle
from tests.analytics.test_metrics_garment import DAY, GarmentMetricsTestBase


class OeeTests(GarmentMetricsTestBase):
    def _setup(self, *, capacity="10", qty=10, scrap_qty=1):
        wc = make_work_center("SEWING-2", capacity_per_hour=capacity)
        bundle = self._bundle(qty=qty, wc=wc)
        self._event(bundle, "BUNDLE_FINISH", ts=DAY.replace(hour=9))
        self._event(bundle, "BUNDLE_START", ts=DAY.replace(hour=10))
        if scrap_qty:
            self._scrap(bundle, scrap_qty, wc=wc, ts=DAY.replace(hour=9))
        return wc, bundle

    def test_formula_availability_performance_quality(self):
        self._setup(capacity="10", qty=10, scrap_qty=1)

        rows = oee._compute_oee(
            {
                "granularity": "day",
                "group_by": "work_center",
            }
        )

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertAlmostEqual(row["availability"], 0.25, places=3)
        self.assertAlmostEqual(row["performance"], 0.5, places=3)
        self.assertAlmostEqual(row["quality"], round(10 / 11, 3), places=3)
        self.assertAlmostEqual(row["value"], 11.36, places=2)
        self.assertEqual(row["label"], "SEWING-2")

    def test_tanpa_event_returns_empty(self):
        make_work_center("SEWING-X", capacity_per_hour=10)

        rows = oee._compute_oee(
            {
                "granularity": "day",
                "group_by": "period",
            }
        )

        self.assertEqual(rows, [])

    def test_capacity_nol_performance_satu(self):
        self._setup(capacity="0")

        rows = oee._compute_oee(
            {
                "granularity": "day",
                "group_by": "work_center",
            }
        )

        self.assertEqual(rows[0]["performance"], 1.0)

    def test_group_by_period_menggabung_hari(self):
        self._setup()

        rows = oee._compute_oee(
            {
                "granularity": "day",
                "group_by": "period",
            }
        )

        self.assertEqual(rows[0]["key"], DAY.date().isoformat())

    def test_granularity_week_key_senin(self):
        self._setup()

        rows = oee._compute_oee(
            {
                "granularity": "week",
                "group_by": "period",
            }
        )

        self.assertEqual(rows[0]["key"], "2026-10-05")

    def test_filter_work_center_mengeluarkan_wc_lain(self):
        self._setup()
        other = make_work_center("QC-9", capacity_per_hour=5)
        bundle = self._bundle(qty=5, wc=other)
        self._event(bundle, "BUNDLE_FINISH", ts=DAY.replace(hour=11))

        rows = oee._compute_oee(
            {
                "granularity": "day",
                "group_by": "work_center",
                "work_center_id": other.pk,
            }
        )

        self.assertEqual([row["label"] for row in rows], ["QC-9"])

class WipFlowTests(GarmentMetricsTestBase):
    def _setup(self):
        wc = make_work_center("SEWING-2")
        b1 = self._bundle(qty=10, wc=wc)
        b2 = self._bundle(qty=10, wc=wc)
        self._event(b1, "BUNDLE_START", ts=DAY.replace(hour=9, minute=5))
        self._event(b2, "BUNDLE_START", ts=DAY.replace(hour=9, minute=15))
        self._event(b1, "BUNDLE_FINISH", ts=DAY.replace(hour=9, minute=45))
        return wc, b1, b2

    def test_in_minus_out_per_jam(self):
        self._setup()

        rows = wip_flow._compute_wip_flow({"group_by": "period"})

        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["in"], rows[0]["out"], rows[0]["value"]), (2, 1, 1))

    def test_negatif_berarti_mengalir(self):
        wc = make_work_center("QC-1")
        bundle = self._bundle(wc=wc)
        self._event(bundle, "BUNDLE_START", ts=DAY.replace(hour=9, minute=1))
        for index in range(3):
            self._event(bundle, "BUNDLE_FINISH", ts=DAY.replace(hour=9, minute=10 + index))

        rows = wip_flow._compute_wip_flow({"group_by": "period"})

        self.assertEqual(rows[0]["value"], -2)

    def test_group_by_work_center_label(self):
        self._setup()

        rows = wip_flow._compute_wip_flow({"group_by": "work_center"})

        self.assertEqual(rows[0]["label"], "SEWING-2")
        self.assertEqual(rows[0]["value"], 1)

    def test_payload_direction_menimpa_tipe_event(self):
        wc = make_work_center("SABLON-1")
        bundle = self._bundle(wc=wc)
        self._event(
            bundle,
            "CUSTOM_EVENT",
            ts=DAY.replace(hour=9, minute=5),
            payload={"direction": "out", "work_center_id": wc.pk},
        )

        rows = wip_flow._compute_wip_flow({"group_by": "work_center"})

        self.assertEqual(rows[0]["value"], -1)

    def test_tanpa_event_kosong(self):
        self.assertEqual(
            wip_flow._compute_wip_flow({"group_by": "period"}),
            [],
        )

    def test_dua_jam_terpisah(self):
        wc = make_work_center("CUTTING-1")
        bundle = self._bundle(wc=wc)
        self._event(bundle, "BUNDLE_START", ts=DAY.replace(hour=9, minute=5))
        self._event(bundle, "BUNDLE_START", ts=DAY.replace(hour=10, minute=5))

        rows = wip_flow._compute_wip_flow({"group_by": "period"})

        self.assertEqual(len(rows), 2)

class WcIdleAlertTests(TestCase):
    def _event(self, wc, ts):
        from apps_industry.garment.models import BundleEvent

        bundle = make_bundle(current_work_center=wc)
        event = BundleEvent.objects.create(bundle=bundle, event_type="BUNDLE_START")
        BundleEvent.objects.filter(pk=event.pk).update(ts=ts)

    def test_idle_tiga_jam_alert_medium(self):
        wc = make_work_center("SEWING-2")
        now = timezone.make_aware(datetime(2026, 10, 14, 14, 0))
        self._event(wc, now - timedelta(hours=3))

        alert = wc_idle.check_wc_idle(now=now)

        self.assertIsNotNone(alert)
        self.assertEqual(alert["severity"], "MEDIUM")
        self.assertEqual(alert["work_centers"][0]["work_center"], "SEWING-2")
        self.assertIn("idle", alert["message"].lower())

    def test_event_baru_tidak_alert(self):
        wc = make_work_center("QC-1")
        now = timezone.make_aware(datetime(2026, 10, 14, 14, 0))
        self._event(wc, now - timedelta(minutes=30))

        self.assertIsNone(wc_idle.check_wc_idle(now=now))

    def test_di_luar_jam_kerja_tidak_alert(self):
        wc = make_work_center("CUTTING-1")
        self._event(wc, timezone.make_aware(datetime(2026, 10, 14, 10, 0)))

        self.assertIsNone(
            wc_idle.check_wc_idle(
                now=timezone.make_aware(datetime(2026, 10, 14, 19, 0))
            )
        )


class BufferOverflowAlertTests(TestCase):
    def test_buffer_21_alert_high(self):
        wc = make_work_center("SEWING-2")
        for _index in range(21):
            make_bundle(current_work_center=wc)

        alert = buffer_overflow.check_buffer_overflow()

        self.assertIsNotNone(alert)
        self.assertEqual(alert["severity"], "HIGH")
        self.assertEqual(alert["work_centers"][0]["buffer_length"], 21)

    def test_buffer_pada_threshold_tidak_alert(self):
        wc = make_work_center("SEWING-3")
        for _index in range(20):
            make_bundle(current_work_center=wc)

        self.assertIsNone(buffer_overflow.check_buffer_overflow())

    def test_threshold_custom(self):
        wc = make_work_center("SEWING-4")
        for _index in range(6):
            make_bundle(current_work_center=wc)

        self.assertIsNotNone(buffer_overflow.check_buffer_overflow(threshold=5))


class AlertListenerTests(TestCase):
    def test_bundle_event_memicu_idle_dan_buffer(self):
        with patch(
            "integrations.analytics.services.analytics_config_services.get_config",
            return_value=type("C", (), {"enabled": True})(),
        ), patch(
            "integrations.analytics.plugins.garment.streams.wc_idle.check_wc_idle",
            return_value={"message": "WC idle"},
        ) as idle, patch(
            "integrations.analytics.plugins.garment.streams.buffer_overflow.check_buffer_overflow",
            return_value={"message": "Buffer overflow"},
        ) as buffer, patch.object(
            event_listener, "_notify_wa"
        ) as notify:
            event_listener.handle_bundle_state_changed(payload={"bundle_id": 1})

        idle.assert_called_once()
        buffer.assert_called_once()
        self.assertEqual(notify.call_count, 2)


