import {
  Banknote,
  Bot,
  CheckCircle2,
  Factory,
  FileText,
  LayoutDashboard,
  Package,
  Settings,
  ShoppingCart,
  TrendingUp,
  type LucideIcon,
} from 'lucide-react';

/**
 * nav-config.ts - sumber tunggal navigasi App Shell (Blueprint v3 bagian 5.2).
 *
 * Dipakai `Sidebar` (rel aplikasi), `TopBar` (menu kontekstual), dan `useRole`
 * (filter per role). JANGAN duplikasi daftar ini di komponen lain.
 *
 * Semua ikon dari `lucide-react` (tidak ada import file gambar/asset).
 */

export interface NavMenuItem {
  label: string;
  path: string;
  /**
   * F16 — anak menu (mis. `Products ▾ → List | New`). Kosong/undefined ⇒ TopBar merender
   * item ini sebagai **link biasa** (tanpa dropdown). Diisi hanya kalau halaman anaknya
   * BENAR-BENAR ada di `App.tsx` (jangan bikin path fiktif).
   */
  children?: readonly NavMenuItem[];
}

export interface NavApp {
  id: string;
  label: string;
  icon: LucideIcon;
  path: string;
  topbar: NavMenuItem[];
}

export const NAV_APPS: NavApp[] = [
  { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard, path: '/', topbar: [] },
  {
    id: 'production',
    label: 'Production',
    icon: Factory,
    path: '/production',
    topbar: [
      { label: 'Shop Floor', path: '/production/scan' },
      { label: 'Buffer Queue', path: '/production/buffer-queue' },
      { label: 'Routing', path: '/production/routing' },
      { label: 'QC', path: '/production/qc' },
      // H2.3 — Work Order MES (list = halaman F13; form/detail baru H2.3).
      { label: 'Work Order', path: '/production/work-orders' },
    ],
  },
  {
    id: 'inventory',
    label: 'Inventory',
    icon: Package,
    path: '/inventory',
    topbar: [
      { label: 'Products', path: '/inventory/products' },
      // H1.1 — CRUD master produk (MES = source of truth). Path `/master/products`
      // dipetakan ke app ini lewat `LEGACY_APP_PATHS` di bawah.
      { label: 'Master Products', path: '/master/products' },
      // H1.2 — CRUD master UoM (satuan); dipakai juga oleh dropdown di form produk.
      { label: 'Master UoM', path: '/master/uoms' },
      // H3.6 — CRUD master pajak (tax: tarif/jenis + pajak default MES; dipakai juga
      // oleh dropdown `tax_ids` di form SO/PO H2.1/H2.2).
      { label: 'Master Pajak', path: '/master/taxes' },
      // H1.3 — CRUD master gudang (warehouse).
      { label: 'Master Gudang', path: '/master/warehouses' },
      // H1.4 — CRUD master lokasi (location: usage 7 nilai + hierarki induk/gudang).
      { label: 'Master Lokasi', path: '/master/locations' },
      // H1.5 — CRUD master BOM (header + komponen inline).
      { label: 'Master BOM', path: '/master/boms' },
      // H1.6 — CRUD master partner (pelanggan + supplier).
      { label: 'Master Partner', path: '/master/partners' },
      // H1.7 — CRUD master work center (stasiun kerja; MES-only).
      { label: 'Master Work Center', path: '/master/work-centers' },
      // H1.8 — CRUD master production line (lini + anggota WC; MES-only).
      { label: 'Master Production Line', path: '/master/production-lines' },
      // H1.9 — CRUD master routing DAG (alur proses; MES-only, endpoint B22 extend).
      { label: 'Master Routing', path: '/master/routings' },
      // H2.5 — LOG inventory adjustment MES → Odoo (stok tetap di Odoo; form di
      // `/inventory/adjust` dijangkau dari tombol "Buat Adjustment" di halaman ini).
      { label: 'Adjustment', path: '/inventory/adjustments' },
      // H2.6 — LOG stock transfer MES → Odoo (picking internal; form di
      // `/inventory/transfer` dijangkau dari tombol "Buat Transfer" di halaman ini).
      { label: 'Transfer', path: '/inventory/transfers' },
      { label: 'Operations', path: '/inventory/operations' },
      { label: 'Reporting', path: '/inventory/reporting' },
      { label: 'Configuration', path: '/inventory/config' },
    ],
  },
  {
    id: 'sales',
    label: 'Sales',
    icon: FileText,
    path: '/sales',
    topbar: [
      // H2.1 — Sales Order MES (transaksi; push ke Odoo saat CONFIRMED).
      { label: 'Orders', path: '/sales/orders' },
    ],
  },
  {
    id: 'purchase',
    label: 'Purchase',
    icon: ShoppingCart,
    path: '/purchase',
    topbar: [
      { label: 'Orders', path: '/purchase/orders' },
      { label: 'Vendors', path: '/purchase/vendors' },
      { label: 'Reporting', path: '/purchase/reporting' },
    ],
  },
  {
    id: 'quality',
    label: 'Quality',
    icon: CheckCircle2,
    path: '/quality',
    topbar: [
      { label: 'Defect Log', path: '/quality/defects' },
      { label: 'AQL', path: '/quality/aql' },
      { label: 'Rework', path: '/quality/rework' },
    ],
  },
  {
    id: 'reports',
    label: 'Reports',
    icon: TrendingUp,
    path: '/reports',
    topbar: [
      { label: 'Line Efficiency', path: '/reports/line-efficiency' },
      { label: 'Lead Time', path: '/reports/lead-time' },
      { label: 'On-Time Delivery', path: '/reports/on-time-delivery' },
      { label: 'WIP', path: '/reports/wip' },
      // F9/9.4 — halaman baru (endpoint §6.2 SUDAH ADA; anon 403).
      { label: 'Reconciliation', path: '/reports/reconciliation' },
      // H4.1 — laporan penjualan (GET /reports/sales/, DB murni read-only).
      { label: 'Sales', path: '/reports/sales' },
      // H4.2 — laporan pembelian (GET /reports/purchases/, DB murni read-only).
      { label: 'Purchases', path: '/reports/purchases' },
      // H4.3 — laporan stok snapshot (GET /reports/stock/, Odoo via I7).
      { label: 'Stock', path: '/reports/stock' },
      // H4.4 — laporan HPP/laba kotor (GET /reports/cogs/, DB murni).
      { label: 'HPP (COGS)', path: '/reports/cogs' },
      // H4.5 — laporan laba-rugi PnL (GET /reports/pnl/, DB murni).
      { label: 'Laba-Rugi', path: '/reports/pnl' },
      // H4.6 — laporan produksi (GET /reports/production/, DB murni).
      { label: 'Produksi', path: '/reports/production' },
      // H4.7 — dashboard eksekutif (GET /dashboard/executive/, orkestrasi H4.1–H4.6).
      // Menu SENGAJA di app `reports` (bukan app `dashboard`) supaya `appLandingPath`
      // app Dashboard tetap `/`; path-nya dipetakan lewat `LEGACY_APP_PATHS` di bawah.
      { label: 'Executive', path: '/dashboard/executive' },
    ],
  },
  {
    id: 'settings',
    label: 'Settings',
    icon: Settings,
    path: '/settings',
    topbar: [
      { label: 'Routing', path: '/settings/routing' },
      { label: 'Bundling', path: '/settings/bundling' },
      { label: 'Line Allocation', path: '/settings/line-allocation' },
      // H5.1 — profil perusahaan (identitas MES; MES-only).
      { label: 'Company', path: '/settings/company' },
      // Sprint C — penomoran dokumen (MES-only; prefix/tahun/counter).
      { label: 'Number Sequence', path: '/settings/sequences' },
      // H5.2 — mata uang (mirror res.currency Odoo; MES-only).
      { label: 'Currencies', path: '/settings/currencies' },
      { label: 'Devices', path: '/settings/devices' },
      { label: 'Users', path: '/settings/users' },
      // F9/9.4 — audit produk tanpa odoo_id (endpoint §6.1 SUDAH ADA; anon 403).
      { label: 'Audit', path: '/settings/audit' },
      // F15 — monitoring sync (Fase 4.4: `GET /sync/records/`).
      { label: 'Sync Monitor', path: '/settings/sync' },
      // H5.6 — profil config integrasi MES ↔ Odoo (aktivasi lewat .env + restart).
      { label: 'Integration', path: '/settings/integration' },
      // H5.8 — profil gateway WhatsApp (URUTAN AKHIR: landing tetap /settings/routing).
      { label: 'WA Gateway', path: '/settings/wa' },
      // H5.5 — jejak audit (read-only; BUKAN `/settings/audit` milik F9 = audit produk).
      { label: 'Audit Log', path: '/settings/audit-log' },
      // H5.7 — profil printer thermal ESC/POS (URUTAN AKHIR: landing tetap /settings/routing).
      { label: 'Printer', path: '/settings/printers' },
      // H5.4 — matrix izin (profil + efektif; enforcement tetap guard kode) — TERAKHIR.
      { label: 'Permissions', path: '/settings/permissions' },
    ],
  },
  { id: 'ai', label: 'AI Assistant', icon: Bot, path: '/ai/chat', topbar: [] },
  {
    // F15 — Finance jadi NYATA (Fase 4.4: `GET /finance/invoices/` sudah ada).
    id: 'finance',
    label: 'Finance',
    icon: Banknote,
    path: '/finance',
    topbar: [
      { label: 'Invoices', path: '/finance/invoices' },
      // H3.1 — CRUD Customer Invoice MES (harga & pajak nyata; draft ke Odoo).
      // Halaman F15 di atas TETAP = antrean I5 read-only (dari SyncRecord).
      { label: 'Customer Invoices', path: '/finance/customer-invoices' },
      // H3.2 — CRUD Vendor Bill MES (tagihan vendor; draft `in_invoice` ke Odoo).
      // I6 (`MaterialReadiness.vendor_bill_*`) & B10 (`/purchase/orders`) TIDAK diubah.
      { label: 'Vendor Bills', path: '/finance/vendor-bills' },
      // H3.3 — CRUD Payment MES (satu model dua arah: customer bayar kita /
      // kita bayar vendor; draft `account.payment` ke Odoo). Rekonsiliasi di Odoo.
      { label: 'Payments', path: '/finance/payments' },
      // H3.4 — CRUD Journal Entry manual MES (double-entry; draft `account.move`
      // `move_type='entry'` ke Odoo, journal `general` saja). Posting di Odoo.
      { label: 'Journal Entries', path: '/finance/journal-entries' },
    ],
  },
];

