# Konfigurasi Integrasi Django MES ↔ Odoo per Klien

Template konfigurasi & checklist onboarding **satu instance MES** ke **satu
database Odoo klien**. Ditulis untuk Fase I (integrasi) — lihat juga
`docs/integrations/CONTRACT.md` (kontrak field & TX yang dikunci) dan
`docs/integrations/framework_jsonrpc_validation.md` (metode validasi probe).

> **Aturan**: semua id/nilai yang spesifik klien (lokasi, UoM, kredensial) **hanya**
> lewat `.env` — tidak ada id hardcode di kode. Kontrak TX memvalidasi nilai ini
> saat runtime dan menolak push dengan pesan jelas kalau belum diisi.

Pasang variabel `.env` **sebelum** menjalankan container; `.env` dibaca saat
container dibuat, jadi perubahan setelahnya butuh:

```bash
docker compose up -d --force-recreate django celery_worker celery_beat
```

---

## 1. Variabel `.env` (wajib)

Nilai `<...>` = **placeholder**, jangan pakai contoh id di bawah apa adanya.

### 1.1 Adapter & kredensial Odoo

| Nama | Contoh | Deskripsi | Wajib |
|---|---|---|---|
| `ERP_ADAPTER` | `odoo` | Adapter aktif: `odoo` (produksi) atau `null` (dev/test, tanpa ERP). Nilai tak dikenal → fallback `null` + log WARNING | ✅ |
| `ODOO_URL` | `http://odoo:8069` | Base URL JSON-RPC Odoo (di docker-compose: nama service `odoo`) | ✅ |
| `ODOO_DB` | `<nama_db_klien>` | Nama database Odoo klien | ✅ |
| `ODOO_USER` | `<user_api_klien>` | Login user API (bukan admin personal) | ✅ |
| `ODOO_API_KEY` | `<api_key_klien>` | API key / password user API | ✅ |
| `ODOO_TIMEOUT` | `30.0` | Timeout request JSON-RPC (detik) | opsional (default 30) |

### 1.2 Lokasi (`stock.location`) untuk two-stage & scrap

Rantai lokasi yang dipakai MES (lihat CONTRACT.md §TX-WIP-ISSUE / TX-FG-RECEIPT):

```
WH/Stok (bahan) --WIP ISSUE--> Virtual Locations/Production --FG RECEIPT--> WH/Finished Goods
      ^ ODOO_LOCATION_WIP_ID                ^ ODOO_LOCATION_PRODUCTION_ID        ^ ODOO_LOCATION_FG_ID
```

| Nama | Contoh | Deskripsi | Wajib |
|---|---|---|---|
| `ODOO_LOCATION_WIP_ID` | `<id_wh_stok>` | Gudang bahan — **sumber** WIP issue (`stock.move.location_id`) | ✅ untuk TX-WIP |
| `ODOO_LOCATION_PRODUCTION_ID` | `<id_virtual_production>` | Lokasi produksi/WIP — **tujuan** WIP issue & **sumber** FG receipt. Harus lokasi `usage='production'` (Virtual Locations/Production), bukan lokasi internal | ✅ untuk TX-WIP & TX-FG |
| `ODOO_LOCATION_FG_ID` | `<id_wh_fg>` | Gudang barang jadi — **tujuan** FG receipt | ✅ untuk TX-FG |
| `ODOO_LOCATION_SCRAP_ID` | `<id_virtual_scrap>` | Lokasi scrap — tujuan TX-SCRAP (`stock.scrap.location_id`) | ✅ untuk TX-SCRAP |

Catatan:
- **`ODOO_LOCATION_RECEIPT_ID` / `ODOO_LOCATION_DELIVERY_ID` tidak dipakai kode ini**
  (tidak ada di `config/settings.py`; dibiarkan kosong/absen). Kalau alur
  in/out picking dari Odoo perlu dipetakan ke MES, itu pekerjaan baru — bukan
  bagian Fase I.
- Ketiga id TX wajib **valid** saat push; kalau kosong adapter mengembalikan
  `ERPResponse(ok=False)` dengan pesan
  `Location WIP/PRODUCTION belum dikonfigurasi (ODOO_LOCATION_*)` — bukan
  mengirim payload setengah jadi. Pesan serupa muncul untuk
  `ODOO_LOCATION_FG_ID`, `ODOO_LOCATION_SCRAP_ID`, dan `ODOO_UOM_ID` yang kosong.

### 1.3 Unit of Measure

| Nama | Contoh | Deskripsi | Wajib |
|---|---|---|---|
| `ODOO_UOM_ID` | `<id_uom_pcs>` | id `uom.uom` untuk **PCS**. Dipakai TX-SCRAP karena `stock.scrap.product_uom_id` **wajib** dan MES tidak menyimpan UoM per produk (satu UoM untuk semua scrap) | ✅ untuk TX-SCRAP |

### 1.3b Transfer antar-lokasi (opsional)

| Nama | Contoh | Deskripsi | Wajib |
|---|---|---|---|
| `ODOO_PICKING_TYPE_INTERNAL_ID` | `<id_picking_type_internal>` | id `stock.picking.type` untuk **transfer antar lokasi internal** (H2.6, `stock.picking`). **Kosong** (default) → adapter mencari sendiri `stock.picking.type` dengan `code='internal'`; isi nilainya bila Odoo klien punya lebih dari satu tipe internal (supaya tidak salah pilih) | opsional |

> Sejak **H5.6** variabel ini resmi dideklarasikan di `config/settings.py`
> (`ODOO_PICKING_TYPE_INTERNAL_ID`); sebelumnya hanya dibaca lewat
> `getattr(settings, …, None)` di `adapters/odoo.py`.

### 1.4 Rekonsiliasi stok & alert

