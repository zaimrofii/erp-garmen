import { createElement } from 'react';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  ACCESS_DENIED_ACTION,
  ACCESS_DENIED_MESSAGE,
  ACCESS_DENIED_TITLE,
  AccessDeniedView,
} from '@/app/AccessDenied';
import { APP_LANDING_MISSING_MESSAGE, AppLandingMissing } from '@/app/AppIndexRedirect';
import { appLandingPath, findAppById } from '@/app/nav-config';
import { firstAllowedPathForRole } from '@/app/useRole';
import {
  ROUTE_ERROR_BACK,
  ROUTE_ERROR_RELOAD,
  ROUTE_ERROR_TITLE,
  RouteErrorBoundary,
  RouteErrorFallback,
} from '@/components/organisms/RouteErrorBoundary';
import { attrOf, htmlOf, textOf } from '../../helpers/react-tree';

/**
 * FIX ROUTE — audit perbaikan routing (tanpa DOM; `renderToString` + pemindaian sumber).
 *
 * Yang dikunci di sini:
 *  1. `appLandingPath`/`firstAllowedPathForRole` = PURE (prefix app → halaman pertama);
 *  2. `App.tsx`: route indeks 7 app ada, `/` memakai `RootRoute`, dan SETIAP elemen route
 *     di dalam App Shell dibungkus `RouteErrorBoundary`;
 *  3. anti-loop: tidak ada redirect ke `/dashboard` (dijaga SUPERVISOR_ROLES);
 *  4. UI "Akses Ditolak" + fallback error boundary punya elemen yang benar.
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');
const read = (relative: string): string => readFileSync(path.join(ROOT, relative), 'utf8');

const APP_SOURCE = read('src/App.tsx');
const ROOT_ROUTE_SOURCE = read('src/app/RootRoute.tsx');
const ROLE_ROUTE_SOURCE = read('src/app/RoleRoute.tsx');

/** Potong `App.tsx` per `<Route` (lookahead) supaya tiap potongan = satu route. */
function routeBlocks(source: string): string[] {
  return source.split(/(?=<Route\b)/).slice(1);
}

const APP_INDEX_ROUTES: ReadonlyArray<readonly [string, string]> = [
  ['/production', 'production'],
  ['/inventory', 'inventory'],
  ['/purchase', 'purchase'],
  ['/quality', 'quality'],
  ['/reports', 'reports'],
  ['/settings', 'settings'],
  ['/finance', 'finance'],
];

describe('FIX ROUTE — appLandingPath (pure): prefix app → halaman pertama', () => {
  it('app ber-menu memakai item topbar PERTAMA', () => {
    expect(appLandingPath(findAppById('production'))).toBe('/production/scan');
    expect(appLandingPath(findAppById('settings'))).toBe('/settings/routing');
    expect(appLandingPath(findAppById('finance'))).toBe('/finance/invoices');
    expect(appLandingPath(findAppById('inventory'))).toBe('/inventory/products');
    expect(appLandingPath(findAppById('purchase'))).toBe('/purchase/orders');
    expect(appLandingPath(findAppById('quality'))).toBe('/quality/defects');
    expect(appLandingPath(findAppById('reports'))).toBe('/reports/line-efficiency');
  });

  it('app tanpa menu memakai path app-nya sendiri (Dashboard/AI) & id tak dikenal aman', () => {
    expect(appLandingPath(findAppById('dashboard'))).toBe('/');
    expect(appLandingPath(findAppById('ai'))).toBe('/ai/chat');
    expect(appLandingPath(findAppById('tidak-ada'))).toBeUndefined();
    expect(appLandingPath(undefined)).toBeUndefined();
  });
});

