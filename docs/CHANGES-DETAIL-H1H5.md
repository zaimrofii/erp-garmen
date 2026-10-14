# CHANGES DETAIL — H1–H5 (MES sebagai ERP Produksi)

**Berlaku sejak:** 2026-10-10
**Untuk:** AI/Cline/senior dev yang melanjutkan pengembangan H1–H5
**Konteks:** MES = ERP Produksi (single point of input). Odoo = back-office pasif.

> Baca juga: `docs/REPLACE-NOTICE.md` (konsep baru), `docs/blueprint.md` (arsitektur).

---

## 🔴 CRITICAL — Jangan Sampai Salah

### 1. Arah Sync (KRITIS)

| Data                                                                                 | Arah                       | Alasan                                                                                          |
| ------------------------------------------------------------------------------------ | -------------------------- | ----------------------------------------------------------------------------------------------- |
| **Master** (Product, Partner, BOM, UoM, Warehouse, Location, Tax, Journal, Currency) | **Dua arah**               | Klien lama sudah punya data di Odoo → harus bisa tarik. Klien baru input di MES → push ke Odoo. |
| **Transaksi** (SO, PO, WO, Bundle, Scrap, Invoice, Bill, Payment)                    | **Satu arah (MES → Odoo)** | MES = source of truth. Odoo hanya pencatat pasif.                                               |

**Implikasi:**

- Endpoint master CRUD butuh **2 mode**: `source='mes'` (MES master) atau `source='odoo'` (ditarik Odoo)
- Setiap perubahan master di MES → **push async** ke Odoo via Celery
- Setiap perubahan master di Odoo (jarang) → **tarik berkala** via beat (mis. tiap 1 jam)

### 2. `odoo_id` = Kunci Idempotensi (WAJIB)

Semua model master **HARUS** punya field `odoo_id` (`PositiveBigIntegerField`, nullable, `db_index=True`).

- Saat MES buat Product baru → sync ke Odoo → **simpan `odoo_id`** dari response
- Saat sync master dari Odoo → `update_or_create(odoo_id=...)`
- **Jangan pernah** pakai `code` atau `name` sebagai kunci sync — bisa duplikat.

### 3. Number Sequence (Auto-Numbering)

MES harus punya **number sequence sendiri**, terpisah dari Odoo:

- `SO-2026-0001`, `PO-2026-0001`, `WO-2026-0001`, `INV-2026-0001`, `BB-2026-0001`
- **Format:** `<PREFIX>-<YEAR>-<SEQ:04d>`
- **Reset per tahun**
- **Sync ke Odoo:** kirim `ref` = number MES, biarkan Odoo punya number sendiri (mis. `SO/2026/0001`)
- **JANGAN** pakai number Odoo sebagai primary reference

### 4. Stock Move = Dompet Kosong

MES **TIDAK** simpan stok sendiri (kecuali WIP/FG di Bundle).

- Stok master ada di **Odoo** (per lokasi)
- MES hanya **trigger stock move** via sync (WIP issue, FG receipt, scrap)
- Untuk tampilan stok → **fetch on-demand dari Odoo** (dengan cache 5 menit)

**Implikasi:**

- Kalau Odoo down → stok tidak tampil (kecuali cache)
- Jangan bikin tabel `StockQuantity` di MES — duplikasi & rawan drift

### 5. Harga Jual & HPP (Belum Ada di MES)

- Saat ini **harga jual = 0** di invoice (I5)
- H1–H3 harus tambah:
  - `Product.sale_price` (harga jual)
  - `Product.cost_price` (HPP)
  - `OrderLine.price_unit`
  - `PurchaseOrderLine.price_unit`
- **Sync ke Odoo:** push harga saat invoice/bill
- **Jangan biarkan** invoice ter-post dengan harga 0 → **validasi di MES**: `price_unit > 0` sebelum push

### 6. Tax/PPN (Baru)

- Tambah `Tax` model di MES (reuse `master.Tax` yang sudah ada)
- Invoice harus punya field `tax_ids[]` (list FK ke Tax)
- **Default PPN 11%** (Indonesia 2026) — konfigurabel di Settings
- Sync ke Odoo: kirim `tax_ids` saat create `account.move`