| Nama | Contoh | Deskripsi | Wajib |
|---|---|---|---|
| `RECONCILIATION_TOLERANCE_UNITS` | `5` | Toleransi selisih **absolut** (unit) sebelum dianggap alert | opsional (default 5) |
| `RECONCILIATION_TOLERANCE_PCT` | `0.01` | Toleransi **relatif** terhadap qty MES (`0.01` = 1%) untuk volume besar | opsional (default 0.01) |
| `RECONCILIATION_ALERT_WA_TO` | `<62812xxxxxxx>,<62813xxxxxxx>` | Nomor WA penerima alert rekonsiliasi (dipisah koma). **Kosong** = alert dilewati (hanya log info) | opsional |

Aturan alert: produk di-flag `is_alert` kalau
`|diff| > max(RECONCILIATION_TOLERANCE_UNITS, RECONCILIATION_TOLERANCE_PCT × mes_qty)`.

### 1.5 WhatsApp (kanal notifikasi)

| Nama | Contoh | Deskripsi | Wajib |
|---|---|---|---|
| `WA_BACKEND` | `mock` | Implementasi gateway: `mock` (satu-satunya yang ada sekarang). Nilai lain → fallback `mock` + log WARNING | opsional |
| `WA_API_URL` | `<url_vendor_wa>` | Base URL penyedia WA — **belum dipakai** `MockWAGateway`; disiapkan untuk implementasi berikutnya | opsional |
| `WA_API_KEY` | `<api_key_wa>` | API key penyedia WA — idem | opsional |

Catatan **H5.8 (Settings → WA Gateway, `/settings/wa`)**: halaman itu menyimpan **profil
gateway** di `master.WAConfig` (singleton, endpoint `GET|PUT /api/v1/settings/wa/` +
`POST …/test-connection/`) dengan pola **Opsi B** seperti H5.6 — tiga env di tabel ini tetap
**sumber yang benar-benar dipakai** `get_wa_gateway()` (konsumen tidak disentuh). Halaman
**tidak** meng-override `.env`: aktivasi = salin ke `.env` + `docker compose restart django
celery_worker celery_beat` (dilaporkan UI lewat `effective`/`diverges`/`needs_restart`).
`WA_API_KEY` disimpan plaintext + **selalu** di-mask `***` di API.

### 1.5b Printer thermal ESC/POS (kanal cetak)

| Nama | Contoh | Deskripsi | Wajib |
|---|---|---|---|
| `PRINTER_BACKEND` | `mock` | Backend cetak: `mock` (file `.bin`, default — tanpa printer fisik), `usb` (**stub**: butuh `python-escpos` + `libusb`), `network` (TCP raw). Nilai tak dikenal → fallback `mock` + log WARNING | opsional |
| `PRINTER_USB_VENDOR_ID` | `0x04b8` | Vendor id printer USB — **wajib** bila `PRINTER_BACKEND=usb` | kondisional |
| `PRINTER_USB_PRODUCT_ID` | `0x0202` | Product id printer USB — **wajib** bila `PRINTER_BACKEND=usb` | kondisional |
| `PRINTER_NETWORK_HOST` | `<ip_printer>` | Host printer jaringan (mis. `192.168.1.50`) — **wajib** bila `PRINTER_BACKEND=network` | kondisional |
| `PRINTER_NETWORK_PORT` | `9100` | Port TCP raw printing (1..65535) — **wajib** bila `PRINTER_BACKEND=network` | kondisional |
| `PRINTER_MOCK_DIR` | `/tmp/print_mock` | Folder hasil "cetak" backend `mock` (di `/tmp` supaya tidak masuk repo) | opsional |

Catatan **H5.7 (Settings → Printer, `/settings/printers`)**: halaman itu menyimpan **profil
printer** di `master.PrinterConfig` (singleton, endpoint `GET|PUT /api/v1/settings/printer/`
+ `POST …/test-connection/`) dengan pola **Opsi B** seperti H5.6/H5.8 — enam env di tabel ini
tetap **sumber yang benar-benar dipakai** `integrations/printing.backends.get_backend()`
(konsumen tidak disentuh). Halaman **tidak** meng-override `.env`: aktivasi = salin ke `.env`
+ `docker compose restart django celery_worker celery_beat` (dilaporkan UI lewat
`effective`/`diverges`/`needs_restart`). Tombol **Test Koneksi** **tidak pernah mencetak**:
`mock` = cek folder, `usb` = laporan stub, `network` = TCP connect `host:port` tanpa kirim
bytes ESC/POS. Tidak ada field rahasia di sini ⇒ response **tanpa mask** (beda H5.6/H5.8).

### 1.6 Contoh `.env` (placeholder — jangan pakai nilai contoh apa adanya)

```bash
# --- Adapter & kredensial Odoo -------------------------------------------
ERP_ADAPTER=odoo
ODOO_URL=http://odoo:8069
ODOO_DB=<nama_db_klien>
ODOO_USER=<user_api_klien>
ODOO_API_KEY=<api_key_klien>
ODOO_TIMEOUT=30

# --- Lokasi Odoo klien (lihat §2 untuk cara mengambil id) ----------------
ODOO_LOCATION_WIP_ID=<id_wh_stok>
ODOO_LOCATION_PRODUCTION_ID=<id_virtual_production>
ODOO_LOCATION_FG_ID=<id_wh_fg>
ODOO_LOCATION_SCRAP_ID=<id_virtual_scrap>
ODOO_UOM_ID=<id_uom_pcs>
ODOO_PICKING_TYPE_INTERNAL_ID=<id_picking_type_internal>

# --- Rekonsiliasi stok & alert -------------------------------------------
RECONCILIATION_TOLERANCE_UNITS=5
RECONCILIATION_TOLERANCE_PCT=0.01
RECONCILIATION_ALERT_WA_TO=

# --- WhatsApp -------------------------------------------------------------
WA_BACKEND=mock
WA_API_URL=
WA_API_KEY=

# --- Printer thermal ESC/POS ---------------------------------------------
PRINTER_BACKEND=mock
PRINTER_USB_VENDOR_ID=
PRINTER_USB_PRODUCT_ID=
PRINTER_NETWORK_HOST=
PRINTER_NETWORK_PORT=
PRINTER_MOCK_DIR=/tmp/print_mock
```