describe('FIX ROUTE — firstAllowedPathForRole (pure): anti-loop', () => {
  it('role tanpa app Dashboard diarahkan ke app pertamanya (bukan /dashboard, bukan /)', () => {
    expect(firstAllowedPathForRole('inventory')).toBe('/inventory/products');
    expect(firstAllowedPathForRole('purchasing')).toBe('/purchase/orders');
  });

  it('Dashboard (`/`) selalu DILEWATI supaya tidak memantul ke dirinya sendiri', () => {
    // admin/owner punya app dashboard, tapi fungsi ini dipakai hanya saat role TIDAK punya
    // dashboard → harus melewati '/' dan memberi path app lain yang nyata.
    expect(firstAllowedPathForRole('admin')).toBe('/inventory/products');
    expect(firstAllowedPathForRole('owner')).toBe('/production/scan');
    expect(firstAllowedPathForRole('operator')).toBe('/production/scan');
    expect(firstAllowedPathForRole('qc')).toBe('/production/scan');
  });

  it('setiap role (kecuali pemilik Dashboard murni) menghasilkan path nyata', () => {
    for (const role of ['operator', 'qc', 'admin', 'inventory', 'purchasing', 'owner'] as const) {
      expect(firstAllowedPathForRole(role), role).not.toBe('/');
    }
  });
});

describe('FIX ROUTE — RootRoute: sesi dulu, baru halaman', () => {
  it('loading → spinner; belum login → /login?redirect=/ (tanpa redirect ke /dashboard)', () => {
    expect(ROOT_ROUTE_SOURCE).toContain('if (device.loading) return <AuthLoading />');
    expect(ROOT_ROUTE_SOURCE).toContain("if (device.user === null) return <Navigate to={loginRedirectPath('/')} replace />");
  });

  it('sesi ada → DashboardPage untuk role pemilik app dashboard', () => {
    expect(ROOT_ROUTE_SOURCE).toContain("isAppAllowed(role, 'dashboard')");
    expect(ROOT_ROUTE_SOURCE).toContain('return <DashboardPage />');
  });

  it('ANTI-LOOP: tidak ada redirect ke /dashboard; role lain memakai firstAllowedPathForRole', () => {
    expect(ROOT_ROUTE_SOURCE).not.toContain('to="/dashboard"');
    expect(ROOT_ROUTE_SOURCE).toContain('firstAllowedPathForRole(role)');
    expect(ROOT_ROUTE_SOURCE).toContain('return <AccessDenied />');
  });
});

describe('FIX ROUTE — App.tsx: route indeks 7 app + error boundary per route', () => {
  it('setiap path app ber-menu punya route AppIndexRedirect dengan app yang benar', () => {
    for (const [routePath, appId] of APP_INDEX_ROUTES) {
      expect(APP_SOURCE, routePath).toContain(`path="${routePath}"`);
      expect(APP_SOURCE, routePath).toContain(`<AppIndexRedirect app="${appId}" />`);
    }
  });

  it('route `/` memakai RootRoute (bukan DashboardPage langsung)', () => {
    expect(APP_SOURCE).toContain('<RootRoute />');
    expect(APP_SOURCE).not.toContain('path="/" element={<DashboardPage />}');
  });

  it('SETIAP elemen route (kecuali pembungkus AppShell) dibungkus RouteErrorBoundary', () => {
    const blocks = routeBlocks(APP_SOURCE).filter((block) => block.includes('element={'));

    expect(blocks.length).toBeGreaterThan(40);

    for (const block of blocks) {
      const routePath = /path="([^"]+)"/.exec(block)?.[1] ?? '?';

      // Kerangka: `<Route path="*" element={<AppShell>…}>` (isi shell punya route sendiri).
      if (block.includes('<AppShell>')) continue;

      expect(block, `route ${routePath} tanpa RouteErrorBoundary`).toContain('<RouteErrorBoundary>');
    }
  });

  it('halaman login pun dibungkus (crash di /login tidak menjadi layar putih)', () => {
    const loginBlock = routeBlocks(APP_SOURCE).find((block) => block.includes('path="/login"'));

    expect(loginBlock).toBeDefined();
    expect(loginBlock).toContain('<RouteErrorBoundary>');
    expect(loginBlock).not.toContain('<AppShell>');
  });

  it('fallback `*` memakai RoleGuardFallback + boundary', () => {
    const fallback = routeBlocks(APP_SOURCE).find(
      (block) => block.includes('path="*"') && block.includes('RoleGuardFallback'),
    );

    expect(fallback).toBeDefined();
    expect(fallback).toContain('<RouteErrorBoundary>');
  });
});

