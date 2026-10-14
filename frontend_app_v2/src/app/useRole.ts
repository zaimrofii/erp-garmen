import { useMemo, useState } from "react";
import { NAV_APPS, appLandingPath, type NavApp } from "@/app/nav-config";
import {
  useDeviceProfile,
  type DeviceProfile,
  type DeviceProfileSource,
} from "@/core/useDeviceProfile";

/**
 * useRole.ts - resolver role (Blueprint v3 bagian 5.3) + filter sidebar.
 *
 * Prioritas (Blueprint bagian 5.3, dijabarkan sebagai kode):
 *   1. URL `?role=xxx`      -> untuk testing/dev (menang atas semuanya);
 *   2. `localStorage['mes-role']` -> preferensi user;
 *   3. Device profil (`useDeviceProfile()`) -> HP/Scanner = operator, Kios/Desktop = supervisor;
 *      kalau profil hanya FALLBACK generik (level 5) -> pakai lebar viewport
 *      (`lg` = 1024px) supaya desktop demo tidak terjebak minimenu operator.
 *
 * `NAV_APPS` TIDAK disimpan di sini - selalu diimpor dari `app/nav-config.ts`.
 */

export type Role =
  | "operator"
  | "supervisor"
  | "qc"
  | "admin"
  | "inventory"
  | "purchasing"
  | "owner";

export const ROLES: readonly Role[] = [
  "operator",
  "supervisor",
  "qc",
  "admin",
  "inventory",
  "purchasing",
  "owner",
];

export const ROLE_STORAGE_KEY = "mes-role";
export const ROLE_QUERY_PARAM = "role";

export const ROLE_LABELS: Record<Role, string> = {
  operator: "Operator Lantai",
  supervisor: "Supervisor Produksi",
  qc: "Quality Control",
  admin: "Admin Sistem",
  inventory: "Staf Inventory",
  purchasing: "Staf Purchasing",
  owner: "Owner",
};

export const DEFAULT_DESKTOP_ROLE: Role = "owner";
export const DEFAULT_HANDHELD_ROLE: Role = "operator";

/** Breakpoint `lg` Tailwind - dipakai hanya saat profil device masih fallback generik. */
const DESKTOP_MIN_WIDTH = 1024;

/** App mana yang boleh dilihat tiap role (Blueprint v3 bagian 5.3). */
export const ROLE_APPS: Record<Role, string[]> = {
  // F13/13.4 (keputusan D1): operator & qc juga "punya" app Dashboard supaya Sidebar
  // menyorot Dashboard saat berada di `/` (route `/` tetap TANPA RoleRoute karena ia
  // target redirect netral — menjaga `/` berisiko loop redirect).
  operator: ["dashboard", "production"],
  supervisor: ["dashboard", "production", "quality", "reports"],
  qc: ["dashboard", "production", "quality"],
  admin: [
    "dashboard",
    "inventory",
    "purchase",
    "quality",
    "reports",
    "settings",
    "ai",
    // F15 — app Finance jadi NYATA (antrean invoice Fase 4.4).
    "finance",
    // H2.1 — app Sales jadi NYATA (Sales Order; guard SALES_ROLES = admin/owner).
    "sales",
  ],
  inventory: ["inventory", "purchase", "reports"],
  purchasing: ["purchase", "reports"],
  owner: [
    "dashboard",
    "production",
    "inventory",
    "purchase",
    "quality",
    "reports",
    // H5: Settings (guard SETTINGS_ROLES = admin + owner).
    "settings",
    "ai",
    // F15 — Finance: owner + admin (route FINANCE_ROLES).
    "finance",
    // H2.1 — Sales: owner + admin (route SALES_ROLES).
    "sales",
  ],
};

export function isRole(value: unknown): value is Role {
  return typeof value === "string" && ROLES.some((role) => role === value);
}

/** Kode role BACKEND (`UPPERCASE`, migrasi `core_auth.0002`/`0004`) -> union UI `Role`. */
export const ROLE_BY_CODE: Record<string, Role> = {
  OPERATOR: "operator",
  QC: "qc",
  SUPERVISOR: "supervisor",
  ADMIN: "admin",
  OWNER: "owner",
  PURCHASING: "purchasing",
};

/**
 * PURE - label role manusiawi dari `user.role_code` (`/auth/me/`, UPPERCASE).
 *
 * Label diambil dari `ROLE_LABELS` supaya hanya ada SATU daftar label (pill TopBar juga
 * memakainya). Input di-`toUpperCase()` dulu (toleran); kode di luar daftar dikembalikan
 * apa adanya (jangan mengarang label untuk kode asing), kosong -> `—`.
 */
export function roleLabelFromCode(code: string | null | undefined): string {
  const raw = (code ?? "").trim().toUpperCase();
  if (raw.length === 0) return "—";

  const role = ROLE_BY_CODE[raw];

  return role === undefined ? raw : ROLE_LABELS[role];
}

/**
 * Kode role yang boleh membuka app Settings - cermin `UPPERCASE` dari `SETTINGS_ROLES`
 * di `App.tsx` (`['admin', 'owner']`). Guard route tetap `RoleRoute`; konstanta ini hanya
 * memutuskan apakah pintu "Pengaturan" ditampilkan di menu akun.
 */