> `.env` **jangan** di-commit berisi kredensial nyata. Satu file `.env` per
> klien/instance MES.
>
> **H5.6 (Settings → Integration)**: MES menyediakan **halaman profil config**
> (`/settings/integration`) yang menyimpan nilai-nilai di atas ke DB agar gampang
> dibaca/diedit ber-jejak. ⚠️ **Halaman itu TIDAK meng-override `.env`** (keputusan
> Opsi B): konsumen (adapter, transport, task) tetap membaca `.env`/`settings`. Jadi
> setelah menyimpan di UI: **salin nilainya ke `.env` lalu**
> `docker compose restart django celery_worker celery_beat`. Halaman menampilkan
> `effective` (nilai yang benar-benar aktif), `diverges` (beda DB vs `.env`) dan
> `needs_restart` supaya tidak menyesatkan.

---

## 2. Setup Odoo (per klien)

### 2.1 Lokasi yang harus ada

| Kebutuhan | `usage` yang benar | Contoh `complete_name` | Dipakai oleh |
|---|---|---|---|
| Gudang bahan (WIP) | `internal` | `WH/Stok` (boleh punya anak rak/gate) | sumber TX-WIP-ISSUE (`ODOO_LOCATION_WIP_ID`) |
| Lokasi produksi | `production` (**virtual**, bukan internal) | `Virtual Locations/Production` | tujuan WIP & sumber FG (`ODOO_LOCATION_PRODUCTION_ID`) |
| Gudang barang jadi | `internal` | `WH/Finished Goods` | tujuan TX-FG-RECEIPT (`ODOO_LOCATION_FG_ID`) |
| Lokasi scrap | `inventory` (virtual) | `Virtual Locations/Scrap` | tujuan TX-SCRAP (`ODOO_LOCATION_SCRAP_ID`) |

Verifikasi `usage` + ambil id **langsung dari Odoo klien** (jangan tebak):

```bash
# semua lokasi internal (yang dipakai rekonsiliasi)
docker compose exec django python manage.py shell -c \
"from integrations.erp_sync.transport import get_transport; t=get_transport(); \
print([(r['id'], r['complete_name']) for r in t.fetch_internal_locations()]); t.close()"
```

```bash
# cari lokasi virtual production/scrap (usage + id)
# dari UI Odoo: Inventory → Configuration → Locations → filter "Virtual"
```

Catatan portabilitas:
- lokasi boleh punya **anak** (rak/gate): WIP issue tetap memakai id induknya,
  sedangkan rekonsiliasi menghitung anak-anaknya lewat operator `child_of`;
- **jangan** memakai lokasi bertipe virtual/`production` sebagai `WH/Stok`
  (stok fisik harus di lokasi `internal`), dan sebaliknya jangan memakai
  lokasi `internal` sebagai tujuan WIP/Production.

### 2.2 User API + hak akses minimal

Buat **user khusus API** (bukan akun admin personal), lalu isi
`ODOO_USER` + `ODOO_API_KEY`.

| Model Odoo | Hak minimal | Dipakai oleh |
|---|---|---|
| `stock.move`, `stock.quant`, `stock.location` | read + create/write | push WIP/FG, scrap, rekonsiliasi (`stock.quant` read) |
| `stock.scrap` | create (+ unlink draft) | TX-SCRAP |
| `purchase.order`, `purchase.order.line` | read | material readiness (I3) |
| `sale.order`, `sale.order.line` | read | sales order sync (I2) |
| `product.product`, `product.template`, `mrp.bom`, `mrp.bom.line` | read | master sync (I1) |
| `account.move` | read + create (+ write draft) | vendor bill read (I6) & customer invoice draft (I5) |
| `account.journal`, `account.tax`, `uom.uom`, `res.partner`, `res.currency`, `stock.warehouse` | read | master sync (I1) |

Perubahan data master (produk/BOM/partner) **tidak** dilakukan MES — hanya
dibaca; kalau user API kelebihan hak, risikonya bukan dari kode ini.

### 2.3 UoM PCS + id-nya

- Pastikan `uom.uom` untuk **PCS/Units** ada di klien (Odoo default: "Units");
  catat id-nya ke `ODOO_UOM_ID` (di instance dev: `33`).
- `stock.scrap.product_uom_id` **wajib**; MES belum menyimpan UoM per produk →
  satu `ODOO_UOM_ID` untuk semua TX-SCRAP. Kalau klien punya beberapa UoM
  (lusin/karton), ubah produk di MES dulu atau sesuaikan pemetaannya
  (pekerjaan baru).

### 2.4 Journal & mata uang (invoice)

- Invoice customer dikirim **draft** tanpa `journal_id`/`currency_id` → Odoo
  memakai default company, jadi cukup pastikan klien punya ≥1
  `account.journal` (tipe sale) dan mata uang company terisi.
- Verifikasi lewat master sync: jumlah `account.journal` setelah sync `journals`
  harus > 0 (di instance dev: 8 journal).

---

## 3. Sync Master Data (wajib pertama kali)

