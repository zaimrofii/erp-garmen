import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { findAppByPath } from '@/app/nav-config';
import { isAppAllowed, ROLE_APPS, ROLES, type Role } from '@/app/useRole';

/**
 * F12/12.1 — AUDIT filter role: semua route × 7 role.
 *
 * Sumber: `src/App.tsx` (route + guard `RoleRoute roles={…}`), `ROLE_APPS` (app yang boleh
 * dilihat role), `findAppByPath` (app pemilik path). Tes ini mengunci TEMUAN — bukan
 * menuntut nol anomali — supaya kombinasi yang tidak konsisten terlihat & tidak makin banyak
 * diam-diam. Kalau guard/nav diubah, daftar di bawah WAJIB ditinjau ulang.
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function read(relative: string): string {
  return readFileSync(path.join(ROOT, relative), 'utf8');
}

const APP_SOURCE = read('src/App.tsx');

/** `const X: Role[] = [...]` → daftar role. */
function parseRoleConsts(source: string): Record<string, Role[]> {
  const result: Record<string, Role[]> = {};

  for (const match of source.matchAll(/const (\w+): Role\[\] = \[([^\]]*)\];/g)) {
    const name = match[1] ?? '';
    const body = match[2] ?? '';

    result[name] = [...body.matchAll(/'([^']+)'/g)].map((item) => item[1] as Role);
  }

  return result;
}

interface RouteEntry {
  path: string;
  guard: string | null;
}

/** Potong per `<Route`, lalu ambil `path` + nama konstanta role pada potongan itu. */
function parseRoutes(source: string): RouteEntry[] {
  const entries: RouteEntry[] = [];

  for (const chunk of source.split(/<Route\b/).slice(1)) {
    const routePath = /path="([^"]+)"/.exec(chunk)?.[1];
    if (routePath === undefined) continue;

    entries.push({ path: routePath, guard: /roles=\{(\w+)\}/.exec(chunk)?.[1] ?? null });
  }

  return entries;
}

const ROLE_CONSTS = parseRoleConsts(APP_SOURCE);
const ROUTES = parseRoutes(APP_SOURCE);

/** Role di guard yang TIDAK boleh melihat app pemilik path → user akan di-redirect. */
function roleAppConflicts(): string[] {
  const found: string[] = [];

  for (const route of ROUTES) {
    if (route.guard === null || route.path === '*') continue;

    const appId = findAppByPath(route.path)?.id;
    if (appId === undefined) continue;

    const roles = ROLE_CONSTS[route.guard] ?? [];

    for (const role of roles) {
      if (!isAppAllowed(role, appId)) {
        found.push(`${route.path} [${route.guard}] → role '${role}' tidak boleh app '${appId}'`);
      }
    }
  }

  return found.sort();
}