export const SETTINGS_ROLE_CODES: readonly string[] = ["ADMIN", "OWNER"];

/**
 * PURE - true kalau `role_code` boleh membuka `/settings`.
 *
 * Sengaja menerima `role_code` dari `/auth/me/` (OTORITATIF), BUKAN `useRole()` - role di
 * `useRole()` berasal dari `localStorage['mes-role']`/device/viewport sehingga bisa diubah
 * klien dan tidak boleh dipakai sebagai penentu hak akses.
 */
export function canOpenSettings(code: string | null | undefined): boolean {
  return SETTINGS_ROLE_CODES.includes((code ?? "").trim().toUpperCase());
}

/** PURE - daftar app yang terlihat untuk satu role (urutan tetap mengikuti NAV_APPS). */
export function visibleAppsForRole(role: Role): NavApp[] {
  const allowed = ROLE_APPS[role];

  return NAV_APPS.filter((app) => allowed.includes(app.id));
}

/**
 * PURE - true kalau role berhak atas app ini.
 * Dipakai AppShell sebagai gerbang "tidak ada route bocor": kalau user mengetik URL
 * app yang bukan haknya, shell tidak menampilkan judul/menu app tersebut.
 */
export function isAppAllowed(role: Role, appId: string): boolean {
  return ROLE_APPS[role].includes(appId);
}

/** PURE - profil device (5 level) -> role default. */
export function roleForDeviceProfile(profile: DeviceProfile): Role {
  switch (profile) {
    case "OPERATOR_HP":
    case "SCANNER_USB":
      return DEFAULT_HANDHELD_ROLE;
    case "KIOSK_TABLET":
    case "DESKTOP":
      return DEFAULT_DESKTOP_ROLE;
  }
}

function readViewportRole(): Role {
  if (typeof window === "undefined") return DEFAULT_DESKTOP_ROLE;

  return window.innerWidth >= DESKTOP_MIN_WIDTH
    ? DEFAULT_DESKTOP_ROLE
    : DEFAULT_HANDHELD_ROLE;
}

/**
 * PURE - role default dari hasil `useDeviceProfile()`.
 * Level 5 = fallback generik (`OPERATOR_HP`) tanpa bukti device nyata -> pakai viewport.
 */
export function roleForDevice(input: {
  profile: DeviceProfile;
  level: DeviceProfileSource["level"];
}): Role {
  if (input.level <= 4) return roleForDeviceProfile(input.profile);

  return readViewportRole();
}

function readRoleFromSearch(): Role | null {
  if (typeof window === "undefined") return null;

  try {
    const raw = new URLSearchParams(window.location.search).get(
      ROLE_QUERY_PARAM,
    );

    return isRole(raw) ? raw : null;
  } catch {
    return null;
  }
}

function readStoredRole(): Role | null {
  if (typeof window === "undefined") return null;

  try {
    const raw = window.localStorage.getItem(ROLE_STORAGE_KEY);

    return isRole(raw) ? raw : null;
  } catch {
    return null;
  }
}

/** Simpan preferensi role (dipakai nanti saat ada pemilih role di Fase 17+). */
export function persistRole(role: Role): void {
  if (typeof window === "undefined") return;

  try {
    window.localStorage.setItem(ROLE_STORAGE_KEY, role);
  } catch {
    /* diabaikan dengan sengaja - preferensi role tidak boleh menjatuhkan aplikasi */
  }
}

/**
 * Role aktif. Query param & localStorage dibaca sekali saat mount (lazy initializer)
 * supaya nilai stabil selama sesi - reload halaman untuk mengganti role.
 */
export function useRole(): Role {
  const { profile, source } = useDeviceProfile();

  const [role] = useState<Role>(() => {
    const fromQuery = readRoleFromSearch();
    if (fromQuery !== null) return fromQuery;

    const stored = readStoredRole();
    if (stored !== null) return stored;

    return roleForDevice({ profile, level: source.level });
  });

  return role;
}

/** App yang boleh tampil di sidebar untuk role aktif. */
export function useVisibleApps(): NavApp[] {
  const role = useRole();

  return useMemo(() => visibleAppsForRole(role), [role]);
}

/**
 * PURE - path halaman pertama yang boleh dibuka `role` (FIX ROUTE).
 *
 * Dipakai `RootRoute`: role yang TIDAK punya app Dashboard (mis. `inventory`, `purchasing`)
 * diarahkan ke app pertamanya, BUKAN ke `/dashboard` (yang dijaga `SUPERVISOR_ROLES` dan
 * akan memantulkan mereka kembali → loop) dan bukan pula ke `/` (loop ke dirinya sendiri).
 * Dashboard (`/`) dilewati; `undefined` = role tidak punya app sama sekali.
 */
export function firstAllowedPathForRole(role: Role): string | undefined {
  for (const app of visibleAppsForRole(role)) {
    const landing = appLandingPath(app);

    if (landing !== undefined && landing !== '/') return landing;
  }

  return undefined;
}
