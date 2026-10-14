// ADAPTER — pintu data auth hybrid (F6.2). Resource ke-47 `auth`, seluruhnya REAL
// (backend F6.1 sudah menyediakan 6 endpoint).
//
// Keputusan: barrel ini memakai `pickAdapter('auth', …)` (bukan `export * from './real/auth'`)
// supaya key `MODE.auth` benar-benar dipakai — konsisten dengan barrel lain (mis.
// `api/settings.ts`) dan jumlah adapter tetap satu sumber di `api/_adapter.ts`.
import { pickAdapter } from './_adapter';
import * as real from './real/auth';

/** Login admin/supervisor (E1). Gagal → `AuthError` (pesan siap tampil). */
export const login = pickAdapter('auth', real.login, real.login);

/** Login operator via kode 4 digit (E2). Sesi 8 jam diatur backend. */
export const loginOperator = pickAdapter('auth', real.loginOperator, real.loginOperator);

/** Logout (E3) — idempotent (401 tetap dianggap sukses). */
export const logout = pickAdapter('auth', real.logout, real.logout);

/** Sesi aktif (E4): `null` kalau belum login (401). */
export const getMe = pickAdapter('auth', real.getMe, real.getMe);

/** Ganti password sendiri (E5). */
export const changePassword = pickAdapter('auth', real.changePassword, real.changePassword);

export { AuthError } from './real/auth';
export {
  AUTH_CHANGE_PASSWORD_PATH,
  AUTH_LOGIN_OPERATOR_PATH,
  AUTH_LOGIN_PATH,
  AUTH_LOGOUT_PATH,
  AUTH_ME_PATH,
  buildChangePasswordBody,
  buildLoginBody,
  buildOperatorLoginBody,
  readAuthUser,
} from './real/auth';
export type { AuthUser } from './real/auth';
