// REAL — auth hybrid (F6.2 / backend F6.1 `core/auth/api.py`).
//
//   POST `/auth/login/`           → `{id, username, email, full_name, role_code, is_superuser, is_staff}`
//   POST `/auth/login-operator/`  → `{id, username, full_name, role_code}` (subset — F6.1 E2)
//   POST `/auth/logout/`          → `{ok: true}`
//   GET  `/auth/me/`              → data user + `device_profile`/`wc_code` (null bila sesi biasa)
//   POST `/auth/change-password/` → `{ok: true}` (400 "Password lama salah" bila salah)
//
// Tidak ada shape yang dikarang: field dibaca apa adanya dari respons backend. E2 (login
// operator) memang mengirim subset → `email`/`is_superuser`/`is_staff` diisi nilai netral;
// `hooks/useAuth.ts` memanggil `getMe()` setelah login supaya profil yang disimpan lengkap.
//
// Catatan: `ApiClient` hanya punya `get`/`post` — kelima endpoint auth semuanya GET/POST,
// jadi tidak perlu `client.request()` (beda dengan B26 yang memakai PUT/DELETE).
import type { ApiClient, ApiResponse } from '@/integrations/api-client';
import { authErrorMessage, LOGIN_MESSAGES } from '@/lib/login-form';
import { isRecord, readBool, readNullableStr, readNum, readStr } from './_shape';

export const AUTH_LOGIN_PATH = '/auth/login/';
export const AUTH_LOGIN_OPERATOR_PATH = '/auth/login-operator/';
export const AUTH_LOGOUT_PATH = '/auth/logout/';
export const AUTH_ME_PATH = '/auth/me/';
export const AUTH_CHANGE_PASSWORD_PATH = '/auth/change-password/';

/** User yang sedang login (kontrak E1/E4). `device_profile`/`wc_code` hanya dari device cookie. */
export interface AuthUser {
  id: number;
  username: string;
  email: string;
  full_name: string;
  /** Kode role UPPERCASE (`OPERATOR`/`ADMIN`/…) atau `null` untuk akun teknis tanpa role. */
  role_code: string | null;
  is_superuser: boolean;
  is_staff: boolean;
  /** Profil perangkat (E4, mis. `OPERATOR_HP`) — `null` kalau login lewat session biasa. */
  device_profile?: string | null;
  /** Work center binding perangkat (E4) — `null` kalau tidak ada. */
  wc_code?: string | null;
}

/**
 * Error endpoint auth: pesannya SUDAH siap tampil (`authErrorMessage`) dan `status`-nya
 * dibawa supaya pemanggil bisa membedakan 401/429/network tanpa mem-parse teks.
 */
export class AuthError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(
    status: number,
    detail: string,
    retryAfterSeconds: number | null,
    fallback?: string,
  ) {
    super(authErrorMessage({ status, detail, retryAfterSeconds, fallback }));
    this.name = 'AuthError';
    this.status = status;
    this.detail = detail;
  }
}

/** PURE — satu objek user backend → `AuthUser`; bentuk tak dikenal → `null`. */
export function readAuthUser(raw: unknown): AuthUser | null {
  if (!isRecord(raw)) return null;

  const id = readNum(raw['id']);
  const username = readStr(raw['username']);
  if (id <= 0 || username.length === 0) return null;

  return {
    id,
    username,
    email: readStr(raw['email']),
    full_name: readStr(raw['full_name']),
    role_code: readNullableStr(raw['role_code']),
    is_superuser: readBool(raw['is_superuser']),
    is_staff: readBool(raw['is_staff']),
    device_profile: readNullableStr(raw['device_profile']),
    wc_code: readNullableStr(raw['wc_code']),
  };
}

/** PURE — body login admin/supervisor (`{username, password}`). */
export function buildLoginBody(username: string, password: string): Record<string, string> {
  return { username: username.trim(), password };
}

/** PURE — body login operator (`{operator_code}`). */
export function buildOperatorLoginBody(operatorCode: string): Record<string, string> {
  return { operator_code: operatorCode.trim() };
}

/** PURE — body ganti password (`{old_password, new_password}`). */
export function buildChangePasswordBody(
  oldPassword: string,
  newPassword: string,
): Record<string, string> {
  return { old_password: oldPassword, new_password: newPassword };
}

function toAuthError(res: ApiResponse<unknown>, fallback?: string): AuthError {
  return new AuthError(
    res.status,
    res.error?.message ?? '',
    typeof res.retryAfter === 'number' ? res.retryAfter : null,
    fallback,
  );
}

function requireUser(res: ApiResponse<unknown>, fallback: string): AuthUser {
  if (!res.ok) throw toAuthError(res, fallback);

  const user = readAuthUser(res.data);
  if (user === null) throw new Error('Bentuk respons login tidak dikenali.');

  return user;
}

/** Login admin/supervisor (E1) — 401 → `AuthError` berisi teks backend. */
export async function login(
  client: ApiClient,
  username: string,
  password: string,
): Promise<AuthUser> {
  return requireUser(
    await client.post<unknown>(AUTH_LOGIN_PATH, buildLoginBody(username, password)),
    LOGIN_MESSAGES.invalidCredentials,
  );
}

/** Login operator via kode 4 digit (E2) — umur sesi 8 jam diatur backend. */
export async function loginOperator(
  client: ApiClient,
  operatorCode: string,
): Promise<AuthUser> {
  return requireUser(
    await client.post<unknown>(AUTH_LOGIN_OPERATOR_PATH, buildOperatorLoginBody(operatorCode)),
    LOGIN_MESSAGES.invalidOperatorCode,
  );
}

/**
 * Logout (E3). 401 dianggap **sukses** (sesi sudah tidak ada) supaya logout idempotent —
 * user yang membiarkan sesinya kedaluwarsa tetap bisa keluar dengan tenang.
 */
export async function logout(client: ApiClient): Promise<void> {
  const res = await client.post<unknown>(AUTH_LOGOUT_PATH, {});

  if (!res.ok && res.status !== 401) throw toAuthError(res);
}

/** Sesi aktif (E4): `null` bila belum login (401); error lain → melempar. */
export async function getMe(client: ApiClient): Promise<AuthUser | null> {
  const res = await client.get<unknown>(AUTH_ME_PATH);

  if (res.status === 401) return null;
  if (!res.ok) throw toAuthError(res);

  return readAuthUser(res.data);
}

/** Ganti password sendiri (E5). Password lama salah → 400 ("Password lama salah"). */
export async function changePassword(
  client: ApiClient,
  oldPassword: string,
  newPassword: string,
): Promise<void> {
  const res = await client.post<unknown>(
    AUTH_CHANGE_PASSWORD_PATH,
    buildChangePasswordBody(oldPassword, newPassword),
  );

  if (!res.ok) throw toAuthError(res, LOGIN_MESSAGES.changePasswordFailed);
}

