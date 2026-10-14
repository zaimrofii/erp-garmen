import { describe, expect, it } from 'vitest';
import { fetchPendingApprovals, HITL_QUEUE_PATH } from '@/api/real/hitl';
import { fetchLocationStock } from '@/api/real/inventoryReporting';
import { fetchDeviceProfiles } from '@/api/real/settingsDevices';
import { fetchRoles } from '@/api/real/settingsRoles';
import { fetchUsers } from '@/api/real/settingsUsers';
import { createApiClient } from '@/integrations/api-client';

/**
 * F5.4.CLOSE LIVE — 5 endpoint terakhir (B26–B30) vs backend Django yang sedang jalan.
 *
 * Dijalankan HANYA kalau `MES_LIVE=1` (default: skip, supaya `bun run test` hijau tanpa backend):
 *
 *   MES_LIVE=1 ~/.bun/bin/bun --bun run test tests/live
 *
 * Catatan: `GET /settings/users/` butuh sesi admin/owner — tanpa sesi backend membalas
 * 403 (bukti endpoint hidup & permission jalan), jadi 403 diterima sebagai hasil valid.
 */

const LIVE = process.env['MES_LIVE'] === '1';
const BASE_URL = process.env['MES_API_BASE_URL'] ?? 'http://localhost:8000/api/v1';

describe.skipIf(!LIVE)('F5.4.CLOSE LIVE — B26–B30', () => {
  const client = createApiClient({ baseUrl: BASE_URL });

  it('B30 GET /inventory/reporting/ → baris lokasi + total_locations + generated_at', async () => {
    const report = await fetchLocationStock(client);

    expect(Array.isArray(report.rows)).toBe(true);
    expect(report.total_locations).toBe(report.rows.length);
    expect(typeof report.generated_at).toBe('string');
    expect(report.generated_at.length).toBeGreaterThan(0);

    for (const row of report.rows) {
      expect(row.location_code.length).toBeGreaterThan(0);
      expect(row.total_qty).toBeGreaterThanOrEqual(0);
      expect(row.product_count).toBeGreaterThanOrEqual(0);
    }
  });

  it('B29 GET /ai/hitl/queue/ → ListPage (state default PENDING)', async () => {
    const rows = await fetchPendingApprovals(client);

    expect(Array.isArray(rows)).toBe(true);
    for (const row of rows) {
      expect(row.status).toBe('pending');
      expect(row.action.length).toBeGreaterThan(0);
    }
    expect(HITL_QUEUE_PATH).toBe('/ai/hitl/queue/');
  });

  it('B27 GET /settings/roles/ → role UI lowercase (kode backend UPPERCASE)', async () => {
    const roles = await fetchRoles(client);

    expect(Array.isArray(roles)).toBe(true);
    for (const role of roles) {
      expect(role).toBe(role.toLowerCase());
    }
  });

  it('B28 GET /settings/devices/ → katalog profil (code ← device_type)', async () => {
    const profiles = await fetchDeviceProfiles(client);

    expect(Array.isArray(profiles)).toBe(true);
    for (const profile of profiles) {
      expect(profile.code.length).toBeGreaterThan(0);
      expect(typeof profile.label).toBe('string');
    }
  });

  it('B26 GET /settings/users/ → daftar user (admin) atau 403 (tanpa sesi admin)', async () => {
    try {
      const users = await fetchUsers(client, { limit: 1 });

      expect(Array.isArray(users)).toBe(true);
    } catch (error) {
      // Tanpa sesi admin/owner backend membalas 403 → tetap membuktikan endpoint hidup.
      expect(String(error)).toMatch(/403|ADMIN|OWNER|admin|owner|role/i);
    }
  });
});
