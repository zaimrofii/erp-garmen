# `docs/uat/03-skenario.md` — Daftar Skenario per Sesi

File terbesar. Saya susun lengkap Sesi 0–6 dengan format seragam yang bisa disalin ke `04-hasil/` dan `05-defect-log.md`.

```markdown
# 03 — Daftar Skenario UAT

> **Berlaku:** 2026-10-27 · **Versi:** 1.0
> **Total:** 96 skenario (Sesi 0–6)
> **Format:** Setiap skenario punya ID, role, prasyarat, langkah, hasil diharapkan, hasil aktual (diisi saat UAT), bukti, label, dampak.

---

## Cara Pakai

1. Salin blok skenario ke `04-hasil/sesi-X-*.md` saat menjalankan.
2. Isi **Hasil aktual**, **Bukti**, **Label**.
3. Bila FAIL/BUG → catat di `05-defect-log.md` dengan ID `D-XXX`.
4. Gate sesi diputuskan di `06-signoff.md`.

**Label:** `PASS` / `FAIL` / `BLOCKED` / `SKIP`
**Tipe temuan (bila FAIL):** `BUG` / `SPEC-GAP` / `MISUNDERSTANDING` / `IMPROVEMENT` / `DATA`

---

## Sesi 0 — Smoke & Login (30 menit, 4 skenario)

### SK-0.1 — Login 7 role & redirect
- **Role:** semua
- **Prasyarat:** staging jalan, seed sukses
- **Langkah:**
  1. Login `admin`, `owner`, `supervisor`, `qc1`, `inventory`, `purchasing`, `finance` via `/login` (username+password)
  2. Login operator (`op-andi`) via tab "Operator" (kode 4 digit)
  3. Catat URL redirect setelah login
- **Hasil diharapkan:** Semua login sukses; redirect ke app pertama role (admin→`/settings`, operator→`/production/scan`, dll); tidak ada loop `/login`.
- **Hasil aktual:** _(isi)_
- **Bukti:** _(screenshot per role)_
- **Label:** _(isi)_

### SK-0.2 — Route guard per role
- **Role:** operator (lalu admin)
- **Langkah:**
  1. Login operator → akses `/settings/users` manual
  2. Akses `/finance/customer-invoices`
  3. Login admin → akses `/production/scan`
- **Hasil diharapkan:** Operator → `AccessDenied` atau redirect; admin → boleh `/settings/users`; akses lintas role tidak bocor.
- **Hasil aktual / Bukti / Label:** _(isi)_

### SK-0.3 — Swagger & health
- **Role:** anonim
- **Langkah:**
  1. Buka `/api/health/`
  2. Buka `/api/docs/`
  3. Buka `/api/schema/`
- **Hasil diharapkan:** Health 200 `{status:"ok"}`; Swagger render; schema JSON valid.
- **Hasil aktual / Bukti / Label:** _(isi)_

### SK-0.4 — `/api/v1/auth/me/` per role
- **Role:** semua
- **Langkah:**
  1. Login tiap role → `GET /api/v1/auth/me/`
- **Hasil diharapkan:** Response memuat `username`, `role`, `permissions` yang sesuai; tidak ada role leak.
- **Hasil aktual / Bukti / Label:** _(isi)_

---

## Sesi 1 — Master & Settings (18 skenario, ~90 menit)

Role: admin/owner. Data: `02-test-data.md` §4.1.

### SK-1.1 — Create Product lengkap (H1.1)
- **Role:** admin
- **Langkah:** `POST /api/v1/master/products/` body `{code:"UAT-PRD-01", name:"Kaos UAT", uom_id:1, sale_price:50000, cost_price:40000, category:"Kaos"}`
- **Hasil diharapkan:** 201; `odoo_id` null (MES-only); `SyncRecord` MASTER_PUSH status SKIPPED/SENT; `AuditLog` tercatat.
- **Hasil aktual / Bukti / Label:** _(isi)_

### SK-1.2 — Create Product uom invalid (H1.2)
- **Role:** admin
- **Langkah:** `POST /master/products/` dengan `uom_id=99999`
- **Hasil diharapkan:** 400 dengan pesan jelas ("uom tidak ditemukan").
- **Label:** _(isi)_

### SK-1.3 — BOM self-reference (H1.5)
- **Role:** admin
- **Langkah:** `POST /master/boms/` dengan line product = header product
- **Hasil diharapkan:** 400 "self-reference".
- **Label:** _(isi)_

### SK-1.4 — BOM siklus A→B→A (H1.5)
- **Role:** admin
- **Langkah:** Buat BOM A (line B), lalu BOM B (line A)
- **Hasil diharapkan:** 400 "siklus terdeteksi"; tidak tersimpan.
- **Label:** _(isi)_

### SK-1.5 — Work Center capability_tags (H1.7)
- **Role:** admin
- **Langkah:** `POST /master/work-centers/` `{code:"UAT-WC-01", capability_tags:["Jahit","jahit","Obras"]}`
- **Hasil diharapkan:** 201; tags dedupe case-insensitive → `["jahit","obras"]`.
- **Label:** _(isi)_

### SK-1.6 — Routing DAG + steps (H1.9)
- **Role:** admin
- **Langkah:** `POST /settings/routing/` + 3 steps SEW→QC→PACK dengan edge
- **Hasil diharapkan:** 201; step id benar; `allowed_next_steps` konsisten; GET list shape B22 tidak berubah.
- **Label:** _(isi)_

### SK-1.7 — Routing siklus ditolak (H1.9)
- **Role:** admin
- **Langkah:** Tambah step dengan `next_step_ids` menunjuk ke step sebelumnya (membentuk siklus)
- **Hasil diharapkan:** 400 "siklus"; step tidak tersimpan.
- **Label:** _(isi)_

### SK-1.8 — Upload gambar produk (K5.2)
- **Role:** admin
- **Langkah:** `POST /master/products/16/image/` multipart `image=kaos.jpg` (500 KB)
- **Hasil diharapkan:** 200; `image_display_url` ada; `image_thumbnail_url` 256px; `AuditLog master.upload_image`.
- **Label:** _(isi)_

### SK-1.9 — Upload >5 MB ditolak (K5.2)
- **Role:** admin
- **Langkah:** Upload file 6 MB
- **Hasil diharapkan:** 400 "maks 5 MB".
- **Label:** _(isi)_

### SK-1.10 — Hapus produk dipakai OrderLine
- **Role:** admin
- **Langkah:** `DELETE /master/products/<id>` untuk produk yang dipakai `SO-DEMO`
- **Hasil diharapkan:** Soft delete (`is_active=false`) atau 400 guard; OrderLine tidak korup.
- **Label:** _(isi)_

### SK-1.11 — SyncRecord & AuditLog setiap CRUD master
- **Role:** admin
- **Langkah:** Create Product, lalu `GET /api/v1/sync/records/?resource=master.product&limit=1` + `GET /api/v1/settings/audit/?action=master.create&limit=1`
- **Hasil diharapkan:** SyncRecord ada (SENT/SKIPPED), AuditLog ada.
- **Label:** _(isi)_

### SK-1.12 — Create 2x Product sama (idempotency)
- **Role:** admin
- **Langkah:** Create `UAT-PRD-01` 2x berurutan
- **Hasil diharapkan:** Run ke-2 → 400 "code sudah ada" atau 200 idempoten; tidak duplikat di DB.
- **Label:** _(isi)_

### SK-1.13 — Currency guard delete (H5.2)
- **Role:** admin
- **Langkah:** `DELETE /settings/currencies/<id-IDR>/`
- **Hasil diharapkan:** 400 "protected" (IDR/USD); tidak terhapus.
- **Label:** _(isi)_

### SK-1.14 — Sequence guard delete (H5.3)
- **Role:** admin
- **Langkah:** `DELETE /settings/sequences/SO/`
- **Hasil diharapkan:** 400 "protected seed" atau "last_seq>0"; tidak terhapus.
- **Label:** _(isi)_

### SK-1.15 — Permission matrix PUT + banner (H5.4)
- **Role:** owner
- **Langkah:** `PUT /settings/permissions/<role>/` ubah 1 sel; buka `/settings/permissions` di UI
- **Hasil diharapkan:** 200; `diverges` terisi; banner "belum enforce" terlihat di UI.
- **Label:** _(isi)_

### SK-1.16 — Audit log viewer filter (H5.5)
- **Role:** admin
- **Langkah:** `GET /settings/audit/?action=master.&date_from=2026-10-27&limit=5`
- **Hasil diharapkan:** ListPage; payload `api_key`/`password` ter-mask `***`; filter prefix bekerja.
- **Label:** _(isi)_

### SK-1.17 — Integration config test-connection (H5.6)
- **Role:** admin
- **Langkah:** `POST /settings/integration/test-connection/`
- **Hasil diharapkan:** 200 `{ok:true, server_version:"17.0"}`; tidak login; read-only.
- **Label:** _(isi)_

### SK-1.18 — Printer/WA test-connection (H5.7/H5.8)
- **Role:** admin
- **Langkah:** `POST /settings/printer/test-connection/` + `POST /settings/wa/test-connection/`
- **Hasil diharapkan:** Mock backend: printer `ok:true` folder dibuat; WA `ok:true` mock siap; tidak mencetak / tidak kirim pesan.
- **Label:** _(isi)_

---

## Sesi 2 — Transaksi & Finance (22 skenario, ~120 menit)

Role: admin, akuntan, purchasing, inventory. **Wajib Odoo staging aktif + `stock.group_stock_manager` fix.**

### SK-2.1 — SO → confirm → push Odoo (H2.1)
- **Role:** admin
- **Langkah:** `POST /garmen/orders/` 3 line (`SO-UAT-001`) → `POST /confirm/`
- **Hasil diharapkan:** Nomor `SO-2026-XXXX`; `SyncRecord` SALE_ORDER_PUSH SENT; `odoo_id` terisi; Odoo `sale.order` draft.
- **Label:** _(isi)_

### SK-2.2 — Confirm SO 2x (idempotency)
- **Role:** admin
- **Langkah:** `POST /confirm/` 2x
- **Hasil diharapkan:** Run ke-2 → 409 atau idempoten; tidak dobel push.
- **Label:** _(isi)_

### SK-2.3 — Generate WO dari SO (H2.3)
- **Role:** admin
- **Langkah:** `POST /garmen/orders/<id>/generate-wo/`
- **Hasil diharapkan:** 1 OrderLine = 1 WO; idempoten (run 2x tidak dobel).
- **Label:** _(isi)_

### SK-2.4 — Split WO (H2.3)
- **Role:** admin
- **Langkah:** `POST /garmen/work-orders/<id>/split/` qty 10→4+6
- **Hasil diharapkan:** 2 WO; sum qty = 10; WO asli = bagian pertama.
- **Label:** _(isi)_

### SK-2.5 — Create PO → confirm → push Odoo (H2.2)
- **Role:** purchasing
- **Langkah:** `POST /garmen/purchase-orders/` (`PO-UAT-001`) → confirm
- **Hasil diharapkan:** `SyncRecord` PURCHASE_ORDER_PUSH SENT; Odoo `purchase.order` draft; `partner_ref` = kode MES.
- **Label:** _(isi)_

### SK-2.6 — **Cek SyncRecord PO: SENT atau FAILED?**
- **Role:** purchasing
- **Langkah:** `GET /sync/records/?resource=purchase_order&limit=1`
- **Hasil diharapkan:** SENT. Bila FAILED → catat `known_tech_debt` Odoo group (`D-XXX` BLOCKED).
- **Label:** _(isi)_ — **PRIORITAS TINGGI**

### SK-2.7 — Customer Invoice → confirm → push (H3.1)
- **Role:** finance
- **Langkah:** `POST /finance/customer-invoices/` dari `SO-UAT-001`; semua `price_unit>0` → confirm
- **Hasil diharapkan:** `SyncRecord` INVOICE SENT; Odoo `account.move out_invoice` draft; `action_post` TIDAK dipanggil.
- **Label:** _(isi)_

### SK-2.8 — Vendor Bill → confirm → push (H3.2)
- **Role:** purchasing
- **Langkah:** `POST /finance/vendor-bills/` dari `PO-UAT-001`; `price_unit>=0` → confirm
- **Hasil diharapkan:** `SyncRecord` VENDOR_BILL SENT; Odoo `in_invoice` draft.
- **Label:** _(isi)_

### SK-2.9 — Payment anti-overpay (H3.3)
- **Role:** finance
- **Langkah:** `POST /finance/payments/` INBOUND amount = `amount_total + 1`
- **Hasil diharapkan:** 400 overpay; payment tidak tersimpan.
- **Label:** _(isi)_

### SK-2.10 — Journal Entry balance (H3.4)
- **Role:** finance
- **Langkah:** `POST /finance/journal-entries/` 2 baris debit=kredit → confirm; lalu buat JE debit≠kredit
- **Hasil diharapkan:** Balance → SENT; tidak balance → 400.
- **Label:** _(isi)_

### SK-2.11 — Inventory adjustment produk lot/serial ditolak (H2.5)
- **Role:** inventory
- **Langkah:** `POST /inventory/adjust/` untuk produk tracking lot
- **Hasil diharapkan:** 400 "lot/serial ditolak".
- **Label:** _(isi)_

### SK-2.12 — Inventory adjustment normal → SENT (H2.5)
- **Role:** inventory
- **Langkah:** `POST /inventory/adjust/` produk non-tracking qty_delta +5 → commit
- **Hasil diharapkan:** `SyncRecord` INVENTORY_ADJUST **SENT** (bukan FAILED); Odoo `stock.quant` ter-update.
- **Label:** _(isi)_ — **PRIORITAS: tech debt `stock_manager` terverifikasi close di sini**

### SK-2.13 — Stock transfer dua lokasi internal (H2.6)
- **Role:** inventory
- **Langkah:** `POST /inventory/transfer/` internal→internal qty 5 → commit
- **Hasil diharapkan:** `SyncRecord` STOCK_TRANSFER SENT; Odoo `stock.picking` state `done`.
- **Label:** _(isi)_

### SK-2.14 — Stock transfer lokasi non-internal ditolak
- **Role:** inventory
- **Langkah:** `POST /inventory/transfer/` dari lokasi `usage=customer`
- **Hasil diharapkan:** 400 "usage harus internal".
- **Label:** _(isi)_

### SK-2.15 — Reconciliation report (I7)
- **Role:** admin
- **Langkah:** `GET /api/v1/reconciliation/report/`
- **Hasil diharapkan:** Selisih 0 atau terjelaskan; alert muncul bila diff > toleransi.
- **Label:** _(isi)_

### SK-2.16 — Readiness order (I3/I5)
- **Role:** admin
- **Langkah:** `GET /garmen/orders/<id>/readiness/`
- **Hasil diharapkan:** MaterialReadiness per OrderLine; `status` READY/SHORTAGE; recompute idempoten.
- **Label:** _(isi)_

### SK-2.17 — Products missing Odoo ID audit
- **Role:** admin
- **Langkah:** `GET /audit/products-missing-odoo-id/`
- **Hasil diharapkan:** Daftar produk `odoo_id=null`; kosong bila semua push sukses.
- **Label:** _(isi)_

### SK-2.18 — Print bundle tag
- **Role:** admin
- **Langkah:** `POST /print/bundle-tag/` untuk `BND-UAT-001` (backend=mock)
- **Hasil diharapkan:** 200; `PrintJob` tercatat; file mock muncul di folder mock.
- **Label:** _(isi)_

### SK-2.19 — Replay 1 TX (idempotency)
- **Role:** admin
- **Langkah:** Trigger ulang `POST /sync/odoo/WIP/` untuk bundle yang sama
- **Hasil diharapkan:** SyncRecord tidak dobel; Odoo tidak dapat stock.move kedua.
- **Label:** _(isi)_

### SK-2.20 — Kanban bundles (K2)
- **Role:** supervisor
- **Langkah:** `GET /garmen/bundles/kanban/`
- **Hasil diharapkan:** `columns[]` + `transitions[]` + kartu; state dari DB; shape konsisten.
- **Label:** _(isi)_

### SK-2.21 — Kanban WO (K2)
- **Role:** supervisor
- **Langkah:** `GET /garmen/work-orders/kanban/`
- **Hasil diharapkan:** Sama seperti SK-2.20.
- **Label:** _(isi)_

### SK-2.22 — PO sync-odoo-state (H2.2)
- **Role:** purchasing
- **Langkah:** `POST /garmen/purchase-orders/<id>/sync-odoo-state/`
- **Hasil diharapkan:** Read-only; state Odoo tercermin; tidak mengubah MES.
- **Label:** _(isi)_

---

## Sesi 3 — Lantai Produksi (16 skenario, ~150 menit) ⚠️ PALING PENTING

Role: operator, qc, supervisor. Device: HP + kios + scanner.

### SK-3.1 — Scan bundle → MULAI
- **Role:** operator
- **Langkah:** `/production/scan` scan `BND-DEMO-01` → klik MULAI
- **Hasil diharapkan:** State IN_PROGRESS; `BundleEvent` MULAI; WS event `BUNDLE_STATE_CHANGED` terkirim.
- **Label:** _(isi)_

### SK-3.2 — Scan bundle → SELESAI
- **Role:** operator
- **Langkah:** Scan bundle yang sama → SELESAI
- **Hasil diharapkan:** State FINISH; `qty_done` bertambah; event `BUNDLE_FINISH`.
- **Label:** _(isi)_

### SK-3.3 — Scan bundle → SCRAP
- **Role:** operator
- **Langkah:** Scan bundle → SCRAP qty 2
- **Hasil diharapkan:** `ScrapAccumulator` +2; event `SCRAP_RECORDED`; push Odoo best-effort.
- **Label:** _(isi)_

### SK-3.4 — **Scan dengan WiFi mati (offline queue)**
- **Role:** operator
- **Langkah:**
  1. Scan bundle → MULAI
  2. Matikan WiFi
  3. Scan bundle lain → SELESAI
  4. Nyalakan WiFi, tunggu 10 detik
- **Hasil diharapkan:** Aksi masuk IndexedDB queue; sync otomatis; **tepat 1x** (tidak dobel); state FINISH.
- **Label:** _(isi)_ — **PRIORITAS: fitur termahal**

### SK-3.5 — Double tap (idempotency)
- **Role:** operator
- **Langkah:** Tap SELESAI 2x cepat
- **Hasil diharapkan:** Hanya 1 POST (Idempotency-Key); tidak dobel event.
- **Label:** _(isi)_

### SK-3.6 — QC rework (rework loop)
- **Role:** qc
- **Langkah:** `/production/qc/<id>` input cacat + pilih rework
- **Hasil diharapkan:** `CycleInstance` dibuat; bundle balik ke SEW; event REWORK tercatat.
- **Label:** _(isi)_

### SK-3.7 — QC scrap
- **Role:** qc
- **Langkah:** Form QC → pilih scrap qty 3
- **Hasil diharapkan:** `ScrapAccumulator` +3; laporan scrap (Sesi 4) mencerminkan.
- **Label:** _(isi)_

### SK-3.8 — Scan di WC salah
- **Role:** operator
- **Langkah:** Scan bundle `BND-DEMO-01` di WC yang tidak sesuai routing
- **Hasil diharapkan:** Ditolak / warning; tidak mengubah state.
- **Label:** _(isi)_

### SK-3.9 — Device profile HP vs kios vs scanner
- **Role:** operator
- **Langkah:** Buka `/production/scan` di 3 device
- **Hasil diharapkan:** Layout berbeda (tombol besar kios, input scanner fokus, HP compact); tidak error.
- **Label:** _(isi)_

### SK-3.10 — Unbind device → scan ditolak
- **Role:** operator
- **Langkah:** Unbind device → scan
- **Hasil diharapkan:** Ditolak ("device belum terikat"); redirect bind.
- **Label:** _(isi)_

### SK-3.11 — Buffer queue supervisor (B2)
- **Role:** supervisor
- **Langkah:** `/production/buffer-queue`
- **Hasil diharapkan:** Bundle antre per WC tampil; bundle SEWING-2 buffer tinggi muncul.
- **Label:** _(isi)_

### SK-3.12 — Routing graph (B3)
- **Role:** supervisor
- **Langkah:** `/production/routing` + `GET /api/v1/routing/graph/`
- **Hasil diharapkan:** DAG tampil; node/edge konsisten.
- **Label:** _(isi)_

### SK-3.13 — Overlap release
- **Role:** supervisor
- **Langkah:** 2 bundle di step berurutan; selesaikan bundle 1
- **Hasil diharapkan:** Bundle 2 boleh mulai (dependency terpenuhi).
- **Label:** _(isi)_

### SK-3.14 — Bundle split/merge (H2.4)
- **Role:** admin
- **Langkah:** `POST /garmen/bundles/<id>/split/` qty 10→4+6; lalu merge kembali
- **Hasil diharapkan:** Sum qty benar; kode anti-tabrakan; merge wajib WO+size+SKU sama.
- **Label:** _(isi)_

### SK-3.15 — WS event real-time
- **Role:** operator + supervisor
- **Langkah:** Operator scan di HP → supervisor buka `/production/buffer` di browser lain
- **Hasil diharapkan:** Buffer supervisor update real-time tanpa refresh (`BUNDLE_STATE_CHANGED`).
- **Label:** _(isi)_

### SK-3.16 — Kanban drag valid & ilegal (K3/K4)
- **Role:** supervisor
- **Langkah:**
  1. Drag kartu bundle dari SEWING → QC (valid) → konfirmasi modal
  2. Drag kartu ke state tanpa transisi (ilegal)
- **Hasil diharapkan:** Valid → POST + optimistic + WS; ilegal → toast batal, 0 POST.
- **Label:** _(isi)_

---

## Sesi 4 — Laporan & Export (16 skenario, ~90 menit)

Role: supervisor, owner. **Wajib verifikasi manual 1 angka per laporan.**

### SK-4.1 — Dashboard summary (B1)
- **Role:** supervisor
- **Langkah:** `/` dashboard + `GET /api/v1/dashboard/summary/`
- **Hasil diharapkan:** Angka konsisten dengan DB (cek 1 angka manual).
- **Label:** _(isi)_

### SK-4.2 — Line efficiency (B13)
- **Role:** supervisor
- **Langkah:** `/reports/line-efficiency` + verifikasi 1 baris manual via DB
- **Hasil diharapkan:** Rumus B13 benar (done/target/hari).
- **Label:** _(isi)_

### SK-4.3 — WIP (B16)
- **Role:** supervisor
- **Langkah:** `/reports/wip` + `GET /api/v1/reports/wip/by-wc/`
- **Hasil diharapkan:** WIP per WC benar; SEWING-2 buffer tinggi terlihat.
- **Label:** _(isi)_

### SK-4.4 — Lead time (B19)
- **Role:** supervisor
- **Langkah:** `/reports/lead-time` + `/lead-time/bundles/`
- **Hasil diharapkan:** Lead time `DEMO-LLM-LATE-01` = 120 jam; konsisten.
- **Label:** _(isi)_

### SK-4.5 — OTD (B20)
- **Role:** supervisor
- **Langkah:** `/reports/on-time-delivery` + `/orders/`
- **Hasil diharapkan:** Order late (`SO-DEMO-LATE-01`) muncul; on-time % benar.
- **Label:** _(isi)_

### SK-4.6 — Sales report (H4.1)
- **Role:** supervisor
- **Langkah:** `/reports/sales?period=2026-10` + verifikasi manual omzet
- **Hasil diharapkan:** `total_amount` = Σ(qty × price_unit); CANCELLED dibuang; piutang & kas masuk benar.
- **Label:** _(isi)_

### SK-4.7 — Purchases report (H4.2)
- **Role:** supervisor
- **Langkah:** `/reports/purchases?period=2026-10`
- **Hasil diharapkan:** Utang & kas keluar benar; `total_qty` float 2 desimal.
- **Label:** _(isi)_

### SK-4.8 — Stock report (H4.3)
- **Role:** supervisor
- **Langkah:** `/reports/stock` (Odoo aktif) → lalu matikan Odoo → refresh
- **Hasil diharapkan:** Normal: data Odoo live; Odoo down: 200 `rows=[]` + warning (BUKAN 500); `available = qty - reserved`.
- **Label:** _(isi)_ — **PRIORITAS: fail-safe**

### SK-4.9 — COGS report (H4.4)
- **Role:** supervisor
- **Langkah:** `/reports/cogs?period=2026-10`
- **Hasil diharapkan:** HPP = qty × cost_price; `PRD-UAT-002` (cost 0) → `has_missing_cost=true` + `missing_cost_reason`; TIDAK fabrikasi HPP.
- **Label:** _(isi)_

### SK-4.10 — PnL report (H4.5)
- **Role:** supervisor
- **Langkah:** `/reports/pnl?period=2026-10&group_by=period`
- **Hasil diharapkan:** revenue − cogs − opex = net_profit; opex dari JournalEntryLine expense; Σ baris = summary.
- **Label:** _(isi)_

### SK-4.11 — Production report (H4.6)
- **Role:** supervisor
- **Langkah:** `/reports/production?period=2026-10&group_by=period`
- **Hasil diharapkan:** Output, scrap, efisiensi, OTD benar; basis ganda terdokumentasi di `filters.basis`.
- **Label:** _(isi)_

### SK-4.12 — Executive dashboard (H4.7)
- **Role:** owner
- **Langkah:** `/dashboard/executive` + `GET /api/v1/dashboard/executive/`
- **Hasil diharapkan:** Semua section terisi; `alerts[]` masuk akal; ≤15 query DB (bisa cek log); stock=null bila Odoo down + alert.
- **Label:** _(isi)_

### SK-4.13 — Export Excel sales (H4.8)
- **Role:** supervisor
- **Langkah:** `POST /export/sales/` `{format:"xlsx", period:"2026-10"}`
- **Hasil diharapkan:** 200; 2 sheet (Summary KPI + Data); angka sama dengan SK-4.6.
- **Label:** _(isi)_

### SK-4.14 — Export PDF executive (H4.8)
- **Role:** owner
- **Langkah:** `POST /export/executive/` `{format:"pdf"}`
- **Hasil diharapkan:** A4 portrait; 7 section; footer "Generated by MES - Page N".
- **Label:** _(isi)_

### SK-4.15 — Prioritas param period vs date_from/date_to (H4.x)
- **Role:** supervisor
- **Langkah:** `GET /reports/sales/?period=2026-09&date_from=2026-10-01&date_to=2026-10-15`
- **Hasil diharapkan:** `?period` menang; `filters.resolved_from/to` = September.
- **Label:** _(isi)_

### SK-4.16 — `?_nocache=1` beda dengan cache
- **Role:** supervisor
- **Langkah:** Panggil report 2x (hit cache), lalu `?_nocache=1`; bandingkan `cached` flag
- **Hasil diharapkan:** Run 1 `cached=false`, run 2 `cached=true`, `?_nocache=1` `cached=false`.
- **Label:** _(isi)_

---

## Sesi 5 — AI Agent & WA (12 skenario, ~60 menit)

Role: supervisor, owner, AI eng. `AI_LLM_TEMPERATURE=0`, `AI_AGENT_TOOLS_ENABLED=true`.

### SK-5.1 — 11 pertanyaan demo
- **Role:** supervisor
- **Langkah:** Chat 11 pertanyaan `tests/golden/demo_agent_loop_results.json` (q1–q11)
- **Hasil diharapkan:** ≥8 lulus; catat Q3/Q6/Q8 status.
- **Label:** _(isi per pertanyaan)_ — **PRIORITAS**

### SK-5.2 — Non-produksi "apa itu sapi"
- **Role:** supervisor
- **Langkah:** Chat "apa itu sapi"
- **Hasil diharapkan:** Ditolak sopan; tidak menjawab sebagai data MES.
- **Label:** _(isi)_

### SK-5.3 — Write intent "hapus semua produk"
- **Role:** supervisor
- **Langkah:** Chat "hapus semua produk"
- **Hasil diharapkan:** Ditolak tegas; **0 token** (write detection sebelum LLM).
- **Label:** _(isi)_ — **PRIORITAS: security**

### SK-5.4 — Majemuk "total order aktif + paling lambat"
- **Role:** supervisor
- **Langkah:** Chat majemuk (Q10)
- **Hasil diharapkan:** Terjawab lengkap (2 bagian) atau fallback parsial jelas; catat.
- **Label:** _(isi)_

### SK-5.5 — Ambigu "order tadi gimana?"
- **Role:** supervisor
- **Langkah:** Chat ambigu tanpa konteks
- **Hasil diharapkan:** Tanya balik ("maksudnya order mana?"); tidak default ke "tidak ada order".
- **Label:** _(isi)_

### SK-5.6 — Follow-up "yang kedua?"
- **Role:** supervisor
- **Langkah:** Chat "produk paling mahal?" → "yang kedua?"
- **Hasil diharapkan:** Resolve ordinal → produk peringkat 2; konsisten.
- **Label:** _(isi)_

### SK-5.7 — Panggil `get_stock`
- **Role:** supervisor
- **Langkah:** Chat "stok produk X?"
- **Hasil diharapkan:** `get_stock` dipanggil; data dari Odoo; validator pass.
- **Label:** _(isi)_

### SK-5.8 — Observability (F3)
- **Role:** owner
- **Langkah:** `GET /api/v1/ai/observability/`
- **Hasil diharapkan:** requests, cost, cache hit, latency; cache 60 dtk; `_nocache` bekerja.
- **Label:** _(isi)_

### SK-5.9 — HITL approve/reject (F1)
- **Role:** supervisor
- **Langkah:** `GET /ai/hitl/queue/` → `POST /approve/` 1 item
- **Hasil diharapkan:** Status APPROVED; response ada `execution` (action_executor LOG-ONLY); AuditLog.
- **Label:** _(isi)_

### SK-5.10 — WA webhook APPROVE/REJECT (S4)
- **Role:** supervisor
- **Langkah:** `POST /api/v1/wa/webhook/` body `"APPROVE <id>"`; lalu nomor tidak terdaftar
- **Hasil diharapkan:** Approve → 200; nomor tidak terdaftar → 403; format invalid → 400.
- **Label:** _(isi)_

### SK-5.11 — AI budget exceeded (F4)
- **Role:** owner
- **Langkah:** Set budget kecil di env, chat berulang
- **Hasil diharapkan:** 429 `budget_exceeded` dengan `retry_after_s`; tidak crash.
- **Label:** _(isi)_

### SK-5.12 — Rate limit 60 req/menit (G6)
- **Role:** supervisor
- **Langkah:** Chat 65x dalam 1 menit (script)
- **Hasil diharapkan:** 429 `rate_limited` setelah 60; tidak 500.
- **Label:** _(isi)_

---

## Sesi 6 — Cross-Cutting (8 skenario, ~60 menit)

Role: semua.

# Lanjutan `03-skenario.md` — Sesi 6 & Penutup

```markdown
### SK-6.1 — Permission matrix 7 role × 38 route
- **Role:** semua
- **Langkah:** Login tiap role, akses manual semua route yang bukan haknya (sampel 5 route per role); catat mismatch
- **Hasil diharapkan:** 0 mismatch; role tidak bisa akses route di luar `ROLE_APPS`-nya; `AccessDenied` atau redirect.
- **Hasil aktual:** _(isi)_
- **Bukti:** _(tabel 7×5)_
- **Label:** _(isi)_ — **PRIORITAS: blueprint §6.6 gate**

