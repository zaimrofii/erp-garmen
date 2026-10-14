// REAL - settings roles (F5.4.CLOSE / backend B27). GET `/settings/roles/`.
//
// Pemetaan: `code` backend = **UPPERCASE** (`OPERATOR`/`QC`/`SUPERVISOR`/`ADMIN`/`OWNER`,
// migrasi `core_auth.0002`) sedangkan UI memakai union lowercase → adapter
// men-`toLowerCase()` lewat `toUiRole()`. Role backend TIDAK punya kolom `label`/
// `permissions` (label = `Role.name`, permissions tidak ada di kontrak B27).
//
// Kode di luar 5 role default **dilewati** saat dipetakan ke union UI `Role`
// (memperluas union = mengarang kontrak); versi lengkap tetap tersedia lewat
// `fetchRoleRows()` untuk halaman yang butuh `label`/`user_count`.
import type { ApiClient } from '@/integrations/api-client';
import type { Role } from '@/types/settings';
import {
  buildQueryPath,
  getParsed,
  isRecord,
  readBool,
  readListPage,
  readStr,
  readNum,
  type ListPage,
} from './_shape';

export const SETTINGS_ROLES_PATH = '/settings/roles/';

export interface RoleRow {
  id: number;
  /** Kode UPPERCASE (`OPERATOR`…). */
  code: string;
  /** `Role.name` backend. */
  label: string;
  description: string;
  is_active: boolean;
  /** Aditif dari `annotate(Count("users"))` (B27). */
  user_count: number;
}

const ROLE_CODE_TO_UI: Record<string, Role> = {
  OPERATOR: 'operator',
  QC: 'qc',
  SUPERVISOR: 'supervisor',
  ADMIN: 'admin',
  OWNER: 'owner',
};

/** PURE — kode backend → union UI; tak dikenal / kosong → `null`. */
export function toUiRole(code: string | null): Role | null {
  return ROLE_CODE_TO_UI[(code ?? '').trim().toUpperCase()] ?? null;
}

/** PURE — satu baris backend → `RoleRow`. */
export function readRoleRow(raw: unknown): RoleRow | null {
  if (!isRecord(raw)) return null;

  return {
    id: readNum(raw['id']),
    code: readStr(raw['code']),
    label: readStr(raw['label']),
    description: readStr(raw['description']),
    is_active: readBool(raw['is_active']),
    user_count: readNum(raw['user_count']),
  };
}

/** PURE — respons ListPage role. */
export function readRolePage(raw: unknown): ListPage<RoleRow> | null {
  return readListPage<RoleRow>(raw, readRoleRow);
}

/** Baris mentah + `total_count` (halaman yang butuh `label`/`user_count`). */
export async function fetchRoleRows(
  client: ApiClient,
  params: { limit?: number | null; cursor?: number | null } = {},
): Promise<ListPage<RoleRow>> {
  return getParsed(
    client,
    buildQueryPath(SETTINGS_ROLES_PATH, { limit: params.limit, cursor: params.cursor }),
    readRolePage,
    'daftar role',
  );
}

/** Daftar role sebagai union UI (dipakai UserManagementPage / filter sidebar). */
export async function fetchRoles(
  client: ApiClient,
  params: { limit?: number | null; cursor?: number | null } = {},
): Promise<Role[]> {
  const page = await fetchRoleRows(client, params);
  const roles: Role[] = [];

  for (const row of page.rows) {
    const role = toUiRole(row.code);
    if (role !== null && !roles.includes(role)) roles.push(role);
  }

  return roles;
}
