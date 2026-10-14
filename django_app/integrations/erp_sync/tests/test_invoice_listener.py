"""Test listener invoice (`WORK_ORDER_STATE_CHANGED`) — tanpa Odoo.

Listener didaftarkan di ``integrations/erp_sync/apps.py:ready()`` dengan kontrak
``listener(*, event_name, payload)`` (lihat ``core/event_bus/registry.py`` dan
``core/event_bus/tasks.py`` — listener async dipanggil di worker oleh task
``event_bus.dispatch_event``). Di sini listener dipanggil **langsung** supaya
deterministik, dengan ``InvoiceSyncService`` di-mock (tanpa DB antrean nyata).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.test import TestCase

from apps_industry.garment.models import Order, OrderLine, WorkOrder
from core.event_bus.registry import get_listeners
from core.event_bus.signals import WORK_ORDER_STATE_CHANGED
from integrations.erp_sync.apps import _on_work_order_state_changed
from master.models import Partner, Product

SERVICE = "integrations.erp_sync.services.InvoiceSyncService"


class InvoiceListenerTests(TestCase):
    """Payload ``WORK_ORDER_STATE_CHANGED`` = {wo_id, wo_code, action, state, version}.

    Aturan listener: invoice hanya di-enqueue kalau **semua** ``WorkOrder`` order
    itu sudah ``DONE`` (event dikirim SETELAH state WO tersimpan — lihat
    ``garment/api/actions/executor.py``). Test yang memverifikasi pemanggilan
    ``enqueue`` karena itu menandai dulu WO-nya ``DONE`` lewat :meth:`mark_done`.
    """

    @classmethod
    def setUpTestData(cls):
        cls.customer = Partner.objects.create(
            code="PT-LST-1", name="PT Listener", odoo_id=51
        )
        cls.product = Product.objects.create(
            code="KTS-LST-1", name="Kaos Listener", odoo_id=100
        )
        cls.order = Order.objects.create(code="ORD-LST-1000", customer=cls.customer)
        line = OrderLine.objects.create(order=cls.order, product=cls.product, qty=2)
        cls.work_order = WorkOrder.objects.create(
            code="WO-LST-1000", order_line=line, qty_planned=2
        )

    # ------------------------------------------------------------------ helper
    @classmethod
    def make_work_order(cls, code, state="DRAFT"):
        """WorkOrder tambahan untuk order fixture (OrderLine sama — boleh >1 WO)."""
        return WorkOrder.objects.create(
            code=code,
            order_line=cls.order.lines.order_by("id").first(),
            qty_planned=1,
            state=state,
        )

    @staticmethod
    def mark_done(*work_orders):
        """Tandai WO ``DONE`` seperti executor (state disimpan sebelum event)."""
        for work_order in work_orders:
            WorkOrder.objects.filter(pk=work_order.pk).update(state="DONE")

    @classmethod
    def payload(cls, state, wo_id=None):
        """Payload seperti yang dikirim `garment/services/action_events.py`."""
        return {
            "wo_id": cls.work_order.pk if wo_id is None else wo_id,
            "wo_code": "WO-LST-1000",
            "action": "WO_CLOSE",
            "state": state,
            "version": "abc123",
        }

    def call_listener(self, state, wo_id=None):
        """Panggil listener dengan service di-mock; return mock service-nya."""
        service = MagicMock()
        with patch(SERVICE, return_value=service):
            _on_work_order_state_changed(
                event_name=WORK_ORDER_STATE_CHANGED,
                payload=self.payload(state, wo_id),
            )
        return service

    # -------------------------------------------------------------------- test
    def test_state_done_enqueue_dipanggil(self):
        # Satu-satunya WO order ini sudah DONE → semua WO selesai.
        self.mark_done(self.work_order)

        service = self.call_listener("DONE")

        service.enqueue.assert_called_once()
        self.assertEqual(service.enqueue.call_args.args[0], self.order)

    def test_wo_lain_belum_done_tidak_enqueue(self):
        self.mark_done(self.work_order)  # WO pemicu sudah DONE
        self.make_work_order("WO-LST-2000")  # WO kedua masih DRAFT

        service = self.call_listener("DONE")

        service.enqueue.assert_not_called()

    def test_wo_terakhir_done_enqueue_dipanggil(self):
        self.mark_done(self.work_order)
        wo_kedua = self.make_work_order("WO-LST-3000")
        self.mark_done(wo_kedua)  # semua WO order sudah DONE

        service = self.call_listener("DONE", wo_id=wo_kedua.pk)

        service.enqueue.assert_called_once()
        self.assertEqual(service.enqueue.call_args.args[0], self.order)

    def test_wo_cancelled_tidak_memblokir_invoice(self):
        """WO ``CANCELLED`` dianggap selesai → invoice tetap di-enqueue (I8.2)."""
        self.mark_done(self.work_order)  # WO pemicu sudah DONE
        self.make_work_order("WO-LST-4000", state="CANCELLED")

        service = self.call_listener("DONE")

        service.enqueue.assert_called_once()
        self.assertEqual(service.enqueue.call_args.args[0], self.order)

    def test_state_in_progress_tidak_enqueue(self):
        self.mark_done(self.work_order)  # WO-nya DONE, state event bukan DONE
        service = self.call_listener("IN_PROGRESS")

        service.enqueue.assert_not_called()

    def test_state_cancelled_tidak_enqueue(self):
        self.mark_done(self.work_order)
        service = self.call_listener("CANCELLED")

        service.enqueue.assert_not_called()

    def test_error_di_listener_tidak_raise(self):
        self.mark_done(self.work_order)  # supaya listener benar-benar memanggil enqueue
        service = MagicMock()
        service.enqueue.side_effect = RuntimeError("db mati")

        with patch(SERVICE, return_value=service):
            with self.assertLogs("integrations.erp_sync.apps", level="ERROR"):
                _on_work_order_state_changed(
                    event_name=WORK_ORDER_STATE_CHANGED,
                    payload=self.payload("DONE"),
                )

        service.enqueue.assert_called_once()  # sudah dicoba, error ditelan

    def test_wo_tidak_ditemukan_tidak_raise_dan_tidak_enqueue(self):
        service = MagicMock()

        with patch(SERVICE, return_value=service):
            _on_work_order_state_changed(
                event_name=WORK_ORDER_STATE_CHANGED,
                payload=self.payload("DONE", wo_id=999_999),
            )

        service.enqueue.assert_not_called()

    def test_listener_terdaftar_di_registry(self):
        self.assertIn(
            _on_work_order_state_changed, get_listeners(WORK_ORDER_STATE_CHANGED)
        )