Integrasi **tidak** akan berguna sebelum master data MES terisi: rekonsiliasi
stok membandingkan hanya produk yang punya `Product.odoo_id`, dan readiness
mencocokkan komponen BOM lewat `Product.odoo_id` juga.

### 3.1 Urutan sync

Urutan berikut penting (BOM butuh Product; BOMLine butuh Product; dst.):

| # | Entity | Task | Isi |
|---|---|---|---|
| 1 | `products` | `erp_sync.sync_master_products` | `product.product` → `master.Product` (+ `odoo_tmpl_id`) |
| 2 | `boms` | `erp_sync.sync_master_boms` | `mrp.bom` + `mrp.bom.line` → `master.BOM`/`BOMLine` |
| 3 | `partners` | `erp_sync.sync_master_partners` | `res.partner` → `master.Partner` |
| 4 | `locations` | `erp_sync.sync_master_locations` | `stock.location` → `master.Location` |
| 5 | `taxes` | `erp_sync.sync_master_taxes` | `account.tax` → `master.Tax` |
| 6 | `uoms` | `erp_sync.sync_master_uoms` | `uom.uom` → `master.UoM` |
| 7 | `warehouses` | `erp_sync.sync_master_warehouses` | `stock.warehouse` → `master.Warehouse` |
| 8 | `journals` | `erp_sync.sync_master_journals` | `account.journal` → `master.Journal` |
| 9 | `currencies` | `erp_sync.sync_master_currencies` | `res.currency` → `master.Currency` |

### 3.2 Menjalankan manual (sekali di awal)

```bash
# endpoint (auth wajib — login dulu di UI/klien API, atau pakai sesi admin Django)
curl -X POST http://localhost:8000/api/v1/sync/master/products/ -H "Authorization: <kredensial>"
```

```bash
# atau langsung task Celery (tanpa HTTP)
docker compose exec django python manage.py shell -c \
"from integrations.erp_sync.tasks_master import sync_master_products as t; print(t())"
```

### 3.3 Verifikasi

```bash
docker compose exec django python manage.py shell -c \
"from master.models import Product, BOM, Partner, Location; \
print(Product.objects.count(), Product.objects.filter(odoo_id__isnull=False).count(), \
BOM.objects.count(), Partner.objects.count(), Location.objects.count())"
```

Kriteria lulus:
- `Product.objects.filter(odoo_id__isnull=False).count() > 0` (di instance dev: 26);
- `BOM.objects.count() > 0`, `Location.objects.count() > 0`;
- produk yang belum punya `odoo_id` → cek §6 poin pertama.

> Master sync juga terjadwal otomatis tiap hari 02:00 WIB (lihat §4), tapi
> **onboarding klien baru harus** menjalankannya manual sekali supaya tidak
> menunggu jadwal.

---

## 4. Beat Schedule (default)

14 entry di `CELERY_BEAT_SCHEDULE` (`config/settings.py`), zona waktu
`CELERY_TIMEZONE=Asia/Jakarta`. Jadwal berikut adalah **default** — boleh
disesuaikan per klien di settings (bukan `.env`).

| # | Key | Jadwal (WIB) | Task | Fungsi |
|---|---|---|---|---|
| 1 | `sync-master-products` | harian 02:00 | `erp_sync.sync_master_products` | produk Odoo → MES |
| 2 | `sync-master-boms` | harian 02:00 | `erp_sync.sync_master_boms` | BOM + komponen |
| 3 | `sync-master-partners` | harian 02:00 | `erp_sync.sync_master_partners` | partner/customer/vendor |
| 4 | `sync-master-locations` | harian 02:00 | `erp_sync.sync_master_locations` | lokasi gudang |
| 5 | `sync-master-taxes` | harian 02:00 | `erp_sync.sync_master_taxes` | pajak |
| 6 | `sync-master-uoms` | harian 02:00 | `erp_sync.sync_master_uoms` | UoM |
| 7 | `sync-master-warehouses` | harian 02:00 | `erp_sync.sync_master_warehouses` | warehouse |
| 8 | `sync-master-journals` | harian 02:00 | `erp_sync.sync_master_journals` | journal akuntansi |
| 9 | `sync-master-currencies` | harian 02:00 | `erp_sync.sync_master_currencies` | mata uang |
| 10 | `sync-sale-orders` | tiap 5 menit | `erp_sync.sync_sale_orders` | poll SO Odoo → Order MES (I2) |
| 11 | `sync-scrap-accumulator` | 06:00, 14:00, 22:00 | `erp_sync.sync_scrap_accumulator` | kirim scrap per shift (I4) |
| 12 | `sync-invoice` | tiap 15 menit | `erp_sync.sync_invoice` | kirim customer invoice (I5) |
| 13 | `recompute-readiness` | harian 04:00 | `erp_sync.recompute_readiness` | refresh readiness **hanya OrderLine yang belum READY** + agregat vendor bill (I3/I6, dikonsolidasi I7) |
| 14 | `reconcile-stock` | Senin 03:00 (mingguan) | `erp_sync.reconcile_stock` | rekonsiliasi stok MES vs Odoo + alert WA (I7) |

Verifikasi jumlah entry (test mengunci 14):

```bash
docker compose exec django python -m pytest config/tests/test_settings_beat.py -q
```

Catatan operasional:
- push WIP/FG **tidak** dijadwalkan — dipicu per event bundle (endpoint
  `POST /api/v1/sync/odoo/<stage>/`) lalu dikirim task Celery;
- invoice dipicu listener `WORK_ORDER_STATE_CHANGED` (semua WO order `DONE`
  atau `CANCELLED`) — I8.2;
- setelah mengubah jadwal: `docker compose up -d --force-recreate celery_beat celery_worker`.

---

## 5. Verifikasi Portabilitas (UAT checklist)

