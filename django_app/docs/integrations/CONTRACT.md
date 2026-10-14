# CONTRACT.md — Signature Terkunci (Per Alur)

> Framework: `FRAMEWORK_JSONRPC_VALIDATION.md` v2.1 (§4.2).
> Field di bawah **terverifikasi** dari `tools/odoo_probe/snapshot_schema.json`
> (Odoo `17.0-20260817`, probe 2026-10-05).
> Saat ini berisi **empat entry**: `TX-WIP-ISSUE`, `TX-FG-RECEIPT`, `TX-SCRAP`,
> dan `TX-INVOICE`.

---

## TX-WIP-ISSUE

**Model:** `stock.move`
**Method:** `create`
**Arah:** MES → Odoo
**Trigger:** Bundle pertama START di WC cutting (WO)
**Signature (real repo):** `OdooAdapter.push_wip_issue_wo(self, wo) -> ERPResponse` — method **BARU** (Step 7); method lama `push_wip_issue(payload)` **tidak diubah**
**Input `wo`:** `{"product_id": <pk Product Django>, "qty": <float>, "ref": <str>, "uom_id"?: <id uom.uom Odoo>}`
**Mapping produk:** `master.Product.id` → `master.Product.odoo_id` (repo **tidak** punya model `OdooMapping`)
**Idempotency:** di **tasks** (`SyncRecord` + `SyncIdempotency`), **BUKAN** di adapter
**Settings lokasi:** `ODOO_LOCATION_WIP_ID` (sumber, **`53`** = `WH/WIP`) → `ODOO_LOCATION_PRODUCTION_ID` (tujuan, **`24`** = `Virtual Locations/Production`) — tidak ada `location_id` hardcode
**Idempotency key:** `SyncRecord(resource="work_order", resource_id=<wo_id>, stage="WIP")`
**Odoo Version:** 17.0 Community (verified 2026-10-05)

### Payload (minimal terverifikasi)

```json
[
  {
    "product_id": 100,
    "product_uom_qty": 12.0,
    "product_uom": 33,
    "location_id": 53,
    "location_dest_id": 24,
    "name": "WO-STEP7-0001",
    "reference": "WO-STEP7-0001"
  }
]
```

> Angka di atas **nyata** (bukan placeholder): `product_id`/`product_uom` dari Odoo,
> `location_id`/`location_dest_id` dari settings. Kode **tidak** meng-hardcode
> `location_id` — nilai itu hanya contoh payload.

### Field

- **Wajib:** `product_id`, `product_uom_qty`, `product_uom`, `location_id`, `location_dest_id`, `name`, `picking_type_id`
- **Opsional:** `origin`, `reference`
- **Readonly (JANGAN kirim):** `state`, `picking_id`

### ⚠️ Catatan Field (hasil probe `snapshot_schema.json`)

- `product_id` → `many2one` → `product.product`, `required: true`.
- `product_uom_qty` → `type: float`, `required: true` — **BUKAN** `qty` atau `product_qty`.
- `product_uom` → `many2one` → **`uom.uom`** (`relation: "uom.uom"`), `required: true` — **BUKAN** `product.uom`.
- `location_id` → `many2one` → `stock.location`, `required: true`.
- `location_dest_id` → `many2one` → `stock.location`, `required: true`.
- `name` → `type: char`, `required: true`.
- ⚠️ **Koreksi vs template §1.4:** `picking_type_id` ternyata **`required: false`** pada snapshot
  (bukan field wajib DB). Odoo mengisinya lewat onchange/default `stock.picking`, jadi tetap
  kirim, tapi **jangan** dijadikan andalan validasi "wajib".
- Field `required: true` **lengkap** pada `stock.move` (9): `name`, `date`, `company_id`,
  `product_id`, `product_uom_qty`, `product_uom`, `location_id`, `location_dest_id`,
  `procure_method` (`date`/`company_id`/`procure_method` terisi otomatis oleh Odoo).

### Return

`[id]` — integer (id `stock.move` yang dibuat). Contoh: `[123]`.

### Error yang mungkin

| Error | Penyebab | Handling |
| --- | --- | --- |
| `UserError: cannot validate transfer` | Tanpa `picking_id` | Buat `stock.picking` dulu |
| `ValidationError: UoM category mismatch` | UoM produk ≠ UoM kirim | Pastikan `product_uom` = UoM produk |

### Dependensi (harus ada dulu)

- `master.Product` (Django) memiliki `odoo_id` = id `product.product` Odoo.
  Contoh: `Product(code="KTS-EXPORT-L", odoo_id=100)`.
- `uom.uom` "PCS" (Odoo id `33`) — hasil `tools/fixtures/seed_minimal.py`.
- `.env`: `ODOO_LOCATION_WIP_ID` (**wajib**), `ODOO_LOCATION_PRODUCTION_ID` (**wajib**).
  Nilai nyata Odoo saat ini: `WH/WIP` = `53`, `Virtual Locations/Production` = `24`.

### Status nilai (terverifikasi)

| Item | Nilai | Sumber |
| --- | --- | --- |
| `product.product` (FG) | `100` = `KTS-EXPORT-L` | Odoo (via `Product.odoo_id`) |
| `uom.uom` | `33` = `PCS` | seed §5.1 |
| `location_id` (WIP) | `53` = `WH/WIP` | Odoo + `.env` `ODOO_LOCATION_WIP_ID` |
| `location_dest_id` (PRODUCTION) | `24` = `Virtual Locations/Production` | Odoo + `.env` `ODOO_LOCATION_PRODUCTION_ID` |

> **Chain lokasi (Fase I7):** `53` (`WH/WIP`) → **`24` (`Virtual Locations/Production`)** → `54` (`WH/FG`).
> Produksi memakai **virtual location** (`usage: production`) ⇒ konsumsi **benar-benar keluar
> persediaan** (sebelumnya `50` = `WH/Production` yang `usage: internal` ⇒ stok hanya berpindah
> antar lokasi internal dan total persediaan tidak pernah turun).

> `picking_type_id` **tidak dipakai** di `push_wip_issue_wo` (tidak ada setting
> baru — sesuai permintaan "jangan tambah settings kalau tidak perlu").

### Test

`tests/integration/test_odoo_adapter_wo.py::OdooAdapterPushWipIssueWoTests`
(`test_push_wip_issue_wo_sukses` + `test_push_wip_issue_wo_payload_kurang_field`)

---

## TX-FG-RECEIPT

**Model:** `stock.move`
**Method:** `create`
**Arah:** MES → Odoo
**Trigger:** WO selesai (semua bundle DONE) — penerimaan barang jadi ke gudang FG
**Signature (real repo):** `OdooAdapter.push_fg_receipt_wo(self, wo) -> ERPResponse` — method **BARU** (Step 8); method lama `push_fg_receipt(payload)` **tidak diubah**
**Input `wo`:** `{"product_id": <pk Product Django>, "qty": <float>, "ref": <str>, "uom_id"?: <id uom.uom Odoo>}`
**Mapping produk:** `master.Product.id` → `master.Product.odoo_id` (repo **tidak** punya model `OdooMapping`)
**Idempotency:** di **tasks** (`SyncRecord` + `SyncIdempotency`, `stage="FG"`), **BUKAN** di adapter
**Settings lokasi:** `ODOO_LOCATION_PRODUCTION_ID` (sumber, **`24`** = `Virtual Locations/Production`) → `ODOO_LOCATION_FG_ID` (tujuan, **`54`** = `WH/FG`) — tidak ada `location_id` hardcode
**Idempotency key:** `SyncRecord(resource="work_order", resource_id=<wo_id>, stage="FG")`
**Odoo Version:** 17.0 Community (verified 2026-10-05)

### Payload (minimal terverifikasi)

```json
[
  {
    "product_id": 100,
    "product_uom_qty": 8.0,
    "product_uom": 33,
    "location_id": 24,
    "location_dest_id": 54,
    "name": "WO-STEP8-0001",
    "reference": "WO-STEP8-0001"
  }
]
```

> Angka di atas **nyata**: `location_id` = `Virtual Locations/Production` (24),
> `location_dest_id` = `WH/FG` (54), `product_uom` = `PCS` (33),
> `product_id` = `KTS-EXPORT-L` (100).
> Kode **tidak** meng-hardcode id — nilai itu hanya contoh payload.

### Field

- **Wajib:** `product_id`, `product_uom_qty`, `product_uom`, `location_id`, `location_dest_id`, `name`
- **Opsional:** `origin`, `reference`
- **Readonly (JANGAN kirim):** `state`, `picking_id`

### ⚠️ Catatan Field

