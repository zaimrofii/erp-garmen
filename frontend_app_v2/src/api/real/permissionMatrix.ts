// REAL - Permission Matrix (H5.4). Endpoint: `/api/v1/settings/permissions/`
//   GET `/settings/permissions/`            → {matrix, effective, diverges, resources,
//                                             actions, roles, banner}
//   PUT `/settings/permissions/<role_id>/`  → amplop yang sama + {role_id,
//                                             updated_count, sync_record_id, sync_status}
//
// Backend `apps_industry/garment/api/settings/views.py::SettingsPermissions*`:
//   * GET `IsAuthenticated` (anonim 403) — baca matrix = transparansi;
//   * PUT **ADMIN/OWNER** (`_require_admin`) — body `{updates: [...]}` atau
//     `{matrix: {resource: {action: bool}}}`;
//   * **Opsi A′**: `matrix` = profil (ber-jejak ledger SKIPPED), `effective` = aturan yang
//     berlaku sekarang (snapshot kode), `diverges` = sel yang beda, `banner` = peringatan
//     bahwa enforcement TETAP hardcoded di kode.
//
// Catatan: `ApiClient` hanya punya `get`/`post` — PUT lewat `client.request()`.
import type { ApiClient } from '@/integrations/api-client';
import type {
  PermissionDivergence,
  PermissionDivergences,
  PermissionEnvelope,
  PermissionInput,
  PermissionMatrix,
  PermissionRole,
  PermissionSaveResult,
} from '@/types/permission-matrix';
import { PERMISSION_BANNER_FALLBACK } from '@/types/permission-matrix';
import { unwrap } from '../client';
import { isRecord, readBool, readNum, readStr } from './_shape';

/** Path relatif terhadap `VITE_API_BASE_URL` (`…/api/v1`). */
export const SETTINGS_PERMISSIONS_PATH = '/settings/permissions/';

/** Path tulis satu role. */
export function permissionRolePath(roleId: number): string {
  return `${SETTINGS_PERMISSIONS_PATH}${String(roleId)}/`;
}

/** PURE — satu baris role; `null` kalau tanpa `id` angka. */
export function readPermissionRole(raw: unknown): PermissionRole | null {
  if (!isRecord(raw)) return null;

  const id = raw['id'];
  if (typeof id !== 'number' || !Number.isFinite(id)) return null;

  return {
    id,
    code: readStr(raw['code']),
    label: readStr(raw['label']),
    is_active: readBool(raw['is_active']),
  };
}

/** PURE — `{resource: {action: bool}}` → hanya nilai boolean yang diterima. */
export function readCellMap(raw: unknown): Record<string, Record<string, boolean>> {
  const cell: Record<string, Record<string, boolean>> = {};
  if (!isRecord(raw)) return cell;

  for (const [resource, actions] of Object.entries(raw)) {
    if (!isRecord(actions)) continue;
    const perAction: Record<string, boolean> = {};
    for (const [action, value] of Object.entries(actions)) {
      if (typeof value === 'boolean') perAction[action] = value;
    }
    cell[resource] = perAction;
  }

  return cell;
}

/** PURE — `{role_id: {resource: {action: bool}}}`. */
export function readMatrix(raw: unknown): PermissionMatrix {
  const matrix: PermissionMatrix = {};
  if (!isRecord(raw)) return matrix;

  for (const [roleId, cell] of Object.entries(raw)) {
    matrix[roleId] = readCellMap(cell);
  }

  return matrix;
}

/** PURE — daftar string (mis. `resources`/`actions`). */
export function readStrList(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];

  return raw.map((item) => readStr(item)).filter((item) => item !== '');
}

/** PURE — satu sel divergensi (`{profile, effective}` boolean). */
export function readDivergence(raw: unknown): PermissionDivergence | null {
  if (!isRecord(raw)) return null;
  if (typeof raw['profile'] !== 'boolean' || typeof raw['effective'] !== 'boolean') {
    return null;
  }

  return { profile: raw['profile'], effective: raw['effective'] };
}

/** PURE — `diverges` mentah → `PermissionDivergences`. */
export function readDivergences(raw: unknown): PermissionDivergences {
  const diverges: PermissionDivergences = {};
  if (!isRecord(raw)) return diverges;

  for (const [roleId, cell] of Object.entries(raw)) {
    const perResource: Record<string, Record<string, PermissionDivergence>> = {};

    if (isRecord(cell)) {
      for (const [resource, actions] of Object.entries(cell)) {
        if (!isRecord(actions)) continue;
        const perAction: Record<string, PermissionDivergence> = {};
        for (const [action, value] of Object.entries(actions)) {
          const parsed = readDivergence(value);
          if (parsed !== null) perAction[action] = parsed;
        }
        perResource[resource] = perAction;
      }
    }

    diverges[roleId] = perResource;
  }

  return diverges;
}