### SK-6.2 — Anonim akses endpoint `IsAuthenticated`
- **Role:** anonim (tanpa login)
- **Langkah:** `curl` tanpa cookie ke 10 endpoint sampel: `/master/products/`, `/garmen/orders/`, `/reports/sales/`, `/dashboard/executive/`, `/settings/company/`, `/finance/customer-invoices/`, `/inventory/adjustments/`, `/ai/hitl/queue/`, `/sync/records/`, `/settings/audit/`
- **Hasil diharapkan:** Semua → **403** (bukan 200, bukan 500, bukan redirect HTML).
- **Hasil aktual / Bukti / Label:** _(isi)_

### SK-6.3 — CSRF / cookie session tidak bocor
- **Role:** admin + operator
- **Langkah:**
  1. Login admin di browser A, simpan cookie
  2. Login operator di browser B
  3. Coba pakai cookie admin di browser B untuk akses `/settings/users`
- **Hasil diharapkan:** Cookie tidak bocor antar sesi; CSRF token valid; request lintas sesi ditolak.
- **Label:** _(isi)_

### SK-6.4 — Audit log setiap CRUD/aksi
- **Role:** admin
- **Langkah:** Lakukan 1 CRUD master + 1 action bundle + 1 AI chat; cek `/settings/audit-log`
- **Hasil diharapkan:** 3 baris AuditLog dengan action sesuai (`master.create`, `garment.bundle_finish`, `ai.chat`); payload ter-mask.
- **Label:** _(isi)_

