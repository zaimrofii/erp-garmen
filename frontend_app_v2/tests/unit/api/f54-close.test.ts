import { describe, expect, it } from 'vitest';
import { MODE } from '@/api/_adapter';
import {
  buildHitlDecisionPath,
  buildHitlQueuePath,
  decideApproval,
  DEFAULT_REJECT_NOTE,
  fetchAllApprovals,
  fetchPendingApprovals,
  HITL_QUEUE_PATH,
  readHitlRow,
  toHitlApproval,
} from '@/api/real/hitl';
import {
  buildInventoryReportingPath,
  fetchLocationStock,
  INVENTORY_REPORTING_PATH,
  readLocationStockReport,
} from '@/api/real/inventoryReporting';
import {
  buildSettingsDevicesPath,
  fetchDeviceProfileRows,
  fetchDeviceProfiles,
  readDeviceProfileRow,
  SETTINGS_DEVICES_PATH,
  toDeviceProfile,
} from '@/api/real/settingsDevices';
import {
  fetchRoleRows,
  fetchRoles,
  readRoleRow,
  SETTINGS_ROLES_PATH,
  toUiRole,
} from '@/api/real/settingsRoles';
import {
  buildSettingsUsersPath,
  createUser,
  deleteUser,
  fetchUsers,
  SETTINGS_USERS_PATH,
  splitFullName,
  readSettingsUserPage,
  readSettingsUserRow,
  toRole,
  toRoleCode,
  toUser,
  updateUser,
} from '@/api/real/settingsUsers';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';

/**
 * F5.4.CLOSE — 5 MODE terakhir yang di-flip ke REAL (B26 users, B27 roles,
 * B28 devices, B29 HITL, B30 inventory reporting).
 *
 * Fokus uji: pemetaan shape backend → shape UI (role UPPERCASE→lowercase,
 * `full_name`↔`first_name/last_name`, `is_active`↔`active`, amplop laporan) dan
 * path/verb yang benar (PUT/DELETE lewat `client.request`).
 */

interface Stub {
  client: ApiClient;
  gets: string[];
  posts: { path: string; body: unknown }[];
  requests: { path: string; method: string; body: unknown }[];
}

function stubClient(handler: (path: string) => unknown): Stub {
  const gets: string[] = [];
  const posts: { path: string; body: unknown }[] = [];
  const requests: { path: string; method: string; body: unknown }[] = [];

  const respond = (path: string): ApiResponse<unknown> => ({
    ok: true,
    status: 200,
    data: handler(path),
  });

  const client = {
    get: async <T,>(path: string): Promise<ApiResponse<T>> => {
      gets.push(path);
      return respond(path) as ApiResponse<T>;
    },
    post: async <T,>(path: string, body?: unknown): Promise<ApiResponse<T>> => {
      posts.push({ path, body });
      return respond(path) as ApiResponse<T>;
    },
    request: async <T,>(
      path: string,
      options?: { method?: string; body?: unknown },
    ): Promise<ApiResponse<T>> => {
      requests.push({ path, method: options?.method ?? 'GET', body: options?.body });
      return respond(path) as ApiResponse<T>;
    },
  } as unknown as ApiClient;

  return { client, gets, posts, requests };
}

const USER_ROW = {
  id: 7,
  username: 'spv.lineb',
  email: 'spv.lineb@garment.local',
  full_name: 'Budi Santoso',
  role: 'SUPERVISOR',
  is_active: true,
  is_staff: false,
  last_login: null,
  date_joined: '2026-01-02T08:00:00+07:00',
};

const USER_PAGE = { rows: [USER_ROW], total_count: 1, has_more: false, next_cursor: null };

const ROLE_PAGE = {
  rows: [
    {
      id: 1,
      code: 'OPERATOR',
      label: 'Operator',
      description: 'operator lantai',
      is_active: true,
      user_count: 4,
    },
    {
      id: 2,
      code: 'SABLON_LEAD',
      label: 'Lead Sablon',
      description: 'role khusus klien',
      is_active: true,
      user_count: 1,
    },
  ],
  total_count: 2,
  has_more: false,
  next_cursor: null,
};

const DEVICE_PAGE = {
  rows: [
    {
      id: 3,
      device_type: 'KIOSK_TABLET',
      label: 'Kiosk Tablet',
      description: 'tablet lantai',
      active: true,
      config: { scan: true },
      binding_count: 2,
    },
  ],
  total_count: 1,
  has_more: false,
  next_cursor: null,
};