- Sama seperti `TX-WIP-ISSUE` (keduanya `stock.move.create`); lihat catatan field di entry atas.
- Arah lokasi **kebalikan** WIP issue: WIP = `WIP → PRODUCTION`, FG = `PRODUCTION → FG`.
- `product_uom` → `uom.uom` (**BUKAN** `product.uom`); `product_uom_qty` → **BUKAN** `qty`/`product_qty`.

### Return

`[id]` — integer (id `stock.move` yang dibuat). Contoh: `[222]`.

### Error yang mungkin

| Error | Penyebab | Handling |
| --- | --- | --- |
| `UserError: cannot validate transfer` | Tanpa `picking_id` | Buat `stock.picking` dulu |
| `ValidationError: UoM category mismatch` | UoM produk ≠ UoM kirim | Pastikan `product_uom` = UoM produk |
| `AccessError` (Fault 4) | user Odoo read-only | Pakai user dengan hak Inventory |

### Dependensi (harus ada dulu)

- `master.Product` (Django) memiliki `odoo_id` = id `product.product` Odoo.
  Contoh: `Product(code="KTS-EXPORT-L", odoo_id=100)`.
- `uom.uom` "PCS" (Odoo id `33`) — hasil `tools/fixtures/seed_minimal.py`.
- `.env`: `ODOO_LOCATION_PRODUCTION_ID` (**wajib**), `ODOO_LOCATION_FG_ID` (**wajib**).

### Status nilai (terverifikasi)

| Item | Nilai | Sumber |
| --- | --- | --- |
| `product.product` (FG) | `100` = `KTS-EXPORT-L` | Odoo (via `Product.odoo_id`) |
| `uom.uom` | `33` = `PCS` | seed §5.1 |
| `location_id` (PRODUCTION) | `24` = `Virtual Locations/Production` | `.env` `ODOO_LOCATION_PRODUCTION_ID` |
| `location_dest_id` (FG) | `54` = `WH/FG` | `.env` `ODOO_LOCATION_FG_ID` |

> **Chain lokasi (Fase I7):** `53` (`WH/WIP`) → **`24` (`Virtual Locations/Production`)** → `54` (`WH/FG`).
> `24` adalah **virtual location** (`usage: production`) ⇒ bahan benar-benar dikonsumsi
> (keluar dari persediaan) saat WIP issue, dan dikembalikan sebagai barang jadi saat FG receipt.

### Test

`tests/integration/test_odoo_adapter_fg.py::OdooAdapterPushFgReceiptWoTests`
(`test_push_fg_receipt_wo_sukses` + `test_push_fg_receipt_wo_payload_kurang_field`)

---

## TX-SCRAP

**Model:** **`stock.scrap`** — DIKUNCI (BUKAN `stock.move.line`; field `is_scrap`
**tidak ada** di Odoo `17.0-20260817` ini — sudah diverifikasi: `ValueError:
Invalid field 'is_scrap' on model 'stock.move.line'`)
**Method:** `create` + `action_validate`
**Arah:** MES → Odoo
**Trigger:** ScrapAccumulator periodik (barang rusak/afval)
**Signature (real repo):** `OdooAdapter.push_scrap_wo(self, wo) -> ERPResponse` — method **BARU** (Step 9)
**Input `wo`:** `{"product_id": <pk Product Django>, "qty": <float>, "ref": <str>, "uom_id": <id uom.uom Odoo>}` — `uom_id` **wajib** (`stock.scrap.product_uom_id` required)
**Mapping produk:** `master.Product.id` → `master.Product.odoo_id`
**Idempotency:** di **tasks** (`SyncRecord`), **BUKAN** di adapter
**Settings lokasi:** `ODOO_LOCATION_WIP_ID` (asal) & `ODOO_LOCATION_SCRAP_ID` (lokasi scrap) — tidak ada `location_id` hardcode
**Odoo Version:** 17.0 Community (verified 2026-10-05)

### Payload (minimal terverifikasi) — field wajib `stock.scrap`

| Field | Tipe | Wajib | Contoh | Catatan |
| --- | --- | --- | --- | --- |
| `product_id` | many2one | ✅ | `100` | → `product.product` |
| `scrap_qty` | float | ✅ | `1.0` | jumlah barang rusak |
| `product_uom_id` | many2one | ✅ | `33` | → `uom.uom` (PCS) |
| `location_id` | many2one | ✅ | `53` | lokasi **asal** = `ODOO_LOCATION_WIP_ID` |
| `scrap_location_id` | many2one | ✅ | `26` | `Virtual Locations/Scrap` (company default) |
| `name` / `origin` | char | – | `SCRAP-STEP9-0001` | diisi dari `ref` |

```json
[
  {
    "product_id": 100,
    "scrap_qty": 1.0,
    "product_uom_id": 33,
    "location_id": 53,
    "scrap_location_id": 26,
    "name": "SCRAP-STEP9-0001",
    "origin": "SCRAP-STEP9-0001"
  }
]
```

### Alur method (`push_scrap_wo`)

1. Validasi `wo` (`product_id`, `qty`, `ref`, `uom_id`) → map `Product.odoo_id`.
2. `stock.scrap.create` dengan 5 field wajib di atas (+ `name`/`origin`).
3. `stock.scrap.action_validate([[id]])` → `state` jadi **`done`**.
4. Verifikasi `state == "done"`. Kalau Odoo tidak memvalidasi (mis. **stok kurang** →
   Odoo membalas wizard `stock.warn.insufficient.qty.scrap`), draft scrap di-`unlink`
   (best-effort) lalu return `ERPResponse(ok=False)` — tidak ada record menggantung.

### Return

`[id]` — integer (id `stock.scrap`). Contoh: `[3]`.

### ⚠️ Catatan penting

- Hitungan field: `product_uom_id` / `scrap_qty` (bukan `product_uom` / `product_uom_qty`).
- `action_validate` sukses hanya kalau **stok cukup** di `location_id`; kalau tidak, Odoo
  mengembalikan wizard (bukan exception).
- **Scrap `done` tidak bisa dihapus** (`You cannot delete a scrap which is done.`) →
  jejak `stock.move` permanen. Karena itu test otomatis memakai **mock** untuk jalur
  validasi-sukses; bukti E2E nyata dilakukan manual (create→validate→`done`→bersihkan
  via `write(state='draft')`+`unlink`).

### Error yang mungkin

| Error | Penyebab | Handling |
| --- | --- | --- |
| `AccessError` (Fault 4) | user read-only | pakai user dengan hak Inventory |
| `Incompatible companies` | `scrap_location_id` beda company dari lokasi asal | pakai scrap location sesuai company (id `26`) |
| wizard `stock.warn.insufficient.qty.scrap` | stok lokasi asal kurang | tambah stok / scrap dari lokasi berstok |

### Dependensi (harus ada dulu)

- `master.Product` dengan `odoo_id` (contoh `Product(code="KTS-EXPORT-L", odoo_id=100)`).
- `uom.uom` "PCS" (id `33`).
- `.env`: `ODOO_LOCATION_WIP_ID` (**asal**, `53`), `ODOO_LOCATION_SCRAP_ID` (`26`).
- Stok cukup di lokasi asal agar validasi sukses.

### Test

`tests/integration/test_odoo_adapter_scrap.py`
(`OdooAdapterPushScrapWoMockTests` = positip & negatif; `OdooAdapterPushScrapWoNyataTests` = integrasi Odoo nyata)


---

## TX-INVOICE

**Model:** `account.move` (`move_type="out_invoice"` — Customer Invoice)
**Method:** `create` — **TANPA** `action_post`
**Arah:** MES → Odoo
**Trigger:** listener `WORK_ORDER_STATE_CHANGED` state `DONE`, **hanya** kalau **SEMUA** `WorkOrder` order itu sudah `DONE` (Fase I5)
**Signature (real repo):** `OdooAdapter.push_customer_invoice_wo(self, wo) -> ERPResponse` — method **BARU** (Fase I5); method lama `push_customer_invoice(payload)` **tidak dibuat**
**Input `wo`:** `{"order_id": <pk Order Django>, "ref": <str>, "invoice_date"?: <"YYYY-MM-DD">}` — `wo` mengirim **pk Django** (pola sama `push_scrap_wo`); `invoice_date` default `timezone.localdate()`
**Mapping:** `Order.customer` → `Partner.odoo_id` (**wajib**) & tiap `OrderLine.product` → `Product.odoo_id` (varian; baris yang `odoo_id`-nya kosong **dilewati**)
**Idempotency:** di **service/tasks** — `SyncRecord(resource="order", resource_id=<order.pk>, stage="INVOICE")` (unique constraint DB) — **BUKAN** di adapter
**Settings tambahan:** tidak ada (tidak butuh `ODOO_LOCATION_*` / `ODOO_UOM_ID`)
**Odoo Version:** 17.0 Community — field diverifikasi **live** `fields_get` 2026-10-06 (instance punya 8 `account.journal`, 24 `account.move` → modul accounting aktif)

