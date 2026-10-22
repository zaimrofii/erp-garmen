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
} from "lucide-react";

/**
 * nav-config.ts - sumber tunggal navigasi App Shell (Blueprint v3 bagian 5.2).
 *
 * Dipakai `Sidebar` (rel aplikasi), `TopBar` (menu kontekstual), dan `useRole`
 * (filter per role). JANGAN duplikasi daftar ini di komponen lain.
 *
 * Semua ikon dari `lucide-react` (tidak ada import file gambar/asset).
 *
 * OPSI B (2026-10-15): Work Center, Production Line, dan Routing DIPINDAH dari
 * app `inventory` ke app `production` karena ketiganya domain produksi (stasiun
 * kerja, lini, alur proses) — bukan master inventory. Semua `Master *` lain
 * tetap di `inventory` (produk, UoM, pajak, gudang, lokasi, BOM, partner).
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
  {
    id: "dashboard",
    label: "Dashboard", // Tetap Dashboard
    icon: LayoutDashboard,
    path: "/",
    topbar: [],
  },
  {
    id: "production",
    label: "Produksi", // ID 'production', Label 'Produksi'
    icon: Factory,
    path: "/production/work-orders",
    topbar: [
      // PRA-0A.1 (Q2) — RESTORE keputusan 1A (K3.6): landing app production =
      // `/production/scan`. Urutan ini juga yang membuat guard produksi (K4-b)
      // konsisten: 3 master produksi disisipkan setelah QC.
      { label: "Area Operator (Shop Floor)", path: "/production/scan" },
      { label: "Quality Control (QC)", path: "/production/qc" },
      { label: "Stasiun Kerja (WC)", path: "/master/work-centers" },
      { label: "Lini Produksi", path: "/master/production-lines" },
      { label: "Master Routing", path: "/master/routings" },
      { label: "Routing", path: "/production/routing" },
      { label: "Perintah Kerja (WO)", path: "/production/work-orders" },
      // PRA-0A.1 (Catatan #2) — Opsi B: alur produksi WO → Bundle → Buffer.
      { label: "Bundle", path: "/bundles" },
      { label: "Antrean Buffer", path: "/production/buffer-queue" },
    ],
  },
  {
    id: "inventory",
    label: "Stok & Gudang", // Bahasa Indonesia ramah awam
    icon: Package,
    path: "/inventory",
    topbar: [
      { label: "Produk & Bahan", path: "/master/products" },
      { label: "Satuan (UoM)", path: "/master/uoms" },
      { label: "Pajak", path: "/master/taxes" },
      { label: "Gudang", path: "/master/warehouses" },
      { label: "Lokasi Rak", path: "/master/locations" },
      { label: "Resep Produk (BOM)", path: "/master/boms" },
      { label: "Pemasok & Pelanggan", path: "/master/partners" },
      { label: "Penyesuaian Stok", path: "/inventory/adjustments" },
      { label: "Transfer Stok", path: "/inventory/transfers" },
      { label: "Operasional Gudang", path: "/inventory/operations" },
      { label: "Laporan Stok", path: "/inventory/reporting" },
      { label: "Lokasi & Stok", path: "/inventory/config" },
    ],
  },
  {
    id: "sales",
    label: "Penjualan", // ID 'sales', Label 'Penjualan'
    icon: FileText,
    path: "/sales/orders",
    topbar: [{ label: "Pesanan Masuk (SO)", path: "/sales/orders" }],
  },
  {
    id: "purchase",
    label: "Pembelian", // ID 'purchase', Label 'Pembelian'
    icon: ShoppingCart,
    path: "/purchase",
    topbar: [
      { label: "Pesanan Beli (PO)", path: "/purchase/orders" },
      { label: "Supplier / Vendor", path: "/purchase/vendors" },
      { label: "Laporan Pembelian", path: "/purchase/reporting" },
    ],
  },
  {
    id: "quality",
    label: "Kualitas (QC)",
    icon: CheckCircle2,
    path: "/quality",
    topbar: [
      { label: "Log Cacat", path: "/quality/defects" },
      { label: "Standar AQL", path: "/quality/aql" },
      { label: "Perbaikan (Rework)", path: "/quality/rework" },
    ],
  },
  {
    id: "finance",
    label: "Keuangan", // ID 'finance', Label 'Keuangan'
    icon: Banknote,
    path: "/finance",
    topbar: [
      { label: "Faktur Tagihan", path: "/finance/invoices" },
      { label: "Faktur Pelanggan", path: "/finance/customer-invoices" },
      { label: "Tagihan Vendor", path: "/finance/vendor-bills" },
      { label: "Pembayaran", path: "/finance/payments" },
      { label: "Jurnal Umum", path: "/finance/journal-entries" },
    ],
  },
  {
    id: "reports",
    label: "Laporan",
    icon: TrendingUp,
    path: "/reports",
    topbar: [
      { label: "Efisiensi Lini", path: "/reports/line-efficiency" },
      { label: "Lead Time Produksi", path: "/reports/lead-time" },
      {
        label: "Ketepatan Pengiriman (OTD)",
        path: "/reports/on-time-delivery",
      },
      { label: "Pantauan WIP", path: "/reports/wip" },
      { label: "Rekonsiliasi Odoo", path: "/reports/reconciliation" },
      { label: "Laporan Penjualan", path: "/reports/sales" },
      { label: "Laporan Pembelian", path: "/reports/purchases" },
      { label: "Laporan Stok", path: "/reports/stock" },
      { label: "Harga Pokok (HPP)", path: "/reports/cogs" },
      { label: "Laba Rugi (PnL)", path: "/reports/pnl" },
      { label: "Laporan Produksi", path: "/reports/production" },
      { label: "Dashboard Eksekutif", path: "/dashboard/executive" },
    ],
  },
  {
    id: "analytics",
    label: "Analitik",
    icon: TrendingUp,
    path: "/analytics",
    topbar: [{ label: "Metrik", path: "/analytics" }],
  },
  {
    id: "settings",
    label: "Pengaturan",
    icon: Settings,
    path: "/settings",
    topbar: [
      // PRA-0A.1 (Q1) — RESTORE perilaku resmi `/settings → /settings/routing`
      // (current-project.json:1365). Tiga halaman ini punya route di App.tsx
      // tetapi sempat kehilangan item nav saat cleanup K3.6/K3.7.
      { label: "Routing", path: "/settings/routing" },
      { label: "Bundling", path: "/settings/bundling" },
      { label: "Line Allocation", path: "/settings/line-allocation" },
      { label: "Profil Perusahaan", path: "/settings/company" },
      { label: "Penomoran Otomatis", path: "/settings/sequences" },
      { label: "Mata Uang", path: "/settings/currencies" },
      { label: "Perangkat Kios/HP", path: "/settings/devices" },
      { label: "Pengguna & Hak Akses", path: "/settings/users" },
      { label: "Integrasi Odoo", path: "/settings/integration" },
      { label: "WhatsApp Gateway", path: "/settings/wa" },
      // PRA-0A.1 — kontrak urutan historis H5.7: Printer dipasang SETELAH Audit Log.
      { label: "Log Audit Sistem", path: "/settings/audit-log" },
      // Sprint C.3 — toggle & kesiapan analytics (dekat item audit).
      { label: "Analitik", path: "/settings/analytics" },
      // Sprint F.3 — observability AI (tepat setelah Analitik).
      { label: "AI Observability", path: "/settings/ai-observability" },
      { label: "Printer Thermal", path: "/settings/printers" },
      // PRA-0A.1 (K4-c) — tiga halaman ini sudah punya route di `App.tsx`
      // (`SETTINGS_ROLES`) tetapi belum punya menu, jadi tak bisa ditemukan user.
      // Read-only/monitoring → diletakkan setelah Audit Log.
      { label: "Permission Matrix", path: "/settings/permissions" },
      { label: "Sync Monitor", path: "/settings/sync" },
      { label: "Product Audit", path: "/settings/audit" },
    ],
  },
  {
    id: "ai",
    label: "Asisten AI",
    icon: Bot,
    path: "/ai/chat",
    topbar: [
      { label: "Chat", path: "/ai/chat" },
      { label: "HITL", path: "/ai/hitl" },
    ],
  },
];

/**
 * F13/13.2-13.3 — alias path yang TIDAK diawali `path` app-nya sendiri.
 *
 * OPSI B: `/master/work-centers`, `/master/production-lines`, `/master/routings`
 * dipetakan ke app `production` (menunya di `production.topbar`), sementara
 * `/master/*` lain tetap di `inventory`.
 */