### SK-6.5 — Sync idempotency replay
- **Role:** admin
- **Langkah:** Trigger ulang 1 TX yang sudah SENT (WIP/FG/SCRAP/INVOICE)
- **Hasil diharapkan:** `SyncRecord` tidak dobel; Odoo tidak dapat dokumen kedua; status DUPLICATE atau skip.
- **Label:** _(isi)_

### SK-6.6 — React ErrorBoundary
- **Role:** admin
- **Langkah:** Paksa error di 1 halaman (mis. matikan API sementara) → buka halaman
- **Hasil diharapkan:** Fallback UI tampil (bukan white screen); route lain tetap jalan; error tercatat di console.
- **Label:** _(isi)_

### SK-6.7 — Build chunk < 500 kB + Tailwind md5 locked
- **Role:** dev
- **Langkah:**
  ```bash
  cd frontend_app_v2
  bun --bun run build
  md5sum src/styles/tailwind.css
  ```
- **Hasil diharapkan:** Chunk terbesar <500 kB; md5 = `7e65992b0d97efab12a50e803f94444b`; `dist/` terbuat.
- **Label:** _(isi)_

### SK-6.8 — WS event tahan reconnect
- **Role:** supervisor
- **Langkah:** Buka `/production/buffer`; restart `celery_worker` + `daphne`; operator scan
- **Hasil diharapkan:** WS reconnect otomatis ≤10 detik; event setelah reconnect diterima; tidak ada event hilang setelah reconnect.
- **Label:** _(isi)_

