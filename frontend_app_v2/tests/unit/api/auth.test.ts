import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  AUTH_CHANGE_PASSWORD_PATH,
  AUTH_LOGIN_OPERATOR_PATH,
  AUTH_LOGIN_PATH,
  AUTH_LOGOUT_PATH,
  AUTH_ME_PATH,
  AuthError,
  buildChangePasswordBody,
  buildLoginBody,
  buildOperatorLoginBody,
  changePassword,
  getMe,
  login,
  loginOperator,
  logout,
  readAuthUser,
} from '@/api/auth';
import {
  createApiClient,
  needsCredentials,
  readRetryAfterSeconds,
} from '@/integrations/api-client';

/**
 * F6.2 — adapter auth (`api/real/auth.ts`) + barrel `api/auth.ts`.
 *
 * Semua request dijalankan lewat `createApiClient` dengan `fetch` di-stub, jadi yang diuji
 * adalah path, body, dan pemetaan respons/error (tanpa DOM, tanpa backend). Kontrak respons
 * diambil dari `django_app/core/auth/api.py` (F6.1) — tidak ada shape yang dikarang.
 */

const BASE_URL = 'http://localhost:8000/api/v1';

interface FetchCall {
  url: string;
  init: RequestInit;
}

function stubFetch(
  body: unknown,
  status = 200,
  headers: Record<string, string> = {},
): FetchCall[] {
  const calls: FetchCall[] = [];

  vi.stubGlobal(
    'fetch',
    vi.fn((url: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(url), init: init ?? {} });

      return Promise.resolve(
        new Response(JSON.stringify(body), {
          status,
          headers: { 'Content-Type': 'application/json', ...headers },
        }),
      );
    }),
  );

  return calls;
}

function stubFetchReject(message: string): void {
  vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new Error(message))));
}

function client() {
  return createApiClient({ baseUrl: BASE_URL });
}

function bodyOf(call: FetchCall): unknown {
  return JSON.parse(String(call.init.body ?? 'null')) as unknown;
}