---

## 🟡 PENTING — Jangan Lupa

### 7. Role Baru: `purchasing`

- Sudah ada di frontend (F3-A) tapi belum di `Role.Code` backend
- **Tambah** role `PURCHASING` di seeding migration
- Akses: `/purchase/*` (orders, vendors, reporting, bills)

### 8. Field yang Sering Dibutuhkan UI Tapi Belum Ada

Tambahkan di model master saat H1:

| Model            | Field Baru                                                              | Untuk                |
| ---------------- | ----------------------------------------------------------------------- | -------------------- |
| `Product`        | `category`, `sale_price`, `cost_price`, `weight`, `image_url`, `uom_id` | Form produk lengkap  |
| `Partner`        | `email`, `phone`, `city`, `address`, `npwp`, `is_vendor`, `is_customer` | Form partner lengkap |
| `BOM`            | `output_qty`, `is_active`                                               | Harga HPP            |
| `WorkCenter`     | `wc_type`, `capability_tags`, `capacity_per_hour`                       | Routing, allocator   |
| `ProductionLine` | `capability_tags`                                                       | Allocator            |

### 9. Sync Idempotency Wajib di Semua CRUD

- Setiap endpoint POST/PUT/DELETE master → **tulis `SyncRecord`**
- Resource baru: `master.product`, `master.partner`, `master.bom`, dst.
- Stage baru: `MASTER_PUSH` (MES → Odoo), `MASTER_PULL` (Odoo → MES)
- **Jangan pakai `stage='WIP'/'FG'/'SCRAP'/'INVOICE'`** — itu untuk transaksi produksi

### 10. Audit Trail untuk CRUD

- Setiap create/update/delete master → **AuditLog** (action: `master.create|update|delete`)
- Field metadata: `{model, odoo_id, changes: {...}}`
- Gunakan `core/audit/AuditLogger` yang sudah ada

---

## 🟢 NICE TO HAVE

### 11. Import/Export Excel

- Setiap list master → tombol **Export Excel**
- Bulk import via template Excel (Product, Partner, BOM)
- Gunakan `openpyxl` (sudah ada di requirements kalau perlu)

### 12. Validasi Bisnis

- Product code **unik**
- Partner NPWP **format valid** (kalau diisi)
- BOM **tidak boleh** punya siklus (product jadi bahan dirinya)
- SO deadline **tidak boleh** < hari ini
- PO expected_date **tidak boleh** < hari ini

### 13. Multi-UoM

- Product bisa punya **UoM beli** & **UoM jual** berbeda (mis. beli roll, jual pcs)
- Field: `uom_purchase_id`, `uom_sale_id`, `uom_ratio`
- Konversi otomatis saat SO/PO

### 14. Draft → Confirmed → Done State

Semua transaksi (SO, PO, WO, Invoice) punya state machine:

- `DRAFT` (editable)
- `CONFIRMED` (locked, siap produksi)
- `DONE` (selesai, sync Odoo)
- `CANCELLED` (batal)
- **Hanya DRAFT** yang bisa di-edit/delete

---

## ⚠️ JANGAN LAKUKAN

1. ❌ **Jangan bikin tabel stock (hanya menampilkan data dari odoo, bukan simpan di django)** di MES — Odoo yang simpan
2. ❌ **Jangan embed iframe Odoo** — MES app single
3. ❌ **Jangan pakai `code`/`name` sebagai kunci sync** — pakai `odoo_id`
4. ❌ **Jangan sync transaksi dari Odoo ke MES** — satu arah saja
5. ❌ **Jangan bikin endpoint `/api/v1/master/*`** kalau sudah ada di `/api/v1/settings/*` — cek dulu (routing/bundling/line-allocation sudah ada di settings)
6. ❌ **Jangan hapus field lama** — hanya tambah (backward compat)
7. ❌ **Jangan lupa `odoo_id`** di response — frontend butuh untuk debug sync

---

## 📋 CHECKLIST SEBELUM MULAI H1

