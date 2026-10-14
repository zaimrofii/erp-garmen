// ADAPTER - satu-satunya pintu data Settings/Admin (TANPA logic domain).
//
// F3A.CLOSE: `settingsRouting` / `settingsBundling` / `settingsLineAllocation` = REAL (GET+POST).
// F5.4.CLOSE: `settingsUsers` (B26, CRUD) + `settingsDevices` (B28, katalog profil) = REAL
// → `api/dummy/settings.ts` DIHAPUS (tidak ada lagi MODE dummy di file ini).
import { pickAdapter } from './_adapter';
import * as realBundling from './real/settingsBundling';
import * as realDevices from './real/settingsDevices';
import * as realLineAllocation from './real/settingsLineAllocation';
import * as realRouting from './real/settingsRouting';
import * as realUsers from './real/settingsUsers';

/** Konfigurasi DAG routing (RoutingConfigPage, LineAllocationPage) — REAL (B22). */
export const fetchRoutingConfigs = pickAdapter(
  'settingsRouting',
  realRouting.fetchRoutingConfigs,
  realRouting.fetchRoutingConfigs,
);

/** Simpan routing baru (POST /settings/routing/) — REAL (B22). */
export const saveRoutingConfig = pickAdapter(
  'settingsRouting',
  realRouting.saveRoutingConfig,
  realRouting.saveRoutingConfig,
);

export { SETTINGS_ROUTING_PATH, toRoutingConfig, toRoutingSteps } from './real/settingsRouting';
export type {
  RoutingCreateInput,
  RoutingRow,
  RoutingStepInput,
  RoutingStepRow,
} from './real/settingsRouting';

/** Aturan bundling (BundlingRulesPage) — REAL (B24, `GET /settings/bundling/`). */
export const fetchBundlingRules = pickAdapter(
  'settingsBundling',
  realBundling.fetchBundlingRules,
  realBundling.fetchBundlingRules,
);

/** Buat aturan bundling (POST /settings/bundling/) — REAL (B24). */
export const createBundlingRule = pickAdapter(
  'settingsBundling',
  realBundling.createBundlingRule,
  realBundling.createBundlingRule,
);

export { SETTINGS_BUNDLING_PATH } from './real/settingsBundling';
export type { BundlingRuleInput, BundlingRuleRow } from './real/settingsBundling';

/** Alokasi work center ke line (LineAllocationPage) — REAL (B25). */
export const fetchLineAllocations = pickAdapter(
  'settingsLineAllocation',
  realLineAllocation.fetchLineAllocations,
  realLineAllocation.fetchLineAllocations,
);

/** Buat aturan alokasi (POST /settings/line-allocation/) — REAL (B25). */
export const createLineAllocation = pickAdapter(
  'settingsLineAllocation',
  realLineAllocation.createLineAllocation,
  realLineAllocation.createLineAllocation,
);

export { SETTINGS_LINE_ALLOCATION_PATH } from './real/settingsLineAllocation';
export type { LineAllocationInput, LineAllocationRow } from './real/settingsLineAllocation';

/** Daftar user (UserManagementPage) — REAL (B26, admin/owner). */
export const fetchUsers = pickAdapter('settingsUsers', realUsers.fetchUsers, realUsers.fetchUsers);

/** Buat user (POST /settings/users/) — REAL (B26). Password minimal 8 karakter. */
export const createUser = pickAdapter('settingsUsers', realUsers.createUser, realUsers.createUser);

/** Ubah user (PUT /settings/users/<id>/) — REAL (B26). */
export const updateUser = pickAdapter('settingsUsers', realUsers.updateUser, realUsers.updateUser);

/** Nonaktifkan user (DELETE = soft delete) — REAL (B26). */
export const deleteUser = pickAdapter('settingsUsers', realUsers.deleteUser, realUsers.deleteUser);

/** F6.3 — minta kode operator baru (memakai PUT yang sudah ada; tanpa endpoint baru). */
export const regenerateOperatorCode = pickAdapter(
  'settingsUsers',
  realUsers.regenerateOperatorCode,
  realUsers.regenerateOperatorCode,
);

export {
  SETTINGS_USERS_PATH,
  readSettingsUserRow,
  splitFullName,
  toRoleCode,
  toUser,
  userInputFromRow,
} from './real/settingsUsers';
export type { SettingsUserInput, SettingsUserRow, SettingsUsersParams } from './real/settingsUsers';

/** Katalog profil perangkat (DeviceProfilesPage) — REAL (B28, katalog profil Opsi A). */
export const fetchDeviceProfiles = pickAdapter(
  'settingsDevices',
  realDevices.fetchDeviceProfiles,
  realDevices.fetchDeviceProfiles,
);

export { SETTINGS_DEVICES_PATH } from './real/settingsDevices';
export { fetchDeviceProfileRows, readDeviceProfileRow, toDeviceProfile } from './real/settingsDevices';
export type { DeviceProfileRow, SettingsDevicesParams } from './real/settingsDevices';

// Catatan cleanup Fase 14.1: `fetchRoles` PINDAH ke `api/roles.ts`
// (MODE.settingsRoles) supaya resource role punya adapter sendiri.

