import { Boxes, type LucideIcon } from 'lucide-react';
import { NAV_APPS, type NavApp } from '@/app/nav-config';
/**
 * menu-config.ts - definisi MENU BAR Odoo-style (F5).
 *
 * Aturan penting: **tidak menyalin** `nav-config.ts` — daftar app/ikon/item tetap
 * bersumber dari `NAV_APPS` (single source of truth, lihat catatan di file itu) dan
 * diturunkan di sini, LALU ditambah placeholder untuk app yang belum punya halaman.
 *
 * Hanya item yang route-nya BENAR-BENAR ada yang `disabled`-nya tidak diset
 * (dikunci oleh `tests/unit/app/menu-config.test.ts` yang memindai `src/App.tsx`).
 * Item placeholder memakai `disabled: true` + `hint` sehingga bisa ditampilkan tetapi
 * TIDAK pernah memicu navigasi.
 */

export interface MenuItem {
  /**
   * Id stabil (dipakai `MENU_APPS`/key). Opsional: menu TopBar boleh datang dari
   * `NavApp.topbar` (`{label, path}` saja) — kalau kosong, `path` yang jadi identitas.
   */
  id?: string;
  label: string;
  /** Ada kalau item punya halaman (link/dropdown anak). */
  path?: string;
  /**
   * Anak menu (mis. `Products ▾ → List | New`).
   * F16: kosong/undefined → TopBar merender item sebagai **link**, bukan dropdown.
   */
  children?: readonly MenuItem[];
  /** Placeholder: boleh tampil, tidak boleh diklik. */
  disabled?: boolean;
  hint?: string;
}

export interface MenuApp {
  id: string;
  label: string;
  icon: LucideIcon;
  items: MenuItem[];
}

/**
 * App NAV_APPS yang halaman-nya ada di `app.path` ITU SENDIRI (route penuh).
 * App lain memakai `topbar[]`; `path` app (mis. `/inventory`) hanya prefix, bukan route.
 */
const APP_LEAF_ROUTES: Record<string, string> = {
  dashboard: '/',
  ai: '/ai/chat',
};

/**
 * App dari brief F5 yang BELUM ada halaman/route-nya di frontend v3.
 * F15: `finance` DIKELUARKAN dari sini karena halaman `/finance/invoices` sudah nyata.
 * H2.1: `sales` DIKELUARKAN juga karena halaman `/sales/orders*` sudah nyata (app
 * Sales kini ada di `NAV_APPS`) ⇒ sisa placeholder: hanya Master.
 */
export const PLACEHOLDER_APPS: readonly { id: string; label: string; icon: LucideIcon; hint: string }[] = [
  { id: 'master', label: 'Master', icon: Boxes, hint: 'belum ada halaman/endpoint' },
];

function itemsForApp(app: NavApp): MenuItem[] {
  if (app.topbar.length > 0) {
    return app.topbar.map((menu) => ({ id: menu.path, label: menu.label, path: menu.path }));
  }

  const leaf = APP_LEAF_ROUTES[app.id];
  if (leaf === undefined) return [];

  return [{ id: leaf, label: app.label, path: leaf }];
}

/** Menu per app: 10 app nyata (dari NAV_APPS, termasuk Sales sejak H2.1) + 1 placeholder. */
export const MENU_APPS: MenuApp[] = [
  ...NAV_APPS.map((app) => ({
    id: app.id,
    label: app.label,
    icon: app.icon,
    items: itemsForApp(app),
  })),
  ...PLACEHOLDER_APPS.map((app) => ({
    id: app.id,
    label: app.label,
    icon: app.icon,
    items: [
      {
        id: `${app.id}:placeholder`,
        label: app.label,
        disabled: true,
        hint: app.hint,
      },
    ],
  })),
];

/** PURE - menu app yang boleh ditampilkan untuk daftar id app (mis. `useVisibleApps`). */
export function menuAppsForIds(ids: readonly string[]): MenuApp[] {
  const allowed = new Set(ids);

  return MENU_APPS.filter((app) => allowed.has(app.id));
}

/** PURE - target navigasi item; `null` untuk item disabled (placeholder). */
export function resolveMenuTarget(item: MenuItem): string | null {
  if (item.disabled === true) return null;

  return item.path ?? null;
}

/** PURE - path item yang AKTIF untuk `pathname` (termasuk sub-route, mis. `/production/qc/42`). */
export function findActiveMenuPath(app: MenuApp, pathname: string): string | undefined {
  return app.items.find(
    (item) => item.path !== undefined && (pathname === item.path || pathname.startsWith(`${item.path}/`)),
  )?.path;
}

/** PURE - true kalau `pathname` berada di dalam salah satu item app ini. */
export function isMenuAppActive(app: MenuApp, pathname: string): boolean {
  return findActiveMenuPath(app, pathname) !== undefined;
}

/** PURE - true kalau SEMUA item app ini placeholder (dipakai untuk meredupkan trigger). */
export function isPlaceholderApp(app: MenuApp): boolean {
  return app.items.length > 0 && app.items.every((item) => item.disabled === true);
}

/* ------------------------------------------------------------------
   F16 — menu DALAM app aktif (TopBar). Item tanpa `children` = link,
   item dengan `children` = dropdown. Helper di bawah dipakai AppMenuBar.
   ------------------------------------------------------------------ */

/** PURE — path yang cocok dengan `pathname` (termasuk sub-route, mis. `/inventory/products/42`). */
function pathMatches(path: string | undefined, pathname: string): boolean {
  if (path === undefined) return false;

  return pathname === path || pathname.startsWith(`${path}/`);
}

/**
 * PURE — path AKTIF untuk satu item menu: path **anak** yang cocok lebih dulu, lalu path
 * item itu sendiri. `undefined` = item tidak aktif (dipakai highlight + `aria-current`).
 *
 * Anak diperiksa DULU supaya sub-halaman yang lebih spesifik menang: item
 * `Products (/inventory/products)` dengan anak `/inventory/products/new` harus
 * menyalakan `New`, bukan `Products`.
 */
export function findMenuItemPath(item: MenuItem, pathname: string): string | undefined {
  // Kandidat = path anak-anak + path item sendiri; yang MENANG adalah yang PALING
  // SPESIFIK (path terpanjang). Contoh: untuk `/inventory/products/new`, anak `New`
  // (`/inventory/products/new`) mengalahkan `List` (`/inventory/products`) yang juga
  // cocok sebagai prefix.
  const candidates = [...(item.children ?? []).map((child) => child.path), item.path].filter(
    (path): path is string => typeof path === 'string' && pathMatches(path, pathname),
  );

  return candidates.sort((a, b) => b.length - a.length)[0];
}

/** PURE — item menu ini aktif untuk `pathname` (item sendiri atau salah satu anaknya). */
export function isMenuItemActive(item: MenuItem, pathname: string): boolean {
  return findMenuItemPath(item, pathname) !== undefined;
}
