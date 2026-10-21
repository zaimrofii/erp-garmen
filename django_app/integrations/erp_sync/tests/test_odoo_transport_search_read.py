"""Regression PRA-0B.1 — `OdooTransport.search_read` publik + tracking produk.

Bug asli: ``fetch_product_tracking`` memanggil ``reader.search_read(...)``,
padahal ``OdooTransport`` hanya punya ``_search_read`` → ``AttributeError``
(warning saat commit, tracking produk tidak terbaca).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from apps_industry.garment.services.inventory_adjustment_services import (
    fetch_product_tracking,
)
from integrations.erp_sync.transport.odoo_transport import OdooTransport


class OdooTransportSearchReadTests(SimpleTestCase):
    def test_delegasi_ke_search_read_internal(self):
        transport = OdooTransport()
        rows = [{"id": 1}, {"id": 2}]

        with patch.object(transport, "_search_read", return_value=rows) as inner:
            result = transport.search_read(
                "product.product", [["id", "=", 1]], ["id"]
            )

        self.assertEqual(result, rows)
        inner.assert_called_once_with("product.product", [["id", "=", 1]], ["id"])

    def test_limit_memotong_hasil(self):
        transport = OdooTransport()

        with patch.object(transport, "_search_read", return_value=[{"id": 1}, {"id": 2}]):
            result = transport.search_read(
                "product.product", [["id", "=", 1]], ["id"], limit=1
            )

        self.assertEqual(result, [{"id": 1}])

    def test_fetch_product_tracking_memakai_search_read(self):
        calls: dict = {}

        class FakeTransport:
            def search_read(self, model, domain, fields, limit=None):
                calls.update(model=model, domain=domain, fields=fields, limit=limit)
                return [{"tracking": "lot"}]

        result = fetch_product_tracking(
            SimpleNamespace(odoo_id=7), transport=FakeTransport()
        )

        self.assertEqual(result, "lot")
        self.assertEqual(calls["model"], "product.product")
        self.assertEqual(calls["limit"], 1)