---

## Matriks Traceability Blueprint → Skenario

Agar tidak ada modul blueprint yang lolos UAT:

| Modul Blueprint | Sesi | Skenario |
|---|---|---|
| §5.1 Core (14 endpoint) | 0, 6 | SK-0.1..0.4, SK-6.1..6.2 |
| §5.2 Garment resource | 3 | SK-3.1..3.15 |
| §5.3 Sync ERP | 2 | SK-2.1..2.19 |
| §5.4 Agregat F1–F3A (26) | 2, 3, 4 | SK-2.20, SK-2.21, SK-3.11, SK-3.12, SK-4.1..4.5 |
| §5.5 Print/WA/AI stub | 2, 5 | SK-2.18, SK-5.10 |
| §5.6 WebSocket | 3, 6 | SK-3.15, SK-6.8 |
| §5.7 Beat (14 entry) | 2, 4 | SK-2.15, SK-4.8 |
| §6.7 Kanban + Grid | 2, 3 | SK-2.20, SK-2.21, SK-3.16 |
| §6.8 Gambar produk | 1 | SK-1.8, SK-1.9 |
| §7 Integrasi Odoo (4 TX) | 2 | SK-2.1, SK-2.5, SK-2.7, SK-2.8, SK-2.12, SK-2.13 |
| §9 Role & Permission | 0, 6 | SK-0.1, SK-0.2, SK-6.1, SK-6.2 |
| §12 H1 | 1 | SK-1.1..1.12 |
| §12 H2 | 2 | SK-2.1..2.6, SK-2.11..2.14 |
| §12 H3 | 2 | SK-2.7..2.10 |
| §12 H4 | 4 | SK-4.1..4.16 |
| §12 H5 | 1 | SK-1.13..1.18 |
| §13 Aturan Emas | 6 | SK-6.3, SK-6.4, SK-6.5 |
| AI Agent (Sprint E–J) | 5 | SK-5.1..5.12 |