/**
 * F13/13.2-13.3 — alias path yang TIDAK diawali `path` app-nya sendiri.
 *
 * Ini penambahan NILAI (bukan perubahan struktur `NAV_APPS`): dipakai `findAppByPath`
 * supaya Sidebar (sorotan app aktif), TopBar (judul + menu konteks), `BottomNav`, dan
 * `RoleGuardFallback` mengenali app pemilik path-path berikut:
 *
 *  - `/bundles`, `/workshop`, `/work-orders` = route alur produksi v2 yang berdiri sendiri
 *    (sekarang dipetakan ke app `production`, konsisten dengan `RoleRoute`-nya = PRODUCTION_ROLES);
 *  - `/dashboard` = alias app Dashboard (di `NAV_APPS` app Dashboard memakai path `/`);
 *  - `/dashboard/executive` = H4.7 dashboard eksekutif (menunya di app `reports`; guard
 *    route-nya `SUPERVISOR_ROLES`). SENGAJA bukan app `dashboard` supaya
 *    `appLandingPath` app Dashboard tetap `/` (lihat `tests/unit/app/route-fix.test.ts`);
 *  - `/master/products*` = H1.1 CRUD master produk (keputusan modul: menunya di app
 *    `inventory`), guard-nya `INVENTORY_ROLES` — sama seperti `/inventory/*`;
 *  - `/master/uoms*` = H1.2 CRUD master UoM (menunya juga di app `inventory`);
 *  - `/master/taxes*` = H3.6 CRUD master pajak (menu di app `inventory`);
 *  - `/master/warehouses*` = H1.3 CRUD master gudang (menunya juga di app `inventory`).
 *  - `/master/locations*` = H1.4 CRUD master lokasi (menunya juga di app `inventory`).
 *  - `/master/boms*` = H1.5 CRUD master BOM (menunya juga di app `inventory`).
 *  - `/master/partners*` = H1.6 CRUD master partner (menunya juga di app `inventory`).
 *  - `/master/work-centers*` = H1.7 CRUD master work center (menu di app `inventory`).
 *  - `/master/production-lines*` = H1.8 CRUD master production line (menu di app `inventory`).
 *  - `/master/routings*` = H1.9 CRUD master routing DAG (menu di app `inventory`).
 */
