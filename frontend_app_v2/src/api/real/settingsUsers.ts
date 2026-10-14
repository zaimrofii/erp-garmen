// REAL - settings users (F5.4.CLOSE / backend B26).
//   GET|POST `/settings/users/`  +  PUT|DELETE `/settings/users/<id>/`
//
// Pemetaan UI ↔ backend (tidak ada shape yang dikarang):
//   * `role` backend = kode **UPPERCASE** (`OPERATOR`/`QC`/`SUPERVISOR`/`ADMIN`/`OWNER`,
//     migrasi `core_auth.0002`) → adapter men-`toLowerCase()` saat baca & `toUpperCase()`
//     saat kirim (`toRoleCode`/`toRole`);
//   * `full_name` UI **tidak ada** di backend → dipecah `first_name` + `last_name`
//     (kata pertama = first_name, sisanya last_name) lewat `splitFullName()`;
//   * `active` UI ← `is_active`; `email`/`is_staff`/`last_login`/`date_joined` aditif;
//   * `DELETE` backend = **soft delete** (`is_active=False`; baris tetap ada).
//
// Catatan: `ApiClient` hanya punya `get`/`post` — PUT/DELETE lewat `client.request()`.
import type { ApiClient, ApiResponse } from '@/integrations/api-client';
import type { Role, User } from '@/types/settings';
import { unwrap } from '../client';
import {
  buildQueryPath,
  getParsed,
  isRecord,
  readBool,
  readListPage,
  readNullableStr,
  readNum,
  readStr,
  type ListPage,
} from './_shape';

export const SETTINGS_USERS_PATH = '/settings/users/';

export interface SettingsUserRow {
  id: number;
  username: string;
  email: string;
  full_name: string;
  /** Kode role UPPERCASE (`OPERATOR`…) atau `null` (akun teknis tanpa role). */
  role: string | null;
  /**
   * F6.3 — kode operator 4/6 digit (role OPERATOR/QC) atau `null` (role lain).
   * Backend `serialize_user` mengirim field ini sejak F6.3.
   */
  operator_code: string | null;
  is_active: boolean;
  is_staff: boolean;
  last_login: string | null;
  date_joined: string | null;
}

export interface SettingsUserInput {
  username: string;
  email: string;
  /** Wajib saat create; kosong/`undefined` saat update = password tidak diubah. */
  password?: string;
  full_name: string;
  role: Role;
  active: boolean;
  /**
   * F6.3 — `''` = **minta kode operator baru** (backend mengundi via `User.save()`),
   * 4/6 digit = dipakai apa adanya, `undefined`/`null` = field tidak dikirim
   * (kode lama tidak diubah). Field ini TIDAK memakai nama backend `operator_code`
   * di lapisan UI supaya penamaan tetap camelCase seperti `full_name` di atas.
   */
  operatorCode?: string | null;
}

/** Peta kode role backend → union UI (5 role default; kode lain → `null`). */
export const ROLE_CODE_TO_ROLE: Record<string, Role> = {
  OPERATOR: 'operator',
  QC: 'qc',
  SUPERVISOR: 'supervisor',
  ADMIN: 'admin',
  OWNER: 'owner',
};

/** PURE — kode role backend (`OPERATOR`) dari union UI (`operator`). */
export function toRoleCode(role: string): string {
  return role.trim().toUpperCase();
}

/** PURE — union UI dari kode backend; kode tak dikenal → `null` (jangan dikarang). */
export function toRole(value: string | null): Role | null {
  return ROLE_CODE_TO_ROLE[(value ?? '').trim().toUpperCase()] ?? null;
}

/** PURE — `full_name` UI → `first_name` + `last_name` (backend tanpa kolom full_name). */
export function splitFullName(fullName: string): { first_name: string; last_name: string } {
  const parts = fullName.trim().split(/\s+/).filter((part) => part.length > 0);

  return { first_name: parts[0] ?? '', last_name: parts.slice(1).join(' ') };
}

/** PURE — satu baris backend → `SettingsUserRow`. */
export function readSettingsUserRow(raw: unknown): SettingsUserRow | null {
  if (!isRecord(raw)) return null;

  return {
    id: readNum(raw['id']),
    username: readStr(raw['username']),
    email: readStr(raw['email']),
    full_name: readStr(raw['full_name']),
    role: readNullableStr(raw['role']),
    operator_code: readNullableStr(raw['operator_code']),
    is_active: readBool(raw['is_active']),
    is_staff: readBool(raw['is_staff']),
    last_login: readNullableStr(raw['last_login']),
    date_joined: readNullableStr(raw['date_joined']),
  };
}

/** PURE — respons ListPage user. */
export function readSettingsUserPage(raw: unknown): ListPage<SettingsUserRow> | null {
  return readListPage<SettingsUserRow>(raw, readSettingsUserRow);
}

