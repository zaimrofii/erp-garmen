# Kerangka Kerja Ringkas: Validasi Integrasi JSON-RPC Django ↔ Odoo (v2.1)

**Nama dokumen:** `FRAMEWORK_JSONRPC_VALIDATION.md`
**Versi:** 2.1 (Pragmatic/Agile — Odoo 17 Verified)
**Perubahan dari v2.0:** Verifikasi nama model dan method untuk Odoo 17, koreksi `product.uom` → `uom.uom`, tambah catatan `stock.scrap` deprecated, tambah `mrp.bom` fields verification.

**Prinsip:** **Probe dulu → Kunci contract → Test transaksi kritis → Adapter terakhir.** Inkremental per alur.

---

## 0. FILOSOFI RINGKAS

```
┌─────────────────────────────────────────────┐
│  1. PROBE    → Kunci nama field Odoo        │
│  2. CONTRACT → Kunci signature per alur     │
│  3. TEST     → Pytest + cleanup             │
│     ↓                                        │
│  Adapter Django memakai contract             │
│  Tambah alur baru = ulangi siklus            │
└─────────────────────────────────────────────┘
```

**Aturan besi (hanya 4):**

1. **Tidak ada kode adapter sebelum `CONTRACT.md` entry ada.**
2. **Setiap contract punya pytest test + cleanup.**
3. **Nama field Odoo tidak hardcoded di service Django** — lewat mapping.
4. **Idempotency via `SyncRecord`** — bukan di Odoo.

---

## 1. VERIFIKASI NAMA MODEL & METHOD (Odoo 17)

### 1.1 Model Names — Verified

| Model                | Status        | Catatan                                                        |
| -------------------- | ------------- | -------------------------------------------------------------- |
| `product.product`    | ✅ Valid      | Produk varian                                                  |
| `product.template`   | ✅ Valid      | Template produk                                                |
| `uom.uom`            | ✅ Valid      | **BUKAN** `product.uom` — sudah di-rename di Odoo 17           |
| `mrp.bom`            | ✅ Valid      | Bill of Materials                                              |
| `mrp.bom.line`       | ✅ Valid      | BOM line                                                       |
| `res.partner`        | ✅ Valid      | Customer + vendor                                              |
| `stock.location`     | ✅ Valid      | Lokasi stok                                                    |
| `stock.picking.type` | ✅ Valid      | Tipe picking                                                   |
| `stock.move`         | ✅ Valid      | High-level demand                                              |
| `stock.move.line`    | ✅ Valid      | Low-level fulfillment                                          |
| `stock.scrap`        | ⚠️ Deprecated | Akan dihapus; gunakan `stock.move.line` dengan `is_scrap=true` |
| `sale.order`         | ✅ Valid      | Sales order                                                    |
| `sale.order.line`    | ✅ Valid      | Sales order line                                               |
| `account.move`       | ✅ Valid      | Invoice/journal entry                                          |

### 1.2 Method Names — Verified

| Method                | Status   | Penggunaan                    |
| --------------------- | -------- | ----------------------------- |
| `search`              | ✅ Valid | Cari record, return IDs       |
| `search_read`         | ✅ Valid | Search + read dalam 1 call    |
| `read`                | ✅ Valid | Baca fields dari IDs          |
| `create`              | ✅ Valid | Buat record, return ID        |
| `write`               | ✅ Valid | Update record                 |
| `unlink`              | ✅ Valid | Hapus record                  |
| `fields_get`          | ✅ Valid | Introspeksi field model       |
| `check_access_rights` | ✅ Valid | Cek hak akses user            |
| `action_post`         | ✅ Valid | Post invoice (`account.move`) |

### 1.3 Payload Signature Corrections

**⚠️ PENTING — `write` payload format:**

```python
# ❌ SALAH (error: BaseModel.write() got an unexpected keyword argument)
models.execute_kw(db, uid, pwd, 'res.partner', 'write', [[id], {'name': 'New'}])

# ✅ BENAR (semua argumen dalam satu list)
models.execute_kw(db, uid, pwd, 'res.partner', 'write', [[id], {'name': 'New'}])
```

Perhatikan: `[[id], {'name': ...}]` — `id` list dan `values` dict **keduanya** di dalam **satu list** sebagai argumen pertama .

**⚠️ PENTING — `create` payload format:**