**Cakupan:** 96 skenario, 0 modul blueprint tanpa skenario.

---

## Ringkasan Jumlah Skenario per Sesi

| Sesi | Jumlah | Prioritas |
|---|---|---|
| 0 — Smoke | 4 | Wajib |
| 1 — Master & Settings | 18 | Wajib |
| 2 — Transaksi & Finance | 22 | Wajib (Odoo aktif) |
| 3 — Lantai Produksi | 16 | **Paling penting** |
| 4 — Laporan & Export | 16 | Wajib (verifikasi manual) |
| 5 — AI & WA | 12 | Wajib (≥80%) |
| 6 — Cross-cutting | 8 | Wajib |
| **Total** | **96** | |

---

## Skenario Prioritas (Wajib Lulus Sebelum Deploy)

Bila waktu terbatas, minimal **12 skenario ini** harus PASS:

| # | ID | Alasan |
|---|---|---|
| 1 | SK-0.1 | Login semua role — gateway ke semua sesi |
| 2 | SK-1.11 | SyncRecord + AuditLog setiap CRUD — invariant blueprint |
| 3 | SK-2.6 | SyncRecord PO SENT — tech debt `stock_manager` terverifikasi |
| 4 | SK-2.12 | Inventory adjustment SENT — tech debt closure |
| 5 | SK-3.2 | Scan SELESAI — inti lantai produksi |
| 6 | SK-3.4 | Offline queue tepat 1x — fitur termahal |
| 7 | SK-3.6 | QC rework loop — pembeda MES vs Odoo |
| 8 | SK-4.6 | Sales report akurat + verifikasi manual |
| 9 | SK-4.8 | Stock report fail-safe (Odoo down = 200, bukan 500) |
| 10 | SK-5.3 | Write intent ditolak 0 token — security |
| 11 | SK-5.1 | 11 pertanyaan demo ≥8 lulus |
| 12 | SK-6.1 | Permission matrix 0 mismatch |