### Payload (minimal) — field yang dikirim

| Field | Tipe | Wajib (Odoo) | Contoh | Catatan |
| --- | --- | --- | --- | --- |
| `partner_id` | many2one → `res.partner` | `required: false` | `51` | dari `order.customer.odoo_id`; adapter menolak (`ok=False`) kalau customer/odoo_id kosong |
| `move_type` | selection | **`required: true`** | `out_invoice` | `out_invoice` = "Customer Invoice" ✅ terverifikasi ada di selection |
| `invoice_date` | date | `required: false` | `2026-10-06` | default `timezone.localdate()` (WIB) |
| `ref` | char | `required: false` | `INV-ORD-INV-0001` | `f"INV-{order.code}"` |
| `invoice_line_ids` | one2many → `account.move.line` | `required: false` | `[(0, 0, {...})]` | minimal satu baris (kalau semua OrderLine terlewat → `ok=False`) |

Baris invoice — command `(0, 0, {...})`, satu per `OrderLine`:

| Field baris | Tipe | Contoh | Catatan |
| --- | --- | --- | --- |
| `product_id` | many2one → `product.product` | `100` | id **varian** (`Product.odoo_id`) |
| `quantity` | float | `12` | = `OrderLine.qty` |
| `price_unit` | float | `0` | **sementara 0** — MES belum menyimpan harga jual; supervisor melengkapi di UI Odoo |
| `name` | char | `KTS-EXPORT-L` | = `Product.code` |

```json
[
  {
    "partner_id": 51,
    "move_type": "out_invoice",
    "invoice_date": "2026-10-06",
    "ref": "INV-ORD-INV-0001",
    "invoice_line_ids": [
      [0, 0, {"product_id": 100, "quantity": 12, "price_unit": 0, "name": "KTS-EXPORT-L"}]
    ]
  }
]
```

### Field yang TIDAK dikirim (sengaja)

- `journal_id` & `currency_id` — keduanya `required: true` di Odoo, tapi **default company** yang mengisinya
  (diverifikasi ada 8 `account.journal` di instance). MES tidak menyimpan id journal/currency.
- `action_post` **tidak** dipanggil → invoice tetap **draft** supaya harga (dan pajak) di-review supervisor di UI Odoo.

### Alur method (`push_customer_invoice_wo`)

1. Validasi `wo` (`order_id`, `ref`) → resolve `Order` dari pk Django.
2. Resolve `order.customer` → `partner_id`; customer `None` atau `odoo_id` kosong → `ERPResponse(ok=False)`.
3. Bangun `invoice_line_ids` dari `OrderLine` yang `product.odoo_id`-nya terisi (urutan `id`). Kalau **semua** kosong → `ERPResponse(ok=False)`.
4. `account.move.create` dengan 5 field di atas (tanpa `journal_id`/`currency_id`).
5. Return `ERPResponse(ok=True, erp_id=str(move_id), stage="INVOICE")` — **tanpa** `action_post`.

### Return

`[id]` — integer (id `account.move`). Contoh: `[42]`.

### ⚠️ Catatan penting

- `wo` berisi **pk Django** (`order_id`) — adapter yang memetakan ke id Odoo (pola `push_scrap_wo`).
- Invoice **draft** + `price_unit=0` ⇒ **tidak valid** untuk di-`post` sebelum harga diisi. Ini disengaja (repositori belum menyimpan harga jual).
- OrderLine tanpa `product.odoo_id` (produk belum tersinkron) **dilewati** barisnya, bukan menggagalkan seluruh invoice.
- Satu order = satu invoice (`SyncRecord` unique per `(resource, resource_id, stage)`), walau order punya banyak `WorkOrder`.

### Error yang mungkin

| Error | Penyebab | Handling |
| --- | --- | --- |
| `AccessError` (Fault 4) | user Odoo read-only | pakai user dengan hak Accounting/Invoice |
| `MissingError` (`product.product(NN)`) | `Product.odoo_id` tidak ada di Odoo | sync master produk dulu |
| `ValidationError` (journal/currency) | default company tidak lengkap | lengkapi konfigurasi company di Odoo |
| `ok=False` (pesan adapter) | customer/odoo_id kosong, semua OrderLine tanpa `odoo_id`, `wo` kurang `order_id`/`ref`, client Odoo belum siap | perbaiki data master / sinkron ulang |

### Dependensi (harus ada dulu)

- `master.Order` dengan `customer` yang punya `odoo_id` (contoh `Partner(code="PT Buyer Export", odoo_id=51)`).
- Minimal satu `OrderLine` dengan `product.odoo_id` (contoh `Product(code="KTS-EXPORT-L", odoo_id=100)`).
- Kredensial Odoo dengan hak membuat invoice (bukan read-only).

### Test

`tests/integration/test_odoo_adapter_invoice.py`
(`OdooAdapterPushCustomerInvoiceWoMockTests` = positip & negatif, **mock saja** — tanpa test Odoo nyata
karena invoice nyata sulit dibersihkan tanpa hak admin; bukti E2E dilakukan manual)

---

## MASTER-WAREHOUSE-CREATE

**Model:** `stock.warehouse`
**Method:** `create` (belum punya `odoo_id`) / `write` (sudah punya)
**Arah:** MES → Odoo
**Trigger:** POST/PUT/DELETE `/api/v1/master/warehouses/` → task `erp_sync.push_master_warehouse`
**Signature (real repo):** `_push_warehouse_to_odoo(warehouse, payload) -> str` (di dalam
`integrations/erp_sync/tasks_master_push.py`); payload dari `warehouse_payload(warehouse)`
**Payload terkirim (6 field, hasil probe `fields_get`):**

```json
{
  "name": "Gudang Kedua",
  "code": "WH2",
  "reception_steps": "one_step",
  "delivery_steps": "ship_only",
  "active": true
}
```

**Field yang SENGAJA tidak dikirim (sprint utang `warehouse-create-mapping`, OPSI B):**

| Field Odoo | `required` | Alasan tidak dikirim |
| --- | --- | --- |
| `view_location_id` | ya | **Dibuat sendiri Odoo** di `stock/models/stock_warehouse.py::create()` baris 109–126 (`stock.location.create({'name': code, 'usage': 'view', ...})`) |
| `lot_stock_id` | ya | Dibuat Odoo via `_get_locations_values(vals)` dengan induk `view_location_id` |
| `company_id` | ya, **`readonly=True`** | Default dari company user (`default_get`); mengirimnya tidak berguna |

Menurunkan `view_location_id`/`lot_stock_id` dari MES = **mengarang data** (MES tidak punya
relasi Warehouse→Location; arah relasinya `Location.warehouse` dan itu dipakai untuk `stock.location`).

**Guard yang tetap berlaku (`MasterPushError`, task → `FAILED` tanpa retry):**
`code` kosong atau > 5 karakter (`short_name` Odoo **size=5**), `reception_steps`/`delivery_steps`
di luar selection Odoo (`one_step|two_steps|three_steps`, `ship_only|pick_ship|pick_pack_ship`).

**Odoo Version:** 17.0 Community (sumber `create()` dibaca langsung di container, verified 2026-10-11)

### Test

- `tests/integration/test_push_warehouse_mapping.py` (8 test; klien Odoo **di-mock** `FakeOdooClient`,
  tanpa menyentuh jaringan): create dipanggil + `odoo_id` disimpan, payload terbukti bebas 3 field,
  update tetap `write`, guard non-breaking, pull tidak berubah.
- `tests/integration/test_master_warehouses_crud.py` (19 test; 1 test task odoo-mode diperbarui
  menjadi jalur **create**).

## TX-INVENTORY-ADJUST

Inventory Adjustment MES → Odoo (H2.5). **MES tidak menyimpan stok** — yang dikirim MES
adalah *niat penyesuaian* (`qty_delta`), stok tetap milik Odoo per lokasi
(`docs/CHANGES-DETAIL-H1H5.md` §4).

- **Model MES (log/audit):** `garment.InventoryAdjustment`
  (`code`, `product` PROTECT, `location` PROTECT, `qty_delta`, `qty_before`, `qty_after`,
  `reason`, `state DRAFT→COMMITTED→SYNCED/FAILED`, `odoo_move_id`, `odoo_reference`,
  `last_error`, `created_by`).
