"""Test `MaterialReadinessService` (I3) — transport di-mock, tanpa Odoo.

Cakupan: WAITING/PARTIAL/READY, baris PO yang tak match komponen, BOM tidak ada,
idempotensi OneToOne, `expected_date` = min `date_planned`, `compute_batch`,
wiring `get_transport` default (dipanggil + ditutup), dan error per-item di batch.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

from django.test import TestCase

from apps_industry.garment.models import MaterialReadiness, Order, OrderLine
from integrations.erp_sync.services.material_readiness import MaterialReadinessService
from master.models import BOM, BOMLine, Product

GET_TRANSPORT = "integrations.erp_sync.services.material_readiness.get_transport"


class FakeTransport:
    """Transport palsu: PO/line/vendor bill dari daftar yang disiapkan test."""

    def __init__(self, orders=None, lines=None, error=None, bills=None):
        self.orders = list(orders or [])
        self.lines = list(lines or [])
        self.bills = list(bills or [])
        self.error = error
        self.calls = []
        self.closed = False

    def fetch_purchase_orders(self, since=None, states=("purchase", "done")):
        self.calls.append(("orders", since, tuple(states)))
        if self.error is not None:
            raise self.error
        return self.orders

    def fetch_purchase_order_lines(self, order_ids, since=None):
        self.calls.append(("lines", tuple(order_ids or []), since))
        return self.lines

    def fetch_vendor_bills(self, since=None, states=("draft", "posted")):
        self.calls.append(("bills", since, tuple(states)))
        return self.bills

    def close(self):
        self.closed = True


class MaterialReadinessServiceTestCase(TestCase):
    """BOM FG-001 = kain 2.0 + benang 0.5 per unit; OrderLine qty=4 → butuh 10."""

    @classmethod
    def setUpTestData(cls):
        cls.fg = Product.objects.create(
            code="FG-001", name="Kaos Jadi", odoo_id=501, odoo_tmpl_id=900
        )
        cls.fabric = Product.objects.create(code="FAB-001", name="Kain", odoo_id=601)
        cls.thread = Product.objects.create(code="THR-001", name="Benang", odoo_id=602)
        cls.other = Product.objects.create(code="ACC-999", name="Aksesoris", odoo_id=999)

        cls.bom = BOM.objects.create(code="BOM-FG-001", product=cls.fg)
        BOMLine.objects.create(bom=cls.bom, product=cls.fabric, product_qty=2.0)
        BOMLine.objects.create(bom=cls.bom, product=cls.thread, product_qty=0.5)

        # Produk tanpa BOM + produk dengan BOM yang komponennya tak dipasok PO.
        cls.fg_no_bom = Product.objects.create(
            code="FG-002", name="Tanpa BOM", odoo_id=502
        )
        cls.fg_other_bom = Product.objects.create(
            code="FG-003", name="BOM Lain", odoo_id=503, odoo_tmpl_id=901
        )
        cls.lining = Product.objects.create(code="LIN-001", name="Furing", odoo_id=603)
        bom_lain = BOM.objects.create(code="BOM-FG-003", product=cls.fg_other_bom)
        BOMLine.objects.create(bom=bom_lain, product=cls.lining, product_qty=1.0)

        cls.order = Order.objects.create(code="ORD-MR-1000")
        cls.line = OrderLine.objects.create(order=cls.order, product=cls.fg, qty=4)
        cls.line_no_bom = OrderLine.objects.create(
            order=cls.order, product=cls.fg_no_bom, qty=3
        )

    @staticmethod
    def po_line(line_id, product_odoo_id, qty_received, order_id=1, date_planned=None):
        """Baris ``purchase.order.line`` seperti hasil transport."""
        return {
            "id": line_id,
            "order_id": [order_id, f"PO-{order_id}"],
            "product_id": [product_odoo_id, "produk"],
            "qty_received": qty_received,
            "date_planned": date_planned,
        }

    def compute(self, transport, order_line):
        return MaterialReadinessService(transport=transport).compute(order_line)

    def test_waiting_tanpa_po(self):
        transport = FakeTransport(orders=[])

        readiness = self.compute(transport, self.line)

        self.assertEqual(readiness.required_qty, 10.0)
        self.assertEqual(readiness.received_qty, 0.0)
        self.assertEqual(readiness.shortage_qty, 10.0)
        self.assertEqual(readiness.status, "WAITING")
        self.assertIsNone(readiness.expected_date)
        self.assertEqual(readiness.po_ids, [])
        self.assertEqual(readiness.po_line_ids, [])
        self.assertIsNotNone(readiness.last_computed_at)
        # Transport di-inject pemanggil → TIDAK ditutup oleh service.
        self.assertFalse(transport.closed)

    def test_partial_po_sebagian(self):
        transport = FakeTransport(
            orders=[{"id": 1, "state": "purchase"}],
            lines=[self.po_line(11, 601, 4.0)],
        )

        readiness = self.compute(transport, self.line)

        self.assertEqual(readiness.required_qty, 10.0)
        self.assertEqual(readiness.received_qty, 4.0)
        self.assertEqual(readiness.shortage_qty, 6.0)
        self.assertEqual(readiness.status, "PARTIAL")
        self.assertEqual(readiness.po_ids, [1])
        self.assertEqual(readiness.po_line_ids, [11])
        # Domain PO: states default ('purchase','done') lalu lines per po_ids.
        self.assertEqual(transport.calls[0], ("orders", None, ("purchase", "done")))
        self.assertEqual(transport.calls[1], ("lines", (1,), None))

    def test_ready_po_menutup_kebutuhan(self):
        transport = FakeTransport(
            orders=[{"id": 1, "state": "purchase"}],
            lines=[self.po_line(11, 601, 12.0)],
        )

        readiness = self.compute(transport, self.line)

        self.assertEqual(readiness.received_qty, 12.0)
        self.assertEqual(readiness.shortage_qty, 0.0)
        self.assertEqual(readiness.status, "READY")

    def test_produk_po_tidak_match_komponen_bom(self):
        transport = FakeTransport(
            orders=[{"id": 1, "state": "purchase"}],
            lines=[
                self.po_line(11, 999, 5.0),  # ACC-999 bukan komponen BOM FG-001
                self.po_line(12, 603, 5.0),  # LIN-001 komponen BOM produk lain
            ],
        )

        readiness = self.compute(transport, self.line)

        self.assertEqual(readiness.required_qty, 10.0)
        self.assertEqual(readiness.received_qty, 0.0)
        self.assertEqual(readiness.shortage_qty, 10.0)
        self.assertEqual(readiness.status, "WAITING")
        self.assertEqual(readiness.po_ids, [])
        self.assertEqual(readiness.po_line_ids, [])

    def test_bom_tidak_ada_required_nol_status_ready(self):
        transport = FakeTransport(
            orders=[{"id": 1, "state": "purchase"}],
            lines=[self.po_line(11, 601, 5.0)],
        )

        with self.assertLogs(
            "integrations.erp_sync.services.material_readiness", level="WARNING"
        ) as logs:
            readiness = self.compute(transport, self.line_no_bom)

        self.assertEqual(readiness.required_qty, 0.0)
        self.assertEqual(readiness.received_qty, 0.0)
        self.assertEqual(readiness.shortage_qty, 0.0)
        self.assertEqual(readiness.status, "READY")
        # "tanpa BOM" dilaporkan lewat log warning (bukan flag di return).
        self.assertIn("BOM aktif", " ".join(logs.output))

    def test_idempotensi_compute_dua_kali_tetap_satu_baris(self):
        transport = FakeTransport(
            orders=[{"id": 1, "state": "purchase"}],
            lines=[self.po_line(11, 601, 12.0)],
        )
        service = MaterialReadinessService(transport=transport)

        pertama = service.compute(self.line)
        kedua = service.compute(self.line)

        self.assertEqual(pertama.pk, kedua.pk)
        self.assertEqual(
            MaterialReadiness.objects.filter(order_line=self.line).count(), 1
        )
        self.assertEqual(MaterialReadiness.objects.count(), 1)

    def test_compute_batch_dua_order_line_counter_status(self):
        # line (FG-001, qty 4 → butuh 10) ditutup PO 12 → READY.
        # line_lain (FG-003, qty 2 → butuh 2, komponen furing) tak dipasok → WAITING.
        line_lain = OrderLine.objects.create(
            order=self.order, product=self.fg_other_bom, qty=2
        )
        transport = FakeTransport(
            orders=[{"id": 1, "state": "purchase"}],
            lines=[self.po_line(11, 601, 12.0)],
        )

        result = MaterialReadinessService(transport=transport).compute_batch(
            OrderLine.objects.filter(pk__in=[self.line.pk, line_lain.pk])
        )

        self.assertEqual(result["processed"], 2)
        self.assertEqual(result["ready"], 1)
        self.assertEqual(result["waiting"], 1)
        self.assertEqual(result["partial"], 0)
        self.assertEqual(result["errors"], 0)
        self.assertEqual(MaterialReadiness.objects.count(), 2)

    def test_expected_date_min_date_planned_dari_po_match(self):
        transport = FakeTransport(
            orders=[{"id": 1, "state": "purchase"}],
            lines=[
                self.po_line(11, 601, 4.0, date_planned="2026-10-20 08:00:00"),
                self.po_line(12, 602, 3.0, date_planned="2026-10-15 09:30:00"),
            ],
        )

        readiness = self.compute(transport, self.line)

        self.assertEqual(readiness.expected_date, date(2026, 10, 15))
        self.assertEqual(readiness.received_qty, 7.0)
        self.assertEqual(readiness.po_line_ids, [11, 12])
        self.assertEqual(readiness.po_ids, [1])

    def test_get_transport_default_dipanggil_dan_ditutup(self):
        transport = FakeTransport(orders=[])

        with patch(GET_TRANSPORT, return_value=transport) as get_transport_mock:
            MaterialReadinessService().compute(self.line)

        get_transport_mock.assert_called_once_with()
        self.assertTrue(transport.closed)

    # ------------------------------------------------------------ vendor bill
    def test_vendor_bill_posted_mengisi_status_ids_amount(self):
        transport = FakeTransport(
            orders=[{"id": 1, "name": "P00012", "state": "purchase"}],
            lines=[self.po_line(11, 601, 12.0)],
            bills=[
                {
                    "id": 900,
                    "invoice_origin": "P00012",
                    "state": "posted",
                    "amount_total": 150.0,
                }
            ],
        )

        readiness = self.compute(transport, self.line)

        self.assertEqual(readiness.vendor_bill_status, "POSTED")
        self.assertEqual(readiness.vendor_bill_ids, [900])
        self.assertEqual(readiness.vendor_bill_amount, 150.0)
        # Ringkasan PO tidak berubah (regresi ringan).
        self.assertEqual(readiness.status, "READY")

    def test_tanpa_vendor_bill_status_none(self):
        transport = FakeTransport(
            orders=[{"id": 1, "name": "P00012", "state": "purchase"}],
            lines=[self.po_line(11, 601, 12.0)],
            bills=[],
        )

        readiness = self.compute(transport, self.line)

        self.assertEqual(readiness.vendor_bill_status, "NONE")
        self.assertEqual(readiness.vendor_bill_ids, [])
        self.assertEqual(readiness.vendor_bill_amount, 0.0)

    def test_multi_vendor_bill_agregat_ambil_tertinggi(self):
        transport = FakeTransport(
            orders=[{"id": 1, "name": "P00012", "state": "purchase"}],
            lines=[self.po_line(11, 601, 4.0)],
            bills=[
                {
                    "id": 901,
                    "invoice_origin": "P00012",
                    "state": "draft",
                    "amount_total": 50.0,
                },
                {
                    "id": 902,
                    "invoice_origin": "P00012",
                    "state": "posted",
                    "amount_total": 70.0,
                },
            ],
        )

        readiness = self.compute(transport, self.line)

        self.assertEqual(readiness.vendor_bill_status, "POSTED")  # tertinggi
        self.assertEqual(readiness.vendor_bill_ids, [901, 902])
        self.assertEqual(readiness.vendor_bill_amount, 120.0)

    def test_vendor_bill_invoice_origin_lain_diabaikan(self):
        transport = FakeTransport(
            orders=[{"id": 1, "name": "P00012", "state": "purchase"}],
            lines=[self.po_line(11, 601, 4.0)],
            bills=[
                {
                    "id": 903,
                    "invoice_origin": "P99999",  # bukan PO yang match
                    "state": "posted",
                    "amount_total": 10.0,
                }
            ],
        )

        readiness = self.compute(transport, self.line)

        self.assertEqual(readiness.vendor_bill_status, "NONE")
        self.assertEqual(readiness.vendor_bill_ids, [])

    def test_vendor_bill_cancel_dianggap_none(self):
        transport = FakeTransport(
            orders=[{"id": 1, "name": "P00012", "state": "purchase"}],
            lines=[self.po_line(11, 601, 4.0)],
            bills=[
                {
                    "id": 904,
                    "invoice_origin": "P00012",
                    "state": "cancel",
                    "amount_total": 99.0,
                }
            ],
        )

        readiness = self.compute(transport, self.line)

        self.assertEqual(readiness.vendor_bill_status, "NONE")
        self.assertEqual(readiness.vendor_bill_ids, [])
        self.assertEqual(readiness.vendor_bill_amount, 0.0)

    def test_compute_batch_mencatat_error_tanpa_menghentikan_batch(self):
        transport = FakeTransport(error=RuntimeError("odoo mati"))

        with self.assertLogs(
            "integrations.erp_sync.services.material_readiness", level="ERROR"
        ):
            result = MaterialReadinessService(transport=transport).compute_batch(
                [self.line, self.line_no_bom]
            )

        self.assertEqual(result["processed"], 0)
        self.assertEqual(result["errors"], 2)
        self.assertEqual(MaterialReadiness.objects.count(), 0)

    def test_compute_batch_fetch_po_sekali_untuk_tiga_order_line(self):
        # Tiga OrderLine produk FG-001 → PO cukup di-fetch SEKALI per batch.
        line_b = OrderLine.objects.create(order=self.order, product=self.fg, qty=1)
        line_c = OrderLine.objects.create(order=self.order, product=self.fg, qty=2)
        transport = FakeTransport(
            orders=[{"id": 1, "state": "purchase"}],
            lines=[self.po_line(11, 601, 12.0)],
        )

        result = MaterialReadinessService(transport=transport).compute_batch(
            OrderLine.objects.filter(pk__in=[self.line.pk, line_b.pk, line_c.pk])
        )

        self.assertEqual(result["processed"], 3)
        self.assertEqual(result["ready"], 3)
        # 1x fetch header + 1x fetch baris (bukan 2x per OrderLine).
        self.assertEqual(len([c for c in transport.calls if c[0] == "orders"]), 1)
        self.assertEqual(len([c for c in transport.calls if c[0] == "lines"]), 1)

    def test_bonus_compute_single_tetap_fetch_sendiri(self):
        """``compute(order_line)`` single: signature & perilaku fetch tetap."""
        transport = FakeTransport(orders=[], lines=[])

        MaterialReadinessService(transport=transport).compute(self.line)

        self.assertEqual(len([c for c in transport.calls if c[0] == "orders"]), 1)
        self.assertEqual(len([c for c in transport.calls if c[0] == "lines"]), 0)