- [ ] `docs/REPLACE-NOTICE.md` sudah dibuat
- [ ] `docs/CHANGES-DETAIL-H1H5.md` (dokumen ini) sudah dibuat
- [ ] `curent_project.json` sudah di-tambah `concept_notice`
- [ ] Tim/AI sudah baca dokumen ini
- [ ] Keputusan sync arah: **dua arah master, satu arah transaksi** ✅
- [ ] Keputusan Odoo peran: **back-office pasif** ✅
- [ ] Keputusan number sequence: **MES punya sendiri** ✅
- [ ] Role `PURCHASING` akan ditambah di H1

---

## 🎯 URUTAN IMPLEMENTASI H1 (WAJIB IKUT)

Dependency antar modul:

1. **H1.1 Product** — paling fundamental, semua modul butuh Product
2. **H1.2 UoM** — dibutuhkan Product (`uom_id` FK)
3. **H1.3 Warehouse** — dibutuhkan Inventory
4. **H1.4 Location** — dibutuhkan Inventory
5. **H1.5 Partner** — dibutuhkan SO/PO (customer/vendor)
6. **H1.6 BOM** — dibutuhkan Produksi (material readiness)
7. **H1.7 Work Center** — dibutuhkan Routing
8. **H1.8 Production Line** — dibutuhkan Routing
9. **H1.9 Process Routing** — terakhir (depend ke WC + Line)

**Jangan lompat urutan** — akan bikin dependency rusak.

---

## 📊 URUTAN H1–H5 LENGKAP

| Fase      | Isi                                                                                 | Durasi          |
| --------- | ----------------------------------------------------------------------------------- | --------------- |
| **H1**    | Master CRUD (9 modul)                                                               | 1 minggu        |
| **H2**    | Transaksi (SO, PO, WO, Bundle, Inventory Adj, Transfer)                             | 1.5 minggu      |
| **H3**    | Finance (Invoice, Bill, Payment, Journal, Product Price, Tax)                       | 1 minggu        |
| **H4**    | Laporan (Sales, Purchases, Stock, HPP, PnL, Production, Dashboard, Export)          | 1 minggu        |
| **H5**    | Settings (Company, Currency, Sequence, Permission, Audit, Integration, Printer, WA) | 1 minggu        |
| **Total** |                                                                                     | **~5–6 minggu** |

---

## 🎯 POLA IMPLEMENTASI PER MODUL

**1 modul = 1 siklus Backend → Frontend → JSON.**

### Step A — Backend (~40 baris prompt)

- Extend model (kalau perlu) + migration
- Endpoint CRUD (GET/POST/PUT/DELETE)
- Sync ke Odoo (push async + pull berkala)
- Audit + validasi + idempotency (`SyncRecord`)
- Test minimum 15 per modul
- Gate: pytest hijau, 0 breaking change, `makemigrations --check` OK

### Step B — Frontend (~30 baris prompt)

- Adapter real (`src/api/real/<resource>.ts`)
- Halaman list + form + detail
- Route di `App.tsx` + nav-config
- Test minimum 10 per modul
- Gate: typecheck + lint + test + build hijau

### Step C — JSON Update (~10 baris prompt)

- Update `django_app/docs/curent_project.json` + `frontend_app_v2/docs/current-project.json`
- 1 entry per modul

---

## 📌 RINGKAS

| Aturan          | Nilai                                                                      |
| --------------- | -------------------------------------------------------------------------- |
| Sync master     | Dua arah                                                                   |
| Sync transaksi  | Satu arah (MES → Odoo)                                                     |
| Kunci sync      | `odoo_id`                                                                  |
| Number sequence | MES punya sendiri, format `<PREFIX>-<YEAR>-<SEQ>`                          |
| Stock           | Di Odoo, MES fetch on-demand                                               |
| Harga & tax     | Tambah di H1–H3, wajib > 0 sebelum push                                    |
| State transaksi | DRAFT → CONFIRMED → DONE → CANCELLED                                       |
| Idempotency     | SyncRecord setiap CRUD master                                              |
| Audit           | AuditLog setiap CRUD master                                                |
| Urutan H1       | Product → UoM → Warehouse → Location → Partner → BOM → WC → Line → Routing |

---

**Dokumen ini mengikat sampai ada notice resmi pengganti.**