const REPORT_BODY = {
  rows: [
    {
      location_code: 'WH/WIP',
      location_name: 'Gudang Bahan (WIP)',
      product_count: 3,
      total_qty: 120,
      last_updated: '2026-10-10T09:00:00+07:00',
    },
    {
      location_code: 'Virtual/Scrap',
      location_name: 'Scrap',
      product_count: 0,
      total_qty: 0,
      last_updated: null,
    },
  ],
  total_locations: 2,
  generated_at: '2026-10-10T09:05:00+07:00',
};

function hitlRow(state: string, id: number, created: string) {
  return {
    id,
    request_type: 'SCRAP_BUNDLE',
    resource_type: 'bundle',
    resource_id: 'BDL-1',
    payload: { qty: 4 },
    reason: 'kain rusak',
    priority: 'HIGH',
    state,
    requested_by: 'ai.agent',
    requested_at: created,
    expires_at: null,
    decided_by: null,
    decided_at: null,
    decision_note: null,
  };
}

function hitlHandler(path: string): unknown {
  if (path.includes('state=PENDING')) {
    return { rows: [hitlRow('PENDING', 2, '2026-10-10T08:00:00+07:00')], total_count: 1, has_more: false, next_cursor: null };
  }
  if (path.includes('state=APPROVED')) {
    return { rows: [hitlRow('APPROVED', 1, '2026-10-10T10:00:00+07:00')], total_count: 1, has_more: false, next_cursor: null };
  }
  if (path.includes('state=REJECTED')) {
    return { rows: [], total_count: 0, has_more: false, next_cursor: null };
  }

  return { rows: [hitlRow('EXPIRED', 3, '2026-10-09T07:00:00+07:00')], total_count: 1, has_more: false, next_cursor: null };
}

describe('F5.4.CLOSE — MODE 5 key terakhir', () => {
  it('B26/B27/B28/B29/B30 semuanya real', () => {
    for (const key of [
      'settingsUsers',
      'settingsRoles',
      'settingsDevices',
      'hitl',
      'inventoryReporting',
    ]) {
      expect(MODE[key], key).toBe('real');
    }
  });
});

describe('F5.4.CLOSE — B26 settings/users', () => {
  it('parse baris + mapping role UPPERCASE → union lowercase', () => {
    const row = readSettingsUserRow(USER_ROW);

    expect(readSettingsUserRow('nope')).toBeNull();
    expect(row?.full_name).toBe('Budi Santoso');
    expect(readSettingsUserPage(USER_PAGE)?.total_count).toBe(1);

    const user = toUser(row!);

    expect(user).toEqual({
      id: 7,
      username: 'spv.lineb',
      email: 'spv.lineb@garment.local',
      full_name: 'Budi Santoso',
      role: 'supervisor',
      active: true,
      // F6.3 — `toUser` meneruskan `operator_code` (null untuk role non-OPERATOR/QC).
      operator_code: null,
    });
  });

  it('toRole/toRoleCode + fallback role tak dikenal', () => {
    expect(toRoleCode(' operator ')).toBe('OPERATOR');
    expect(toRole('ADMIN')).toBe('admin');
    expect(toRole(null)).toBeNull();
    expect(toRole('TEKNISI')).toBeNull();

    const unknown = toUser({ ...readSettingsUserRow(USER_ROW)!, role: 'TEKNISI' });
    expect(unknown.role).toBe('operator');
    expect(SETTINGS_USERS_PATH).toBe('/settings/users/');
  });

  it('splitFullName: kata pertama first_name, sisanya last_name', () => {
    expect(splitFullName('Budi Santoso')).toEqual({ first_name: 'Budi', last_name: 'Santoso' });
    expect(splitFullName('Budi')).toEqual({ first_name: 'Budi', last_name: '' });
    expect(splitFullName('   ')).toEqual({ first_name: '', last_name: '' });
  });

  it('buildSettingsUsersPath: role dikirim UPPERCASE, is_active apa adanya', () => {
    expect(
      buildSettingsUsersPath({ q: 'budi', role: 'operator', isActive: false, limit: 5 }),
    ).toBe('/settings/users/?q=budi&role=OPERATOR&is_active=false&limit=5');
    expect(buildSettingsUsersPath()).toBe('/settings/users/');
  });

  it('fetchUsers → User[] (email + active dari is_active)', async () => {
    const { client, gets } = stubClient(() => USER_PAGE);
    const users = await fetchUsers(client, { isActive: true });

    expect(gets).toEqual(['/settings/users/?is_active=true']);
    expect(users).toHaveLength(1);
    expect(users[0]?.email).toBe('spv.lineb@garment.local');
    expect(users[0]?.active).toBe(true);
  });

  it('createUser POST body (first/last name, role_code UPPERCASE, password)', async () => {
    const { client, posts } = stubClient(() => USER_ROW);
    const created = await createUser(client, {
      username: ' spv.lineb ',
      email: ' spv.lineb@garment.local ',
      password: 'rahasia123',
      full_name: 'Budi Santoso',
      role: 'supervisor',
      active: true,
    });

    expect(posts[0]?.path).toBe('/settings/users/');
    expect(posts[0]?.body).toEqual({
      username: 'spv.lineb',
      email: 'spv.lineb@garment.local',
      first_name: 'Budi',
      last_name: 'Santoso',
      role_code: 'SUPERVISOR',
      is_active: true,
      password: 'rahasia123',
    });
    expect(created.role).toBe('supervisor');
  });

  it('updateUser = PUT; password kosong TIDAK dikirim (tidak diubah)', async () => {
    const { client, requests } = stubClient(() => USER_ROW);
    await updateUser(client, 7, {
      username: 'spv.lineb',
      email: 'spv.lineb@garment.local',
      full_name: 'Budi Santoso',
      role: 'supervisor',
      active: false,
    });

    expect(requests[0]?.path).toBe('/settings/users/7/');
    expect(requests[0]?.method).toBe('PUT');
    expect(requests[0]?.body).not.toHaveProperty('password');
    expect(requests[0]?.body).toMatchObject({ is_active: false, role_code: 'SUPERVISOR' });
  });

  it('deleteUser = DELETE (soft delete) tanpa body', async () => {
    const { client, requests } = stubClient(() => ({}));

    await expect(deleteUser(client, 7)).resolves.toBeUndefined();
    expect(requests[0]).toEqual({ path: '/settings/users/7/', method: 'DELETE', body: undefined });
  });
});

