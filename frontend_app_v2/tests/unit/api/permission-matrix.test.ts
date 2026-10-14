import { describe, expect, it } from 'vitest';
import {
  SETTINGS_PERMISSIONS_PATH,
  fetchPermissionMatrix,
  permissionRolePath,
  readCellMap,
  readDivergence,
  readDivergences,
  readMatrix,
  readPermissionEnvelope,
  readPermissionRole,
  readPermissionSaveResult,
  readStrList,
  toPermissionBody,
  updateRolePermissions,
} from '@/api/permissionMatrix';
import { MODE, isReal } from '@/api/_adapter';
import { PERMISSION_BANNER_FALLBACK } from '@/types/permission-matrix';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';

/**
 * H5.4 — adapter Permission Matrix (`/api/v1/settings/permissions/`).
 *
 * Bentuk = PERSIS `core/auth/permission_services.py`: `matrix`/`effective`
 * `{role_id: {resource: {action: bool}}}`, `diverges` `{role_id: {resource: {action:
 * {profile, effective}}}}`, `roles` `[{id, code, label, is_active}]`, plus `banner`.
 */

const ROLES = [
  { id: 4, code: 'ADMIN', label: 'Administrator', is_active: true },
  { id: 1, code: 'OPERATOR', label: 'Operator', is_active: true },
];

const MATRIX = {
  '4': { settings: { read: true, create: false, update: false, delete: false } },
  '1': { bundles: { read: true, create: false, update: false, delete: false } },
};

const EFFECTIVE = {
  '4': { settings: { read: true, create: true, update: true, delete: true } },
  '1': { bundles: { read: true, create: false, update: true, delete: false } },
};

const DIVERGES = { '1': { bundles: { update: { profile: false, effective: true } } } };

const ENVELOPE = {
  matrix: MATRIX,
  effective: EFFECTIVE,
  diverges: DIVERGES,
  resources: ['bundles', 'settings'],
  actions: ['read', 'create', 'update', 'delete'],
  roles: ROLES,
  banner: '⚠️ Perubahan di halaman ini disimpan sebagai PROFIL …',
};

interface RecordedRequest {
  path: string;
  method: string;
  body?: unknown;
}

function stubClient(data: unknown): { client: ApiClient; requests: RecordedRequest[] } {
  const requests: RecordedRequest[] = [];
  const reply = <T,>(): ApiResponse<T> => ({ ok: true, status: 200, data: data as T });

  const client = {
    get: async <T,>(path: string): Promise<ApiResponse<T>> => {
      requests.push({ path, method: 'GET' });

      return reply<T>();
    },
    post: async <T,>(path: string, body: unknown): Promise<ApiResponse<T>> => {
      requests.push({ path, method: 'POST', body });

      return reply<T>();
    },
    request: async <T,>(
      path: string,
      options?: { method?: 'GET' | 'POST' | 'PUT' | 'DELETE'; body?: unknown },
    ): Promise<ApiResponse<T>> => {
      requests.push({ path, method: options?.method ?? 'GET', body: options?.body });

      return reply<T>();
    },
  } as unknown as ApiClient;

  return { client, requests };
}

function failingClient(status: number, message: string): ApiClient {
  const response = <T,>(): ApiResponse<T> => ({
    ok: false,
    status,
    error: { kind: 'http_error', message },
  });

  return {
    request: async <T,>(): Promise<ApiResponse<T>> => response<T>(),
    get: async <T,>(): Promise<ApiResponse<T>> => response<T>(),
    post: async <T,>(): Promise<ApiResponse<T>> => response<T>(),
  } as unknown as ApiClient;
}