- **Ledger:** `SyncRecord(resource="inventory_adjustment", stage="INVENTORY_ADJUST")`
  (resource & stage **baru**, aditif) — siklus penuh `PENDING → SENT/FAILED`
  (transaksi nyata, **bukan** `SKIPPED`).
- **Penomoran MES:** `next_number("ADJ")` → `ADJ-<TAHUN>-<SEQ:04d>`
  (sequence di-seed migration `master.0015_seed_adj_sequence`).

### Jalur Odoo 17 (terverifikasi probe + sumber, 2026-10-12)

| Kandidat | Hasil |
| --- | --- |
| `stock.inventory.adjustment` | **TIDAK ADA** di Odoo 17 (hanya wizard `stock.inventory.adjustment.name` = pengisi nama) |
| `stock.move` + `_action_done()` | **Tidak bisa** via XML-RPC (`_action_done` method *private*, `stock_move.py:1907`) |
| `stock.quant` + `action_apply_inventory()` | **DIPAKAI** — method publik (`stock_quant.py:445`), Odoo sendiri yang membuat `stock.move` + `_action_done()` |

Alur (`OdooAdapter.push_inventory_adjustment`):

1. `stock.quant.search_read` (`product_id`, `location_id`) → **`quantity`** (on-hand);
2. `target = on-hand + qty_delta` (MES menyimpan delta, Odoo menuntut nilai **absolut**);
3. tulis **`inventory_quantity = target`** dengan context `inventory_mode=True`
   (`write` kalau quant ada, `create` kalau belum) —
   `set_inventory_quantity_auto_apply=True` dipakai supaya wizard konflik/tracked Odoo
   dilewati (flag internal yang dipakai wizard `stock.change.product.qty` sendiri);
4. `stock.quant.action_apply_inventory()` — Odoo membuat `stock.move` dari/ke
   `product.property_stock_inventory` (lokasi virtual *Inventory adjustment*) lalu
   `_action_done()`;
5. `stock.move.search_read` mencari move dengan `name` = context **`inventory_name`**
   (= `"<kode MES> <reason>"`) → id-nya disimpan sebagai `odoo_move_id`.

### Prasyarat operasional (WAJIB)

- User API Odoo (**API Bot**) **harus** punya grup **`stock.group_stock_manager`** —
  `_apply_inventory()` melempar `UserError('Only a stock manager can validate an
  inventory adjustment.')` tanpa grup itu.
- **Cara set:** Odoo → **Settings → Users → (API Bot) → Inventory: Manager** → Save.
- Tanpa grup tersebut: task menandai adjustment `FAILED` dengan pesan
  `Odoo UserError: user API tidak punya stock.group_stock_manager. Hubungi admin Odoo
  untuk set grup Inventory/Manager.` (dicatat `last_error` + ledger `FAILED`) — **tidak**
  di-retry (bukan error jaringan).
- Status prerequisite ini dilacak sebagai utang/risiko operasional
  `known_tech_debt → "odoo-api-stock-manager-group"` (owner: **admin Odoo klien**,
  bukan utang dev) di `django_app/docs/curent_project.json`.

### Guard MES (semua → 400/409, tidak ada push setengah jalan)

- `location.usage` **wajib** `'internal'` (view/production/scrap/supplier/customer/transit ditolak);
- `qty_delta` **≠ 0** dan `|qty_delta| ≤ 1.000.000`;
- `reason` **wajib** (≤ 500 karakter) — ikut dikirim sebagai nama move Odoo;
- produk **tracking `lot`/`serial` DITOLAK** (MES belum mengelola `lot_id`; jalur quant
  akan memicu wizard `stock.track.confirmation` di Odoo) — pesan: *"Adjustment untuk
  produk tracking lot/serial belum didukung — gunakan Odoo UI atau tunggu sprint terpisah"*;
- `product.odoo_id` & `location.odoo_id` **wajib** saat commit (kalau tidak →
  pesan sinkronkan master dulu);
- `qty_after` = on-hand hasil pembacaan pasca-apply (dari `raw.target` adapter).

### Endpoint

| Method | Path | Fungsi |
| --- | --- | --- |
| `POST` | `/api/v1/inventory/adjust/` | buat log (`DRAFT`); `?commit=true` = langsung `COMMITTED` + push |
| `GET` | `/api/v1/inventory/adjustments/` | daftar log + filter `search`/`state`/`product_id`/`location_id` |
| `GET` | `/api/v1/inventory/adjustments/<id>/` | detail + info ledger sync |
| `POST` | `/api/v1/inventory/adjustments/<id>/commit/` | `DRAFT → COMMITTED` + enqueue push |
| `GET` | `/api/v1/inventory/stock-qty/?product_id=&location_id=` | on-hand Odoo **on-demand** (read-only) |

Izin: **`IsAuthenticated` tanpa role** (keputusan pemilik proyek H2.5). Frontend memakai
guard `INVENTORY_ROLES` (`/inventory/*`).

### Non-breaking

`/api/v1/inventory/products/` (B7), `/inventory/operations/` (B8), `/inventory/reporting/`
(B30), `services/reconciliation.py` (I7, baca `stock.quant`), `services/scrap_sync.py`
(I4, push `stock.scrap`) **tidak disentuh**.

**Odoo Version:** 17.0 (`17.0-20260817`), verified read-only 2026-10-12.

### Test

- `tests/integration/test_inventory_adjustments.py` — create/validasi/commit/task push
  (adapter & broker **di-mock**, tanpa jaringan) + non-breaking B7/B8/B30/I4/I7.



## TX-STOCK-TRANSFER

Stock Transfer MES → Odoo (H2.6) — **internal transfer antar dua lokasi internal**.
MES hanya mencatat **log** (`garment.StockTransfer`: produk, lokasi asal/tujuan, qty,
snapshot on-hand asal) lalu mengirim SATU ARAH; saldo tetap milik Odoo
(`docs/CHANGES-DETAIL-H1H5.md` §4).

- **Model MES (log):** `from_location`/`to_location`/`product` (FK PROTECT), `qty`
  (> 0), `qty_before` (snapshot informatif, **tidak memblokir**), `reason` opsional,
  `state DRAFT→COMMITTED→SYNCED/FAILED`, `odoo_picking_id`, `odoo_picking_name`,
  `last_error`, `code` (`next_number('TRF')` → `TRF-<TAHUN>-<SEQ:04d>`).
- **Ledger:** `SyncRecord(resource="stock_transfer", stage="STOCK_TRANSFER")` (baru,
  aditif) — siklus penuh `PENDING → SENT/FAILED` (transaksi nyata, **bukan** SKIPPED).

### Jalur Odoo 17 (terverifikasi probe + sumber, 2026-10-12)

| Kandidat | Hasil |
| --- | --- |
| `stock.move` + `_action_done()` | **Tidak bisa** via XML-RPC (`_action_done` *private*, `stock_picking.py:978`) |
| `stock.quant` write | Tidak relevan (quant = on-hand, bukan pemindah barang) |
| **`stock.picking` + `button_validate()`** | **DIPAKAI** — `button_validate()` publik (`stock_picking.py:1134`) dan di dalamnya sudah: `draft_picking.action_confirm()` (1137) → auto-isi `move.quantity = product_uom_qty` (1138–1141) → `_pre_action_done_hook()` auto-set `picked=True` (1206–1210) → `_action_done()` (1163) |

Alur (`OdooAdapter.push_stock_transfer_wo`):

1. resolve `picking_type_id` **tanpa hardcode**: settings `ODOO_PICKING_TYPE_INTERNAL_ID`
   bila ada, kalau tidak `stock.picking.type.search_read([("code","=","internal")])`
   (probe dev: id=5 `Transfer Internal`, seq `INT`);
2. `stock.picking.create` `{picking_type_id, location_id (asal), location_dest_id
   (tujuan), origin = kode MES, move_ids=[(0,0,{name, product_id, product_uom_qty,
   location_id, location_dest_id})]}` — `location_id`/`location_dest_id`/
   `picking_type_id` **required=True** di Odoo (dikirim eksplisit); field create yang
   dipakai `move_ids` (One2many polos), **bukan** `move_ids_without_package` (ber-domain);
3. **`button_validate()`** dengan context `skip_backorder=True` → melewati cabang
   wizard backorder (`stock_picking.py:1211`); MES **tidak** memanggil
   `action_assign()` manual (keputusan H2.6: satu langkah, hindari risiko state);
