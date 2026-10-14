// ADAPTER - satu-satunya pintu data Role (TANPA logic domain).
//
// Halaman WAJIB mengimpor dari sini - JANGAN dari `./dummy/*` atau `./real/*`.
// F5.4.CLOSE: MODE.settingsRoles === 'real' (B27) → `api/dummy/roles.ts` dihapus.
import { pickAdapter } from './_adapter';
import * as real from './real/settingsRoles';

/** Semua role yang dikenal backend (filter sidebar Fase 16 + UserManagementPage). */
export const fetchRoles = pickAdapter('settingsRoles', real.fetchRoles, real.fetchRoles);

export { SETTINGS_ROLES_PATH } from './real/settingsRoles';
export { fetchRoleRows, readRoleRow, readRolePage, toUiRole } from './real/settingsRoles';
export type { RoleRow } from './real/settingsRoles';
