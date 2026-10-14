#!/usr/bin/env python
"""Probe Odoo sekali jalan — Odoo 17 verified.

Script ini adalah **Fase 1 (PROBE)** dari kerangka validasi JSON-RPC
Django ↔ Odoo (lihat ``docs/integrations/framework_jsonrpc_validation.md`` §3.1).
Tujuannya mengunci nama field Odoo sebelum contract per alur ditulis:

1. Autentikasi ke Odoo lewat ``xmlrpc/2/common`` lalu cocokkan uid dengan
   ``ODOO_USER_ID``.
2. ``fields_get`` untuk model yang BENAR-BENAR dipakai di alur kritis.
3. ``check_access_rights`` (read/write/create) untuk mendeteksi masalah akses.
4. Tulis kamus field ke ``tools/odoo_probe/snapshot_schema.json``.

Kredensial dibaca dari environment (tidak ada kredensial hardcode):

* ``ODOO_URL``      — base URL Odoo (mis. ``http://odoo:8069``)
* ``ODOO_DB``       — nama database
* ``ODOO_USER``     — login user (mis. ``api_bot``)
* ``ODOO_API_KEY``  — API key / password user
* ``ODOO_USER_ID``  — uid yang diharapkan (dipakai untuk verifikasi login)

Catatan Odoo 17:

* Model UoM adalah ``uom.uom`` (**BUKAN** ``product.uom``).
* ``stock.scrap`` deprecated → pakai ``stock.move.line`` dengan ``is_scrap=true``.

Cara jalan (dari folder ``django_app``):

    python tools/odoo_probe/probe.py

Output:

* ``tools/odoo_probe/snapshot_schema.json`` — kamus field Odoo.
* Ringkasan per model (jumlah field) di stdout + daftar access issue.
"""

from __future__ import annotations

import json
import os
import xmlrpc.client
from pathlib import Path

#: Lokasi output snapshot. Di-anchor ke folder script (bukan CWD) supaya hasilnya
#: selalu mendarat di ``tools/odoo_probe/snapshot_schema.json``.
SNAPSHOT_PATH = Path(__file__).resolve().parent / "snapshot_schema.json"

#: Model yang BENAR-BENAR dipakai di alur kritis.
#: VERIFIED: ``uom.uom`` (bukan ``product.uom``), ``stock.move.line`` untuk scrap.
MODELS = [
    # Master
    "product.product", "product.template", "uom.uom",
    "mrp.bom", "mrp.bom.line",
    "res.partner", "stock.location", "stock.picking.type",
    # Order
    "sale.order", "sale.order.line",
    # Transaksi keluar
    "stock.move", "stock.move.line",
    # Invoice (opsional, untuk alur customer invoice)
    "account.move", "account.move.line",
]

#: Atribut field yang diambil dari ``fields_get``.
FIELD_ATTRIBUTES = ["string", "type", "relation", "required", "readonly"]

#: Operasi yang dicek hak aksesnya lewat ``check_access_rights``.
ACCESS_OPS = ("read", "write", "create")


def main() -> None:
    """Auth + fields_get + access check + tulis snapshot."""
    url = os.environ["ODOO_URL"]
    db = os.environ["ODOO_DB"]
    user = os.environ["ODOO_USER"]
    pwd = os.environ["ODOO_API_KEY"]
    uid = int(os.environ["ODOO_USER_ID"])

    common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
    auth_uid = common.authenticate(db, user, pwd, {})
    assert auth_uid == uid, f"❌ UID mismatch: {auth_uid} != {uid}"
    print(f"✅ Auth OK uid={auth_uid} | Odoo {common.version()['server_version']}")

    models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")
    snapshot: dict[str, dict] = {}
    access_issues: list[tuple[str, str, str]] = []

    for model in MODELS:
        try:
            fields = models.execute_kw(
                db, uid, pwd, model, "fields_get",
                [], {"attributes": FIELD_ATTRIBUTES},
            )
            snapshot[model] = fields

            # Cek hak akses per operasi (raise_exception=True → fault kalau tidak boleh).
            for op in ACCESS_OPS:
                try:
                    models.execute_kw(
                        db, uid, pwd, model, "check_access_rights",
                        [op], {"raise_exception": True},
                    )
                except Exception as exc:  # noqa: BLE001 - semua error = access issue
                    access_issues.append((model, op, str(exc)))

            print(f"  {model}: {len(fields)} fields")
        except Exception as exc:  # noqa: BLE001 - model tak ada / tanpa akses baca
            print(f"  ❌ {model}: {exc}")
            access_issues.append((model, "fields_get", str(exc)))

    SNAPSHOT_PATH.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Ringkasan: berapa model yang berhasil di-snapshot + lokasi file.
    print(f"\n📦 Snapshot: {len(snapshot)}/{len(MODELS)} model → {SNAPSHOT_PATH}")

    if access_issues:
        print("\n⚠️  Access issues:")
        for model, op, err in access_issues:
            print(f"  ❌ {model}.{op}: {err}")
    else:
        print("\n✅ Semua access OK")


if __name__ == "__main__":
    main()
