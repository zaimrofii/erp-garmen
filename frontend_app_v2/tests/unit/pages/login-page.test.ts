import { createElement } from 'react';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AuthError } from '@/api/auth';
import {
  AdminLoginForm,
  LoginCard,
  LoginError,
  OperatorNumpad,
} from '@/pages/auth/LoginPage';
import {
  applyOperatorKey,
  authErrorMessage,
  DEFAULT_LOGIN_TAB,
  DEFAULT_POST_LOGIN_PATH,
  errorMessageOf,
  isOperatorCodeComplete,
  LOGIN_MESSAGES,
  LOGIN_PATH,
  NUMPAD_KEYS,
  operatorCodeSlots,
  postLoginPath,
  readRedirectTarget,
  readRememberedUsername,
  REMEMBER_STORAGE_KEY,
  persistRememberedUsername,
} from '@/lib/login-form';
import { deviceInfoText, isSwitchIntent } from '@/lib/device-mode';
import { attrOf, attrsOf, callProp, findElement, htmlOf, textOf } from '../../helpers/react-tree';

/**
 * F6.2 — halaman login (`pages/auth/LoginPage.tsx`).
 *
 * Tanpa DOM/jsdom (`.clinerules` §ENVIRONMENT): struktur & teks diuji dengan
 * `renderToString`, handler diuji dengan `callProp`, dan alur submit (yang butuh `useAuth` +
 * Router) diuji lewat fungsi PURE + pemeriksaan sumber (pola `qc-actions.test.ts`).
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');
const PAGE_SOURCE = readFileSync(path.join(ROOT, 'src/pages/auth/LoginPage.tsx'), 'utf8');

function card(overrides: Partial<Parameters<typeof LoginCard>[0]> = {}) {
  return LoginCard({
    tab: DEFAULT_LOGIN_TAB,
    onTabChange: () => undefined,
    username: '',
    password: '',
    remember: false,
    code: '',
    busy: false,
    error: null,
    onUsernameChange: () => undefined,
    onPasswordChange: () => undefined,
    onRememberChange: () => undefined,
    onCodeKey: () => undefined,
    onSubmitAdmin: () => undefined,
    onSubmitOperator: () => undefined,
    ...overrides,
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('F6.2 — tab default & numpad (10, 11)', () => {
  it('10. default tab = admin → form username/password, TANPA numpad', () => {
    const tree = card();

    expect(attrOf(tree, 'data-login-page')).toBe('true');
    expect(attrOf(tree, 'data-login-form')).toBe('admin');
    expect(textOf(tree)).toContain('Admin/Supervisor');
    expect(textOf(tree)).toContain('Operator');
    expect(textOf(tree)).toContain('Ingat saya');
    expect(textOf(tree)).toContain(LOGIN_MESSAGES.contactAdmin);
    // form admin: 2 input (username/password) — numpad tidak ikut render
    expect(attrsOf(tree, 'data-login-form')).toEqual(['admin']);
  });

  it('11. tab operator → numpad 0-9 + display 4 slot; form admin hilang', () => {
    const tree = card({ tab: 'operator' });

    expect(attrOf(tree, 'data-login-form')).toBe('operator');
    expect(attrsOf(tree, 'data-code-slot')).toEqual(['empty', 'empty', 'empty', 'empty']);
    for (const digit of ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9']) {
      expect(NUMPAD_KEYS, digit).toContain(digit);
      expect(attrsOf(tree, 'aria-label'), digit).toContain(digit);
    }
    expect(htmlOf(tree)).not.toContain('name="username"');
  });

  it('numpad: numpad penuh (4 digit) mengaktifkan tombol Login', () => {
    const filled = card({ tab: 'operator', code: '1234' });
    const partial = card({ tab: 'operator', code: '12' });

    expect(attrsOf(filled, 'data-code-slot')).toEqual(['filled', 'filled', 'filled', 'filled']);
    expect(attrsOf(filled, 'disabled')).toEqual([]); // tombol Login aktif
    expect(attrsOf(partial, 'disabled')).toHaveLength(1); // belum 4 digit → disabled
  });

  it('helper kode operator: max 4 digit, backspace/clear bekerja', () => {
    let code = '';
    for (const digit of ['1', '2', '3', '4', '5']) code = applyOperatorKey(code, digit);

    expect(code).toBe('1234');
    expect(isOperatorCodeComplete(code)).toBe(true);
    expect(operatorCodeSlots('12')).toEqual(['1', '2', '', '']);
    expect(applyOperatorKey('123', 'backspace')).toBe('12');
    expect(applyOperatorKey('123', 'clear')).toBe('');
    expect(applyOperatorKey('1', 'x')).toBe('1');
  });
});

describe('F6.2 — submit form (12, 13)', () => {
  it('12. submit form admin memanggil onSubmit (preventDefault dipakai)', () => {
    const onSubmit = vi.fn();
    const tree = AdminLoginForm({
      username: 'admin1',
      password: 'rahasia123',
      remember: true,
      busy: false,
      onUsernameChange: () => undefined,
      onPasswordChange: () => undefined,
      onRememberChange: () => undefined,
      onSubmit,
    });
    const form = findElement(tree as never, (element) => element.type === 'form');
    const preventDefault = vi.fn();

    callProp(form!, 'onSubmit', { preventDefault });

    expect(preventDefault).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledTimes(1);
    // input terkontrol: nilai dari props terlihat di HTML
    expect(htmlOf(tree)).toContain('value="admin1"');
    expect(htmlOf(tree)).toContain('type="password"');
  });

  it('12b. halaman memanggil login(username, password) dari tab admin', () => {
    expect(PAGE_SOURCE).toContain('await login(username, password)');
    expect(PAGE_SOURCE).toContain('persistRememberedUsername(username, remember)');
    expect(PAGE_SOURCE).toContain('onSubmitAdmin={() => {');
    expect(PAGE_SOURCE).toContain('setError(LOGIN_MESSAGES.missingCredentials)');
  });

  it('13. tombol Login numpad memanggil onSubmit & halaman memanggil loginOperator(code)', () => {
    const onSubmit = vi.fn();
    const tree = OperatorNumpad({
      code: '1234',
      busy: false,
      onKey: () => undefined,
      onSubmit,
    });
    const loginButton = findElement(
      tree as never,
      (element) => element.props['onClick'] === onSubmit,
    );

    callProp(loginButton!, 'onClick');

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(PAGE_SOURCE).toContain('await loginOperator(code)');
    expect(PAGE_SOURCE).toContain('setError(LOGIN_MESSAGES.incompleteCode)');
  });
});

describe('F6.2 — pesan error (14) & pemetaan status', () => {
  it('14. error 401 ditampilkan di kartu (role="alert")', () => {
    const tree = card({ error: LOGIN_MESSAGES.invalidCredentials });

    expect(attrOf(tree, 'data-login-error')).toBe('true');
    expect(attrsOf(tree, 'role')).toContain('alert');
    expect(textOf(tree)).toContain('Username atau password salah');
  });

  it('14b. LoginError tidak merender apa pun saat tidak ada error', () => {
    expect(htmlOf(createElement(LoginError, { message: null }))).toBe('');
  });

  it('errorMessageOf: AuthError 401 memakai teks backend, error lain → pesan jaringan', () => {
    expect(errorMessageOf(new AuthError(401, 'Kode operator tidak valid', null))).toBe(
      'Kode operator tidak valid',
    );
    expect(errorMessageOf(new Error(''))).toBe(LOGIN_MESSAGES.network);
    expect(errorMessageOf('bukan error')).toBe(LOGIN_MESSAGES.network);
  });

  it('authErrorMessage: 429 memakai Retry-After, fallback 60 detik', () => {
    expect(authErrorMessage({ status: 429, retryAfterSeconds: 30 })).toBe(
      'Terlalu banyak percobaan, coba lagi dalam 30 detik',
    );
    expect(authErrorMessage({ status: 429 })).toBe(
      'Terlalu banyak percobaan, coba lagi dalam 60 detik',
    );
    expect(authErrorMessage({ status: 0 })).toBe('Koneksi gagal, cek jaringan');
    expect(authErrorMessage({ status: 401, fallback: LOGIN_MESSAGES.invalidOperatorCode })).toBe(
      'Kode operator tidak valid',
    );
  });
});

describe('F6.2 — redirect & "Ingat saya"', () => {
  it('readRedirectTarget hanya menerima path internal (anti open redirect)', () => {
    expect(readRedirectTarget('?redirect=%2Fbundles%3Ftab%3Dqc')).toBe('/bundles?tab=qc');
    expect(readRedirectTarget('')).toBeNull();
    expect(readRedirectTarget('?redirect=https%3A%2F%2Fevil.example')).toBeNull();
    expect(readRedirectTarget('?redirect=%2F%2Fevil.example')).toBeNull();
  });

  it('postLoginPath: ?redirect= sah dipakai, selain itu /dashboard', () => {
    expect(postLoginPath('/bundles')).toBe('/bundles');
    expect(postLoginPath(null)).toBe(DEFAULT_POST_LOGIN_PATH);
    expect(postLoginPath('')).toBe(DEFAULT_POST_LOGIN_PATH);
    expect(PAGE_SOURCE).toContain('const target = postLoginPath(redirect)');
    expect(PAGE_SOURCE).toContain('navigate(target, { replace: true })');
  });

  it('halaman login TIDAK dipakai sebagai target redirect (loop) & route /login ada di App', () => {
    const app = readFileSync(path.join(ROOT, 'src/App.tsx'), 'utf8');

    expect(LOGIN_PATH).toBe('/login');
    expect(app).toContain('const LoginPage = lazy(');
    expect(app).toContain("import('@/pages/auth/LoginPage')");
  });

  it('persistRememberedUsername menyimpan/menghapus username di localStorage', () => {
    const store = new Map<string, string>();
    vi.stubGlobal('window', {
      localStorage: {
        getItem: (key: string) => store.get(key) ?? null,
        setItem: (key: string, value: string) => store.set(key, value),
        removeItem: (key: string) => store.delete(key),
      },
    });

    persistRememberedUsername(' admin1 ', true);
    expect(readRememberedUsername()).toBe('admin1');
    expect(store.get(REMEMBER_STORAGE_KEY)).toBe('admin1');

    persistRememberedUsername('admin1', false);
    expect(readRememberedUsername()).toBe('');
  });

  it('tanpa window (SSR/test node) → tidak melempar & mengembalikan string kosong', () => {
    expect(readRememberedUsername()).toBe('');
    expect(() => persistRememberedUsername('admin1', true)).not.toThrow();
  });
});

describe('F6.4/FIX ROUTE — mode device di halaman login', () => {
  it('kartu menampilkan info perangkat ter-bind + tautan "Login sebagai user lain"', () => {
    const tree = card({ deviceInfo: deviceInfoText('KIOS', 'SEW-01') });

    expect(attrOf(tree, 'data-login-device-info')).toBe('true');
    expect(textOf(tree)).toContain('Device: KIOS @ SEW-01');
    expect(textOf(tree)).toContain('Login sebagai user lain');
    expect(textOf(tree)).toContain('sudah terikat');
  });

  it('tanpa device ter-bind → tidak ada banner device', () => {
    expect(htmlOf(card())).not.toContain('data-login-device-info');
  });

  it('FIX ROUTE: device ter-bind TANPA sesi TIDAK melewati login (form tetap tampil)', () => {
    // Dulu: `if (device.bound && !isSwitchIntent(...)) <Navigate .../>` → perangkat dengan
    // binding tanpa user langsung diarahkan ke /dashboard padahal API-nya 401/403.
    expect(PAGE_SOURCE).not.toContain('if (device.bound');
    expect(PAGE_SOURCE).toContain('if (user !== null && !isSwitchIntent(location.search))');
    // Banner device tetap informatif (bukan dasar keputusan redirect).
    expect(PAGE_SOURCE).toContain('deviceInfo={device.bound ? deviceInfoText(device.profile, device.wcCode) : null}');
    expect(isSwitchIntent('?switch=1')).toBe(true);
    expect(isSwitchIntent('?redirect=%2Fdashboard')).toBe(false);
  });

  it('mode session/none tidak diubah: form login tetap muncul', () => {
    expect(PAGE_SOURCE).toContain('DEFAULT_LOGIN_TAB');
    expect(PAGE_SOURCE).toContain('<LoginCard');
  });
});