describe('H5.4 — MODE & parsing', () => {
  it('MODE.permissionMatrix = real + path matrix/role', () => {
    expect(MODE['permissionMatrix']).toBe('real');
    expect(isReal('permissionMatrix')).toBe(true);
    expect(SETTINGS_PERMISSIONS_PATH).toBe('/settings/permissions/');
    expect(permissionRolePath(4)).toBe('/settings/permissions/4/');
  });

  it('readPermissionRole / readCellMap / readMatrix / readStrList', () => {
    const role = readPermissionRole(ROLES[0]);

    expect(role?.id).toBe(4);
    expect(role?.code).toBe('ADMIN');
    expect(role?.label).toBe('Administrator');
    expect(role?.is_active).toBe(true);
    expect(readPermissionRole({ code: 'ADMIN' })).toBeNull();

    const cell = readCellMap({ settings: { read: true, create: 'ya' } });

    expect(cell['settings']['read']).toBe(true);
    expect(cell['settings']['create']).toBeUndefined();
    expect(readCellMap('bukan objek')).toEqual({});

    const matrix = readMatrix({ '4': MATRIX['4'], rusak: 'bukan objek' });

    expect(matrix['4']['settings']['read']).toBe(true);
    expect(matrix['rusak']).toEqual({});

    expect(readStrList(['bundles', '', 'settings'])).toEqual(['bundles', 'settings']);
    expect(readStrList('bukan array')).toEqual([]);
  });

  it('readDivergence / readDivergences', () => {
    expect(readDivergence({ profile: false, effective: true })).toEqual({
      profile: false,
      effective: true,
    });
    expect(readDivergence({ profile: 'ya', effective: true })).toBeNull();
    expect(readDivergence(null)).toBeNull();

    const diverges = readDivergences({
      '1': { bundles: { update: { profile: false, effective: true }, rusak: 1 } },
      rusak: 'bukan objek',
    });

    expect(diverges['1']['bundles']['update']).toEqual({ profile: false, effective: true });
    expect(diverges['1']['bundles']['rusak']).toBeUndefined();
    expect(diverges['rusak']).toEqual({});
    expect(readDivergences('bukan objek')).toEqual({});
  });

  it('readPermissionEnvelope + banner fallback', () => {
    const envelope = readPermissionEnvelope(ENVELOPE);

    expect(envelope?.resources).toEqual(['bundles', 'settings']);
    expect(envelope?.actions).toEqual(['read', 'create', 'update', 'delete']);
    expect(envelope?.roles).toHaveLength(2);
    expect(envelope?.matrix['4']['settings']['read']).toBe(true);
    expect(envelope?.effective['4']['settings']['delete']).toBe(true);
    expect(envelope?.diverges['1']['bundles']['update']).toEqual({
      profile: false,
      effective: true,
    });
    expect(envelope?.banner).toContain('PROFIL');

    // banner kosong → fallback (tidak boleh bohong / hilang)
    expect(readPermissionEnvelope({ ...ENVELOPE, banner: '' })?.banner).toBe(
      PERMISSION_BANNER_FALLBACK,
    );

    // bentuk rusak → null
    expect(readPermissionEnvelope({ effective: {} })).toBeNull();
    expect(readPermissionEnvelope('bukan objek')).toBeNull();
  });

  it('readPermissionSaveResult (amplop + metadata tulis)', () => {
    const result = readPermissionSaveResult({
      ...ENVELOPE,
      role_id: 4,
      updated_count: 2,
      sync_record_id: 7,
      sync_status: 'SKIPPED',
    });

    expect(result?.role_id).toBe(4);
    expect(result?.updated_count).toBe(2);
    expect(result?.sync_record_id).toBe(7);
    expect(result?.sync_status).toBe('SKIPPED');

    // tanpa baris ledger (tidak ada perubahan) → sync_* null
    const kosong = readPermissionSaveResult({
      ...ENVELOPE,
      role_id: 4,
      updated_count: 0,
      sync_record_id: null,
      sync_status: null,
    });

    expect(kosong?.sync_record_id).toBeNull();
    expect(kosong?.sync_status).toBeNull();
  });

  it('toPermissionBody (dedupe updates + saring matrix)', () => {
    const body = toPermissionBody({
      updates: [
        { resource: ' bundles ', action: ' READ ', allowed: true },
        { resource: 'bundles', action: 'read', allowed: false },
        { resource: 'settings', action: 'update', allowed: true },
      ],
    });

    expect(body['updates']).toEqual([
      { resource: 'bundles', action: 'read', allowed: true },
      { resource: 'settings', action: 'update', allowed: true },
    ]);

    const matrixBody = toPermissionBody({
      matrix: { bundles: { read: true, create: 'ya' }, rusak: 'bukan objek' },
    });

    expect(matrixBody['matrix']).toEqual({ bundles: { read: true } });

    // tanpa updates/matrix valid → body kosong (backend yang menolak 400)
    expect(toPermissionBody({})).toEqual({});
    expect(toPermissionBody({ updates: [] })).toEqual({});
  });
});

describe('H5.4 — HTTP adapter', () => {
  it('fetchPermissionMatrix GET amplop', async () => {
    const stub = stubClient(ENVELOPE);

    const envelope = await fetchPermissionMatrix(stub.client);

    expect(stub.requests).toEqual([{ path: '/settings/permissions/', method: 'GET' }]);
    expect(envelope.roles[0].code).toBe('ADMIN');
    expect(envelope.diverges['1']['bundles']['update']['effective']).toBe(true);
  });

  it('updateRolePermissions PUT body + hasil', async () => {
    const stub = stubClient({
      ...ENVELOPE,
      role_id: 1,
      updated_count: 1,
      sync_record_id: 9,
      sync_status: 'SKIPPED',
    });

    const result = await updateRolePermissions(stub.client, 1, {
      updates: [{ resource: 'bundles', action: 'update', allowed: true }],
    });

    expect(stub.requests).toEqual([
      {
        path: '/settings/permissions/1/',
        method: 'PUT',
        body: { updates: [{ resource: 'bundles', action: 'update', allowed: true }] },
      },
    ]);
    expect(result.updated_count).toBe(1);
    expect(result.sync_status).toBe('SKIPPED');
  });

  it('gagal HTTP & bentuk rusak → melempar', async () => {
    await expect(
      updateRolePermissions(failingClient(400, "Resource 'odoo' tidak dikenal"), 1, {
        updates: [{ resource: 'odoo', action: 'read', allowed: true }],
      }),
    ).rejects.toThrow('tidak dikenal');
    await expect(
      updateRolePermissions(failingClient(403, 'Hanya user dengan role ADMIN/OWNER'), 1, {
        updates: [{ resource: 'bundles', action: 'read', allowed: true }],
      }),
    ).rejects.toThrow('ADMIN/OWNER');
    await expect(fetchPermissionMatrix(failingClient(403, 'anonim'))).rejects.toThrow('anonim');
    await expect(fetchPermissionMatrix(stubClient({ matrix: {} }).client)).rejects.toThrow(
      'tidak dikenali',
    );
    await expect(
      updateRolePermissions(stubClient({ matrix: {} }).client, 1, { updates: [] }),
    ).rejects.toThrow('tidak dikenali');
  });
});

