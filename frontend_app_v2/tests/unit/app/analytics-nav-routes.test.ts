import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { NAV_APPS, findAppByPath, LEGACY_APP_PATHS } from '@/app/nav-config';
import { isAppAllowed, ROLE_APPS } from '@/app/useRole';

/** Sprint C.3 — nav + role + route untuk app analytics. */

const ROOT = path.resolve(import.meta.dirname, '../../..');
const APP = readFileSync(path.join(ROOT, 'src/App.tsx'), 'utf8');

describe('Analytics nav & routes (C.3)', () => {
  it('NAV_APPS punya app analytics (/analytics, label Analitik)', () => {
    const app = NAV_APPS.find((item) => item.id === 'analytics');

    expect(app).toBeDefined();
    expect(app?.path).toBe('/analytics');
    expect(app?.label).toBe('Analitik');
    expect(app?.topbar[0]?.path).toBe('/analytics');
  });

  it('item Settings Analitik ada SETELAH Log Audit Sistem', () => {
    const settings = NAV_APPS.find((item) => item.id === 'settings');
    const paths = settings?.topbar.map((item) => item.path) ?? [];

    expect(paths).toContain('/settings/analytics');
    expect(paths.indexOf('/settings/analytics')).toBeGreaterThan(
      paths.indexOf('/settings/audit-log'),
    );
  });

  it('ROLE_APPS: supervisor/owner/admin boleh analytics', () => {
    for (const role of ['supervisor', 'owner', 'admin'] as const) {
      expect(ROLE_APPS[role]).toContain('analytics');
      expect(isAppAllowed(role, 'analytics')).toBe(true);
    }
  });

  it('operator TIDAK boleh analytics', () => {
    expect(isAppAllowed('operator', 'analytics')).toBe(false);
  });

  it('route /analytics + /analytics/metrics/:metricId memakai ANALYTICS_ROLES', () => {
    expect(APP).toContain('path="/analytics"');
    expect(APP).toContain('path="/analytics/metrics/:metricId"');
    expect(APP).toContain('const ANALYTICS_ROLES: Role[] = ["supervisor", "owner", "admin"]');
    expect(APP).toContain('roles={ANALYTICS_ROLES}');
  });

  it('route /settings/analytics memakai SETTINGS_ROLES', () => {
    expect(APP).toContain('path="/settings/analytics"');
    expect(APP).toContain('roles={SETTINGS_ROLES}');
  });

  it('LEGACY_APP_PATHS /analytics → app analytics', () => {
    expect(LEGACY_APP_PATHS).toContainEqual({ prefix: '/analytics', appId: 'analytics' });
    expect(findAppByPath('/analytics/metrics/garment.scrap_rate')?.id).toBe('analytics');
  });
});