export const LEGACY_APP_PATHS: readonly { prefix: string; appId: string }[] = [
  { prefix: '/bundles', appId: 'production' },
  { prefix: '/workshop', appId: 'production' },
  { prefix: '/work-orders', appId: 'production' },
  { prefix: '/dashboard', appId: 'dashboard' },
  // H4.7 — dashboard eksekutif: menu di app `reports` (prefix TERPANJANG menang atas
  // `/dashboard`), sehingga app `dashboard` (patokan `appLandingPath = '/'`) tetap utuh.
  { prefix: '/dashboard/executive', appId: 'reports' },
  { prefix: '/master/products', appId: 'inventory' },
  { prefix: '/master/uoms', appId: 'inventory' },
  // H3.6 — master pajak (tax) juga menempel ke app `inventory`.
  { prefix: '/master/taxes', appId: 'inventory' },
  { prefix: '/master/warehouses', appId: 'inventory' },
  { prefix: '/master/locations', appId: 'inventory' },
  { prefix: '/master/boms', appId: 'inventory' },
  { prefix: '/master/partners', appId: 'inventory' },
  { prefix: '/master/work-centers', appId: 'inventory' },
  { prefix: '/master/production-lines', appId: 'inventory' },
  { prefix: '/master/routings', appId: 'inventory' },
];