/** PURE — respons GET → `PermissionEnvelope`; `null` kalau bentuk rusak. */
export function readPermissionEnvelope(raw: unknown): PermissionEnvelope | null {
  if (!isRecord(raw)) return null;
  if (!isRecord(raw['matrix']) || !isRecord(raw['effective'])) return null;

  const roles: PermissionRole[] = [];
  const rawRoles = raw['roles'];
  if (Array.isArray(rawRoles)) {
    for (const item of rawRoles) {
      const role = readPermissionRole(item);
      if (role !== null) roles.push(role);
    }
  }

  const banner = readStr(raw['banner']);

  return {
    matrix: readMatrix(raw['matrix']),
    effective: readMatrix(raw['effective']),
    diverges: readDivergences(raw['diverges']),
    resources: readStrList(raw['resources']),
    actions: readStrList(raw['actions']),
    roles,
    banner: banner === '' ? PERMISSION_BANNER_FALLBACK : banner,
  };
}

/** PURE — respons PUT → `PermissionSaveResult`; `null` kalau amplop rusak. */
export function readPermissionSaveResult(raw: unknown): PermissionSaveResult | null {
  const envelope = readPermissionEnvelope(raw);
  if (envelope === null) return null;

  const record = raw as Record<string, unknown>;
  const syncId = record['sync_record_id'];

  return {
    ...envelope,
    role_id: readNum(record['role_id']),
    updated_count: readNum(record['updated_count']),
    sync_record_id:
      typeof syncId === 'number' && Number.isFinite(syncId) ? syncId : null,
    sync_status:
      syncId === null || syncId === undefined ? null : readStr(record['sync_status']),
  };
}

/** PURE — body PUT dari daftar update/matrix (duplikat (resource, action) dibuang). */
export function toPermissionBody(input: PermissionInput): Record<string, unknown> {
  const body: Record<string, unknown> = {};

  if (Array.isArray(input.updates)) {
    const seen = new Set<string>();
    const updates: { resource: string; action: string; allowed: boolean }[] = [];

    for (const item of input.updates) {
      const resource = item.resource.trim();
      const action = item.action.trim().toLowerCase();
      const key = `${resource}|${action}`;
      if (resource === '' || action === '' || seen.has(key)) continue;
      seen.add(key);
      updates.push({ resource, action, allowed: item.allowed });
    }

    if (updates.length > 0) body['updates'] = updates;
  }

  if (isRecord(input.matrix)) {
    const matrix: Record<string, Record<string, boolean>> = {};

    for (const [resource, actions] of Object.entries(input.matrix)) {
      if (!isRecord(actions)) continue;
      const perAction: Record<string, boolean> = {};
      for (const [action, value] of Object.entries(actions)) {
        if (typeof value === 'boolean') perAction[action] = value;
      }
      if (Object.keys(perAction).length > 0) matrix[resource] = perAction;
    }

    if (Object.keys(matrix).length > 0) body['matrix'] = matrix;
  }

  return body;
}

/** Baca matrix (READ-ONLY). Gagal HTTP (403 non-login) → melempar. */
export async function fetchPermissionMatrix(client: ApiClient): Promise<PermissionEnvelope> {
  const envelope = readPermissionEnvelope(
    unwrap(await client.get<unknown>(SETTINGS_PERMISSIONS_PATH)),
  );
  if (envelope === null) {
    throw new Error('Bentuk respons matrix izin tidak dikenali.');
  }

  return envelope;
}

/** Simpan profil izin satu role (PUT bulk, ADMIN/OWNER) → amplop + metadata tulis. */
export async function updateRolePermissions(
  client: ApiClient,
  roleId: number,
  input: PermissionInput,
): Promise<PermissionSaveResult> {
  const result = readPermissionSaveResult(
    unwrap(
      await client.request<unknown>(permissionRolePath(roleId), {
        method: 'PUT',
        body: toPermissionBody(input),
      }),
    ),
  );
  if (result === null) {
    throw new Error('Bentuk respons simpan matrix izin tidak dikenali.');
  }

  return result;
}