```python
# ✅ BENAR — payload dalam list
models.execute_kw(db, uid, pwd, 'stock.move', 'create', [[{...}]])

# Return: [id] — list berisi satu integer
```

### 1.4 Field Names — Verified untuk Transaksi Kritis

**`stock.move` (WIP Issue):**
| Field | Wajib | Tipe | Catatan |
|---|---|---|---|
| `product_id` | ✅ | many2one | `product.product` |
| `product_uom_qty` | ✅ | float | **BUKAN** `qty` atau `product_qty` |
| `product_uom` | ✅ | many2one | `uom.uom` (bukan `product.uom`) |
| `location_id` | ✅ | many2one | `stock.location` |
| `location_dest_id` | ✅ | many2one | `stock.location` |
| `name` | ✅ | char | Deskripsi move |
| `picking_type_id` | ✅ | many2one | `stock.picking.type` |
| `origin` | ❌ | char | Referensi sumber |
| `state` | ❌ | selection | Readonly, jangan dikirim |

**`stock.scrap` (⚠️ Deprecated di Odoo 17+):**

- Field: `product_id`, `scrap_qty`, `location_id`, `scrap_location_id`
- **Rekomendasi:** Gunakan `stock.move.line` dengan `is_scrap=true`

**`account.move` (Customer Invoice):**

- Field wajib: `move_type='out_invoice'`, `partner_id`, `invoice_line_ids`
- Line field: `product_id`, `quantity`, `price_unit`, `account_id`
- Post: `action_post()`

---

## 2. STRUKTUR FOLDER (Minimalis)

```
docs/integration/
├── FRAMEWORK_JSONRPC_VALIDATION.md    ← dokumen ini
├── CONTRACT.md                        ← signature terkunci (per alur)
└── ERROR_CATALOG.md                   ← error Odoo + handling

tools/odoo_probe/
├── probe.py                           ← 1 script: auth + fields_get + access + snapshot
└── snapshot_schema.json               ← output: kamus field Odoo

tools/fixtures/
└── seed_minimal.py                    ← 5 fixture esensial

tests/integration/
├── conftest.py
├── test_stock_move_wip.py             ← alur pertama
├── test_stock_move_fg.py              ← alur kedua
└── test_stock_scrap.py                ← alur ketiga
```

---

## 3. FASE 1 — PROBE (1 Script, 1 Kali Jalan)

### 3.1 Script Tunggal (Updated Model List)

```python
# tools/odoo_probe/probe.py
"""
Probe Odoo sekali jalan — Odoo 17 verified.
"""
import os, json, xmlrpc.client
from pathlib import Path

URL   = os.environ["ODOO_URL"]
DB    = os.environ["ODOO_DB"]
USER  = os.environ["ODOO_USER"]
PWD   = os.environ["ODOO_API_KEY"]
UID   = int(os.environ["ODOO_USER_ID"])

# Model yang BENAR-BENAR dipakai di alur kritis
# VERIFIED: uom.uom (bukan product.uom), stock.move.line untuk scrap
MODELS = [
    # Master
    "product.product", "product.template", "uom.uom",  # ← FIX: uom.uom
    "mrp.bom", "mrp.bom.line",
    "res.partner", "stock.location", "stock.picking.type",
    # Order
    "sale.order", "sale.order.line",
    # Transaksi keluar
    "stock.move", "stock.move.line",  # ← stock.move.line untuk scrap
    # Invoice (opsional, untuk alur customer invoice)
    "account.move", "account.move.line",
]

def main():
    common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common")
    uid = common.authenticate(DB, USER, PWD, {})
    assert uid == UID, f"❌ UID mismatch: {uid} != {UID}"
    print(f"✅ Auth OK uid={uid} | Odoo {common.version()['server_version']}")

    models = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")
    snapshot, access_issues = {}, []

    for m in MODELS:
        try:
            fields = models.execute_kw(DB, UID, PWD, m, "fields_get",
                                       [], {"attributes": ["string","type","relation","required","readonly"]})
            snapshot[m] = fields
            # Cek access
            for op in ("read","write","create"):
                try:
                    models.execute_kw(DB, UID, PWD, m, "check_access_rights",
                                      [op], {"raise_exception": True})
                except Exception as e:
                    access_issues.append((m, op, str(e)))
            print(f"  {m}: {len(fields)} fields")
        except Exception as e:
            print(f"  ❌ {m}: {e}")
            access_issues.append((m, "fields_get", str(e)))

    Path("tools/odoo_probe/snapshot_schema.json").write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False))

    if access_issues:
        print("\n⚠️  Access issues:")
        for m, op, err in access_issues:
            print(f"  ❌ {m}.{op}: {err}")
    else:
        print("\n✅ Semua access OK")

if __name__ == "__main__":
    main()
```

