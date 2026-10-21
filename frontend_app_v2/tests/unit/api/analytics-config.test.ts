import { describe, expect, it, vi } from 'vitest';
import {
  disableAnalytics,
  enableAnalytics,
  fetchAnalyticsConfig,
  fetchAnalyticsReadiness,
  updateAnalyticsConfig,
} from '@/api/analyticsConfig';
import { MODE } from '@/api/_adapter';
import type { ApiClient } from '@/integrations/api-client';

/** Sprint C.2 — toggle analytics REAL: config, readiness, enable/disable. */

const CONFIG = {
  enabled: false,
  enabled_domains: ['garment'],
  enabled_metrics: [],
  data_readiness_acknowledged_at: null,
  enabled_by: null,
  enabled_at: null,
  disabled_reason: 'not_yet_enabled',
  historical_data_available: false,
  updated_at: '2026-10-18T05:00:00+07:00',
};

const READINESS = {
  ready: true,
  blockers: [],
  soft_blockers: ['no_active_bundles'],
  checked_at: '2026-10-18T05:10:00+07:00',
  thresholds: { sync_records_failed_recent_7d: 0 },
  counts: { active_bundles: 0, products_without_odoo_id_total: 3 },
};

const ENABLE_BODY = {
  ...CONFIG,
  enabled: true,
  disabled_reason: '',
  readiness: READINESS,
  warnings: [
    { code: 'no_active_bundles', message: 'Tidak ada bundle aktif; analytics akan kosong.' },
  ],
};

function clientStub(overrides: Partial<Record<'get' | 'post' | 'request', unknown>>): ApiClient {
  return overrides as unknown as ApiClient;
}

describe('analytics config adapter (C.2)', () => {
  it('fetchAnalyticsConfig parse semua field', async () => {
    const get = vi.fn(async () => ({ ok: true, status: 200, data: CONFIG }));

    const config = await fetchAnalyticsConfig(clientStub({ get }));

    expect(config.enabled).toBe(false);
    expect(config.enabled_domains).toEqual(['garment']);
    expect(config.disabled_reason).toBe('not_yet_enabled');
    expect(get).toHaveBeenCalledWith('/settings/analytics/');
  });

  it('updateAnalyticsConfig PUT body benar', async () => {
    const request = vi.fn(async () => ({ ok: true, status: 200, data: CONFIG }));

    await updateAnalyticsConfig(clientStub({ request }), {
      enabled_domains: ['garment'],
      enabled_metrics: ['garment.scrap_rate'],
    });

    expect(request).toHaveBeenCalledWith('/settings/analytics/', {
      method: 'PUT',
      body: { enabled_domains: ['garment'], enabled_metrics: ['garment.scrap_rate'] },
    });
  });

  it('updateAnalyticsConfig parse respons', async () => {
    const request = vi.fn(async () => ({
      ok: true,
      status: 200,
      data: { ...CONFIG, enabled_domains: ['garment'] },
    }));

    const config = await updateAnalyticsConfig(clientStub({ request }), {
      enabled_domains: ['garment'],
      enabled_metrics: [],
    });

    expect(config.enabled_domains).toEqual(['garment']);
  });

  it('enableAnalytics sukses → EnableResponse (readiness + warnings)', async () => {
    const post = vi.fn(async () => ({ ok: true, status: 200, data: ENABLE_BODY }));

    const result = await enableAnalytics(clientStub({ post }), {
      enabled_domains: ['garment'],
    });

    expect(result.enabled).toBe(true);
    expect(result.readiness.soft_blockers).toEqual(['no_active_bundles']);
    expect(result.warnings[0]?.code).toBe('no_active_bundles');
    expect(post).toHaveBeenCalledWith('/settings/analytics/enable/', {
      enabled_domains: ['garment'],
      enabled_metrics: [],
    });
  });

  it('enableAnalytics gagal readiness → throw', async () => {
    const post = vi.fn(async () => ({
      ok: false,
      status: 400,
      error: { message: 'Kesiapan data belum terpenuhi' },
    }));

    await expect(enableAnalytics(clientStub({ post }))).rejects.toThrow(
      'Kesiapan data belum terpenuhi',
    );
  });

  it('disableAnalytics reason kosong → throw tanpa memanggil client', async () => {
    const post = vi.fn();

    await expect(disableAnalytics(clientStub({ post }), '   ')).rejects.toThrow(
      'Alasan disable wajib diisi',
    );
    expect(post).not.toHaveBeenCalled();
  });

  it('disableAnalytics reason valid → POST body {reason}', async () => {
    const post = vi.fn(async () => ({
      ok: true,
      status: 200,
      data: { ...CONFIG, disabled_reason: 'analytics_disabled' },
    }));

    const config = await disableAnalytics(clientStub({ post }), '  data belum lengkap  ');

    expect(post).toHaveBeenCalledWith('/settings/analytics/disable/', {
      reason: 'data belum lengkap',
    });
    expect(config.disabled_reason).toBe('analytics_disabled');
  });

  it('fetchAnalyticsReadiness: blockers & soft_blockers terpisah', async () => {
    const get = vi.fn(async () => ({ ok: true, status: 200, data: READINESS }));

    const readiness = await fetchAnalyticsReadiness(clientStub({ get }));

    expect(readiness.blockers).toEqual([]);
    expect(readiness.soft_blockers).toEqual(['no_active_bundles']);
    expect(readiness.counts['active_bundles']).toBe(0);
    expect(get).toHaveBeenCalledWith('/analytics/readiness/');
  });

  it('readiness ready=false dengan hard blockers', async () => {
    const get = vi.fn(async () => ({
      ok: true,
      status: 200,
      data: {
        ...READINESS,
        ready: false,
        blockers: ['sync_records_failed_recent_7d:2'],
      },
    }));

    const readiness = await fetchAnalyticsReadiness(clientStub({ get }));

    expect(readiness.ready).toBe(false);
    expect(readiness.blockers).toHaveLength(1);
  });

  it('MODE analyticsConfig/analyticsReadiness = real', () => {
    expect(MODE['analyticsConfig']).toBe('real');
    expect(MODE['analyticsReadiness']).toBe('real');
  });
});
