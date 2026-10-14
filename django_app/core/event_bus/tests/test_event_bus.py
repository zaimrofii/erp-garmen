"""Test minimal event bus: signal sinkron, enqueue Celery, listener async.

`CELERY_TASK_ALWAYS_EAGER=True` dipakai supaya task `dispatch_event` jalan
inline (tanpa broker/worker). Karena `config/celery.py` membaca konfigurasi
`CELERY_*` **saat import**, `override_settings` saja tidak cukup — `setUp()`
juga men-set `celery_app.conf.task_always_eager` langsung.
"""

from __future__ import annotations

from unittest import mock

from django.test import TestCase, override_settings

from config.celery import app as celery_app
from core.event_bus import publisher, registry, signals
from core.event_bus.tasks import dispatch_event

PAYLOAD = {"bundle_id": 7, "from_state": "DRAFT", "to_state": "SEWING"}


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
class EventBusTests(TestCase):
    """Publisher (sinkron + async) dan Celery dispatcher."""

    def setUp(self):
        super().setUp()
        self._task_always_eager = celery_app.conf.task_always_eager
        self._task_eager_propagates = celery_app.conf.task_eager_propagates
        celery_app.conf.task_always_eager = True
        celery_app.conf.task_eager_propagates = True
        registry.clear_listeners()

    def tearDown(self):
        celery_app.conf.task_always_eager = self._task_always_eager
        celery_app.conf.task_eager_propagates = self._task_eager_propagates
        registry.clear_listeners()
        super().tearDown()

    def test_publish_mengirim_signal_sinkron(self):
        diterima = []

        def receiver(sender, **kwargs):
            diterima.append((sender, kwargs["event_name"], kwargs["payload"]))

        signals.bundle_state_changed.connect(receiver, weak=False)
        try:
            publisher.publish(signals.BUNDLE_STATE_CHANGED, PAYLOAD)
        finally:
            signals.bundle_state_changed.disconnect(receiver)

        self.assertEqual(len(diterima), 1)
        sender, event_name, payload = diterima[0]
        self.assertEqual(sender, publisher.SENDER)
        self.assertEqual(event_name, signals.BUNDLE_STATE_CHANGED)
        self.assertEqual(payload, PAYLOAD)

    def test_publish_enqueue_task_celery(self):
        with mock.patch("core.event_bus.publisher.dispatch_event") as mocked_task:
            publisher.publish(signals.SCRAP_RECORDED, PAYLOAD)

        mocked_task.delay.assert_called_once_with(signals.SCRAP_RECORDED, PAYLOAD)

    def test_publish_eager_menjalankan_listener_async(self):
        diterima = []
        registry.register_listener(
            signals.WORK_ORDER_STATE_CHANGED,
            lambda *, event_name, payload: diterima.append((event_name, payload)),
        )

        publisher.publish(signals.WORK_ORDER_STATE_CHANGED, {"wo_id": 3})

        self.assertEqual(
            diterima,
            [(signals.WORK_ORDER_STATE_CHANGED, {"wo_id": 3})],
        )

    def test_dispatch_event_memanggil_listener_registry(self):
        diterima = []
        registry.register_listener(
            signals.ERP_SYNC_COMPLETED,
            lambda **kwargs: diterima.append(kwargs),
        )

        hasil = dispatch_event(signals.ERP_SYNC_COMPLETED, {"stage": "FG"})

        self.assertEqual(
            hasil,
            {"event_name": signals.ERP_SYNC_COMPLETED, "listeners": 1, "executed": 1},
        )
        self.assertEqual(
            diterima,
            [{"event_name": signals.ERP_SYNC_COMPLETED, "payload": {"stage": "FG"}}],
        )

    def test_dispatch_event_tanpa_listener_tetap_ok(self):
        hasil = dispatch_event("EVENT_TANPA_LISTENER", None)
        self.assertEqual(hasil["listeners"], 0)
        self.assertEqual(hasil["executed"], 0)

    def test_publish_menolak_event_name_kosong(self):
        with self.assertRaises(ValueError):
            publisher.publish("", PAYLOAD)