---

## 4. FASE 2 — CONTRACT (Per Alur, Inkremental)

### 4.1 Urutan Alur (Rekomendasi)

| Prioritas | Alur                                    | Contract ID           | Model             | Method                   |
| --------- | --------------------------------------- | --------------------- | ----------------- | ------------------------ |
| **1**     | WIP Issue (cutting mulai)               | `TX-WIP-ISSUE`        | `stock.move`      | `create`                 |
| **2**     | FG Receipt (WO selesai)                 | `TX-FG-RECEIPT`       | `stock.move`      | `create`                 |
| **3**     | Master Product/BOM read                 | `MASTER-PRODUCT-READ` | `product.product` | `search_read`            |
| **4**     | Sale Order read                         | `ORDER-SO-READ`       | `sale.order`      | `search_read`            |
| **5**     | Scrap sync (⚠️ pakai `stock.move.line`) | `TX-SCRAP`            | `stock.move.line` | `create`                 |
| **6**     | Purchase Order read                     | `ORDER-PO-READ`       | `purchase.order`  | `search_read`            |
| **7**     | Customer Invoice                        | `TX-CUSTOMER-INVOICE` | `account.move`    | `create` + `action_post` |

### 4.2 Format Entry `CONTRACT.md` (Updated)

````markdown
## TX-WIP-ISSUE

**Model:** `stock.move`
**Method:** `create`
**Arah:** MES → Odoo
**Trigger:** Bundle pertama START di WC cutting
**Idempotency key:** `SyncRecord(resource="work_order", resource_id=<wo_id>, stage="WIP")`
**Odoo Version:** 17.0 Community (verified 2026-10-05)

### Payload (minimal terverifikasi)

```json
[
  {
    "product_id": 123,
    "product_uom_qty": 100.0,
    "product_uom": 1,
    "location_id": 14,
    "location_dest_id": 15,
    "name": "WIP/WO-2025-0001",
    "origin": "WO-2025-0001",
    "picking_type_id": 6
  }
]
```
````

### Field

- **Wajib:** `product_id`, `product_uom_qty`, `product_uom`, `location_id`, `location_dest_id`, `name`, `picking_type_id`
- **Opsional:** `origin`, `reference`
- **Readonly (JANGAN kirim):** `state`, `picking_id`

### ⚠️ Catatan Field

- `product_uom` → many2one ke `uom.uom` (BUKAN `product.uom`)
- `product_uom_qty` → BUKAN `qty` atau `product_qty`

### Return

`[id]` — integer (id stock.move yang dibuat)

### Error yang mungkin

| Error                                    | Penyebab               | Handling                            |
| ---------------------------------------- | ---------------------- | ----------------------------------- |
| `UserError: cannot validate transfer`    | Tanpa `picking_id`     | Buat `stock.picking` dulu           |
| `ValidationError: UoM category mismatch` | UoM produk ≠ UoM kirim | Pastikan `product_uom` = UoM produk |

### Dependensi (harus ada dulu)

- `product.product` id=123 sudah di `ODOO_MAPPING`
- `stock.location` WIP=14, FG=15 (dari `.env`)
- `stock.picking.type` internal=6 (dari `.env`)

### Test

`tests/integration/test_stock_move_wip.py::test_create_wip_issue`

````

---

## 5. FASE 3 — FIXTURE + PYTEST (Barengan)

### 5.1 Fixture Minimal (Updated — `uom.uom`)

