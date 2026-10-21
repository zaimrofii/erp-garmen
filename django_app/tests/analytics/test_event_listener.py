"""Test listener event bus analytics (B.3) — 8 skenario."""

from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase

from core.event_bus import registry as bus_registry
from core.event_bus.signals import BUNDLE_STATE_CHANGED, SCRAP_RECORDED
from integrations.analytics.config import ANALYTICS_CONFIG
from integrations.analytics.core import event_listener

INVALIDATE = (
    "integrations.analytics.services.analytics_config_services.invalidate_cache"
)


class EventListenerTests(TestCase):
    """Registrasi + dispatch + isolasi kegagalan."""

    def setUp(self):
        bus_registry.clear_listeners()
        event_listener._reset_for_tests()

    def _dispatch(self, event_name: str):
        for listener in bus_registry.get_listeners(event_name):
            listener(event_name=event_name, payload={})

    def test_register_all_registers_four_listeners(self):
        event_listener.register_all()

        total = sum(
            len(bus_registry.get_listeners(name))
            for name in (
                BUNDLE_STATE_CHANGED,
                SCRAP_RECORDED,
                event_listener.SYNC_RECORD_CHANGED,
                event_listener.ANALYTICS_CONFIG_CHANGED,
            )
        )
        self.assertEqual(total, 4)

    def test_register_all_idempotent(self):
        event_listener.register_all()
        event_listener.register_all()

        self.assertEqual(len(bus_registry.get_listeners(BUNDLE_STATE_CHANGED)), 1)

    def test_bundle_state_changed_invalidates_cache(self):
        event_listener.register_all()

        with patch(INVALIDATE) as invalidate:
            self._dispatch(BUNDLE_STATE_CHANGED)

        invalidate.assert_called_once()

    def test_scrap_recorded_invalidates_cache(self):
        event_listener.register_all()

        with patch(INVALIDATE) as invalidate:
            self._dispatch(SCRAP_RECORDED)

        invalidate.assert_called_once()

    def test_sync_record_changed_invalidates_cache(self):
        event_listener.register_all()

        with patch(INVALIDATE) as invalidate:
            self._dispatch(event_listener.SYNC_RECORD_CHANGED)

        invalidate.assert_called_once()

    def test_config_changed_invalidates_cache(self):
        event_listener.register_all()

        with patch(INVALIDATE) as invalidate:
            self._dispatch(event_listener.ANALYTICS_CONFIG_CHANGED)

        invalidate.assert_called_once()

    def test_exception_di_handler_tidak_raise(self):
        event_listener.register_all()

        with patch(INVALIDATE, side_effect=RuntimeError("cache mati")):
            with self.assertLogs("integrations.analytics.core.event_listener", level="ERROR"):
                self._dispatch(SCRAP_RECORDED)  # tidak boleh raise

    def test_config_flag_false_tidak_mendaftarkan(self):
        with patch.dict(ANALYTICS_CONFIG, {"event_bus_listener": False}):
            event_listener.register_all()

        self.assertEqual(bus_registry.get_listeners(BUNDLE_STATE_CHANGED), ())


class OperatorActionUnaffectedTests(TestCase):
    """BUKTI end-to-end: listener analytics error TIDAK menggagalkan aksi operator."""

    def setUp(self):
        from uuid import uuid4

        from rest_framework.test import APIClient

        from config.celery import app as celery_app
        from core.auth.models import User

        self.api = APIClient()
        self.api.force_authenticate(
            User.objects.create_user(
                username=f"op-{uuid4().hex[:8]}", password="rahasia"  # noqa: S106
            )
        )
        self._eager = celery_app.conf.task_always_eager
        celery_app.conf.task_always_eager = True
        bus_registry.clear_listeners(BUNDLE_STATE_CHANGED)

    def tearDown(self):
        from config.celery import app as celery_app

        celery_app.conf.task_always_eager = self._eager
        bus_registry.clear_listeners(BUNDLE_STATE_CHANGED)

    def test_aksi_bundle_tetap_200_walau_listener_error(self):
        from uuid import uuid4

        from apps_industry.garment.tests.factories import make_bundle

        bundle = make_bundle(code=f"BND-{uuid4().hex[:8]}", qty=1)
        metadata = self.api.get(
            f"/api/v1/metadata/bundles/?id={bundle.pk}"
        ).json()
        action_id = metadata["state_machine"]["allowed_actions"][0]["id"]
        version = metadata["resource"]["version"]

        def boom(*, event_name=None, payload=None):
            raise RuntimeError("boom-analytics")

        # Listener analytics (async registry) dibuat MELEDAK.
        bus_registry.register_listener(BUNDLE_STATE_CHANGED, boom)

        from core.event_bus.tasks import dispatch_event

        # Jalankan dispatcher SINKRON (tanpa broker) — jalur listener sama
        # dengan worker: dispatch_event menangkap exception per listener.
        with patch(
            "core.event_bus.publisher.dispatch_event.delay",
            side_effect=lambda *args, **kwargs: dispatch_event(*args, **kwargs),
        ):
            with self.assertLogs("core.event_bus.tasks", level="ERROR") as logs:
                response = self.api.post(
                    f"/api/v1/garmen/bundles/{bundle.pk}/{action_id}/",
                    {},
                    format="json",
                    HTTP_IDEMPOTENCY_KEY=f"tr-{uuid4().hex[:8]}",
                    HTTP_X_BASE_VERSION=version,
                )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            any("gagal saat menangani event" in line for line in logs.output)
        )

