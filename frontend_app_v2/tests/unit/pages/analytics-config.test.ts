import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

/** Sprint C.3 — AnalyticsConfigPage: readiness, enable/disable, filter, terjemahan. */

const ROOT = path.resolve(import.meta.dirname, '../../..');
const SOURCE = readFileSync(
  path.join(ROOT, 'src/pages/settings/AnalyticsConfigPage.tsx'),
  'utf8',
);

describe('AnalyticsConfigPage (C.3)', () => {
  it('fetch config + readiness', () => {
    expect(SOURCE).toContain('fetchAnalyticsConfig');
    expect(SOURCE).toContain('fetchAnalyticsReadiness');
  });

  it('menerjemahkan disabled_reason not_yet_enabled', () => {
    expect(SOURCE).toContain('not_yet_enabled');
    expect(SOURCE).toContain('Belum pernah diaktifkan');
    expect(SOURCE).toContain('analytics_disabled');
  });

  it('hard blockers dirender terpisah (merah)', () => {
    expect(SOURCE).toContain('data-analytics-blockers="hard"');
    expect(SOURCE).toContain('text-accent-coral');
  });

  it('soft blockers dirender terpisah (kuning)', () => {
    expect(SOURCE).toContain('data-analytics-blockers="soft"');
    expect(SOURCE).toContain('text-accent-amber');
  });

  it('tombol Aktifkan disabled kalau ready=false', () => {
    expect(SOURCE).toContain('disabled={!canEnable}');
    expect(SOURCE).toContain('readiness?.ready === true');
  });

  it('tooltip menyebut blocker pertama', () => {
    expect(SOURCE).toContain('Kesiapan data belum terpenuhi');
    expect(SOURCE).toContain('firstBlocker');
  });

  it('modal konfirmasi enable menampilkan peringatan soft blocker', () => {
    expect(SOURCE).toContain('data-analytics-confirm="enable"');
    expect(SOURCE).toContain('Data siap? Analitik akan aktif. Yakin?');
    expect(SOURCE).toContain('Peringatan:');
  });

  it('disable wajib alasan (tombol disabled saat kosong)', () => {
    expect(SOURCE).toContain('data-analytics-confirm="disable"');
    expect(SOURCE).toContain('reason.trim().length === 0');
  });

  it('Simpan Filter memakai updateAnalyticsConfig (PUT)', () => {
    expect(SOURCE).toContain('Simpan Filter');
    expect(SOURCE).toContain('updateAnalyticsConfig');
  });

  it('menampilkan status enable/disable + audit jejak', () => {
    expect(SOURCE).toContain('Aktif sejak');
    expect(SOURCE).toContain('config?.enabled_by');
  });
});