4. verifikasi `state == 'done'`; kalau hasilnya `dict` (wizard) atau state ≠ `done` →
   `FAILED` + pesan jelas; sukses → simpan `odoo_picking_id` + `odoo_picking_name`.

⚠️ Stok Odoo kurang **tidak** dicegah di MES (snapshot `qty_before` hanya informatif:
stok bisa berubah antara snapshot & push) — bila Odoo menolak, task menandai `FAILED`
dengan pesan dari Odoo.

### Prasyarat Odoo

- **Tidak ada prasyarat grup baru**: satu-satunya pengecekan grup terkait transfer
  internal adalah `stock.group_stock_multi_locations` (`stock_picking.py:295`, saat
  mengubah tipe picking) dan user API (`api_bot`) **sudah** memilikinya.
- Opsional: set `ODOO_PICKING_TYPE_INTERNAL_ID` bila ingin mengunci id tipe picking
  (mis. multi-company) — tanpa setting pun sistem mencari `code='internal'`.

### Guard MES (semua → 400/409, tidak ada push setengah jalan)

- kedua lokasi **wajib** `usage='internal'`;
- **`from_location_id != to_location_id`** (pesan: "Lokasi asal dan tujuan TIDAK boleh sama");
- `qty` **> 0** dan ≤ 1.000.000; `reason` opsional ≤ 500 karakter;
- produk **tracking `lot`/`serial` DITOLAK** (MES belum mengelola `lot_id`/`move_line`);
- `product.odoo_id`, `from_location.odoo_id`, **dan** `to_location.odoo_id` wajib saat commit;
- state ≠ `DRAFT` saat commit → 409.

### Endpoint

| Method | Path | Fungsi |
| --- | --- | --- |
| `POST` | `/api/v1/inventory/transfer/` | buat log (`DRAFT`); `?commit=true` = langsung `COMMITTED` + push |
| `GET` | `/api/v1/inventory/transfers/` | daftar log + filter `search`/`state`/`product_id`/`from_location_id`/`to_location_id` |
| `GET` | `/api/v1/inventory/transfers/<id>/` | detail + info ledger sync |
| `POST` | `/api/v1/inventory/transfers/<id>/commit/` | `DRAFT → COMMITTED` + enqueue push |

Pre-flight stok dapat memakai endpoint H2.5 yang sudah ada
(`GET /api/v1/inventory/stock-qty/`, read-only). Izin: **`IsAuthenticated` tanpa role**;
frontend memakai guard `INVENTORY_ROLES`.

### Non-breaking

`/api/v1/inventory/products/` (B7), `/inventory/operations/` (B8), `/inventory/reporting/`
(B30), H2.5 (`/inventory/adjust*`, `/inventory/stock-qty/`, model `InventoryAdjustment`,
stage `INVENTORY_ADJUST`), I4 `services/scrap_sync.py`, I7 `services/reconciliation.py`
— **tidak disentuh**.

**Odoo Version:** 17.0 (`17.0-20260817`), verified read-only 2026-10-12.

### Test

- `tests/integration/test_stock_transfers.py` (35 test) — create/validasi, list+filter,
  detail, commit (+guard 3 sisi `odoo_id` & tracking), adapter picking path
  (klien Odoo **di-mock**), task push (`SYNCED`/`FAILED`/duplicate/no-op), non-breaking
  B7/B8/B30 + H2.5 + I4/I7.

## MASTER-PRICE (H3.5)

Harga produk MES (`sale_price` = harga jual, `cost_price` = HPP) — **sudah ada sejak H1.1**
di `master.Product`; H3.5 melengkapi **jejak audit**, **endpoint khusus**, dan **pull harga**.

### Arah data (PENTING)

- **MES = source of truth master** ⇒ **push** harga selalu dikirim ke Odoo:
  `sale_price` → `product.product.list_price`, `cost_price` → `product.product.standard_price`
  (jalur H1.1 `erp_sync.push_master_product`; payload sudah memuat keduanya).
- **Pull** (beat `sync-master-*`, harian 02:00) **hanya MENGISI bila harga MES masih 0**
  (bootstrap produk baru / sync awal). Harga MES yang sudah > 0 **TIDAK** pernah ditimpa dari
  Odoo — kalau ditimpa, harga yang diisi operator akan ter-reset setiap malam.
  Implementasi: `integrations/erp_sync/tasks_master.py::_product_defaults`.

### Field Odoo yang dipakai (probe read-only 2026-10-12)

| Odoo | Tipe (probe) | MES |
| --- | --- | --- |
| `product.product.list_price` | float — `'Sales Price'` | `Product.sale_price` |
| `product.product.standard_price` | float — `'Cost'` | `Product.cost_price` |
| `currency_id` | m2o `res.currency` (dev: IDR id=12) | — (Currency mirror terpisah) |
| `taxes_id` | m2m `account.tax` | — (belum dipetakan; sprint pajak terpisah) |

`transport/odoo_transport.py::PRODUCT_FIELDS` menambah `list_price` + `standard_price`.

### Endpoint

| Method | Path | Fungsi |
| --- | --- | --- |
| `PUT` | `/api/v1/master/products/<id>/price/` | ubah harga saja + audit `master.update_price` + push |
| `GET` | `/api/v1/master/products/<id>/price-history/` | riwayat harga (dari `AuditLog`, envelope §3) |
| `PUT` | `/api/v1/master/products/<id>/` | **(H1.1, tetap ada)** ubah produk; bila harga ikut berubah ⇒ audit harga juga ditulis (`source=product_update`) |

Izin tulis: `ADMIN`/`OWNER`/`PURCHASING` (pola H1.1 `require_master_writer`).

### Guard & audit

- `sale_price`/`cost_price` **≥ 0**; **0 diizinkan** (produk gratis/diskon penuh),
  **negatif ditolak** (400). Guard `price_unit > 0` **tetap hanya** di baris order saat
  `CONFIRMED` (§5) dan **tidak diubah**.
- `Product.price_updated_at` (baru, nullable) di-set setiap harga berubah.
- Audit granular action **`master.update_price`** dengan metadata
  `{source, fields, before, after}` (mis. `{"sale_price": "50000.00"}` → `{"sale_price": "61000.00"}`).
  **Tidak ada tabel baru** — riwayat dibaca dari `AuditLog` yang sudah append-only.
- Tidak ada perubahan harga ⇒ tidak ada audit/push (nilai identik diabaikan).

## MASTER-TAX (H3.6)

Pajak MES (`master.Tax` — mirror `account.tax` Odoo). Modelnya **sudah ada sejak I1.1**
(`odoo_id`/`code`/`name`/`is_active`, pull-only); H3.6 menambah **tarif & jenis** (aditif),
**CRUD**, **push**, dan penanda **pajak default MES**.

### Field

| MES | Tipe | Odoo | Catatan |
| --- | --- | --- | --- |
| `odoo_id` | bigint unik null | `account.tax.id` | kunci pencocokan (bukan nama!) |
| `code` | char(64) unik | — | di MES; kosong ⇒ dibuat dari `name` (`PPN 11%` → `PPN-11`) |
| `name` | char(255) | `name` | |
| `amount` | Decimal(5,2) | `amount` | **0 diizinkan** (PPN 0%/bebas), negatif ditolak (400) |
| `amount_type` | char(16) | `amount_type` | `percent` (default) \| `fixed` |
| `type_tax_use` | char(16) | `type_tax_use` | `sale` (default) \| `purchase` \| `none` |
| `price_include` | bool | `price_include` | |
| `is_default` | bool | — | **mes-only** (tidak pernah ditarik/dikirim) |
| `is_active` | bool | `active` | DELETE API = soft delete |

### Arah data (PENTING)

- **Push** (setiap POST/PUT/DELETE): `erp_sync.push_master_tax` mengirim
  `{name, amount, amount_type, type_tax_use, price_include, active}`.
  **`tax_group_id` TIDAK dikirim** — di Odoo field itu `required=True` tetapi
  `compute='_compute_tax_group_id'`/`readonly=False` (`account/models/account_tax.py`
  134–139 & 227–239) sehingga Odoo mengisinya dari (`country_id`, `company_id`); sama pola
  `stock.warehouse.view_location_id` (H1.3).
- **Pull** (`sync_master_taxes`, beat harian): `TAX_FIELDS` =
  `["id", "name", "amount", "amount_type", "type_tax_use", "price_include"]`; mapper
  `_tax_defaults` memakai aturan **"isi bila masih default bawaan"** —
  `amount` diisi hanya bila MES **0**, `amount_type`/`type_tax_use`/`price_include` hanya bila
  MES masih `percent`/`sale`/`False`. Konfigurasi yang sudah diubah operator **tidak ditimpa**;
  `is_default` **tidak pernah** ditarik.
