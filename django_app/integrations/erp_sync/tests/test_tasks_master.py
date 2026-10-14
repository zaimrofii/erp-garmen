"""Test task master sync (`tasks_master`) — transport di-mock, tanpa jaringan/Odoo.

Cakupan:

* **happy path per task** (transport mengembalikan 2 baris) → ``created=2, updated=0``;
* **empty response per task** → ``created=0, updated=0``;
* **idempotensi**: panggil task 2x data sama → kedua kali ``updated=2, created=0``;
* **fallback code** ``ODOO-{id}`` untuk baris tanpa kode natural;
* **BOM + BOMLine** (FK) dan factory ``get_transport``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from integrations.erp_sync.tasks_master import (
    sync_master_boms,
    sync_master_currencies,
    sync_master_journals,
    sync_master_locations,
    sync_master_partners,
    sync_master_products,
    sync_master_taxes,
    sync_master_uoms,
    sync_master_warehouses,
)
from integrations.erp_sync.transport import OdooTransport, get_transport
from master.models import (
    BOM,
    BOMLine,
    Currency,
    Journal,
    Location,
    Partner,
    Product,
    Tax,
    UoM,
    Warehouse,
)

GET_TRANSPORT = "integrations.erp_sync.tasks_master.get_transport"

FETCH_METHODS = (
    "fetch_products",
    "fetch_boms",
    "fetch_bom_lines",
    "fetch_partners",
    "fetch_locations",
    "fetch_taxes",
    "fetch_uoms",
    "fetch_warehouses",
    "fetch_journals",
    "fetch_currencies",
)

PRODUCT_ROWS = [
    {"id": 100, "default_code": "KTS-EXPORT-L", "name": "Kaos Export L", "uom_id": [33, "PCS"], "categ_id": [1, "All"], "active": True, "product_tmpl_id": [10, "Kaos Export L"]},
    {"id": 99, "default_code": "KAIN-COTTON-30S", "name": "Kain Cotton 30s", "uom_id": [33, "PCS"], "categ_id": [1, "All"], "active": True, "product_tmpl_id": [9, "Kain Cotton 30s"]},
]
# `product_tmpl_id` = id product.template (BEDA dari product.product.id) -> BOM
# di-resolve lewat `Product.odoo_tmpl_id`.
BOM_ROWS = [
    {"id": 7, "code": "BOM-KTS-L", "product_tmpl_id": [10, "Kaos Export L"], "product_qty": 1.0, "product_uom_id": [33, "PCS"], "type": "normal"},
    {"id": 8, "code": "BOM-KTS-M", "product_tmpl_id": [10, "Kaos Export L"], "product_qty": 1.0, "product_uom_id": [33, "PCS"], "type": "normal"},
]
BOM_LINE_ROWS = [
    {"id": 70, "bom_id": [7, "BOM-KTS-L"], "product_id": [99, "Kain Cotton 30s"], "product_qty": 1.5, "product_uom_id": [33, "PCS"]},
    {"id": 71, "bom_id": [7, "BOM-KTS-L"], "product_id": [99, "Kain Cotton 30s"], "product_qty": 0.5, "product_uom_id": [33, "PCS"]},
]
PARTNER_ROWS = [
    {
        "id": 51,
        "name": "PT Buyer Export",
        "vat": "01.234.567.8-901.000",
        "email": "buyer@example.com",
        "phone": "+62 812",
        "street": "Jl. Merdeka 10",
        "street2": "Blok C",
        "city": "Bandung",
        "is_company": True,
        "customer_rank": 1,
        "supplier_rank": 0,
        "active": True,
    },
    {
        "id": 52,
        "name": "PT Supplier Kain",
        "vat": False,
        "email": "supplier@example.com",
        "phone": False,
        "street": False,
        "street2": False,
        "city": False,
        "is_company": True,
        "customer_rank": 0,
        "supplier_rank": 1,
        "active": True,
    },
]
LOCATION_ROWS = [
    {
        "id": 53,
        "name": "WIP",
        "complete_name": "WH/WIP",
        "usage": "internal",
        "location_id": [7, "WH"],
        "warehouse_id": [1, "YourCompany"],
        "active": True,
    },
    {
        "id": 54,
        "name": "FG",
        "complete_name": "WH/FG",
        "usage": "internal",
        "location_id": [7, "WH"],
        "warehouse_id": [1, "YourCompany"],
        "active": True,
    },
]
TAX_ROWS = [
    {"id": 5, "name": "PPN 11%", "amount": 11.0, "type_tax_use": "sale"},
    {"id": 6, "name": "PPN 11% (Beli)", "amount": 11.0, "type_tax_use": "purchase"},
]
UOM_ROWS = [
    {"id": 33, "name": "PCS", "category_id": [10, "PCS"], "factor": 1.0},
    {"id": 1, "name": "Units", "category_id": [1, "Unit"], "factor": 1.0},
]
WAREHOUSE_ROWS = [
    {"id": 1, "name": "YourCompany", "code": "WH"},
    {"id": 2, "name": "Gudang 2", "code": "WH2"},
]
JOURNAL_ROWS = [
    {"id": 7, "name": "Sales Journal", "code": "SALE", "type": "sale"},
    {"id": 8, "name": "Purchase Journal", "code": "PURCH", "type": "purchase"},
]
CURRENCY_ROWS = [
    {"id": 12, "name": "Rupiah", "symbol": "Rp", "rate": 1.0},
    {"id": 13, "name": "US Dollar", "symbol": "$", "rate": 0.00006},
]


class SyncMasterTaskBase(TestCase):
    """Helper: jalankan task dengan transport di-mock (semua ``fetch_*`` → ``[]``)."""

    def run_task(self, task, **fetches):
        transport = MagicMock()
        for method in FETCH_METHODS:
            getattr(transport, method).return_value = []
        for method, rows in fetches.items():
            getattr(transport, method).return_value = rows

        with patch(GET_TRANSPORT, return_value=transport):
            result = task.apply(kwargs={"since": None}).get()

        return result, transport


class SyncMasterHappyPathTests(SyncMasterTaskBase):
    """Happy path per task: transport mengembalikan 2 baris → created=2, updated=0."""

    def test_products(self):
        result, _ = self.run_task(sync_master_products, fetch_products=PRODUCT_ROWS)

        self.assertEqual(result, {"created": 2, "updated": 0, "skipped": 0})
        self.assertEqual(Product.objects.count(), 2)

    def test_boms(self):
        # BOM di-resolve via `odoo_tmpl_id` (id product.template), bukan odoo_id.
        Product.objects.create(
            code="KTS-EXPORT-L", name="Kaos Export L", odoo_id=100, odoo_tmpl_id=10
        )

        result, _ = self.run_task(sync_master_boms, fetch_boms=BOM_ROWS)

        self.assertEqual(result, {"created": 2, "updated": 0, "skipped": 0})
        self.assertEqual(BOM.objects.count(), 2)

    def test_partners(self):
        result, _ = self.run_task(sync_master_partners, fetch_partners=PARTNER_ROWS)

        self.assertEqual(result, {"created": 2, "updated": 0, "skipped": 0})
        self.assertEqual(Partner.objects.count(), 2)

    def test_partners_memeta_kontak_peran_dan_alamat(self):
        """H1.6 — pull memetakan kontak, alamat (street+street2), NPWP & peran (rank)."""
        self.run_task(sync_master_partners, fetch_partners=PARTNER_ROWS)

        customer = Partner.objects.get(odoo_id=51)
        self.assertEqual(customer.email, "buyer@example.com")
        self.assertEqual(customer.phone, "+62 812")
        self.assertEqual(customer.city, "Bandung")
        self.assertEqual(customer.address, "Jl. Merdeka 10\nBlok C")  # street + street2
        self.assertEqual(customer.npwp, "012345678901000")  # vat → digit
        self.assertIs(customer.is_customer, True)  # customer_rank > 0
        self.assertIs(customer.is_vendor, False)
        self.assertEqual(customer.customer_rank, 1)

        vendor = Partner.objects.get(odoo_id=52)
        self.assertEqual(vendor.address, "")  # street/street2 False → kosong
        self.assertEqual(vendor.npwp, "")
        self.assertIs(vendor.is_customer, False)  # customer_rank = 0
        self.assertIs(vendor.is_vendor, True)  # supplier_rank > 0
        self.assertEqual(vendor.supplier_rank, 1)

    def test_locations(self):
        result, _ = self.run_task(sync_master_locations, fetch_locations=LOCATION_ROWS)

        self.assertEqual(result, {"created": 2, "updated": 0, "skipped": 0})
        self.assertEqual(Location.objects.count(), 2)

    def test_locations_memeta_usage_parent_warehouse(self):
        """H1.4 — pull memetakan ``usage``/``parent``/``warehouse``/``is_active``.

        Induk & gudang di-resolve lewat ``odoo_id`` (7 & 1); kalau belum tersinkron
        → ``None`` (tidak menahan barisnya) — diuji dua kali: tanpa & dengan master.
        """
        # 1) induk & gudang belum tersinkron → baris tetap dibuat, FK null.
        self.run_task(sync_master_locations, fetch_locations=LOCATION_ROWS)
        location = Location.objects.get(odoo_id=53)
        self.assertIsNone(location.parent)
        self.assertIsNone(location.warehouse)
        self.assertEqual(location.usage, Location.Usage.INTERNAL)
        self.assertTrue(location.is_active)

        # 2) master tersedia → FK terisi (idempotent: update, bukan duplikat).
        wip_parent = Location.objects.create(
            odoo_id=7, code="WH", name="WH", usage=Location.Usage.VIEW
        )
        warehouse = Warehouse.objects.create(odoo_id=1, code="WH", name="YourCompany")

        result, _ = self.run_task(sync_master_locations, fetch_locations=LOCATION_ROWS)

        self.assertEqual(result, {"created": 0, "updated": 2, "skipped": 0})
        location.refresh_from_db()
        self.assertEqual(location.parent, wip_parent)
        self.assertEqual(location.warehouse, warehouse)
        self.assertEqual(Location.objects.count(), 3)  # 2 tarikan + 1 induk manual

    def test_taxes(self):
        result, _ = self.run_task(sync_master_taxes, fetch_taxes=TAX_ROWS)

        self.assertEqual(result, {"created": 2, "updated": 0, "skipped": 0})
        # H3.6 — `master.0019` menyemai 3 pajak default MES semua tanpa `odoo_id`,
        # jadi hitungan dibatasi ke baris hasil pull; `amount` kini ikut dipetakan.
        pulled = Tax.objects.filter(odoo_id__isnull=False)
        self.assertEqual(pulled.count(), 2)
        self.assertEqual(sorted(pulled.values_list("name", flat=True)), ["PPN 11%", "PPN 11% (Beli)"])

    def test_uoms(self):
        result, _ = self.run_task(sync_master_uoms, fetch_uoms=UOM_ROWS)

        self.assertEqual(result, {"created": 2, "updated": 0, "skipped": 0})
        self.assertEqual(UoM.objects.count(), 2)

    def test_warehouses(self):
        result, _ = self.run_task(
            sync_master_warehouses, fetch_warehouses=WAREHOUSE_ROWS
        )

        self.assertEqual(result, {"created": 2, "updated": 0, "skipped": 0})
        self.assertEqual(Warehouse.objects.count(), 2)

    def test_journals(self):
        result, _ = self.run_task(sync_master_journals, fetch_journals=JOURNAL_ROWS)

        self.assertEqual(result, {"created": 2, "updated": 0, "skipped": 0})
        self.assertEqual(Journal.objects.count(), 2)

    def test_currencies(self):
        result, _ = self.run_task(sync_master_currencies, fetch_currencies=CURRENCY_ROWS)

        self.assertEqual(result, {"created": 2, "updated": 0, "skipped": 0})
        self.assertEqual(Currency.objects.count(), 2)


class SyncMasterEmptyTests(SyncMasterTaskBase):
    """Empty response per task → created=0, updated=0."""

    def test_products(self):
        result, _ = self.run_task(sync_master_products)
        self.assertEqual(result, {"created": 0, "updated": 0, "skipped": 0})

    def test_boms(self):
        result, _ = self.run_task(sync_master_boms)
        self.assertEqual(result, {"created": 0, "updated": 0, "skipped": 0})

    def test_partners(self):
        result, _ = self.run_task(sync_master_partners)
        self.assertEqual(result, {"created": 0, "updated": 0, "skipped": 0})

    def test_locations(self):
        result, _ = self.run_task(sync_master_locations)
        self.assertEqual(result, {"created": 0, "updated": 0, "skipped": 0})

    def test_taxes(self):
        result, _ = self.run_task(sync_master_taxes)
        self.assertEqual(result, {"created": 0, "updated": 0, "skipped": 0})

    def test_uoms(self):
        result, _ = self.run_task(sync_master_uoms)
        self.assertEqual(result, {"created": 0, "updated": 0, "skipped": 0})

    def test_warehouses(self):
        result, _ = self.run_task(sync_master_warehouses)
        self.assertEqual(result, {"created": 0, "updated": 0, "skipped": 0})

    def test_journals(self):
        result, _ = self.run_task(sync_master_journals)
        self.assertEqual(result, {"created": 0, "updated": 0, "skipped": 0})

    def test_currencies(self):
        result, _ = self.run_task(sync_master_currencies)
        self.assertEqual(result, {"created": 0, "updated": 0, "skipped": 0})


class SyncMasterIdempotencyTests(SyncMasterTaskBase):
    """Panggil task 2x dengan data sama → kedua kali ``updated``, ``created=0``."""

    def test_panggil_dua_kali_data_sama_jadi_updated(self):
        transport = MagicMock()
        for method in FETCH_METHODS:
            getattr(transport, method).return_value = []
        transport.fetch_products.return_value = PRODUCT_ROWS

        with patch(GET_TRANSPORT, return_value=transport):
            first = sync_master_products.apply(kwargs={"since": None}).get()
            second = sync_master_products.apply(kwargs={"since": None}).get()

        self.assertEqual(first, {"created": 2, "updated": 0, "skipped": 0})
        self.assertEqual(second, {"created": 0, "updated": 2, "skipped": 0})
        self.assertEqual(Product.objects.count(), 2)  # tidak bertambah


class SyncMasterCodeFallbackTests(SyncMasterTaskBase):
    """Baris tanpa kode natural → ``code = f"ODOO-{id}"`` (cegah IntegrityError)."""

    def test_uom_tanpa_code_pakai_fallback_odoo_id(self):
        rows = [{"id": 33, "name": "Pieces", "category_id": [1, "Unit"], "factor": 1.0}]

        result, _ = self.run_task(sync_master_uoms, fetch_uoms=rows)

        self.assertEqual(result["created"], 1)
        self.assertEqual(UoM.objects.get(odoo_id=33).code, "ODOO-33")

    def test_product_default_code_kosong_pakai_fallback(self):
        rows = [
            {"id": 123, "default_code": False, "name": "Tanpa Kode", "uom_id": [1, "Units"], "categ_id": [1, "All"], "active": True}
        ]

        self.run_task(sync_master_products, fetch_products=rows)

        self.assertEqual(Product.objects.get(odoo_id=123).code, "ODOO-123")


class SyncMasterBomLineTests(SyncMasterTaskBase):
    """``sync_master_boms`` menyimpan BOM **dan** BOMLine (FK ke BOM)."""

    def test_bom_dan_lines_tersimpan_dengan_fk(self):
        odoo_product = Product.objects.create(
            code="KTS-EXPORT-L", name="Kaos Export L", odoo_id=100, odoo_tmpl_id=10
        )
        material = Product.objects.create(
            code="KAIN-COTTON-30S", name="Kain Cotton 30s", odoo_id=99, odoo_tmpl_id=9
        )

        result, _ = self.run_task(
            sync_master_boms, fetch_boms=BOM_ROWS, fetch_bom_lines=BOM_LINE_ROWS
        )

        self.assertEqual(result, {"created": 4, "updated": 0, "skipped": 0})
        bom = BOM.objects.get(odoo_id=7)
        self.assertEqual(bom.product, odoo_product)
        self.assertEqual(bom.lines.count(), 2)
        self.assertEqual(bom.lines.first().product, material)

    def test_bom_line_tanpa_bom_tersinkron_dilewati(self):
        # `bom` wajib ada (FK tidak nullable) -> line tanpa BOM tetap di-skip.
        result, _ = self.run_task(sync_master_boms, fetch_bom_lines=BOM_LINE_ROWS)

        self.assertEqual(result, {"created": 0, "updated": 0, "skipped": 2})


class SyncMasterBomMappingTests(SyncMasterTaskBase):
    """Mapping id Odoo: BOM pakai ``odoo_tmpl_id``, komponen pakai ``odoo_id``."""

    def test_bom_product_tmpl_id_match_mengisi_product(self):
        product = Product.objects.create(
            code="KTS-EXPORT-L", name="Kaos Export L", odoo_id=100, odoo_tmpl_id=10
        )

        result, _ = self.run_task(sync_master_boms, fetch_boms=BOM_ROWS)

        self.assertEqual(result, {"created": 2, "updated": 0, "skipped": 0})
        self.assertEqual(BOM.objects.get(odoo_id=7).product, product)

    def test_bom_line_product_id_match_odoo_id_mengisi_product(self):
        Product.objects.create(
            code="KTS-EXPORT-L", name="Kaos Export L", odoo_id=100, odoo_tmpl_id=10
        )
        material = Product.objects.create(
            code="KAIN-COTTON-30S", name="Kain Cotton 30s", odoo_id=99, odoo_tmpl_id=9
        )

        result, _ = self.run_task(
            sync_master_boms, fetch_boms=BOM_ROWS, fetch_bom_lines=BOM_LINE_ROWS
        )

        self.assertEqual(result["skipped"], 0)
        self.assertEqual(BOMLine.objects.get(odoo_id=70).product, material)

    def test_bom_template_tidak_match_disimpan_tanpa_product(self):
        result, _ = self.run_task(sync_master_boms, fetch_boms=BOM_ROWS)  # tanpa Product

        self.assertEqual(result, {"created": 2, "updated": 0, "skipped": 2})
        self.assertIsNone(BOM.objects.get(odoo_id=7).product)


class GetTransportFactoryTests(TestCase):
    """Factory ``get_transport()`` (mirror ``get_adapter``) — pola & fail-safe."""

    @override_settings(ERP_ADAPTER="odoo")
    def test_odoo_membangun_transport_dengan_client(self):
        transport = get_transport()

        self.assertIsInstance(transport, OdooTransport)
        self.assertIsNotNone(transport.client)
        transport.close()

    @override_settings(ERP_ADAPTER="null")
    def test_vendor_tanpa_transport_fail_safe_client_none(self):
        transport = get_transport()

        self.assertIsNone(transport.client)
        self.assertEqual(transport.fetch_products(), [])

    @override_settings(
        ERP_ADAPTER="odoo", ODOO_URL="", ODOO_DB="", ODOO_USER="", ODOO_API_KEY=""
    )
    def test_kredensial_kosong_fail_safe_client_none(self):
        self.assertIsNone(get_transport().client)