describe('FIX ROUTE — RoleRoute: pesan jelas, bukan redirect diam-diam', () => {
  it('RoleRoute & RoleGuardFallback memakai AccessDenied (tanpa <Navigate to="/">)', () => {
    expect(ROLE_ROUTE_SOURCE).toContain("import { AccessDenied } from '@/app/AccessDenied'");
    expect(ROLE_ROUTE_SOURCE).toContain('return <AccessDenied />');
    // tidak ada lagi redirect diam-diam (nama modul `Navigate` pun tidak diimpor)
    expect(ROLE_ROUTE_SOURCE).not.toContain("import { Navigate }");
    expect(ROLE_ROUTE_SOURCE).not.toContain('return <Navigate');
  });
});

describe('FIX ROUTE — UI "Akses Ditolak"', () => {
  it('menampilkan judul, pesan, tombol kembali, dan info role/path', () => {
    const tree = createElement(AccessDeniedView, {
      roleLabel: 'Operator Lantai',
      pathname: '/settings/users',
      onBackToDashboard: () => undefined,
    });

    expect(attrOf(tree, 'data-access-denied')).toBe('true');
    expect(textOf(tree)).toContain(ACCESS_DENIED_TITLE);
    expect(textOf(tree)).toContain(ACCESS_DENIED_MESSAGE);
    expect(textOf(tree)).toContain(ACCESS_DENIED_ACTION);
    expect(textOf(tree)).toContain('Operator Lantai');
    expect(textOf(tree)).toContain('/settings/users');
    // otomatis dialihkan (perilaku aman dari versi lama: tidak nyangkut)
    expect(textOf(tree)).toContain('Dialihkan ke Dashboard');
  });
});

describe('FIX ROUTE — app tanpa halaman (defensif)', () => {
  it('AppLandingMissing menjelaskan app belum punya halaman', () => {
    const tree = createElement(AppLandingMissing, { app: 'produksi-x' });

    expect(attrOf(tree, 'data-app-landing-missing')).toBe('produksi-x');
    expect(textOf(tree)).toContain(APP_LANDING_MISSING_MESSAGE);
    expect(textOf(tree)).toContain('produksi-x');
  });
});

describe('FIX ROUTE — RouteErrorBoundary (class, tanpa DOM)', () => {
  it('getDerivedStateFromError menyimpan error; render() meneruskan children saat sehat', () => {
    const boundary = new RouteErrorBoundary({ children: createElement('span', null, 'isi halaman') });

    expect(htmlOf(boundary.render())).toContain('isi halaman');

    const next = RouteErrorBoundary.getDerivedStateFromError(new Error('boom'));

    expect(next.error?.message).toBe('boom');
  });

  it('fallback menampilkan pesan + tombol Kembali ke Dashboard & Muat ulang', () => {
    const tree = createElement(RouteErrorFallback, {
      message: 'boom',
      onBackToDashboard: () => undefined,
      onReload: () => undefined,
    });

    expect(attrOf(tree, 'data-route-error')).toBe('true');
    expect(textOf(tree)).toContain(ROUTE_ERROR_TITLE);
    expect(textOf(tree)).toContain(ROUTE_ERROR_BACK);
    expect(textOf(tree)).toContain(ROUTE_ERROR_RELOAD);
    expect(textOf(tree)).toContain('boom');
  });
});