Jalankan berurutan di instance klien. Semua endpoint **butuh autentikasi**
(`IsAuthenticated`) — 403 untuk request anonim.

### 5.1 SO → Order → Bundle → WIP → FG → Invoice (end-to-end)

| # | Langkah | Cara | Bukti lulus |
|---|---|---|---|
| 1 | SO masuk MES | tunggu `sync-sale-orders` (≤5 menit) atau jalankan `erp_sync.sync_sale_orders()` | `Order.objects` bertambah; `OrderLine.product.odoo_id` terisi |
| 2 | Bundle dibuat | UI MES: order → bundle (atau `Bundle.objects`) | `Bundle` ada, `state=DRAFT` |
| 3 | Bundle start | `POST /api/v1/garmen/bundles/<id>/<BUNDLE_START>/` (auth + `X-Base-Version`) | 200 + `BundleEvent` tercatat + state `CUTTING` |
| 4 | WIP push | `POST /api/v1/sync/odoo/WIP/` (`resource=bundle/work_order`) → task `push_wip_issue` | `SyncRecord.stage=WIP` **SENT**; Odoo: stok bahan turun, muncul di lokasi Production; `AuditLog` action `erp_sync.push_wip` |
| 5 | Bundle selesai | aksi sampai WC terminal (`BUNDLE_FINISH`) | `qty_done` terisi, state `DONE` |
| 6 | FG push | `POST /api/v1/sync/odoo/FG/` → task `push_fg_receipt` | `SyncRecord.stage=FG` **SENT**; Odoo: stok naik di `ODOO_LOCATION_FG_ID` |
| 7 | Invoice | otomatis saat **semua WO** order selesai (atau `erp_sync.sync_invoice()`) | Odoo: 1 `account.move` **draft** per order (`move_type=out_invoice`, `price_unit=0`); `AuditLog` `erp_sync.push_invoice` |

### 5.2 PO → Readiness

| # | Langkah | Bukti lulus |
|---|---|---|
| 1 | PO confirmed di Odoo (`state=purchase`) | — |
| 2 | `GET /api/v1/garmen/orders/<id>/readiness/` | 200 + `lines[]` dengan `status` `WAITING/PARTIAL/READY`, `received_qty` dari PO |
| 3 | `POST .../recompute-readiness/` | 200 + counter `{processed, waiting, partial, ready, errors}`; jalan otomatis 04:00 WIB |
| 4 | (opsional) Vendor bill di Odoo | `vendor_bill_status`/`vendor_bill_ids` terisi **hanya kalau** `invoice_origin` bill = nama PO (lihat §6) |

### 5.3 Scrap sync

| # | Langkah | Bukti lulus |
|---|---|---|
| 1 | Catat scrap di MES (`ScrapAccumulator.qty > 0`) | — |
| 2 | `POST /api/v1/sync/scrap/` (auth) atau tunggu shift 06/14/22 | `{sent, failed, skipped}`; `SyncRecord.stage=SCRAP` SENT; Odoo: `stock.scrap` di `ODOO_LOCATION_SCRAP_ID`; `AuditLog` `erp_sync.push_scrap` |

### 5.4 Reconcile report

| # | Langkah | Bukti lulus |
|---|---|---|
| 1 | Jalankan mingguan (Senin 03:00) atau manual: `erp_sync.reconcile_stock.apply()` | return `{total_products, alert_count, alerts}` |
| 2 | `GET /api/v1/reconciliation/report/?days=7` (auth) | 200 + `{days, count, entries[]}` (`mes_qty`, `odoo_qty`, `diff`, `is_alert`) |
| 3 | (bila ada selisih) alert WA | pesan terkirim ke `RECONCILIATION_ALERT_WA_TO`; kalau kosong → hanya log info (tidak error) |
| 4 | Cek data produk | `GET /api/v1/audit/products-missing-odoo-id/` (§6) |

---

## 6. Troubleshooting

### 6.1 Produk MES tanpa `odoo_id` (rekonsiliasi & invoice "kurang data")

Gejala: rekonsiliasi menghasilkan 0 baris, warning stok tidak turun/naik, atau
invoice tidak lengkap untuk produk tertentu.

```bash
# produk yang belum tersinkron (daftar dipotong 100)
curl -H "Authorization: <kredensial>" \
     http://localhost:8000/api/v1/audit/products-missing-odoo-id/
```

Respons: `{count, products, used_in_open_bundles}` —
`used_in_open_bundles` = subset yang **sedang dipakai bundle di lantai**
(state bukan `DONE`/`DRAFT`) sehingga paling mendesak.

Penyebab & solusi:
- produk dibuat manual di MES / master sync belum jalan → jalankan
  `erp_sync.sync_master_products` (§3);
- produk ada di MES dengan kode berbeda dari Odoo → rapikan mapping (produk MES
  dicocokkan ke Odoo lewat `Product.odoo_id`, bukan kode).

### 6.2 Rekonsiliasi selalu kosong / `NONE`

| Gejala | Cek | Solusi |
|---|---|---|
| `total_products = 0` | `master.Product` belum punya `odoo_id` | §3 sync master + §6.1 |
| `alerts` kosong padahal ada stok di Odoo | produk hanya ada di Odoo (bukan di master MES) | produk Odoo tanpa pasangan MES memang diabaikan (desain) |
| `vendor_bill_status = NONE` (readiness I6) | `account.move.invoice_origin` di Odoo **kosong** | isi origin = nama PO saat membuat bill, atau tunggu jalur alternatif `purchase.order.invoice_ids` (belum diimplementasikan) |
| selisih WIP “aneh” | bundle hasil scrap | state `DONE` + `qty_done=0` **tidak** lagi dihitung WIP (I8.7) |

### 6.3 HTTP 403 / 429

