"""Regression PRA-0B.1 — push inventory adjustment pada quant EXISTING.

Bug asli: adapter selalu mengirim ``product_id``/``location_id`` saat ``write()``
quant; Odoo 17 menolak (``UserError: Quant's editing is restricted``) sehingga
adjustment kedua dst. selalu FAILED. Field itu hanya boleh saat CREATE.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from integrations.erp_sync.adapters.odoo import OdooAdapter

PAYLOAD = {
    "ref": "ADJ-TEST-0001",
    "product_odoo_id": 7,
    "location_odoo_id": 8,
    "qty_delta": 10,
    "inventory_name": "ADJ-TEST-0001 uji",
}


class FakeClient:
    def __init__(self, quants):
        self.quants = quants
        self.calls: list[tuple] = []

    def execute_kw(self, model, method, args, kwargs=None):
        self.calls.append((model, method, args, kwargs or {}))
        if model == "stock.quant" and method == "search_read":
            return self.quants
        if model == "stock.quant" and method == "create":
            return [150]
        if model == "stock.move" and method == "search_read":
            return [{"id": 547, "name": PAYLOAD["inventory_name"]}]
        return True


class InventoryAdjustmentQuantTests(SimpleTestCase):
    def run_push(self, quants):
        client = FakeClient(quants)
        response = OdooAdapter(client=client).push_inventory_adjustment(PAYLOAD)
        return client, response

    def test_write_quant_existing_tanpa_product_location(self):
        client, response = self.run_push([{"id": 150, "quantity": 5.0}])

        write = next(call for call in client.calls if call[1] == "write")
        values = write[2][1]

        self.assertTrue(response.ok)
        self.assertEqual(values, {"inventory_quantity": 15.0})
        self.assertNotIn("product_id", values)
        self.assertNotIn("location_id", values)

    def test_create_quant_baru_menyertakan_product_location(self):
        client, response = self.run_push([])

        create = next(call for call in client.calls if call[1] == "create")
        values = create[2][0]

        self.assertTrue(response.ok)
        self.assertEqual(values["product_id"], 7)
        self.assertEqual(values["location_id"], 8)
        self.assertEqual(values["inventory_quantity"], 10.0)
        self.assertEqual(str(response.erp_id), "547")