describe('F12/12.1 — audit role × route', () => {
  it('semua konstanta guard dikenal & hanya berisi role sah', () => {
    expect(Object.keys(ROLE_CONSTS).sort()).toEqual([
      'ADMIN_ROLES',
      'AI_ROLES',
      'BUFFER_QUEUE_ROLES',
      'FINANCE_ROLES',
      'INVENTORY_ROLES',
      'PRODUCTION_ROLES',
      'PURCHASING_ROLES',
      'QC_ROLES',
      'QUALITY_ROLES',
      'REPORTS_ROLES',
      'ROUTING_ROLES',
      'SALES_ROLES',
      'SETTINGS_ROLES',
      'SUPERVISOR_READINESS_ROLES',
      'SUPERVISOR_ROLES',
    ]);

    for (const [name, roles] of Object.entries(ROLE_CONSTS)) {
      expect(roles.length, name).toBeGreaterThan(0);

      for (const role of roles) {
        expect(ROLES, `${name}:${role}`).toContain(role);
      }
    }
  });

  it('F13 TERTUTUP: tidak ada lagi route dengan role yang tidak boleh melihat app-nya', () => {
    // Sebelum F13 temuan (a): `/production/readiness/:orderId` memakai `SUPERVISOR_ROLES`
    // (memuat `admin`) padahal `ROLE_APPS.admin` tanpa 'production'. Kini guard-nya khusus
    // `SUPERVISOR_READINESS_ROLES` (supervisor+owner) → daftar konflik KOSONG.
    expect(roleAppConflicts()).toEqual([]);
  });

  it('F13/13.2-13.3 TERTUTUP: route lama & alias /dashboard terpetakan ke app-nya', () => {
    // F6.2: `/login` = halaman PUBLIK di luar App Shell → memang bukan milik app mana pun,
    // jadi dikecualikan secara eksplisit. Route lain tetap wajib terpetakan ke sebuah app.
    const PUBLIC_PATHS = ['/login'];
    const orphan = ROUTES.filter(
      (route) =>
        route.path !== '*' &&
        !PUBLIC_PATHS.includes(route.path) &&
        findAppByPath(route.path) === undefined,
    ).map((route) => route.path);

    // Sebelum F13: /bundles, /bundles/:id, /workshop, /workshop/:id, /work-orders, /dashboard
    // tidak terpetakan (sidebar tidak menyorot app saat dibuka). Kini lewat LEGACY_APP_PATHS.
    expect(orphan).toEqual([]);
  });

  it('F13/13.2-13.3: alias path → app id yang benar (termasuk sub-path `:id`)', () => {
    expect(findAppByPath('/bundles')?.id).toBe('production');
    expect(findAppByPath('/bundles/42')?.id).toBe('production');
    expect(findAppByPath('/workshop/42')?.id).toBe('production');
    expect(findAppByPath('/work-orders')?.id).toBe('production');
    expect(findAppByPath('/dashboard')?.id).toBe('dashboard');
    // path app normal TIDAK terpengaruh
    expect(findAppByPath('/production/qc/7')?.id).toBe('production');
    expect(findAppByPath('/')?.id).toBe('dashboard');
    expect(findAppByPath('/tidak-ada')).toBeUndefined();
  });

  it('F13: guard alias route ⊆ ROLE_APPS app-nya (production)', () => {
    for (const routePath of ['/bundles', '/bundles/:id', '/workshop', '/workshop/:id', '/work-orders']) {
      const route = ROUTES.find((item) => item.path === routePath);

      expect(route?.guard, routePath).toBe('PRODUCTION_ROLES');

      for (const role of ROLE_CONSTS[route?.guard ?? ''] ?? []) {
        expect(isAppAllowed(role, 'production'), `${routePath}:${role}`).toBe(true);
      }
    }
  });

  it('F7.1: owner ikut QUALITY_ROLES (super-admin boleh buka /quality/*)', () => {
    expect(ROLE_CONSTS['QUALITY_ROLES']).toEqual(['qc', 'supervisor', 'admin', 'owner']);

    // Konsisten dengan ROLE_APPS: setiap role di guard memang pemilik app 'quality'.
    for (const role of ROLE_CONSTS['QUALITY_ROLES'] ?? []) {
      expect(isAppAllowed(role, 'quality'), role).toBe(true);
    }

    // Tiga route /quality/* memakai guard ini.
    const qualityRoutes = ROUTES.filter((route) => route.path.startsWith('/quality/'));
    expect(qualityRoutes.length).toBe(3);
    for (const route of qualityRoutes) {
      expect(route.guard, route.path).toBe('QUALITY_ROLES');
    }
  });

  it('TERTUTUP (a): readiness = supervisor + owner saja (admin TIDAK boleh)', () => {
    const route = ROUTES.find((item) => item.path === '/production/readiness/:orderId');

    // F13/13.1 (keputusan A2): guard khusus, sejajar BUFFER_QUEUE_ROLES/ROUTING_ROLES.
    expect(route?.guard).toBe('SUPERVISOR_READINESS_ROLES');
    expect(ROLE_CONSTS['SUPERVISOR_READINESS_ROLES']).toEqual(['supervisor', 'owner']);
    expect(ROLE_CONSTS['SUPERVISOR_READINESS_ROLES']).not.toContain('admin');
    // SUPERVISOR_ROLES TIDAK diubah (dipakai `/dashboard` yang memang boleh untuk admin).
    expect(ROLE_CONSTS['SUPERVISOR_ROLES']).toEqual(['supervisor', 'admin', 'owner']);
    expect(ROUTES.find((item) => item.path === '/dashboard')?.guard).toBe('SUPERVISOR_ROLES');
    // Tidak ada lagi konflik role × app di seluruh route.
    expect(roleAppConflicts()).toEqual([]);
  });

  it('TERTUTUP (d): operator/qc punya app dashboard & `/` tetap tanpa guard', () => {
    const root = ROUTES.find((route) => route.path === '/');

    expect(root?.guard).toBeNull();
    expect(isAppAllowed('operator', 'dashboard')).toBe(true);
    expect(isAppAllowed('qc', 'dashboard')).toBe(true);
    // 13.4b — role lain TIDAK ikut ditambah (di luar keputusan D1).
    expect(isAppAllowed('inventory', 'dashboard')).toBe(false);
    expect(isAppAllowed('purchasing', 'dashboard')).toBe(false);
  });

  it('admin membuka /production/readiness/1 → TIDAK lolos RoleRoute (halaman "Akses Ditolak")', () => {
    const guard = ROLE_CONSTS['SUPERVISOR_READINESS_ROLES'] ?? [];

    // Semantik RoleRoute (FIX ROUTE): `!roles.some((allowed) => allowed === role)`
    // → `<AccessDenied />` (dulu `<Navigate to="/" replace />`).
    const wouldRedirect = (role: Role): boolean => !guard.some((allowed) => allowed === role);

    expect(wouldRedirect('admin')).toBe(true);
    expect(wouldRedirect('operator')).toBe(true);
    expect(wouldRedirect('qc')).toBe(true);
    expect(wouldRedirect('supervisor')).toBe(false);
    expect(wouldRedirect('owner')).toBe(false);
    // admin juga tidak boleh app `production` (konsisten dengan ROLE_APPS → tidak "nyangkut").
    expect(isAppAllowed('admin', 'production')).toBe(false);
  });

  it('operator/qc membuka `/` → dilayani tanpa redirect & app-nya dikenali', () => {
    expect(ROUTES.find((route) => route.path === '/')?.guard).toBeNull();

    for (const role of ['operator', 'qc'] as const) {
      expect(findAppByPath('/')?.id).toBe('dashboard');
      expect(isAppAllowed(role, 'dashboard'), role).toBe(true);
    }
  });

  it('matriks lengkap: app mana pun yang boleh dilihat role SELALU punya route terjaga', () => {
    const guardedApps = new Set(
      ROUTES.map((route) => findAppByPath(route.path)?.id).filter((id) => id !== undefined),
    );
    const roleApps = new Set(Object.values(ROLE_APPS).flat());

    for (const appId of roleApps) {
      const reachable =
        guardedApps.has(appId) || appId === 'dashboard' || appId === 'production';

      expect(reachable, `app '${appId}' tidak punya route`).toBe(true);
    }
  });
});