- **403** — semua endpoint ERP/audit memakai `IsAuthenticated` (I8.5, termasuk
  `/api/v1/sync/odoo/<stage>/` yang dulu `AllowAny`). Kirim kredensial user
  MES yang valid.
- **429** — rate limit DRF (`anon 60/min`, `user 300/min`) memakai cache Redis
  bersama. Saat menjalankan test beruntun, mode test otomatis aktif
  (`TESTING` mendeteksi `pytest` — I8.5b) sehingga throttle dilonggarkan; kalau
  429 muncul di lingkungan non-test, cek ulang pola pemanggilan klien.

### 6.4 `pytest` hilang setelah container di-recreate

`requirements.txt` sudah memuat `pytest`/`pytest-django`, tapi container
dibangun dari **image lama**. Bangun ulang:

```bash
docker compose build django
docker compose up -d django
```

(`pip install` manual hanya bertahan sampai container di-recreate berikutnya.)

### 6.5 Push gagal dengan pesan konfigurasi

| Pesan | Arti | Solusi |
|---|---|---|
| `Location WIP/PRODUCTION belum dikonfigurasi (ODOO_LOCATION_*)` | `ODOO_LOCATION_WIP_ID`/`PRODUCTION_ID` kosong | isi `.env` + `--force-recreate` (§1.2) |
| `Location PRODUCTION/FG belum dikonfigurasi (ODOO_LOCATION_*)` | `ODOO_LOCATION_FG_ID` kosong | idem |
| `Product ... belum punya odoo_id (sync master dulu)` | TX-SCRAP tanpa mapping produk | §3 + §6.1 |
| `UoM default belum dikonfigurasi (ODOO_UOM_ID)` | `ODOO_UOM_ID` kosong | isi id UoM PCS (§2.3) |

### 6.6 Push "berhasil" tapi tidak ada di Odoo

Cek `ERP_ADAPTER`: nilai tak dikenal → **fallback `NullAdapter`** (log
`ERP_ADAPTER ... tidak dikenal -> fallback ke null (fail-safe)`) sehingga
`SyncRecord` `SENT` dengan `erp_id` `NULL-<uuid>` tanpa menyentuh Odoo.
Pastikan `ERP_ADAPTER=odoo`.

Lacak kiriman kapan pun lewat audit (I8.11):

```bash
# action: erp_sync.push_wip | push_fg | push_scrap | push_invoice
docker compose exec django python manage.py shell -c \
"from core.audit.models import AuditLog; \
print(list(AuditLog.objects.filter(action='erp_sync.push_wip')[:5].values('resource','resource_id','result','metadata')))"
```

### 6.7 Stok dobel?

Tidak mungkin secara desain: `SyncRecord` punya unique constraint
`(resource, resource_id, stage)`, dan task mengabaikan record yang sudah
`SENT`/`DUPLICATE`. Buktinya load test 1000 stock move (I8.12):

```bash
LOAD_TEST=1 docker compose exec -T -e LOAD_TEST=1 django \
  python -m pytest tests/integration/test_load_1000.py -q
```

---

## 7. Endpoint F1–F3A (ringkasan 23)

23 endpoint agregat yang dikonsumsi frontend v3 (dashboard/reports/quality/inventory/
purchase/settings). Semua `IsAuthenticated` → anonim **403**.

| Group | Endpoint | Method | ID | Test |
|---|---|---|---|---|
| Dashboard | `/api/v1/dashboard/summary/` | GET | B1 | 11 |
| Production | `/api/v1/production/buffer-queue/` | GET | B2 | 9 |
| Production | `/api/v1/routing/graph/` | GET | B3 | 6 |
| Quality | `/api/v1/quality/defects/` | GET / **POST** | B4 / B7b | 13 / 9 |
| Quality | `/api/v1/quality/aql/` | GET | B5 | 7 |
| Quality | `/api/v1/quality/rework/` | GET | B6 | 7 |
| Inventory | `/api/v1/inventory/products/` | GET | B7 | 7 |
| Inventory | `/api/v1/inventory/operations/` | GET | B8 | 7 |
| Purchase | `/api/v1/purchase/orders/` | GET | B10 | 8 |
| Purchase | `/api/v1/purchase/reporting/` | GET | B11 | 10 |
| Purchase | `/api/v1/purchase/vendors/` | GET | B12 | 6 |
| Reports | `/api/v1/reports/line-efficiency/` | GET | B13 | 9 |
| Reports | `/api/v1/reports/wip/` | GET | B16 | 9 |
| Reports | `/api/v1/reports/line-efficiency/by-wc/` | GET | B18 | 5 |
| Reports | `/api/v1/reports/lead-time/` | GET | B19 | 6 |
| Reports | `/api/v1/reports/lead-time/bundles/` | GET | B19b | 5 |
| Reports | `/api/v1/reports/on-time-delivery/` | GET | B20 | 6 |
| Reports | `/api/v1/reports/on-time-delivery/orders/` | GET | B20b | 5 |
| Reports | `/api/v1/reports/wip/by-wc/` | GET | B21 | 5 |
| Settings | `/api/v1/settings/routing/` | GET+**POST** | B22 | 16 |
| Settings | `/api/v1/settings/bundling/` | GET+**POST** | B24 | 12 |
| Settings | `/api/v1/settings/line-allocation/` | GET+**POST** | B25 | 15 |

Implementasi: `integrations/erp_sync/monitoring.py` (agregat read-only) +
`apps_industry/garment/api/settings/views.py` (3 endpoint tulis). Detail per-endpoint
(id, method, bentuk response, test) ada di `docs/blueprint.md` §7b.

Cara cepat memverifikasi semuanya hidup di instance klien:

```bash
docker compose exec django python -m pytest \
  tests/integration/test_dashboard_summary.py tests/integration/test_buffer_queue.py \
  tests/integration/test_routing_graph.py tests/integration/test_quality_defects.py \
  tests/integration/test_quality_aql.py tests/integration/test_quality_rework.py \
  tests/integration/test_inventory_products.py tests/integration/test_inventory_operations.py \
  tests/integration/test_purchase_orders.py tests/integration/test_purchase_reporting.py \
  tests/integration/test_purchase_vendors.py tests/integration/test_reports_line_efficiency.py \
  tests/integration/test_reports_wip.py tests/integration/test_reports_line_efficiency_by_wc.py \
  tests/integration/test_reports_lead_time.py tests/integration/test_reports_on_time_delivery.py \
  tests/integration/test_reports_wip_by_wc.py tests/integration/test_settings_routing.py \
  tests/integration/test_settings_bundling.py tests/integration/test_settings_line_allocation.py \
  -q
```

Performance (sebelum pilot): lihat `docs/perf-benchmark.md` — 5 endpoint agregat sudah
dioptimasi (N+1 dihapus); uji batas query lock di
`tests/integration/test_perf_queries.py`.

---

## 8. Frontend v3 (konsumsi endpoint di atas)

Frontend produksi = **`frontend_app_v2/`** (React hand-coded, bukan metadata-driven).
Setiap resource punya saklar mode di `frontend_app_v2/src/api/_adapter.ts`:

| Item | Nilai (per 2026-10-10) |
|---|---|
| MODE `real` | **41** |
| MODE `dummy` | **5** — `inventoryReporting`, `settingsUsers`, `settingsRoles`, `settingsDevices`, `hitl` |
| Real adapter | `frontend_app_v2/src/api/real/*.ts` (38 file, termasuk helper `_shape.ts`) |
| Dummy adapter | `frontend_app_v2/src/api/dummy/*.ts` (6 file) |
| Total key MODE | 46 |

Arti mode: `real` = halaman memakai endpoint backend (daftar §7); `dummy` = data fixture
lokal (halaman tetap jalan tanpa backend, **bukan** untuk keputusan produksi).

Cara flip sebuah key `dummy → real` (pola yang dipakai F2C.1/F2C.2/F3A.CLOSE):

1. pastikan endpoint-nya ada & hijau (`§7` + test di `tests/integration/`);
2. buat adapter real di `src/api/real/<resource>.ts` — ekspor path + `readX()` **murni** +
   `fetchX(client, ...)`; ikuti pola `src/api/real/_shape.ts` (ListPage/envelope);
3. ubah **satu** nilai di `MODE` (`src/api/_adapter.ts`) menjadi `'real'` dan arahkan
   `pickAdapter(key, realFn, realFn)` di barrel `src/api/<resource>.ts`;
4. hapus file dummy **hanya bila** tidak dipakai key lain (cek `grep`);
5. perbarui test: `frontend_app_v2/tests/unit/api/_adapter.test.ts` mengunci jumlah MODE —
   **real harus 41 / dummy 5** sampai F3-B selesai (saat itu angka naik jadi 46/0);
6. jalankan gate frontend:

```bash
export PATH=$HOME/.bun/bin:$PATH
cd frontend_app_v2
bun run typecheck && bun run lint && bun --bun run test && bun x --bun vite build
```

Catatan produksi frontend:
- `VITE_API_BASE_URL`, `VITE_WS_URL`, `VITE_WS_ENABLED` dibaca **saat build** (build-arg),
  bukan runtime → setelah diubah **rebuild** `frontend_builder`, bukan restart;
- build produksi memakai SSL (WS `wss://`) dan satu domain dengan API (`https://<domain>/api/v1`);
- detail status & statistik: `frontend_app_v2/docs/current-project.json`.

---

## 9. UAT & onboarding (dokumen terkait)

| Kebutuhan | Dokumen | Isi |
|---|---|---|
| UAT Klien A | `docs/uat-checklist.md` | pre-flight → 5 role walkthrough → cross-cutting (WS, offline, device, priority, bottleneck) → issue log → sign-off |
| Onboarding klien baru | `docs/onboarding-klien-baru.md` | 7 tahap (setup Odoo → sync master → `.env.prod` → deploy → seed → UAT → go-live), estimasi 1 hari |
| Operasional harian | `docs/runbook-operasional.md` | cek harian/mingguan/bulanan, troubleshooting, jendela maintenance, kontak eskalasi |
| Audit pra-deploy | `docs/ops-readiness-audit.md` | blocker pra-deploy + status |
| Benchmark performa | `docs/perf-benchmark.md` | angka N=100/1.000/10.000 per endpoint + optimasi N+1 |
| Indeks semua dokumen | `docs/README-index.md` | peta dokumentasi `django_app/docs/` |

Saat UAT, **§5 Verifikasi Portabilitas** di dokumen ini tetap jadi acuan alur ERP
end-to-end (SO → bundle → WIP → FG → invoice, PO → readiness); checklist §9 di atas
melengkapinya dengan per-role UI + sign-off.

---

## 10. Troubleshooting tambahan (pasca F1–F5.3)