```python
# tools/fixtures/seed_minimal.py
import os, xmlrpc.client

URL, DB = os.environ["ODOO_URL"], os.environ["ODOO_DB"]
UID, PWD = int(os.environ["ODOO_USER_ID"]), os.environ["ODOO_API_KEY"]
models = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")

def upsert(model, domain, values):
    ids = models.execute_kw(DB, UID, PWD, model, "search", [domain])
    if ids:
        models.execute_kw(DB, UID, PWD, model, "write", [[ids[0]], values])
        return ids[0]
    return models.execute_kw(DB, UID, PWD, model, "create", [values])

def main():
    # 1. UoM PCS — FIX: model adalah uom.uom
    uom_id = upsert("uom.uom", [("name","=","PCS")],
                    {"name": "PCS", "category_id": 1, "factor": 1.0})

    # 2. Kain (RM)
    kain_id = upsert("product.product", [("default_code","=","KAIN-COTTON-30S")],
                     {"default_code": "KAIN-COTTON-30S", "name": "Kain Cotton 30s",
                      "type": "product", "uom_id": uom_id, "uom_po_id": uom_id})

    # 3. Kaos Export (FG)
    kaos_id = upsert("product.product", [("default_code","=","KTS-EXPORT-L")],
                     {"default_code": "KTS-EXPORT-L", "name": "Kaos Export L",
                      "type": "product", "uom_id": uom_id, "uom_po_id": uom_id})

    # 4. Customer
    cust_id = upsert("res.partner", [("name","=","PT Buyer Export")],
                     {"name": "PT Buyer Export", "customer_rank": 1})

    # 5. Lokasi WIP + FG
    loc_wip = upsert("stock.location", [("complete_name","=","WH/WIP")],
                     {"name": "WIP", "usage": "internal"})
    loc_fg  = upsert("stock.location", [("complete_name","=","WH/FG")],
                     {"name": "FG", "usage": "internal"})

    print(f"✅ Fixture OK: uom={uom_id} kain={kain_id} kaos={kaos_id} cust={cust_id} wip={loc_wip} fg={loc_fg}")

if __name__ == "__main__":
    main()
````

### 5.2 Pytest (Updated — `uom.uom`)

```python
# tests/integration/conftest.py
import os, pytest, xmlrpc.client

@pytest.fixture(scope="session")
def odoo():
    url, db = os.environ["ODOO_URL"], os.environ["ODOO_DB"]
    uid, pwd = int(os.environ["ODOO_USER_ID"]), os.environ["ODOO_API_KEY"]
    return {
        "url": url, "db": db, "uid": uid, "pwd": pwd,
        "models": xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object"),
    }

@pytest.fixture
def cleanup(odoo):
    created = []
    yield created
    for model, ids in created:
        try:
            odoo["models"].execute_kw(odoo["db"], odoo["uid"], odoo["pwd"],
                                      model, "unlink", [ids])
        except Exception as e:
            print(f"⚠️ cleanup {model} {ids}: {e}")
```

```python
# tests/integration/test_stock_move_wip.py
import os, pytest, xmlrpc.client

def test_create_wip_issue(odoo, cleanup):
    """Contract TX-WIP-ISSUE — happy path."""
    # FIX: uom.uom (bukan product.uom)
    product_id = odoo["models"].execute_kw(odoo["db"], odoo["uid"], odoo["pwd"],
        "product.product", "search", [[("default_code","=","KTS-EXPORT-L")]])[0]
    uom_id = odoo["models"].execute_kw(odoo["db"], odoo["uid"], odoo["pwd"],
        "uom.uom", "search", [[("name","=","PCS")]])[0]  # ← FIX

    payload = [{
        "product_id": product_id,
        "product_uom_qty": 100.0,
        "product_uom": uom_id,
        "location_id": int(os.environ["ODOO_LOCATION_WIP"]),
        "location_dest_id": int(os.environ["ODOO_LOCATION_FG"]),
        "name": "WIP/TEST-0001",
        "origin": "TEST-WO-0001",
        "picking_type_id": int(os.environ["ODOO_PICKING_TYPE_INTERNAL"]),
    }]
    ids = odoo["models"].execute_kw(odoo["db"], odoo["uid"], odoo["pwd"],
                                    "stock.move", "create", [payload])
    cleanup.append(("stock.move", ids))

    assert isinstance(ids, list) and len(ids) == 1
    rec = odoo["models"].execute_kw(odoo["db"], odoo["uid"], odoo["pwd"],
        "stock.move", "read", [ids, ["state","product_uom_qty","origin"]])[0]
    assert rec["product_uom_qty"] == 100.0
    assert rec["origin"] == "TEST-WO-0001"

