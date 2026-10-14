#!/usr/bin/env python
"""Seed minimal (fixture esensial) untuk uji integrasi Django ↔ Odoo.

Sesuai FRAMEWORK_JSONRPC_VALIDATION.md v2.1 §5.1.

Pola **upsert**: `search` dulu → kalau ada `write`, kalau tidak ada `create`.

Data yang dibuat:

1. ``uom.uom``         "PCS"              (⚠️ model = ``uom.uom``, BUKAN ``product.uom``)
2. ``product.product`` "KAIN-COTTON-30S"  (RM / kain)
3. ``product.product`` "KTS-EXPORT-L"     (FG / kaos export)
4. ``res.partner``     "PT Buyer Export"  (customer)
5. ``stock.location``  "WH/WIP" & "WH/FG" (lokasi internal)

Penyesuaian Odoo 17 (deviasi kecil dari §5.1 — wajib agar benar-benar jalan):

* "PCS" dibuat di **kategori UoM khusus** (bukan ``category_id=1``): kategori
  "Unit" sudah punya UoM reference ("Units") sehingga Odoo menolak dengan
  ``Fault 2: UoM category Unit should only have one reference unit of measure.``
* ``stock.location`` diberi **parent warehouse "WH"** supaya ``complete_name``
  benar-benar ``WH/WIP`` / ``WH/FG`` dan upsert (domain ``complete_name``)
  menjadi idempotent.

Kredensial dibaca dari environment (tidak ada hardcode):

* ``ODOO_URL``, ``ODOO_DB``, ``ODOO_USER_ID``, ``ODOO_API_KEY``

Cara jalan (di dalam container):

    docker compose exec django python tools/fixtures/seed_minimal.py

Catatan: butuh hak write/create pada ``uom.uom``, ``product.product``,
``res.partner`` dan ``stock.location``. Bila user Odoo hanya read-only untuk
model master, script berhenti dengan ``xmlrpc.client.Fault`` (Odoo Fault 4).
"""

from __future__ import annotations

import os
import xmlrpc.client

URL = os.environ["ODOO_URL"]
DB = os.environ["ODOO_DB"]
UID = int(os.environ["ODOO_USER_ID"])
PWD = os.environ["ODOO_API_KEY"]

models = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")


def upsert(model, domain, values):
    """Cari record dengan `domain`; ada → `write`, tidak ada → `create`.

    Kembalikan id record (integer).
    """
    ids = models.execute_kw(DB, UID, PWD, model, "search", [domain])
    if ids:
        models.execute_kw(DB, UID, PWD, model, "write", [[ids[0]], values])
        return ids[0]
    return models.execute_kw(DB, UID, PWD, model, "create", [values])


def main():
    # 1. UoM PCS — FIX: model adalah uom.uom (BUKAN product.uom).
    #    Odoo 17: kategori "Unit" sudah punya reference ("Units"), jadi PCS
    #    harus dibuat di kategori sendiri agar tidak kena Fault 2.
    cat_id = upsert("uom.category", [("name", "=", "PCS")], {"name": "PCS"})
    uom_id = upsert(
        "uom.uom",
        [("name", "=", "PCS")],
        {"name": "PCS", "category_id": cat_id, "factor": 1.0},
    )

    # 2. Kain (RM)
    kain_id = upsert(
        "product.product",
        [("default_code", "=", "KAIN-COTTON-30S")],
        {
            "default_code": "KAIN-COTTON-30S",
            "name": "Kain Cotton 30s",
            "type": "product",
            "uom_id": uom_id,
            "uom_po_id": uom_id,
        },
    )

    # 3. Kaos Export (FG)
    kaos_id = upsert(
        "product.product",
        [("default_code", "=", "KTS-EXPORT-L")],
        {
            "default_code": "KTS-EXPORT-L",
            "name": "Kaos Export L",
            "type": "product",
            "uom_id": uom_id,
            "uom_po_id": uom_id,
        },
    )

    # 4. Customer
    cust_id = upsert(
        "res.partner",
        [("name", "=", "PT Buyer Export")],
        {"name": "PT Buyer Export", "customer_rank": 1},
    )

    # 5. Lokasi WIP + FG — diberi parent warehouse "WH" supaya complete_name
    #    jadi "WH/WIP"/"WH/FG" (cocok domain di atas → upsert idempotent).
    wh_ids = models.execute_kw(
        DB, UID, PWD, "stock.location", "search", [[("complete_name", "=", "WH")]]
    )
    wh_parent = wh_ids[0] if wh_ids else False

    loc_wip = upsert(
        "stock.location",
        [("complete_name", "=", "WH/WIP")],
        {"name": "WIP", "usage": "internal", "location_id": wh_parent},
    )
    loc_fg = upsert(
        "stock.location",
        [("complete_name", "=", "WH/FG")],
        {"name": "FG", "usage": "internal", "location_id": wh_parent},
    )

    print(
        f"✅ Fixture OK: uom_cat={cat_id} uom={uom_id} kain={kain_id} "
        f"kaos={kaos_id} cust={cust_id} wip={loc_wip} fg={loc_fg}"
    )


if __name__ == "__main__":
    main()
