import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  SETTINGS_USERS_PATH,
  readSettingsUserRow,
  regenerateOperatorCode,
  toUser,
  updateUser,
  userInputFromRow,
  type SettingsUserRow,
} from '@/api/settings';
import { createApiClient } from '@/integrations/api-client';

/**
 * F6.3 — kolom & aksi "Kode Operator" pada layer API (`api/real/settingsUsers.ts`).
 *
 * Regenerate sengaja memakai endpoint yang SUDAH ADA (Opsi B): `PUT /settings/users/<id>/`
 * dengan `operator_code: ""` → backend mengundi kode baru (`User.save()` F6.1). Tidak ada
 * endpoint `/generate-code/` (butuh izin backend per larangan task).
 */

const BASE_URL = 'http://localhost:8000/api/v1';

interface FetchCall {
  url: string;
  init: RequestInit;
}

function stubFetch(body: unknown, status = 200): FetchCall[] {
  const calls: FetchCall[] = [];

  vi.stubGlobal(
    'fetch',
    vi.fn((url: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(url), init: init ?? {} });

      return Promise.resolve(
        new Response(JSON.stringify(body), {
          status,
          headers: { 'Content-Type': 'application/json' },
        }),
      );
    }),
  );

  return calls;
}

function client() {
  return createApiClient({ baseUrl: BASE_URL });
}

function bodyOf(call: FetchCall): Record<string, unknown> {
  return JSON.parse(String(call.init.body ?? '{}')) as Record<string, unknown>;
}

/** Baris backend B26 + F6.3 (serialize_user). */
const OPERATOR_ROW = {
  id: 12,
  username: 'operator1',
  email: 'op1@klien.com',
  full_name: 'Operator Satu',
  role: 'OPERATOR',
  operator_code: '4821',
  is_active: true,
  is_staff: false,
  last_login: null,
  date_joined: '2026-10-10T07:00:00+07:00',
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('F6.3 — parsing kolom operator_code', () => {
  it('readSettingsUserRow membaca operator_code (string) & null untuk role lain', () => {
    const operator = readSettingsUserRow(OPERATOR_ROW);
    const admin = readSettingsUserRow({ ...OPERATOR_ROW, role: 'ADMIN', operator_code: null });

    expect(operator?.operator_code).toBe('4821');
    expect(admin?.operator_code).toBeNull();
    // field lain tidak berubah (tanpa regresi B26)
    expect(operator?.role).toBe('OPERATOR');
    expect(operator?.is_active).toBe(true);
  });

  it('readSettingsUserRow: operator_code hilang → null (bukan string "undefined")', () => {
    const row = readSettingsUserRow({ ...OPERATOR_ROW, operator_code: undefined });

    expect(row?.operator_code).toBeNull();
  });

  it('toUser meneruskan operator_code ke tipe UI', () => {
    const parsed = readSettingsUserRow(OPERATOR_ROW) as SettingsUserRow;
    const user = toUser(parsed);

    expect(user.operator_code).toBe('4821');
    expect(user.role).toBe('operator');
  });
});

describe('F6.3 — regenerateOperatorCode (PUT yang sudah ada)', () => {
  it('mengirim PUT /settings/users/<id>/ dengan operator_code: "" + field wajib B26', async () => {
    const calls = stubFetch(OPERATOR_ROW);

    await regenerateOperatorCode(
      client(),
      12,
      userInputFromRow({
        username: 'operator1',
        email: 'op1@klien.com',
        full_name: 'Operator Satu',
        role: 'operator',
        active: true,
      }),
    );

    expect(calls[0]?.url).toBe(`${BASE_URL}${SETTINGS_USERS_PATH}12/`);
    expect(calls[0]?.init.method).toBe('PUT');
    expect(bodyOf(calls[0]!)).toEqual({
      username: 'operator1',
      email: 'op1@klien.com',
      first_name: 'Operator',
      last_name: 'Satu',
      role_code: 'OPERATOR',
      is_active: true,
      operator_code: '',
    });
    // password TIDAK dikirim (B26: kosong = tidak diubah)
    expect(bodyOf(calls[0]!)).not.toHaveProperty('password');
  });

  it('mengembalikan user hasil parse (kode dipakai UI untuk kolom)', async () => {
    stubFetch({ ...OPERATOR_ROW, operator_code: '9051' });

    const saved = await regenerateOperatorCode(
      client(),
      12,
      userInputFromRow({ username: 'operator1', full_name: 'Operator Satu', role: 'operator', active: true }),
    );

    expect(saved.operator_code).toBe('9051');
  });

  it('400 dari backend → melempar pesan backend (bukan menelan)', async () => {
    stubFetch({ detail: "Field 'operator_code' hanya untuk role OPERATOR atau QC." }, 400);

    const failed = await regenerateOperatorCode(
      client(),
      9,
      userInputFromRow({ username: 'spv1', email: 'spv@klien.com', full_name: 'Spv', role: 'supervisor', active: true }),
    ).catch((error: unknown) => error);

    expect((failed as Error).message).toContain('hanya untuk role OPERATOR');
  });

  it('userInputFromRow: email null/kosong → "" (body tetap valid untuk backend)', () => {
    expect(userInputFromRow({ username: 'x', email: null, full_name: 'X', role: 'qc', active: false })).toEqual({
      username: 'x',
      email: '',
      full_name: 'X',
      role: 'qc',
      active: false,
    });
  });
});

describe('F6.3 — updateUser tidak menyentuh kode bila tidak diminta', () => {
  it('tanpa operatorCode → field operator_code TIDAK dikirim', async () => {
    const calls = stubFetch(OPERATOR_ROW);

    await updateUser(client(), 12, {
      username: 'operator1',
      email: 'op1@klien.com',
      full_name: 'Operator Satu',
      role: 'operator',
      active: true,
    });

    expect(bodyOf(calls[0]!)).not.toHaveProperty('operator_code');
  });

  it('dengan operatorCode eksplisit → dikirim apa adanya (4/6 digit)', async () => {
    const calls = stubFetch(OPERATOR_ROW);

    await updateUser(client(), 12, {
      username: 'operator1',
      email: 'op1@klien.com',
      full_name: 'Operator Satu',
      role: 'operator',
      active: true,
      operatorCode: '7788',
    });

    expect(bodyOf(calls[0]!)['operator_code']).toBe('7788');
  });
});
