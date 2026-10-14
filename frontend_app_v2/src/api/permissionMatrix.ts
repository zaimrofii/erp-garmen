// ADAPTER - satu-satunya pintu data Permission Matrix (H5.4, TANPA logic domain).
//
// H5.4: endpoint `/api/v1/settings/permissions/` (+ `/<role_id>/`) SUDAH ADA di backend →
// MODE.permissionMatrix = 'real' (`_adapter.ts`), jadi tidak ada implementasi dummy.
//
// **Opsi A′**: `matrix` = profil tersimpan (ber-jejak), `effective` = aturan yang berlaku
// sekarang (snapshot kode), `banner` = peringatan bahwa enforcement TETAP hardcoded.
import { pickAdapter } from './_adapter';
import * as real from './real/permissionMatrix';

/** Matrix + efektif + divergensi (`GET /settings/permissions/`) — REAL (H5.4). */
export const fetchPermissionMatrix = pickAdapter(
  'permissionMatrix',
  real.fetchPermissionMatrix,
  real.fetchPermissionMatrix,
);

/** Simpan profil izin satu role (`PUT /settings/permissions/<role_id>/`) — REAL (H5.4). */
export const updateRolePermissions = pickAdapter(
  'permissionMatrix',
  real.updateRolePermissions,
  real.updateRolePermissions,
);

export {
  permissionRolePath,
  readCellMap,
  readDivergence,
  readDivergences,
  readMatrix,
  readPermissionEnvelope,
  readPermissionRole,
  readPermissionSaveResult,
  readStrList,
  SETTINGS_PERMISSIONS_PATH,
  toPermissionBody,
} from './real/permissionMatrix';
export type {
  PermissionDivergence,
  PermissionDivergences,
  PermissionEnvelope,
  PermissionInput,
  PermissionMatrix,
  PermissionRole,
  PermissionSaveResult,
  PermissionUpdate,
} from '@/types/permission-matrix';
export { PERMISSION_BANNER_FALLBACK } from '@/types/permission-matrix';
