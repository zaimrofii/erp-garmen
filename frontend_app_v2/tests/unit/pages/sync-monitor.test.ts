import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * F15 — halaman Sync Monitor (`/settings/sync`, revive F10).
 *
 * Tes berbasis sumber: route + guard admin, adapter `@/api/syncMonitor`, reuse `DenseTable`,
 * filter `stage`/`status` (case-insensitive di adapter), guard `limit`, Toast/trigger,
 * dan item nav Settings.
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function read(relative: string): string {
  return readFileSync(path.join(ROOT, relative), 'utf8');
}

const PAGE = 'src/pages/settings/SyncMonitorPage.tsx';

describe('F15/B.6 — route settings/sync', () => {
  const app = read('src/App.tsx');

  it('route /settings/sync + guard SETTINGS_ROLES (admin)', () => {
    expect(app).toContain('path="/settings/sync"');
    expect(app).toContain('<SyncMonitorPage />');
    expect(app).toMatch(/path="\/settings\/sync"[\s\S]{0,180}SETTINGS_ROLES/);
  });
});

describe('F15/B.5 — halaman', () => {
  const page = read(PAGE);

  it('memuat GET /sync/records/ lewat adapter', () => {
    expect(page).toContain("from '@/api/syncMonitor'");
    expect(page).toContain('getSyncRecords(apiClient, { stage, status, limit })');
    expect(page).toContain("queryKey: ['sync-records', stage, status, limit]");
    expect(page).not.toContain("from '@/api/real/syncMonitor'");
  });

  it('DenseTable + kolom kontrak monitoring (id/resource/stage/status/attempts/error)', () => {
    expect(page).toContain("from '@/components/molecules/DenseTable'");
    expect(page).toContain('<DenseTable');
    expect(page).not.toContain('<table');

    for (const key of ['id', 'resource', 'resource_id', 'stage', 'status', 'attempts', 'last_error', 'erp_id', 'sent_at', 'created_at']) {
      expect(page, key).toContain(`key: '${key}'`);
    }
  });

  it('filter stage + status dari enum backend, tone Badge OKLCH', () => {
    expect(page).toContain('SYNC_STAGES');
    expect(page).toContain('SYNC_STATUSES');
    expect(page).toContain('syncStatusTone(row.status)');
    expect(page).toContain('syncStatusLabel(row.status)');
    expect(page).not.toMatch(/#[0-9a-f]{3,8}\b/i);
  });

  it('guard limit 1..200 + feedback Toast/trigger + retry', () => {
    expect(page).toContain('parseIntParam(limitInput, 1, SYNC_LIMIT_MAX)');
    expect(page).toContain("trigger('success')");
    expect(page).toContain("trigger('error')");
    expect(page).toContain('<Toast');
    expect(page).toContain('Gagal memuat SyncRecord (perlu login?).');
  });
});

describe('F15/B.7 — nav Settings += Sync Monitor', () => {
  it('item Sync Monitor terpasang di nav-config (menu-config turunan)', () => {
    expect(read('src/app/nav-config.ts')).toContain(
      "{ label: 'Sync Monitor', path: '/settings/sync' }",
    );
    expect(read('src/app/menu-config.ts')).toContain('NAV_APPS');
  });
});