describe('F5.4.CLOSE — B27 settings/roles', () => {
  it('parse baris role + toUiRole (kode tak dikenal → null)', () => {
    const row = readRoleRow(ROLE_PAGE.rows[0]);

    expect(readRoleRow(null)).toBeNull();
    expect(row?.label).toBe('Operator');
    expect(toUiRole('operator')).toBe('operator');
    expect(toUiRole('OWNER')).toBe('owner');
    expect(toUiRole('SABLON_LEAD')).toBeNull();
    expect(SETTINGS_ROLES_PATH).toBe('/settings/roles/');
  });

  it('fetchRoleRows → baris mentah (label + user_count)', async () => {
    const { client, gets } = stubClient(() => ROLE_PAGE);
    const page = await fetchRoleRows(client, { limit: 10 });

    expect(gets).toEqual(['/settings/roles/?limit=10']);
    expect(page.total_count).toBe(2);
    expect(page.rows[1]?.user_count).toBe(1);
  });

  it('fetchRoles → union UI lowercase; kode di luar kontrak dilewati', async () => {
    const { client, gets } = stubClient(() => ROLE_PAGE);
    const roles = await fetchRoles(client);

    expect(gets).toEqual(['/settings/roles/']);
    expect(roles).toEqual(['operator']);
  });
});

describe('F5.4.CLOSE — B28 settings/devices', () => {
  it('toDeviceProfile: code ← device_type', () => {
    const row = readDeviceProfileRow(DEVICE_PAGE.rows[0]);

    expect(row?.binding_count).toBe(2);
    expect(row?.config).toEqual({ scan: true });
    expect(toDeviceProfile(row!)).toEqual({
      id: 3,
      code: 'KIOSK_TABLET',
      label: 'Kiosk Tablet',
      description: 'tablet lantai',
    });
  });

  it('buildSettingsDevicesPath: device_type/wc_code/active', () => {
    expect(
      buildSettingsDevicesPath({ deviceType: 'KIOSK_TABLET', wcCode: 'WC-01', active: true }),
    ).toBe('/settings/devices/?device_type=KIOSK_TABLET&wc_code=WC-01&active=true');
    expect(SETTINGS_DEVICES_PATH).toBe('/settings/devices/');
  });

  it('fetchDeviceProfiles + fetchDeviceProfileRows (amplop ListPage)', async () => {
    const { client, gets } = stubClient(() => DEVICE_PAGE);
    const profiles = await fetchDeviceProfiles(client);
    const page = await fetchDeviceProfileRows(client);

    expect(gets).toEqual(['/settings/devices/', '/settings/devices/']);
    expect(profiles[0]?.code).toBe('KIOSK_TABLET');
    expect(page.rows).toHaveLength(1);
  });
});