| Gejala | Cek | Fix |
|---|---|---|
| Dashboard/laporan lambat pada data besar (≥10 rb bundle) | jumlah query konstan? (`tests/integration/test_perf_queries.py` hijau?) | bukan N+1 — penyebab volume; lihat `docs/perf-benchmark.md` §8–§9 (index/cache = F6) |
| Halaman menampilkan **data contoh** (bukan data nyata) | key MODE masih `dummy`? (5 sisa: `inventoryReporting`, `settingsUsers`, `settingsRoles`, `settingsDevices`, `hitl`) | §8 dokumen ini; jangan dipakai untuk keputusan produksi |
| Chatter tidak realtime | devtools → `wss://<domain>/ws/events/` harus **101**; `VITE_WS_ENABLED` | isi `VITE_WS_ENABLED=true` lalu **rebuild** `frontend_builder` + `nginx -s reload` |
| Perubahan `VITE_*` tidak berefek | `VITE_*` = build-arg | `docker compose up -d --force-recreate frontend_builder nginx` |
| **403** di endpoint agregat F1–F3A | permintaan anonim | semua endpoint `IsAuthenticated` → kirim kredensial user MES |
| **400** `from > to` di `/reports/*` | rentang tanggal terbalik | perbaiki parameter `from`/`to` (ISO-8601) |
| **400** `group_by=… tidak dikenal` di `/reports/wip/` | nilai selain `wc`/`none` | pakai `wc` (default) atau `none` |
| **400** POST `/settings/{routing,bundling,line-allocation}/` | body kurang field wajib | routing: `name` + `steps[]`; bundling: `name`; line-allocation: `name` + `wc_type` + `line_id` (angka) — `docs/blueprint.md` §7b |
| Tabel UI kosong padahal data ada | filter periode/pencarian halaman | reset filter; cek `total_count`/`has_more` di respons (§7) |
| “19 test gagal” dianggap regresi | file-nya Celery/ERP/trace | **baseline pre-existing** (`docs/curent_project.json` → `test_pre_existing_failures`); traceback `erp_sync/tasks.py` `task.request.headers` |

Catatan: **beat schedule tetap 14 entry** (terverifikasi F5.3, 2026-10-10 — test
`config/tests/test_settings_beat.py` mengunci jumlah ini).

---

## 11. Variabel `.env.prod` tambahan (produksi, pasca F3-B)

Selain variabel §1 (wajib untuk integrasi), produksi memakai template
**`.env.prod.example`** di root repo (salin → `.env.prod`; panduan per baris ada di
`docs/onboarding-klien-baru.md` §3). Kelompok tambahan:

| Kelompok | Variabel | Catatan |
|---|---|---|
| Django core | `DJANGO_SECRET_KEY` (`openssl rand -hex 32`), `DJANGO_DEBUG=False`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_TIME_ZONE`, `DJANGO_LOG_LEVEL` | `SECRET_KEY` unik per klien |
| Database | `DB_NAME/USER/PASSWORD/HOST/PORT/CONN_MAX_AGE/CONNECT_TIMEOUT` **dan** `POSTGRES_DB/USER/PASSWORD` | DB_* harus sama dengan POSTGRES_* |
| TLS | `SECURE_SSL_REDIRECT=True`, `DJANGO_SECURE_PROXY_SSL_HEADER=True`, `SESSION_COOKIE_SECURE=True`, `CSRF_COOKIE_SECURE=True`, `SECURE_HSTS_SECONDS` (uji awal: `300`), `SECURE_HSTS_INCLUDE_SUBDOMAINS`, `SECURE_HSTS_PRELOAD=False` | aktif saat `DEBUG=False`; TLS diterminasi Nginx |
| Nginx/Certbot | `DOMAIN` (samakan dengan `nginx/conf.d/mes.conf`), `LETSENCRYPT_EMAIL` | dipakai `./scripts/generate-ssl.sh` |
| Frontend build | `VITE_API_BASE_URL` (`https://<domain>/api/v1`), `VITE_WS_URL` (`wss://<domain>/ws`), `VITE_WS_ENABLED=true` | **build-arg** (bukan runtime) |
| Backup | `BACKUP_DIR=./backups`, `RETENTION_DAYS=7`, `BACKUP_INTERVAL_SECONDS=86400` | service `backup` (loop harian) |
| Sentry (opsional) | `SENTRY_DSN`, `SENTRY_ENVIRONMENT`, `SENTRY_RELEASE`, `SENTRY_TRACES_SAMPLE_RATE`, `SENTRY_SEND_DEFAULT_PII` | `SENTRY_DSN` kosong = nonaktif |
| Lain-lain | `CELERY_RESULT_EXPIRES`, `RECONCILIATION_ALERT_WA_TO`, `WA_BACKEND`/`WA_API_URL`/`WA_API_KEY` (opsional; profil H5.8 di `/api/v1/settings/wa/`), `ERP_ADAPTER=odoo` | `WA_*` masih gateway `mock` |

Verifikasi cepat sebelum deploy:

```bash
grep -n "__" .env.prod          # harus KOSONG (tidak ada placeholder tersisa)
docker compose -f docker-compose.prod.yml exec django python -c \
  "import os;print([k for k in ('ODOO_URL','ODOO_API_KEY','ODOO_LOCATION_WIP_ID','ODOO_UOM_ID','DOMAIN') if not os.environ.get(k)])"
```

---

## Lampiran — Test & bukti (untuk onboarding/QA)

```bash
docker compose exec django python -m pytest integrations/erp_sync/tests -q   # integrasi ERP
docker compose exec django python -m pytest integrations/ -q                 # + printing/wa_bot/ai
docker compose exec django python -m pytest apps_industry/ config/ tests/ -q # MES + konfigurasi + integrasi
docker compose exec django python -m pytest tests/integration/test_failsafe_full_stack.py -q  # I8.10
docker compose exec django python -m pytest integrations/erp_sync/tests -k audit -q           # I8.11
```

Referensi dokumen:
- `docs/integrations/CONTRACT.md` — kontrak field & TX (WIP/FG/SCRAP/INVOICE) yang dikunci;
- `docs/integrations/framework_jsonrpc_validation.md` — alur probe → kontrak → test → adapter;
- `docs/curent_project.json` — status fase & entri sprint (I1…I8).