- **Pencocokan jelas**: `odoo_id` (`unique`), **bukan nama** — sample dev membuktikan
  `'12% (Non-Luxury Good)'` bernilai `amount=11.0`.

### Seed default MES (migrasi `master.0019`, idempoten)

| amount | type_tax_use | code | nama | is_default |
| --- | --- | --- | --- | --- |
| 11.00 | sale | `PPN11-SALE` | PPN 11% | **True** |
| 11.00 | purchase | `PPN11-PURCHASE` | PPN 11% (Pembelian) | False |
| 0.00 | sale | `PPN0-SALE` | PPN 0% (Export) | False |

Pencocokan seed = `code` **atau** `(amount, type_tax_use)` yang **`odoo_id IS NULL`** (baris
mirror Odoo tidak pernah "ditempeli" seed ini; data dev punya 16 baris pull ber-`amount=0`).

### Endpoint

| Method | Path | Fungsi |
| --- | --- | --- |
| `GET` | `/api/v1/master/taxes/` | ListPage; `?search=&type_tax_use=&active=&limit=&cursor=` |
| `POST` | `/api/v1/master/taxes/` | create (+ `SyncRecord`/`AuditLog`/push) |
| `GET` | `/api/v1/master/taxes/<id>/` | detail |
| `PUT` | `/api/v1/master/taxes/<id>/` | update (hanya field dikirim) |
| `DELETE` | `/api/v1/master/taxes/<id>/` | **soft delete** (`active=False`, `is_default` dilepas) |
| `POST` | `/api/v1/master/taxes/<id>/set-default/` | jadikan pajak default MES (atomik) |
| `GET` | `/api/v1/master/taxes/default/` | pajak default untuk form SO/PO/invoice |

Izin: GET = semua user terautentikasi (anon 403); tulis (POST/PUT/DELETE/set-default) =
**`ADMIN`/`OWNER`** (`require_master_admin`, pola H1.2). `PURCHASING` **baca** untuk dropdown
`tax_ids` di form SO/PO.

### Non-breaking (dikunci test)

`OrderLine.tax_ids` (H2.1) & `PurchaseOrderLine.tax_ids` (H2.2) tetap M2M `master.Tax` yang
sama; push SO (`tasks_order_push.py`, m2m `tax_id`) dan push PO
(`tasks_purchase_order_push.py`, m2m `taxes_id`) **tidak diubah**. Bila perubahan
`is_default` saja ⇒ **tidak ada push** (mes-only, hanya `AuditLog`).


## CUSTOMER-INVOICE (H3.1)

Customer invoice MES (`master` → transaksi): model **`garment.CustomerInvoice`** +
`CustomerInvoiceLine` (greenfield) yang di-push ke Odoo sebagai `account.move`
**draft**. Jalur **manual** (akuntan memilih order, melengkapi harga & pajak nyata) —
**coexist** dengan jalur otomatis I5 yang **tidak diubah**.

### Dua jalur invoice (JANGAN diadu)

| | I5 otomatis (`erp_sync.sync_invoice`) | H3.1 manual (`erp_sync.push_customer_invoice`) |
| --- | --- | --- |
| Pemicu | listener `WORK_ORDER_STATE_CHANGED` (semua WO selesai) + beat */15 | aksi `CONFIRMED` di UI |
| Sumber | `Order` (tanpa model) | `CustomerInvoice` (model MES) |
| Ledger | `SyncRecord(resource="order", stage="INVOICE")` | `SyncRecord(resource="customer_invoice", stage="INVOICE")` |
| Isi baris | `price_unit=0`, tanpa `tax_ids` (pengingat akuntan) | harga & pajak **nyata** dari baris invoice |
| Endpoint baca | `GET /api/v1/finance/invoices/` (F10/F15, amplop `has_next`, dari SyncRecord) | `GET /api/v1/finance/customer-invoices/` (amplop `has_more`, model) |

Dua jalur memakai **stage yang sama** (`INVOICE`) tetapi **resource berbeda** ⇒ tidak
saling menimpa; `CustomerInvoice.order` **tidak** unique (satu order boleh >1 invoice:
termin/DP — UI memberi `duplicate_warning`, backend **tidak** memblokir).

### Field MES & guard

`code` (`INV-<TAHUN>-<SEQ>` dari Sprint C `next_number('INV')`), `order` (PROTECT),
`customer` (PROTECT), `invoice_date`, `due_date` (opsional), `state`
(`DRAFT|CONFIRMED|SENT|DONE|CANCELLED`), `notes`, `odoo_id` (unik, dari push),
baris: `order_line` (SET_NULL), `product` (PROTECT), `qty`, `price_unit`,
`tax_ids` (m2m `master.Tax`), `line_total` (qty × harga, **sebelum** pajak).

Guard `CONFIRMED` (semua → **400**, bukan push cacat): minimal satu baris; **semua
`price_unit > 0`** (§5); `customer.odoo_id` ada; tiap `product.odoo_id` ada; tiap
`tax.odoo_id` ada. Kegagalan push **bukan** state model — `SyncRecord.status=FAILED` +
`last_error`, invoice tetap `CONFIRMED` (bisa di-retry, idempoten via `SyncRecord`).

### Endpoint (izin tulis **ADMIN/OWNER**; baca semua user terautentikasi)

| Method | Path | Fungsi |
| --- | --- | --- |
| `GET` | `/api/v1/finance/customer-invoices/` | ListPage; `?search=&state=&customer_id=&order_id=&limit=&cursor=` |
| `POST` | `/api/v1/finance/customer-invoices/` | create (+ `lines[]` nested/auto-fill dari `OrderLine`) |
| `GET/PUT/DELETE` | `/api/v1/finance/customer-invoices/<id>/` | detail / update / hapus (**DRAFT-only**, hard delete) |
| `POST` | `/api/v1/finance/customer-invoices/<id>/confirm/` | `DRAFT → CONFIRMED` + enqueue push |
| `POST` | `/api/v1/finance/customer-invoices/<id>/done/` | `CONFIRMED|SENT → DONE` (murni MES) |
| `POST` | `/api/v1/finance/customer-invoices/<id>/cancel/` | `→ CANCELLED` (+ `button_cancel` bila `odoo_id`) |

### Payload push (probe STEP 0 + sumber Odoo 17)

`{partner_id, move_type: "out_invoice"` (**wajib dikirim** — `default_get` menjawab
`'entry'`), `invoice_date`, `ref`, `invoice_line_ids: [(0,0,{product_id, quantity,
price_unit, name, tax_ids: [(6,0,[id…])]})]}`, `invoice_date_due` bila ada.
`account_id`/`product_uom_id` **tidak** dikirim (Odoo mengisi dari produk —
terbukti pada sample dev), `journal_id`/`currency_id` default company, dan
`action_post` **tidak** dipanggil (invoice dibiarkan draft).


## VENDOR-BILL (H3.2)

Tagihan vendor MES: model **`garment.VendorBill`** + `VendorBillLine` (greenfield) yang
di-push ke Odoo sebagai `account.move` **draft** bertipe **`in_invoice`**. Jalur
**manual** (operator membuat bill dari PO H2.2 atau manual, melengkapi harga & pajak
nyata) — **coexist** dengan jalur tarik **I6** yang **tidak diubah**.

### Dua jalur vendor bill (arah berlawanan, JANGAN diadu)

| | I6 tarik (read-only) | H3.2 dorong (`erp_sync.push_vendor_bill`) |
| --- | --- | --- |
| Arah | Odoo → MES | MES → Odoo |
| Pemicu | task `erp_sync.recompute_readiness` (`tasks_vendor_bill.py`, beat harian 04:00) | aksi `CONFIRMED` di UI |
| Sumber/target | `transport.fetch_vendor_bills()` (`VENDOR_BILL_FIELDS`) | model `VendorBill` (MES) |
| Hasil | `MaterialReadiness.vendor_bill_ids/vendor_bill_status/vendor_bill_amount` | `SyncRecord(resource="vendor_bill", stage="VENDOR_BILL")` + `account.move` draft |
| File task | `tasks_vendor_bill.py` (**tidak disentuh**) | `tasks_vendor_bill_push.py` (baru) |

`SyncResource.VENDOR_BILL` **dan** `SyncStage.VENDOR_BILL` sama-sama **baru** (stage
`INVOICE` milik I5/H3.1 **tidak** dipakai ulang karena dokumennya `in_invoice`/label
monitor berbeda) ⇒ tidak pernah menimpa baris `SyncRecord` jalur lain. `VendorBill`
tidak menulis apa pun ke `MaterialReadiness`.