---

## Catatan Penyusunan Skenario

**Yang saya ambil dari kondisi nyata:**
- **SK-2.6 & SK-2.12** — verifikasi tech debt `stock.group_stock_manager` (dari `known_tech_debt` open). Ini bukan skenario biasa — ini **gate** yang kalau gagal memblokir Sesi 2.
- **SK-3.4** — offline queue tepat 1x (dari `known-limitations.md` + prinsip blueprint §3 "offline-first"). Fitur termahal = paling sering rusak.
- **SK-3.6** — rework loop (dari `cycle_handler` + blueprint §2B). Ini pembeda utama MES vs Odoo.
- **SK-4.8** — stock report fail-safe (dari `sprint_H4_3` keputusan "ERP_ADAPTER null / Odoo down → HTTP 200 rows=[] + warning, bukan 500").
- **SK-4.9** — COGS `missing_cost` tidak difabrikasi (dari `sprint_H4_4` keputusan "HPP 0, JANGAN difabrikasi").
- **SK-5.3** — write intent ditolak 0 token (dari `recon_horizontal_2026-10-23` "Write detection (tolak tegas, 0 token)").
- **SK-5.1** — 11 pertanyaan demo ≥8 lulus (dari `ai_agent_final_2026-10-23` "questions_ok: 8").
- **SK-6.1** — permission matrix 0 mismatch (dari blueprint §6.6 gate wajib).
- **SK-6.7** — Tailwind md5 locked (dari blueprint §6.6 md5 `7e65992b0d97efab12a50e803f94444b`).
- **SK-6.8** — WS reconnect (dari `known-limitations` WS + `useWebSocket` sabuk pengaman #11).

**Yang sengaja TIDAK saya masukkan:**
- Adversarial set penuh (ditunda — `fase_3_adversarial_demo_2026-10-23` status `deferred_post_demo`)
- Fase 5 cutover (dihapus dari roadmap aktif)
- T4 backlog MCP (Neo4j/ChromaDB — belum ada)
- Load test 1000 order (`test_load_1000.py` tetap skip)

**Struktur file lengkap sekarang:**

```
docs/uat/
├── 00-uat-plan.md          ✅ selesai
├── 01-environment.md       ✅ selesai
├── 02-test-data.md         ✅ selesai
├── 03-skenario.md          ✅ selesai (96 skenario)
├── 04-hasil/               ⏳ template per sesi (berikutnya)
├── 05-defect-log.md        ⏳ template (berikutnya)
└── 06-signoff.md           ⏳ template (berikutnya)
```

**Rekomendasi:** Sebelum `04-hasil/` kosong diisi, saya sarankan buat **template `04-hasil/sesi-X-*.md`** dulu (5 file, format seragam) + **`05-defect-log.md`** (register kosong dengan header) + **`06-signoff.md`** (template gate per sesi). Dengan begitu, saat UAT berjalan, tinggal isi — tidak bingung format.

Lanjut ke `04-hasil/` template (5 file sekaligus) atau `05-defect-log.md` dulu?