/** Baris user E1 (kontrak F6.1). */
const ADMIN_ROW = {
  id: 7,
  username: 'admin1',
  email: 'admin1@klien.com',
  full_name: 'Admin Satu',
  role_code: 'ADMIN',
  is_superuser: false,
  is_staff: true,
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('F6.2 — E1 login (username + password)', () => {
  it('login() POST /auth/login/ dengan body + kredensial & CSRF', async () => {
    const calls = stubFetch(ADMIN_ROW);

    const user = await login(client(), 'admin1', 'rahasia123');

    expect(calls[0]?.url).toBe(`${BASE_URL}${AUTH_LOGIN_PATH}`);
    expect(calls[0]?.init.method).toBe('POST');
    expect(bodyOf(calls[0]!)).toEqual({ username: 'admin1', password: 'rahasia123' });
    // tulisan → cookie ikut dikirim (sesi baru disimpan)
    expect(calls[0]?.init.credentials).toBe('include');
    expect(user).toMatchObject({ id: 7, username: 'admin1', role_code: 'ADMIN' });
  });

  it('login() 401 memakai teks backend `detail` (AuthError)', async () => {
    stubFetch({ detail: 'Username atau password salah' }, 401);

    const failed = await login(client(), 'admin1', 'salah').catch((error: unknown) => error);

    expect(failed).toBeInstanceOf(AuthError);
    expect((failed as AuthError).status).toBe(401);
    expect((failed as AuthError).message).toBe('Username atau password salah');
  });

  it('login() 429 membaca header Retry-After → pesan "coba lagi dalam X detik"', async () => {
    stubFetch({ detail: 'Terlalu banyak percobaan.' }, 429, { 'Retry-After': '42' });

    const failed = await login(client(), 'admin1', 'rahasia123').catch((error: unknown) => error);

    expect((failed as AuthError).status).toBe(429);
    expect((failed as AuthError).message).toBe(
      'Terlalu banyak percobaan, coba lagi dalam 42 detik',
    );
  });

  it('login() network error → status 0 + pesan "Koneksi gagal, cek jaringan"', async () => {
    stubFetchReject('Failed to fetch');

    const failed = await login(client(), 'admin1', 'rahasia123').catch((error: unknown) => error);

    expect((failed as AuthError).status).toBe(0);
    expect((failed as AuthError).message).toBe('Koneksi gagal, cek jaringan');
  });
});

describe('F6.2 — E2 login operator (kode 4 digit)', () => {
  it('loginOperator() POST /auth/login-operator/ dengan body {operator_code}', async () => {
    const calls = stubFetch({
      id: 9,
      username: 'operator1',
      full_name: 'Operator Satu',
      role_code: 'OPERATOR',
    });

    const user = await loginOperator(client(), '1234');

    expect(calls[0]?.url).toBe(`${BASE_URL}${AUTH_LOGIN_OPERATOR_PATH}`);
    expect(bodyOf(calls[0]!)).toEqual({ operator_code: '1234' });
    expect(user).toMatchObject({
      id: 9,
      username: 'operator1',
      full_name: 'Operator Satu',
      role_code: 'OPERATOR',
      // E2 mengirim subset → field lain netral (bukan dikarang dari angka acak)
      email: '',
      is_superuser: false,
      is_staff: false,
    });
  });

  it('loginOperator() 401 memakai teks backend "Kode operator tidak valid"', async () => {
    stubFetch({ detail: 'Kode operator tidak valid' }, 401);

    const failed = await loginOperator(client(), '9999').catch((error: unknown) => error);

    expect((failed as AuthError).message).toBe('Kode operator tidak valid');
  });
});

describe('F6.2 — E3 logout (idempotent)', () => {
  it('logout() POST /auth/logout/', async () => {
    const calls = stubFetch({ ok: true });

    await logout(client());

    expect(calls[0]?.url).toBe(`${BASE_URL}${AUTH_LOGOUT_PATH}`);
    expect(calls[0]?.init.method).toBe('POST');
  });

  it('logout() 401 TIDAK melempar (sesi sudah habis = sudah keluar)', async () => {
    stubFetch({ detail: 'Belum login' }, 401);

    await expect(logout(client())).resolves.toBeUndefined();
  });
});

describe('F6.2 — E4 me (sesi aktif / device cookie)', () => {
  it('getMe() GET /auth/me/ + mengirim cookie (credentials include)', async () => {
    const calls = stubFetch({ ...ADMIN_ROW, device_profile: null, wc_code: null });

    const user = await getMe(client());

    expect(calls[0]?.url).toBe(`${BASE_URL}${AUTH_ME_PATH}`);
    expect(calls[0]?.init.method).toBe('GET');
    // prefix `/auth/` masuk AUTH_SCOPED_GET_PREFIXES → sessionid ikut walau GET
    expect(calls[0]?.init.credentials).toBe('include');
    expect(needsCredentials('GET', AUTH_ME_PATH)).toBe(true);
    expect(user?.username).toBe('admin1');
  });

  it('getMe() 401 → null (belum login, bukan error)', async () => {
    stubFetch({ detail: 'Authentication credentials were not provided.' }, 401);

    await expect(getMe(client())).resolves.toBeNull();
  });

  it('getMe() membaca device_profile + wc_code (login lewat cookie device)', async () => {
    stubFetch({ ...ADMIN_ROW, device_profile: 'OPERATOR_HP', wc_code: 'WC-AUTH' });

    const user = await getMe(client());

    expect(user?.device_profile).toBe('OPERATOR_HP');
    expect(user?.wc_code).toBe('WC-AUTH');
  });

  it('getMe() error selain 401 → melempar (tidak menyamar jadi "belum login")', async () => {
    stubFetch({ detail: 'Internal server error' }, 500);

    const failed = await getMe(client()).catch((error: unknown) => error);

    expect(failed).toBeInstanceOf(AuthError);
    expect((failed as AuthError).status).toBe(500);
  });
});

describe('F6.2 — E5 ganti password', () => {
  it('changePassword() POST /auth/change-password/ dengan body snake_case', async () => {
    const calls = stubFetch({ ok: true });

    await changePassword(client(), 'rahasia123', 'rahasia456');

    expect(calls[0]?.url).toBe(`${BASE_URL}${AUTH_CHANGE_PASSWORD_PATH}`);
    expect(bodyOf(calls[0]!)).toEqual({
      old_password: 'rahasia123',
      new_password: 'rahasia456',
    });
  });

  it('changePassword() 400 memakai pesan backend ("Password lama salah")', async () => {
    stubFetch({ detail: 'Password lama salah' }, 400);

    const failed = await changePassword(client(), 'salah', 'rahasia456').catch(
      (error: unknown) => error,
    );

    expect((failed as AuthError).status).toBe(400);
    expect((failed as AuthError).message).toBe('Password lama salah');
  });
});

describe('F6.2 — helper murni adapter', () => {
  it('body builder hanya memuat field kontrak', () => {
    expect(buildLoginBody(' admin1 ', 'rahasia123')).toEqual({
      username: 'admin1',
      password: 'rahasia123',
    });
    expect(buildOperatorLoginBody(' 1234 ')).toEqual({ operator_code: '1234' });
    expect(buildChangePasswordBody('lama', 'baru')).toEqual({
      old_password: 'lama',
      new_password: 'baru',
    });
  });

  it('readAuthUser menolak bentuk tak dikenal & menormalkan field kosong', () => {
    expect(readAuthUser(null)).toBeNull();
    expect(readAuthUser('bukan objek')).toBeNull();
    expect(readAuthUser({ id: 0, username: 'x' })).toBeNull();
    expect(readAuthUser({ id: 3 })).toBeNull();

    const minimal = readAuthUser({ id: 3, username: 'operator1' });
    expect(minimal).toMatchObject({
      id: 3,
      username: 'operator1',
      email: '',
      role_code: null,
      is_superuser: false,
      device_profile: null,
    });
  });

  it('readRetryAfterSeconds hanya menerima angka detik', () => {
    expect(readRetryAfterSeconds('42')).toBe(42);
    expect(readRetryAfterSeconds(' 7 ')).toBe(7);
    expect(readRetryAfterSeconds('0')).toBeNull();
    expect(readRetryAfterSeconds('Wed, 21 Oct 2026 07:28:00 GMT')).toBeNull();
    expect(readRetryAfterSeconds(null)).toBeNull();
  });
});