### Field MES & guard

`code` (`VB-<TAHUN>-<SEQ>` dari Sprint C `next_number('VB')`), `purchase_order`
(PROTECT, **nullable** — bill tanpa PO = biaya jasa; **tidak** unique — satu PO boleh
>1 bill: termin/partial, UI memberi `duplicate_warning`), `vendor` (PROTECT), `ref`
(nomor bill dari vendor, **best-effort**), `invoice_date`, `due_date` (opsional),
`state` (`DRAFT|CONFIRMED|SENT|DONE|CANCELLED`), `notes`, `odoo_id` (unik, dari push,
kunci idempotensi); baris: `po_line` (SET_NULL), `product` (PROTECT), `qty`,
`price_unit`, `tax_ids` (m2m `master.Tax`), `line_total` (qty × harga, **sebelum** pajak).

Guard `CONFIRMED` (semua → **400**, bukan push cacat): minimal satu baris; **semua
`qty > 0`**; **semua `price_unit >= 0`** (harga 0 **diizinkan** — beda dari customer
invoice H3.1 yang menuntut `> 0`); `vendor.odoo_id` ada; tiap `product.odoo_id` ada;
tiap `tax.odoo_id` ada. Kegagalan push **bukan** state model —
`SyncRecord.status=FAILED` + `last_error`, bill tetap `CONFIRMED` (bisa di-retry).
`ref` **tidak** pernah memblokir: hanya dibatasi 64 karakter (Odoo `account.move.ref`
`required=False`, tanpa `required="1"` di view, tanpa constraint duplikasi — probe
STEP 0 2026-10-13).

### Endpoint (izin tulis **ADMIN/OWNER**; baca semua user terautentikasi)

| Method | Path | Fungsi |
| --- | --- | --- |
| `GET` | `/api/v1/finance/vendor-bills/` | ListPage; `?search=&state=&vendor_id=&purchase_order_id=&limit=&cursor=` |
| `POST` | `/api/v1/finance/vendor-bills/` | create (+ `lines[]` nested/auto-fill dari `PurchaseOrderLine`) |
| `GET/PUT/DELETE` | `/api/v1/finance/vendor-bills/<id>/` | detail / update / hapus (**DRAFT-only**, hard delete) |
| `POST` | `/api/v1/finance/vendor-bills/<id>/confirm/` | `DRAFT → CONFIRMED` + enqueue push |
| `POST` | `/api/v1/finance/vendor-bills/<id>/done/` | `CONFIRMED|SENT → DONE` (murni MES) |
| `POST` | `/api/v1/finance/vendor-bills/<id>/cancel/` | `→ CANCELLED` (+ `button_cancel` bila `odoo_id`) |

### Payload push (probe STEP 0 + sumber Odoo 17)

`{partner_id, move_type: "in_invoice"` (**wajib dikirim** — `default_get` menjawab
`'entry'`), `ref`, `invoice_date`, `invoice_line_ids: [(0,0,{product_id, quantity,
price_unit, name, tax_ids: [(6,0,[id…])]})]}`, `invoice_date_due` bila ada.

**Tidak** dikirim (dihitung Odoo): `journal_id` (purchase journal), `currency_id`,
`date`, `account_id` (dari produk/kategori), `product_uom_id`, `invoice_origin`
(`readonly=True`), dan `purchase_line_id` (PO MES di Odoo masih `draft` ⇒ tautan baris
bill ke `purchase.order.line` berisiko ditolak). `action_post` **tidak** dipanggil →
bill dibiarkan **draft** untuk diperiksa akuntan. Field pajak barisnya **`tax_ids`**
(`account.move.line`), **bukan** `taxes_id` milik `purchase.order.line` (H2.2).


## PAYMENT (H3.3)

Pembayaran MES (**greenfield**, tidak ada entitas payment sebelumnya): model
**`garment.Payment`** yang di-push ke Odoo sebagai `account.payment` **draft** —
**satu model dua arah** (`payment_type` `INBOUND`/`OUTBOUND`) persis seperti
`account.payment` Odoo.

### Relasi sumber (keputusan STEP 0 = Opsi A)

| `payment_type` | Sumber | Arti |
| --- | --- | --- |
| `INBOUND` | `customer_invoice` (H3.1 `CustomerInvoice`) | customer membayar kita (Odoo `payment_type=inbound`, `partner_type=customer`) |
| `OUTBOUND` | `vendor_bill` (H3.2 `VendorBill`) | kita membayar vendor (Odoo `outbound`/`supplier`) |

Dua FK **nullable** (`customer_invoice`, `vendor_bill`, keduanya `PROTECT`, **tidak**
unique — satu dokumen boleh dibayar beberapa kali: termin/partial) + `CheckConstraint`
DB **`chk_payment_tepat_satu_sumber`** yang mewajibkan **tepat satu** terisi.
Opsi `content_type` (generic FK) **ditolak** — lebih rumit tanpa manfaat untuk dua sumber.
**Multi-dokumen satu payment = sprint terpisah.**

Ledger: `SyncResource.PAYMENT` (`"payment"`) **dan** `SyncStage.PAYMENT` (`"PAYMENT"`)
sama-sama **baru** ⇒ tidak menimpa baris `SyncRecord` I5/H3.1 (`INVOICE`) atau H3.2
(`VENDOR_BILL`). **I5/I6 tidak disentuh**; `MaterialReadiness` tetap dibaca dari Odoo
(module ini **tidak** menulis `payment_state`/`paid_amount` apa pun — Odoo = source of
truth; pull `payment_state` = sprint terpisah, pola I6 `vendor_bill_status`).

### Field MES & guard

`code` (`PAY-<TAHUN>-<SEQ>` dari Sprint C `next_number('PAY')` — sudah ter-seed
`0014_seed_sequences.py`), `payment_type` (`INBOUND|OUTBOUND`), `partner` (PROTECT,
diturunkan dari dokumen sumber bila tidak dikirim), `customer_invoice`/`vendor_bill`
(tepat satu), `amount` (Decimal 18,2), `currency` (**MES-only**, `IDR`), `payment_date`,
`payment_method` (**MES-only**: `manual|bank|cash`), `reference` (no. referensi bank MES,
≤ 64 char), `memo` (catatan MES), `state`
(`DRAFT|CONFIRMED|SENT|DONE|CANCELLED`), `notes`, `odoo_id` (unik, kunci idempotensi).

**Guard anti-overpay** (keputusan STEP 0 — **BLOKIR 400**): Σ `amount` payment **aktif**
(state ≠ `CANCELLED`) dokumen sumber + `amount` baru **tidak boleh** melebihi
`amount_total` dokumen. Divalidasi tiga kali: saat **create**, saat **update**
(mengecualikan payment itu sendiri), dan **diulang saat `CONFIRMED`** (defensive).
Perhitungan **murni MES** (deterministik, tanpa Odoo) memakai field **baru**
`amount_total` (Decimal 18,2) di `CustomerInvoice` **dan** `VendorBill` yang
disinkronkan service H3.1/H3.2 setiap baris ditulis (migrasi aditif `garment/0021` +
`garment/0022`; `amount_total` juga dikembalikan detail/list kedua dokumen itu).

Guard `CONFIRMED` lain (semua → **400**, bukan push cacat): dokumen sumber masih ada;
`amount > 0`; `payment_date` terisi; `partner.odoo_id` ada. Kegagalan push **bukan**
state model — `SyncRecord.status=FAILED` + `last_error`, payment tetap `CONFIRMED`
(bisa di-retry, idempoten via `SyncRecord`).

### Endpoint (izin tulis **ADMIN/OWNER**; baca semua user terautentikasi)

| Method | Path | Fungsi |
| --- | --- | --- |
| `GET` | `/api/v1/finance/payments/` | ListPage; `?search=&state=&payment_type=&partner_id=&customer_invoice_id=&vendor_bill_id=&limit=&cursor=` |
| `POST` | `/api/v1/finance/payments/` | create (guard overpay; nomor `PAY-…`) |
| `GET/PUT/DELETE` | `/api/v1/finance/payments/<id>/` | detail / update / hapus (**DRAFT-only**, hard delete) |
| `POST` | `/api/v1/finance/payments/<id>/confirm/` | `DRAFT → CONFIRMED` + enqueue push |
| `POST` | `/api/v1/finance/payments/<id>/done/` | `CONFIRMED|SENT → DONE` (murni MES) |
| `POST` | `/api/v1/finance/payments/<id>/cancel/` | `→ CANCELLED` (+ `action_cancel` bila `odoo_id`) |

