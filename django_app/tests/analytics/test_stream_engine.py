"""Test stream engine analytics (B.4) — Redis di-mock (tanpa server)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from integrations.analytics.core import stream_engine

PATCH_CLIENT = "integrations.analytics.core.stream_engine._redis_client"


def _mock_client():
    client = MagicMock()
    pipe = MagicMock()
    client.pipeline.return_value.__enter__.return_value = pipe
    return client, pipe


class StreamEngineTests(SimpleTestCase):
    """record_event atomic + evaluate threshold/cooldown."""

    def test_record_event_atomic_zadd_trim_expire(self):
        client, pipe = _mock_client()

        with patch(PATCH_CLIENT, return_value=client):
            stream_engine.record_event(
                {"id": "evt-1", "ts": 1_000.0}, "garment.scrap_rate", 4.2
            )

        pipe.zadd.assert_called_once_with(
            "analytics:stream:garment.scrap_rate", {"evt-1": 1_000.0}
        )
        pipe.zremrangebyscore.assert_called_once_with(
            "analytics:stream:garment.scrap_rate", "-inf", 1_000.0 - 900
        )
        pipe.expire.assert_called_once_with(
            "analytics:stream:garment.scrap_rate", 1800
        )
        pipe.execute.assert_called_once()

    def test_evaluate_threshold_tidak_terlampaui_none(self):
        client, _pipe = _mock_client()

        with patch(PATCH_CLIENT, return_value=client):
            alert = stream_engine.evaluate(
                {"value": 3.0},
                {"metric_id": "garment.scrap_rate", "threshold": 5.0},
            )

        self.assertIsNone(alert)
        client.set.assert_not_called()

    def test_evaluate_threshold_terlampaui_alert_shape(self):
        client, _pipe = _mock_client()
        client.set.return_value = True

        with patch(PATCH_CLIENT, return_value=client):
            alert = stream_engine.evaluate(
                {"value": 7.8},
                {
                    "metric_id": "garment.scrap_rate",
                    "window": "1h",
                    "baseline": 3.1,
                    "threshold": 5.0,
                },
            )

        self.assertIsNotNone(alert)
        assert alert is not None
        self.assertEqual(alert["metric_id"], "garment.scrap_rate")
        self.assertEqual(alert["window"], "1h")
        self.assertEqual(alert["value"], 7.8)
        self.assertEqual(alert["baseline"], 3.1)
        self.assertEqual(alert["threshold"], 5.0)
        self.assertIn(alert["severity"], {"MEDIUM", "HIGH"})
        self.assertIn("detected_at", alert)

    def test_sliding_window_trim_memakai_window_kustom(self):
        client, pipe = _mock_client()

        with patch(PATCH_CLIENT, return_value=client):
            stream_engine.record_event(
                {"id": "evt-2", "ts": 5_000.0, "window": "1h"},
                "garment.lead_time",
                2.0,
            )

        pipe.zremrangebyscore.assert_called_once_with(
            "analytics:stream:garment.lead_time", "-inf", 5_000.0 - 3600
        )

    def test_cooldown_30_menit_hanya_satu_alert(self):
        client, _pipe = _mock_client()
        client.set.return_value = False  # key cooldown sudah ada

        with patch(PATCH_CLIENT, return_value=client):
            alert = stream_engine.evaluate(
                {"value": 9.0},
                {"metric_id": "garment.scrap_rate", "threshold": 5.0},
            )

        self.assertIsNone(alert)
        client.set.assert_called_once_with(
            "analytics:alert:garment.scrap_rate", "1", nx=True, ex=1800
        )

    def test_tidak_ada_key_abadi_expire_selalu_dipanggil(self):
        client, pipe = _mock_client()

        with patch(PATCH_CLIENT, return_value=client):
            stream_engine.record_event(
                {"id": "evt-3", "ts": 1.0, "window": "30m"},
                "garment.rework_rate",
                1.0,
            )

        pipe.expire.assert_called_once_with(
            "analytics:stream:garment.rework_rate", 3600
        )
