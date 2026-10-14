import { createElement } from 'react';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { AuthGate, AuthLoading } from '@/components/organisms/AuthGuard';
import type { AuthUser } from '@/api/auth';
import { guardDecision } from '@/lib/auth-guard';
import { loginRedirectPath, LOGIN_PATH } from '@/lib/login-form';
import { attrOf, attrsOf, findElement, htmlOf, textOf } from '../../helpers/react-tree';

/**
 * F6.2 — `AuthGuard`: gerbang halaman butuh-login.
 *
 * Diuji dua lapis (tanpa DOM/jsdom — `.clinerules` §ENVIRONMENT):
 *  1. `guardDecision()` + `loginRedirectPath()` = PURE;
 *  2. `AuthGate` presentasional (`renderToString`) untuk spinner / redirect / render anak.
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

const USER: AuthUser = {
  id: 7,
  username: 'admin1',
  email: 'admin1@klien.com',
  full_name: 'Admin Satu',
  role_code: 'ADMIN',
  is_superuser: false,
  is_staff: true,
};

describe('F6.2 — guardDecision (pure)', () => {
  it('loading → spinner, walau user belum diketahui', () => {
    expect(guardDecision({ loading: true, user: null })).toBe('loading');
    expect(guardDecision({ loading: true, user: USER })).toBe('loading');
  });

  it('selesai memuat: ada user → allow, tanpa user → redirect', () => {
    expect(guardDecision({ loading: false, user: USER })).toBe('allow');
    expect(guardDecision({ loading: false, user: null })).toBe('redirect');
  });
});

describe('FIX ROUTE — cookie device BUKAN izin masuk (koreksi F6.4)', () => {
  it('11. device ter-bind TANPA sesi → tetap redirect ke /login', () => {
    // Binding device tanpa user tetap ANONIM di backend (core/auth/authentication.py →
    // `authenticate()` = None) sehingga semua API 401/403: dulu bypass `deviceBound`
    // "allow" hanya menghasilkan halaman kosong. Bukti boleh-masuk kini HANYA `user`.
    expect(guardDecision({ loading: false, user: null })).toBe('redirect');
  });

  it('12. kios ber-user (cookie device dibaca backend sebagai sesi) → allow', () => {
    expect(guardDecision({ loading: false, user: USER })).toBe('allow');
  });

  it('13. jangan pernah memutuskan sebelum loading selesai', () => {
    expect(guardDecision({ loading: true, user: null })).toBe('loading');
    expect(guardDecision({ loading: true, user: USER })).toBe('loading');
  });
});

describe('F6.2 — loginRedirectPath (pure)', () => {
  it('membawa halaman yang sedang dibuka ke ?redirect=', () => {
    expect(loginRedirectPath('/dashboard')).toBe(`${LOGIN_PATH}?redirect=%2Fdashboard`);
    expect(loginRedirectPath('/bundles/42', '?tab=qc')).toBe(
      `${LOGIN_PATH}?redirect=%2Fbundles%2F42%3Ftab%3Dqc`,
    );
  });

  it('halaman login sendiri TIDAK dijadikan target (hindari loop)', () => {
    expect(loginRedirectPath(LOGIN_PATH)).toBe(LOGIN_PATH);
  });
});

describe('F6.2 — AuthGate (presentasional)', () => {
  it('7. render children saat authenticated', () => {
    const tree = AuthGate({
      decision: 'allow',
      redirectTo: `${LOGIN_PATH}?redirect=%2Fdashboard`,
      children: createElement('span', { 'data-child': 'true' }, 'Halaman Dashboard'),
    });

    expect(attrOf(tree, 'data-child')).toBe('true');
    expect(textOf(tree)).toContain('Halaman Dashboard');
  });

  it('8. redirect ke /login saat belum login (Navigate dengan ?redirect=)', () => {
    const tree = AuthGate({
      decision: 'redirect',
      redirectTo: `${LOGIN_PATH}?redirect=%2Fdashboard`,
      children: createElement('span', { 'data-child': 'true' }, 'rahasia'),
    });
    const navigate = findElement(tree as never, (element) => element.props['to'] !== undefined);

    expect(navigate?.props['to']).toBe(`${LOGIN_PATH}?redirect=%2Fdashboard`);
    expect(navigate?.props['replace']).toBe(true);
    // halaman rahasia TIDAK ikut dirender (tidak ada elemen anak sama sekali)
    expect(findElement(tree as never, (element) => element.type === 'span')).toBeUndefined();
  });

  it('9. tampil spinner saat loading (tidak render anak, tidak redirect)', () => {
    const tree = AuthGate({
      decision: 'loading',
      redirectTo: LOGIN_PATH,
      children: createElement('span', { 'data-child': 'true' }, 'rahasia'),
    });

    expect(attrOf(tree, 'data-auth-loading')).toBe('true');
    expect(attrsOf(tree, 'role')).toContain('status'); // Spinner punya role="status"
    expect(findElement(tree as never, (element) => element.type === 'span')).toBeUndefined();
    expect(htmlOf(tree)).not.toContain('rahasia');
  });

  it('AuthLoading memakai Spinner berlabel "Memuat"', () => {
    expect(attrOf(createElement(AuthLoading), 'aria-label')).toBe('Memuat');
  });
});

describe('F6.2 — wiring AuthGuard & App', () => {
  const guard = readFileSync(path.join(ROOT, 'src/components/organisms/AuthGuard.tsx'), 'utf8');
  const app = readFileSync(path.join(ROOT, 'src/App.tsx'), 'utf8');

  it('AuthGuard memakai useDeviceMode + useLocation & menghitung redirect dari lokasi sekarang', () => {
    expect(guard).toContain('useDeviceMode()');
    expect(guard).toContain('useLocation()');
    expect(guard).toContain('loading: device.loading');
    expect(guard).toContain('user: device.user');
    expect(guard).toContain('loginRedirectPath(location.pathname, location.search)');
  });

  it('FIX ROUTE: AuthGuard TIDAK lagi mengirim deviceBound (device bukan izin masuk)', () => {
    expect(guard).not.toContain('deviceBound');
    expect(guard).toContain('FIX ROUTE');
  });

  it('App: /login publik (tanpa AppShell) + seluruh route lain dibungkus AuthGuard', () => {
    expect(app).toContain('<AuthProvider>');
    expect(app).toContain('path="/login"');
    expect(app).toContain('<AuthGuard>');
    expect(app).toContain('path="*"');
    // halaman login TIDAK ikut App Shell (full-screen) — route-nya di luar <AppShell>
    const loginBlock = app.slice(app.indexOf('path="/login"'), app.indexOf('path="*"'));
    expect(loginBlock).not.toContain('<AppShell>');
  });
});