/** PURE — baris backend → tipe UI `User` (`role` lowercase, `active` ← `is_active`). */
export function toUser(row: SettingsUserRow): User {
  return {
    id: row.id,
    username: row.username,
    email: row.email,
    full_name: row.full_name,
    role: toRole(row.role) ?? 'operator',
    active: row.is_active,
    operator_code: row.operator_code,
  };
}

export interface SettingsUsersParams {
  q?: string | null;
  /** Union UI (`operator`) — dikirim sebagai kode UPPERCASE. */
  role?: string | null;
  isActive?: boolean | null;
  limit?: number | null;
  cursor?: number | null;
}

/** PURE — path + `?q=&role=&is_active=&limit=&cursor=`. */
export function buildSettingsUsersPath(params: SettingsUsersParams = {}): string {
  return buildQueryPath(SETTINGS_USERS_PATH, {
    q: params.q,
    role: params.role === null || params.role === undefined ? null : toRoleCode(params.role),
    is_active: params.isActive === null || params.isActive === undefined ? null : params.isActive,
    limit: params.limit,
    cursor: params.cursor,
  });
}

/** Body POST/PUT dari input UI (`password` hanya dikirim bila diisi). */
function toUserBody(input: SettingsUserInput): Record<string, unknown> {
  const { first_name, last_name } = splitFullName(input.full_name);
  const body: Record<string, unknown> = {
    username: input.username.trim(),
    email: input.email.trim(),
    first_name,
    last_name,
    role_code: toRoleCode(input.role),
    is_active: input.active,
  };

  if (input.password !== undefined && input.password.length > 0) {
    body['password'] = input.password;
  }

  // F6.3: `operator_code` hanya dikirim kalau caller peduli — `''` = minta kode baru
  // (backend mengundi), 4/6 digit = dipakai apa adanya. `null`/`undefined` = tidak diubah.
  if (typeof input.operatorCode === 'string') {
    body['operator_code'] = input.operatorCode;
  }

  return body;
}

function readSavedUser(res: ApiResponse<unknown>): User {
  const row = readSettingsUserRow(unwrap(res));
  if (row === null) {
    throw new Error('Bentuk respons simpan user tidak dikenali.');
  }

  return toUser(row);
}

/** Daftar user (admin/owner). Gagal HTTP → melempar. */
export async function fetchUsers(
  client: ApiClient,
  params: SettingsUsersParams = {},
): Promise<User[]> {
  const page = await getParsed(
    client,
    buildSettingsUsersPath(params),
    readSettingsUserPage,
    'daftar user',
  );

  return page.rows.map(toUser);
}

/** Buat user (POST). Password minimal 8 karakter (aturan backend). */
export async function createUser(client: ApiClient, input: SettingsUserInput): Promise<User> {
  return readSavedUser(await client.post<unknown>(SETTINGS_USERS_PATH, toUserBody(input)));
}

/** Ubah user (PUT). `password` kosong = password lama dipertahankan. */
export async function updateUser(
  client: ApiClient,
  id: number,
  input: SettingsUserInput,
): Promise<User> {
  return readSavedUser(
    await client.request<unknown>(`${SETTINGS_USERS_PATH}${id}/`, {
      method: 'PUT',
      body: toUserBody(input),
    }),
  );
}

/** Nonaktifkan user (DELETE = **soft delete**; user tidak dihapus dari DB). */
export async function deleteUser(client: ApiClient, id: number): Promise<void> {
  unwrap(await client.request<unknown>(`${SETTINGS_USERS_PATH}${id}/`, { method: 'DELETE' }));
}

/**
 * F6.3 — **minta kode operator baru** untuk satu user.
 *
 * Opsi B (keputusan task): TIDAK ada endpoint `generate-code` baru. Fungsi ini memakai
 * endpoint update yang SUDAH ADA (`PUT /settings/users/<id>/`) dengan `operator_code: ""`
 * → validator B26 meneruskannya dan `User.save()` (F6.1) mengundi kode unik baru
 * (4 digit, atau 6 digit bila 4 digit penuh). Body lain diambil dari user yang bersangkutan
 * karena B26 mewajibkan `username` + `email` di setiap PUT.
 */
export async function regenerateOperatorCode(
  client: ApiClient,
  id: number,
  input: SettingsUserInput,
): Promise<User> {
  return readSavedUser(
    await client.request<unknown>(`${SETTINGS_USERS_PATH}${id}/`, {
      method: 'PUT',
      body: toUserBody({ ...input, operatorCode: '' }),
    }),
  );
}

/** PURE — field wajib B26 untuk PUT dari baris tabel (tanpa mengubah password). */
export function userInputFromRow(user: {
  username: string;
  email?: string | null;
  full_name: string;
  role: Role;
  active: boolean;
}): SettingsUserInput {
  return {
    username: user.username,
    email: (user.email ?? '').trim(),
    full_name: user.full_name,
    role: user.role,
    active: user.active,
  };
}