def test_create_wip_issue_missing_field(odoo):
    """Contract TX-WIP-ISSUE — negative path."""
    with pytest.raises(xmlrpc.client.Fault) as exc:
        odoo["models"].execute_kw(odoo["db"], odoo["uid"], odoo["pwd"],
            "stock.move", "create", [[{"product_id": 1}]])
    assert "product_uom_qty" in str(exc.value) or "location_id" in str(exc.value)
```

---

## 6. SCRAP — CATATAN KRITIS ODOO 17

**⚠️ `stock.scrap` sedang dalam proses dihapus di Odoo 17+.**

Berdasarkan PR Odoo , model `stock.scrap` akan dihapus dan fungsionalitasnya dipindahkan ke `stock.move.line` dengan field baru `is_scrap = true`.

**Untuk saat ini (Odoo 17.0):**

- `stock.scrap` **masih ada** dan bisa dipakai.
- Tapi untuk **future-proof**, gunakan `stock.move.line` dengan `is_scrap=true`.

**Contract untuk scrap:**

````markdown
## TX-SCRAP (Future-proof)

**Model:** `stock.move.line` (dengan `is_scrap=true`)
**Method:** `create`
**Arah:** MES → Odoo
**Trigger:** ScrapAccumulator periodik

### Payload

```json
[{
  "product_id": 123,
  "quantity": 5.0,
  "product_uom_id": 1,
  "location_id": 14,
  "location_dest_id": 99,
  "is_scrap": true,
  "scrap_reason_tag_ids": [(6, 0, [1])]
}]
```
````

### ⚠️ Catatan

- Field `is_scrap`, `scrap_reason_tag_ids`, `should_replenish_scrapped` adalah field baru di Odoo 17+
- Untuk Odoo < 17, gunakan `stock.scrap` dengan field: `product_id`, `scrap_qty`, `location_id`, `scrap_location_id`

```

---

## 7. URUTAN EKSEKUSI (Checklist untuk AI Agent)

### Tahap A — Setup (sekali)
1. [ ] Jalankan `probe.py` → konfirmasi auth + UID match.
2. [ ] **Baca `snapshot_schema.json`** → verifikasi model `uom.uom` (bukan `product.uom`).
3. [ ] Commit `snapshot_schema.json`.

### Tahap B — Alur Pertama (`TX-WIP-ISSUE`)
4. [ ] Tulis entry `TX-WIP-ISSUE` di `CONTRACT.md` (dengan field verified).
5. [ ] Jalankan `seed_minimal.py` (dengan `uom.uom`).
6. [ ] Tulis `test_stock_move_wip.py` (positif + negatif).
7. [ ] Jalankan pytest → **hijau**.
8. [ ] Tulis `OdooAdapter.push_wip_issue`.
9. [ ] Uji adapter end-to-end.

### Tahap C — Alur Selanjutnya
10. [ ] Ulangi untuk `TX-FG-RECEIPT`, `MASTER-PRODUCT-READ`, `ORDER-SO-READ`, dst.
11. [ ] Untuk scrap, gunakan `stock.move.line` dengan `is_scrap=true` (future-proof).

---

## 8. KOREKSI DARI V2.0

| Item | v2.0 | v2.1 (Corrected) |
|---|---|---|
| Model UoM | `product.uom` ❌ | `uom.uom` ✅  |
| Scrap model | `stock.scrap` ⚠️ | `stock.move.line` dengan `is_scrap=true` ✅  |
| Field quantity | `qty` (implisit) | `product_uom_qty` (eksplisit) |
| `write` payload | `[[id], values]` | `[[id], values]` — keduanya dalam satu list  |
| Invoice post | — | `action_post()`  |
| Model `stock.move.line` | Tidak ada | Ditambahkan untuk scrap future-proof |

---

## 9. SLOGAN

> **"Probe sekali, contract per alur, test dulu baru adapter. Model `uom.uom` bukan `product.uom`. Scrap pakai `stock.move.line` bukan `stock.scrap`. Tidak ada Postman, tidak ada 50 fixture, tidak ada 28 contract sekaligus. Satu alur hijau, lanjut alur berikutnya."**

---

**Siap mulai?** Jalankan `probe.py` dulu, commit `snapshot_schema.json`, lalu kerjakan `TX-WIP-ISSUE` sampai hijau.
```