describe('F5.4.CLOSE — B29 HITL queue & keputusan', () => {
  it('readHitlRow + toHitlApproval (requester/action/status dari state)', () => {
    const row = readHitlRow(hitlRow('PENDING', 2, '2026-10-10T08:00:00+07:00'));

    expect(readHitlRow(1)).toBeNull();
    expect(row?.priority).toBe('HIGH');
    expect(HITL_QUEUE_PATH).toBe('/ai/hitl/queue/');

    const pending = toHitlApproval(row!);

    expect(pending).toMatchObject({
      id: 2,
      requester: 'ai.agent',
      action: 'SCRAP_BUNDLE',
      resource: 'bundle',
      resource_id: 'BDL-1',
      status: 'pending',
      created_at: '2026-10-10T08:00:00+07:00',
    });
    expect(toHitlApproval({ ...row!, state: 'EXPIRED' }).status).toBe('expired');
    expect(toHitlApproval({ ...row!, requested_by: null }).requester).toBe('system');
  });

  it('buildHitlQueuePath + buildHitlDecisionPath', () => {
    expect(buildHitlQueuePath()).toBe('/ai/hitl/queue/');
    expect(buildHitlQueuePath({ state: 'APPROVED', priority: 'high', limit: 10 })).toBe(
      '/ai/hitl/queue/?state=APPROVED&priority=high&limit=10',
    );
    expect(buildHitlDecisionPath(5, 'approve')).toBe('/ai/hitl/5/approve/');
    expect(buildHitlDecisionPath(5, 'reject')).toBe('/ai/hitl/5/reject/');
  });

  it('fetchPendingApprovals hanya GET state=PENDING', async () => {
    const { client, gets } = stubClient(hitlHandler);
    const rows = await fetchPendingApprovals(client);

    expect(gets).toEqual(['/ai/hitl/queue/?state=PENDING']);
    expect(rows[0]?.status).toBe('pending');
  });

  it('fetchAllApprovals = 4 GET (PENDING/APPROVED/REJECTED/EXPIRED), urut terbaru dulu', async () => {
    const { client, gets } = stubClient(hitlHandler);
    const rows = await fetchAllApprovals(client);

    expect(gets).toEqual([
      '/ai/hitl/queue/?state=PENDING',
      '/ai/hitl/queue/?state=APPROVED',
      '/ai/hitl/queue/?state=REJECTED',
      '/ai/hitl/queue/?state=EXPIRED',
    ]);
    expect(rows.map((row) => row.status)).toEqual(['approved', 'pending', 'expired']);
  });

  it('decideApproval: approve body {} ; reject wajib note (default bila kosong)', async () => {
    const { client, posts } = stubClient((path) =>
      path.includes('/approve/')
        ? hitlRow('APPROVED', 5, '2026-10-10T11:00:00+07:00')
        : hitlRow('REJECTED', 5, '2026-10-10T11:00:00+07:00'),
    );

    const approved = await decideApproval(client, 5, 'approve');

    expect(posts[0]).toEqual({ path: '/ai/hitl/5/approve/', body: {} });
    expect(approved.status).toBe('approved');

    await decideApproval(client, 5, 'reject');
    expect(posts[1]).toEqual({ path: '/ai/hitl/5/reject/', body: { note: DEFAULT_REJECT_NOTE } });

    await decideApproval(client, 5, 'reject', '  alasan audit  ');
    expect(posts[2]?.body).toEqual({ note: 'alasan audit' });
  });
});

describe('F5.4.CLOSE — B30 inventory reporting', () => {
  it('readLocationStockReport: rows + total_locations + generated_at', () => {
    const report = readLocationStockReport(REPORT_BODY);

    expect(readLocationStockReport({ rows: {} })).toBeNull();
    expect(report?.total_locations).toBe(2);
    expect(report?.rows[0]?.location_code).toBe('WH/WIP');
    expect(report?.rows[0]?.total_qty).toBe(120);
    expect(report?.rows[1]?.last_updated).toBeNull();
    expect(report?.generated_at).toBe('2026-10-10T09:05:00+07:00');
  });

  it('buildInventoryReportingPath + fetchLocationStock', async () => {
    expect(buildInventoryReportingPath()).toBe(INVENTORY_REPORTING_PATH);
    // `URLSearchParams` meng-encode '/' → '%2F' (backend Django tetap membacanya
    // sebagai 'WH/WIP' setelah decode query string).
    expect(buildInventoryReportingPath({ locationCode: 'WH/WIP' })).toBe(
      '/inventory/reporting/?location_code=WH%2FWIP',
    );

    const { client, gets } = stubClient(() => REPORT_BODY);
    const report = await fetchLocationStock(client, { locationCode: 'WH/WIP' });

    expect(gets).toEqual(['/inventory/reporting/?location_code=WH%2FWIP']);
    expect(report.rows).toHaveLength(2);
  });
});