/**
 * PURE — app id pemilik alias path (`/bundles/42` ikut cocok lewat prefix).
 * Urutan dicek dari prefix TERPANJANG supaya alias yang lebih spesifik menang.
 */
export function legacyAppIdForPath(pathname: string): string | undefined {
  const bySpecificity = [...LEGACY_APP_PATHS].sort(
    (a, b) => b.prefix.length - a.prefix.length,
  );

  return bySpecificity.find(
    (entry) => pathname === entry.prefix || pathname.startsWith(`${entry.prefix}/`),
  )?.appId;
}

/**
 * PURE - app yang paling spesifik untuk `pathname`.
 *
 * Diurutkan dari path TERPANJANG supaya `/production/scan` menang atas `/production`,
 * dan `/` (dashboard) hanya dipakai kalau tidak ada yang lain. F13: alias di
 * `LEGACY_APP_PATHS` dicek lebih dulu (path-nya tidak diawali path app mana pun).
 */
export function findAppByPath(pathname: string): NavApp | undefined {
  const legacyId = legacyAppIdForPath(pathname);

  if (legacyId !== undefined) {
    const legacyApp = NAV_APPS.find((app) => app.id === legacyId);

    if (legacyApp !== undefined) return legacyApp;
  }

  const bySpecificity = [...NAV_APPS].sort((a, b) => b.path.length - a.path.length);

  return bySpecificity.find(
    (app) => pathname === app.path || pathname.startsWith(`${app.path}/`),
  );
}

/**
 * PURE - app pemilik id (mis. `findAppById('production')`).
 * Dipakai `AppIndexRedirect` (FIX ROUTE) untuk menerjemahkan path app → halaman pertama.
 */
export function findAppById(id: string): NavApp | undefined {
  return NAV_APPS.find((app) => app.id === id);
}

/**
 * PURE - halaman PERTAMA sebuah app: item pertama `topbar` (atau anak pertamanya), dan
 * `app.path` kalau app tidak punya menu (mis. Dashboard `/`, AI `/ai/chat`).
 *
 * Dipakai `AppIndexRedirect` + `Sidebar`/`RootRoute` (FIX ROUTE) supaya path app yang hanya
 * PREFIX (mis. `/production`, lihat catatan di `menu-config.ts`) tetap mendarat di halaman
 * nyata, bukan `RoleGuardFallback`/404.
 */
export function appLandingPath(app: NavApp | undefined): string | undefined {
  if (app === undefined) return undefined;

  const first = app.topbar[0];
  if (first === undefined) return app.path;

  return first.children?.[0]?.path ?? first.path;
}

/**
 * PURE - path menu (topbar) yang aktif untuk `pathname`, mis. `/production/scan/42`.
 */
export function findActiveMenu(app: NavApp, pathname: string): string | undefined {
  return app.topbar.find(
    (menu) => pathname === menu.path || pathname.startsWith(`${menu.path}/`),
  )?.path;
}

/**
 * Path "alur tugas operator" (HP/Kios): di sini halaman memakai header sendiri
 * (Screen A/B), jadi AppShell menyembunyikan TopBar di bawah `lg` dan tidak
 * merender BottomNav supaya tombol aksi besar tidak bertabrakan dengan navigasi.
 */
const IMMERSIVE_PREFIXES = [
  '/production/scan',
  '/production/shop-floor',
  '/production/bundles',
  '/production/qc',
];

export function isImmersiveOperatorPath(pathname: string): boolean {
  return IMMERSIVE_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}
