"""Test NullAdapter (Fase 4.1): two-stage push, health check, erp_id unik, transport no-op."""

from __future__ import annotations

from django.test import SimpleTestCase

from integrations.erp_sync.adapters.base import ERPAdapter, ERPResponse, ERPTransport
from integrations.erp_sync.adapters.null import NullAdapter

PAYLOAD = {"ref": "WO-1", "qty": 10, "product_ref": "KAOS-PUTIH"}


class NullAdapterTests(SimpleTestCase):
    """NullAdapter harus lolos kontrak bisnis & transport tanpa I/O."""

    def setUp(self):
        self.adapter = NullAdapter()

    def test_implement_kedua_kontrak(self):
        self.assertIsInstance(self.adapter, ERPAdapter)
        self.assertIsInstance(self.adapter, ERPTransport)
        self.assertEqual(self.adapter.name, "null")

    def test_push_wip_issue_selalu_ok(self):
        response = self.adapter.push_wip_issue(PAYLOAD)

        self.assertIsInstance(response, ERPResponse)
        self.assertTrue(response.ok)
        self.assertEqual(response.stage, "WIP")
        self.assertEqual(response.ref, "WO-1")
        self.assertIsNone(response.error)
        self.assertEqual(response.raw["payload"]["qty"], 10)

    def test_push_fg_receipt_stage_fg(self):
        response = self.adapter.push_fg_receipt(PAYLOAD)

        self.assertTrue(response.ok)
        self.assertEqual(response.stage, "FG")
        self.assertEqual(response.ref, "WO-1")

    def test_push_tanpa_ref_tidak_error(self):
        response = self.adapter.push_wip_issue({"qty": 1})

        self.assertTrue(response.ok)
        self.assertEqual(response.ref, "")

    def test_push_tanpa_payload_tidak_error(self):
        response = self.adapter.push_fg_receipt(None)  # type: ignore[arg-type]

        self.assertTrue(response.ok)
        self.assertEqual(response.raw, {"payload": {}})

    def test_erp_id_unik_dan_berprefix_null(self):
        ids = {self.adapter.push_wip_issue({"qty": 1}).erp_id for _ in range(5)}

        self.assertEqual(len(ids), 5)
        for erp_id in ids:
            self.assertTrue(str(erp_id).startswith("NULL-"))

    def test_riwayat_push_dicatat(self):
        self.adapter.push_wip_issue({"qty": 1})
        self.adapter.push_fg_receipt({"qty": 1})

        self.assertEqual([r.stage for r in self.adapter.pushed], ["WIP", "FG"])

    def test_health_check_true(self):
        self.assertTrue(self.adapter.health_check())

    def test_transport_lama_tetap_no_op(self):
        self.assertEqual(self.adapter.login(), 1)
        self.assertEqual(self.adapter.search_read("product.product"), [])
        self.assertEqual(self.adapter.create("stock.move", {"qty": 1}), 999)
        self.assertTrue(self.adapter.write("stock.move", [1], {"qty": 2}))
        self.assertIsNone(self.adapter.call("stock.move", "check"))
        self.assertIsNone(self.adapter.close())

    def test_as_dict_json_safe(self):
        data = self.adapter.push_wip_issue({"qty": 3, "ref": "WO-9"}).as_dict()

        self.assertEqual(
            set(data), {"ok", "erp_id", "error", "stage", "ref", "raw"}
        )
        self.assertEqual(data["stage"], "WIP")
        self.assertEqual(data["ref"], "WO-9")
        self.assertTrue(data["ok"])