Detail menambah `{odoo_sync_status, odoo_sync_error, allowed_actions,
source_amount_total, source_remaining_amount}`; POST/PUT/aksi menambah
`{sync_record_id, task_id, queued}` (pola H3.1/H3.2). Payment **baru** memakai
`status=201`; state awal **DRAFT** (MES-only).

### Payload push (probe STEP 0 + sumber Odoo 17)

`{payment_type: "inbound"|"outbound", partner_type: "customer"|"supplier",
partner_id: <odoo_id>, amount, date, payment_reference: "<kode MES PAY-…>",
ref: <referensi bank MES, fallback kode MES>}` + **opsional** `journal_id` **hanya**
bila setting `ODOO_PAYMENT_JOURNAL_ID` diisi (dev: `13` = Bank `BNK1`; kosong ⇒ Odoo
memilih sendiri lewat `_search_default_journal()`).

**Tidak** dikirim karena dihitung Odoo / tidak ada / readonly: `currency_id` (computed
dari journal/company), `payment_method_line_id` (computed per journal × `payment_type`,
dijaga constraint), `reconciled_invoice_ids`/`reconciled_bill_ids` (**`readonly=True`**),
dan `memo`/`communication` (**field itu tidak ada di Odoo 17** — catatan MES **tidak**
dikirim). `account.payment` `_inherits {'account.move': 'move_id'}` ⇒ create otomatis
membuat satu `account.move` **draft**.

### Rekonsiliasi BUKAN tanggung jawab MES

MES hanya membuat payment **draft**; `action_post` **tidak** dipanggil dan MES **tidak**
mereconcile. Posting + rekonsiliasi dilakukan akuntan di Odoo (probe membuktikan
`reconciled_*` readonly ⇒ MES memang tidak diizinkan menulisnya). Cancel setelah
terkirim memakai `account.payment.action_cancel`; kalau Odoo menolak (payment sudah
diposting), pembatalan di MES tetap sah dan kegagalannya hanya tercatat di
`SyncRecord` (pola `cancel_vendor_bill` H3.2).

## JOURNAL-ENTRY (H3.4)

Jurnal **manual double-entry** MES (**greenfield**, sebelumnya MES tidak punya jurnal
manual) di-push ke Odoo sebagai `account.move` `move_type='entry'` **draft**.

Model **`garment.JournalEntry`** + baris **`garment.JournalEntryLine`**:

| Field | Isi |
| --- | --- |
| `code` | nomor MES `JE-<TAHUN>-<URUT>` (`next_number('JE')`, Sprint C) — **MES-only** |
| `journal` | FK `master.Journal` (PROTECT); **hanya `journal_type='general'`** |
| `entry_date` | tanggal jurnal (Odoo `date` required ⇒ wajib di MES) |
| `ref` | referensi MES (≤ 64 char, opsional) → Odoo `ref` |
| `memo`/`notes` | catatan MES (**tidak** dikirim; Odoo 17 tanpa `narration` terpakai) |
| `total_debit`/`total_credit` | Σ baris (denormalisasi untuk audit + guard) |
| `state` | `DRAFT → CONFIRMED → SENT → DONE` + `CANCELLED` (state BISNIS) |
| `odoo_id` | id `account.move` Odoo (`null` = belum terkirim) |

Baris `JournalEntryLine`: `account` (FK `master.Account`, PROTECT), `partner` (FK
`master.Partner`, opsional/nullable), `name`, `debit`/`credit` (Decimal 18,2) —
**`CheckConstraint` DB `chk_journal_entry_line_debit_xor_credit`** (tepat satu > 0,
tidak negatif).

**Guard sebelum `CONFIRMED`** (semua → **400**, bukan draft cacat):

* journal punya `odoo_id` **dan** (bila `journal_type` diketahui) bertipe `general`.
  `journal_type` **kosong** (baris lama belum pernah di-pull) ⇒ guard **longgar**,
  keputusan diserahkan ke Odoo;
* minimal **2 baris**; tiap baris **debit XOR credit** (> 0); tiap `account.odoo_id`
  ada (kalau belum → 400 + daftar akun yang kurang);
* **Σ debit = Σ kredit** dihitung murni MES dengan toleransi **0.01**
  (`BALANCE_TOLERANCE`) — deterministik, tanpa Odoo.

Kegagalan push **bukan** state model: `SyncRecord.status=FAILED` + `last_error`,
entry tetap `CONFIRMED` (retry idempoten, pola H3.1–H3.3). Ledger memakai
**`SyncResource.JOURNAL_ENTRY`** (`"journal_entry"`) **dan** `SyncStage.JOURNAL_ENTRY`
(`"JOURNAL_ENTRY"`) — keduanya **BARU** (keputusan STEP 0) sehingga tidak menimpa
`INVOICE`/`VENDOR_BILL`/`PAYMENT` milik dokumen dagang. Migrasi aditif:
`erp_sync/0024_alter_syncrecord_*`, `master/0020_account_journal_journal_type`,
`garment/0024_journalentry_journalentryline_and_more`.

**Master pendukung (read-only, pull-only):** `master.Account` (chart of accounts)
di-pull `erp_sync.sync_master_accounts` dari ``account.account`` — Odoo 17 **tidak**
punya field `active` di model itu ⇒ `is_active = not deprecated`; ``master.Journal``
mendapat field aditif `journal_type` (hasil pull `account.journal.type`). Keduanya
dipakai dropdown form dan **tidak** pernah di-push dari MES (chart of accounts &
journal = wewenang akuntan Odoo).

| Method | Path | Catatan |
| --- | --- | --- |
| `GET` | `/api/v1/finance/journal-entries/` | ListPage; `?search=&state=&journal_id=&date_from=&date_to=&limit=&cursor=` |
| `POST` | `/api/v1/finance/journal-entries/` | create (guard double-entry; nomor `JE-…`) |
| `GET/PUT/DELETE` | `/api/v1/finance/journal-entries/<id>/` | detail (`lines[]`) / update / hapus (**DRAFT-only**, hard delete) |
| `POST` | `/api/v1/finance/journal-entries/<id>/confirm/` | `DRAFT → CONFIRMED` + enqueue `erp_sync.push_journal_entry` |
| `POST` | `/api/v1/finance/journal-entries/<id>/done/` | `CONFIRMED|SENT → DONE` (murni MES) |
| `POST` | `/api/v1/finance/journal-entries/<id>/cancel/` | `→ CANCELLED` (+ `button_cancel` bila `odoo_id`) |
| `GET` | `/api/v1/master/accounts/` + `/<id>/` | chart of accounts (**read-only**, tulis → 405) |
| `GET` | `/api/v1/master/journals/` + `/<id>/` | journal + `journal_type` (**read-only**, tulis → 405) |

Respons tulis = baris detail + `{sync_record_id, task_id, queued}` (pola H3.1–H3.3).
Izin tulis = **ADMIN/OWNER** (baca semua user yang login).

Payload adapter (`OdooAdapter.push_journal_entry`) — **tanpa** field yang dikarang:

```
{move_type: "entry", journal_id: <odoo_id>, date: "YYYY-MM-DD", ref: "<ref|kode MES>",
 line_ids: [(0, 0, {account_id, name, debit, credit, partner_id?})]}
```

* `move_type='entry'` dikirim **eksplisit**; `line_ids` = one2many command;
* `currency_id`/`company_id`/`narration`/`display_type` **tidak** dikirim (Odoo
  menghitung/men-default);
* **`action_post` TIDAK pernah dipanggil** — MES hanya membuat draft dan **posting +
  rekonsiliasi adalah pekerjaan akuntan Odoo** (keputusan STEP 0; satu-satunya
  pengecualian konseptual di Phase H3: entry manual bukan dokumen dagang);
* pembatalan setelah terkirim memakai `account.move.button_cancel`; kalau Odoo
  menolak (sudah diposting), pembatalan di MES tetap sah dan kegagalannya hanya
  tercatat di `SyncRecord` (pola `cancel_vendor_bill` H3.2).

Frontend (H3.4): `types/journal-entry.ts` (+ `master-account`/`master-journal`),
`api/real/journalEntries.ts` + barrel `api/journalEntries.ts` (+ `masterAccounts`/
`masterJournals` read-only), `lib/journal-entry.ts` (PURE: validasi, balance, mapping
form), halaman `JournalEntriesPage`/`JournalEntryFormPage`/`JournalEntryDetailPage`
pada route `/finance/journal-entries*` (guard `FINANCE_ROLES`) + item menu Finance;
`MODE.journalEntries`/`masterAccounts`/`masterJournals` = `real`.


