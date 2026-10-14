/**
 * _adapter.ts - peta mode per resource: 'real' (backend sudah ada) atau 'dummy'
 * (backend belum ada, pakai fixture `api/dummy/*`).
 *
 * Satu-satunya tempat untuk memutuskan sumber data. `api/{resource}.ts` (lapisan yang
 * diimpor halaman) memanggil `pickAdapter()` dengan nama resource di file ini, jadi
 * pindah dummy -> real cukup mengubah SATU nilai di `MODE` (+ menambah fungsi di
 * `api/real/{resource}.ts`).
 *
 * CATATAN: `_adapter.ts` tidak boleh mengimpor apa pun (modul ini harus bisa dibaca
 * tanpa efek samping) dan tidak berisi logic domain.
 */

export type AdapterMode = 'real' | 'dummy';

export const MODE: Record<string, AdapterMode> = {
  // REAL - sudah ada backend (Kontrak Backend bagian 1)
  bundles: 'real',
  workOrders: 'real',
  orderLines: 'real', // kontrak v4.3: resource metadata `order-lines` (F1/D7)
  // F2 (R3): adapter baru yang endpoint-nya SUDAH ADA di backend v4.3.
  qcRows: 'real', // F2/2.3  - GET /garmen/qc/ (ScrapAccumulator, read-only)
  syncOdoo: 'real', // F2/2.9  - POST /sync/odoo/{WIP|FG}/ (IsAuthenticated)
  syncMaster: 'real', // F2/2.9  - POST /sync/master/{entity}/ (IsAuthenticated)
  syncScrap: 'real', // F2/2.9  - POST /sync/scrap/ (IsAuthenticated, sinkron)
  readiness: 'real', // F2/2.9b - GET /garmen/orders/{id}/readiness/ (IsAuthenticated)
  // F9 (9.0): endpoint audit & rekonsiliasi SUDAH ADA (anon 403) - read-only, tidak menyentuh Odoo.
  reconciliation: 'real', // F9/9.0 - GET /reconciliation/report/?days=N (§6.2, days 1..90)
  audit: 'real', // F9/9.0 - GET /audit/products-missing-odoo-id/ (§6.1)
  // F15 (revive F10) - endpoint monitoring Fase 4.4 SUDAH ADA di backend (anon 403).
  invoiceQueue: 'real', // F15 - GET /finance/invoices/ (IsAuthenticated)
  syncMonitor: 'real', // F15 - GET /sync/records/?stage=&status= (IsAuthenticated)
  chatter: 'real',
  metadata: 'real',
  devices: 'real',
  aiChat: 'real', // stub {ok:false} tapi endpoint ADA
  print: 'real',
  wa: 'real',

  // DUMMY - belum ada backend (atau bentuk halaman belum dipetakan - lihat catatan)
  dashboard: 'real', // F2C.2 - GET /dashboard/summary/ (B1 + G1)
  bufferQueue: 'real', // F2C.2 - GET /production/buffer-queue/ (B2 + G2)
  routing: 'real', // F2c.1 - GET /routing/graph/ (shape backend, position auto-layout)
  // `qc` nyata ada di key `qcRows`; 4 key di bawah = kontrak UI lama (/quality/* belum ada).
  qcLog: 'real', // F2C.2 - GET /quality/defects/ (B4 + G3)
  qcAql: 'real', // F3A.CLOSE - GET /quality/aql/ (B5)
  qcRework: 'real', // F2C.2 - GET /quality/rework/ (B6)
  qcSubmit: 'real', // F3A.CLOSE - POST /quality/defects/ (B7b)
  inventoryProducts: 'real', // F2c.1 - GET /inventory/products/ (ProductRow, tanpa type/uom)
  inventoryOperations: 'real', // F2C.2 - GET /inventory/operations/ (B8)
  inventoryReporting: 'real', // F5.4.CLOSE - GET /inventory/reporting/ (B30, agregat stok per lokasi)
  // H2.5 - LOG Inventory Adjustment MES -> Odoo (`/inventory/adjust*`, `/inventory/stock-qty/`).
  // Catatan: MES TIDAK menyimpan stok; `stock-qty` = baca on-demand dari Odoo (read-only).
  inventoryAdjustments: 'real',
  // H2.6 - LOG Stock Transfer MES -> Odoo (`/inventory/transfer*`): internal transfer
  // via `stock.picking` + `button_validate()`. MES tetap TIDAK menyimpan stok.
  stockTransfers: 'real',
  // H1.1 - CRUD master produk (MES = source of truth master). `/master/products/`
  // SUDAH ADA di backend (`master/api.py`) -> real, tanpa dummy.
  masterProducts: 'real',
  // H1.2 - CRUD master UoM (`/master/uoms/`, H1.2). Dipakai halaman master UoM
  // + dropdown UoM di form produk -> real, tanpa dummy.
  masterUoms: 'real',
  // H1.3 - CRUD master gudang (`/master/warehouses/`, H1.3) -> real, tanpa dummy.
  masterWarehouses: 'real',
  // H1.4 - CRUD master lokasi (`/master/locations/`, H1.4: hierarki parent/warehouse
  // + usage 7 nilai Odoo) -> real, tanpa dummy.
  masterLocations: 'real',
  // H1.5 - CRUD master BOM (`/master/boms/`, H1.5: header + `lines[]` inline)
  // -> real, tanpa dummy.
  masterBoms: 'real',
  // H1.6 - CRUD master Partner (`/master/partners/`: customer + supplier, NPWP,
  // kontak) -> real, tanpa dummy.
  masterPartners: 'real',
  // H1.7 - CRUD master Work Center (`/master/work-centers/`: tipe stasiun, tag
  // kapabilitas, kapasitas/jam) -> real, tanpa dummy (MES-only, tanpa odoo_id).
  masterWorkCenters: 'real',
  // H1.8 - CRUD master Production Line (`/master/production-lines/`: anggota
  // work center M2M + tag kapabilitas) -> real, tanpa dummy (MES-only).
  masterProductionLines: 'real',
  // H1.9 - CRUD master Routing DAG (`/settings/routing/` B22 di-extend: detail +
  // PUT/DELETE header + CRUD step) -> real, tanpa dummy, tanpa endpoint paralel.
  masterRoutings: 'real',
  // Sprint C - Number Sequence (`/settings/sequences/`: list + preview + PUT).
  // MES-only: nomor MES tidak dikirim ke `ir.sequence` Odoo (counter internal Odoo).
  masterSequences: 'real',
  // H5.2 - Currency (`/settings/currencies/`: CRUD + default MES; mirror `res.currency`).
  // MES-only: tidak ada konsumen MES yang mengirim currency ke Odoo (ledger SKIPPED).
  masterCurrencies: 'real',
  // H5.1 - Company Profile (`/settings/company/`: GET/PUT SINGLETON; greenfield MES).
  // MES-only: identitas perusahaan tidak dikirim ke `res.company` Odoo (ledger SKIPPED).
  company: 'real',
  // H5.6 - Integration Config (`/settings/integration/`: GET/PUT + test-connection).
  // Opsi B: DB menyimpan profil; konsumen tetap baca `.env` (ledger SKIPPED).
  integrationConfig: 'real',
  // H5.8 - WA Gateway Config (`/settings/wa/`: GET/PUT + test-connection gateway).
  // Opsi B: DB menyimpan profil; `get_wa_gateway` tetap baca `.env` (ledger SKIPPED).
  waConfig: 'real',
  // H5.5 - Audit Log Viewer (`/settings/audit/`: daftar + filter + detail).
  // READ-ONLY (append-only) — MODE key BARU supaya tidak bentrok `audit` (F9 audit produk).
  auditLogs: 'real',
  // H5.7 - Printer Config (`/settings/printer/`: GET/PUT + test-connection printer).
  // Opsi B: DB menyimpan profil; `printing.backends.get_backend` tetap baca `.env`.
  printerConfig: 'real',
  // H5.4 - Permission Matrix (`/settings/permissions/`: GET matrix + PUT bulk per role).
  // Opsi A′: profil tersimpan + `effective` (snapshot kode) + banner; enforcement tetap kode.
  permissionMatrix: 'real',
  // H3.6 - CRUD master Tax (`/master/taxes/`: tarif/jenis pajak, pajak default MES,
  // push ke `account.tax`). SUDAH ADA di backend -> real, tanpa dummy.
  masterTaxes: 'real',
  // H3.1 - CRUD Customer Invoice MES (`/finance/customer-invoices/`: model invoice +
  // push `account.move` draft). SUDAH ADA di backend -> real, tanpa dummy.
  // CATATAN: `invoiceQueue` (F15 antrean I5 read-only) TETAP terpisah & tidak diubah.
  customerInvoices: 'real',
  // H3.2 - CRUD Vendor Bill MES (`/finance/vendor-bills/`: model bill + push
  // `account.move` **in_invoice** draft). SUDAH ADA di backend -> real, tanpa dummy.
  // CATATAN: I6 (`MaterialReadiness.vendor_bill_*`, tarikan Odoo) & B10
  // (`purchaseOrders`) TETAP terpisah & tidak diubah.
  vendorBills: 'real',
  // H3.3 - CRUD Payment MES (`/finance/payments/`: satu model dua arah
  // INBOUND/OUTBOUND + push `account.payment` draft). SUDAH ADA di backend -> real.
  // CATATAN: rekonsiliasi tetap di Odoo (MES tidak merekonsiliasi).
  payments: 'real',
  // H3.4 - CRUD Journal Entry manual MES (`/finance/journal-entries/`: double-entry
  // + push `account.move` `move_type='entry'` **draft`; journal `general` saja).
  // SUDAH ADA di backend -> real. CATATAN: posting/rekonsiliasi tetap di Odoo.
  journalEntries: 'real',
  // H3.4 - master Account (chart of accounts) & Journal read-only untuk form Journal
  // Entry (`/master/accounts/`, `/master/journals/`, hasil pull `erp_sync`). Tanpa tulis.
  masterAccounts: 'real',
  masterJournals: 'real',
  // H2.1 - Sales Order (`/garmen/orders/`: CRUD + nested `lines[]` + transisi
  // confirm/done/cancel). Transaksi satu arah MES → Odoo saat CONFIRMED.
  salesOrders: 'real',
  // H2.2 - Purchase Order MES (`/garmen/purchase-orders/`: CRUD + nested `lines[]`
  // + confirm/done/cancel + sync-odoo-state read-only). BUKAN B10 `purchaseOrders`
  // (monitoring read-only dari Odoo di `/purchase/orders/`).
  purchaseOrdersCrud: 'real',
  // H2.3 — Work Order MES (create/update/delete/split/generate + aksi state).
  // B10/F13 `workOrders` (list+detail tipis) TETAP terpisah & tidak diubah.
  workOrdersCrud: 'real',
  // H2.4 — Bundle MES (create/preview/update/delete/split/merge).
  // F13 `bundles` (list/detail tipis + aksi) TETAP terpisah & tidak diubah.
  bundlesCrud: 'real',
  // Endpoint /purchase/* BELUM ADA; `readiness` (key terpisah di atas) = kesiapan
  // material per-Order, BUKAN daftar PO/vendor -> bukan pengganti key ini (F2 recon §3).
  purchaseOrders: 'real', // F2C.2 - GET /purchase/orders/ (B10 + G5)
  purchaseVendors: 'real', // F2C.2 - GET /purchase/vendors/ (B12)
  purchaseReporting: 'real', // F2C.2 - GET /purchase/reporting/ (B11 + G5b)
  // Endpoint /reports/* belum ada di backend (F2 live probe: 404) -> tetap dummy.
  reportsLineEfficiency: 'real', // F2C.2 - GET /reports/line-efficiency/ (B13 + G4b)
  reportsLeadTime: 'real', // F3A.CLOSE - GET /reports/lead-time/ (B19)
  reportsOTD: 'real', // F3A.CLOSE - GET /reports/on-time-delivery/ (B20)
  reportsWIP: 'real', // F2C.2 - GET /reports/wip/ (B16 + G4)
  reportsLineEfficiencyByWc: 'real', // F3A.CLOSE - GET /reports/line-efficiency/by-wc/ (B18)
  reportsLeadTimeBundles: 'real', // F3A.CLOSE - GET /reports/lead-time/bundles/ (B19b)
  reportsOnTimeDeliveryOrders: 'real', // F3A.CLOSE - GET /reports/on-time-delivery/orders/ (B20b)
  reportsWipByWc: 'real', // F3A.CLOSE - GET /reports/wip/by-wc/ (B21)
  reportSales: 'real', // H4.1 - GET /reports/sales/ (agregat penjualan + cache 300 dtk)
  reportPurchases: 'real', // H4.2 - GET /reports/purchases/ (agregat pembelian + cache 300 dtk)
  reportStock: 'real', // H4.3 - GET /reports/stock/ (snapshot stok Odoo via I7 + cache 300 dtk)
  reportCogs: 'real', // H4.4 - GET /reports/cogs/ (laporan HPP/laba kotor + cache 300 dtk)
  reportPnl: 'real', // H4.5 - GET /reports/pnl/ (laporan laba-rugi + cache 300 dtk)
  reportProduction: 'real', // H4.6 - GET /reports/production/ (laporan produksi + cache 300 dtk)
  // H4.7 - GET /dashboard/executive/ (orkestrasi H4.1-H4.6 + alerts; cache 300 dtk).
  // PARALEL: key `dashboard` (B2 `/dashboard/summary/`) TIDAK diubah.
  executiveDashboard: 'real',
  // H4.8 - POST /export/<report>/ (berkas xlsx/pdf; 7 laporan FASE H4).
  export: 'real',
  settingsRouting: 'real', // F3A.CLOSE - GET+POST /settings/routing/ (B22)
  settingsBundling: 'real', // F3A.CLOSE - GET+POST /settings/bundling/ (B24)
  settingsLineAllocation: 'real', // F3A.CLOSE - GET+POST /settings/line-allocation/ (B25)
  settingsUsers: 'real', // F5.4.CLOSE - GET+POST /settings/users/ + PUT|DELETE /settings/users/<id>/ (B26)
  settingsRoles: 'real', // F5.4.CLOSE - GET /settings/roles/ (B27)
  settingsDevices: 'real', // F5.4.CLOSE - GET /settings/devices/ (B28, katalog profil)
  hitl: 'real', // F5.4.CLOSE - GET /ai/hitl/queue/ + POST approve|reject (B29)
  // F6.2 - auth hybrid (backend F6.1): POST login/login-operator/logout/change-password
  // + GET /auth/me/ (session cookie; `AuthGuard` + halaman login memakainya).
  auth: 'real',
};

/** PURE - pilih implementasi real atau dummy sesuai `MODE[resource]`. */
export function pickAdapter<T>(resource: string, real: T, dummy: T): T {
  return MODE[resource] === 'real' ? real : dummy;
}

/** PURE - true kalau resource ini sudah dilayani backend nyata. */
export function isReal(resource: string): boolean {
  return MODE[resource] === 'real';
}