export const LEGACY_APP_PATHS: readonly { prefix: string; appId: string }[] = [
  // PRA-0A.1 (K4-a) — app `production` kini ber-path `/production/work-orders`, sehingga
  // `/production/scan`, `/production/qc`, `/production/buffer-queue`, dst. TIDAK lagi cocok
  // dengan `app.path`. Tanpa prefix ini `findAppByPath('/production/qc')` = undefined →
  // Sidebar tidak menyorot app Produksi saat operator berada di layar Scan/QC.
  // Prefix `/production` memetakan SELURUH route produksi ke app `production`.
  { prefix: "/production", appId: "production" },
  // Sprint C.3 — app analytics (metrik read-only).
  { prefix: "/analytics", appId: "analytics" },
  // S.3 — seluruh halaman AI (chat/HITL) disorot di app `ai`.
  { prefix: "/ai", appId: "ai" },
  { prefix: "/bundles", appId: "production" },
  { prefix: "/workshop", appId: "production" },
  { prefix: "/work-orders", appId: "production" },
  { prefix: "/dashboard", appId: "dashboard" },
  // H4.7 — dashboard eksekutif: menu di app `reports` (prefix TERPANJANG menang).
  { prefix: "/dashboard/executive", appId: "reports" },
  // Master inventory (tetap di `inventory`).
  { prefix: "/master/products", appId: "inventory" },
  { prefix: "/master/uoms", appId: "inventory" },
  { prefix: "/master/taxes", appId: "inventory" },
  { prefix: "/master/warehouses", appId: "inventory" },
  { prefix: "/master/locations", appId: "inventory" },
  { prefix: "/master/boms", appId: "inventory" },
  { prefix: "/master/partners", appId: "inventory" },
  // OPSI B — master produksi (pindah ke `production`).
  { prefix: "/master/work-centers", appId: "production" },
  { prefix: "/master/production-lines", appId: "production" },
  { prefix: "/master/routings", appId: "production" },
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
    (entry) =>
      pathname === entry.prefix || pathname.startsWith(`${entry.prefix}/`),
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

  const bySpecificity = [...NAV_APPS].sort(
    (a, b) => b.path.length - a.path.length,
  );

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
export function findActiveMenu(
  app: NavApp,
  pathname: string,
): string | undefined {
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
  "/production/scan",
  "/production/shop-floor",
  "/production/bundles",
  "/production/qc",
];

export function isImmersiveOperatorPath(pathname: string): boolean {
  return IMMERSIVE_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}
