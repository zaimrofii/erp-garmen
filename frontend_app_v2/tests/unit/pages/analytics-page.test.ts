import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

/** Sprint C.3 — AnalyticsPage: read-only, banner OFF, nocache, DenseTable. */

const ROOT = path.resolve(import.meta.dirname, '../../..');
const SOURCE = readFileSync(path.join(ROOT, 'src/pages/analytics/AnalyticsPage.tsx'), 'utf8');

describe('AnalyticsPage (C.3)', () => {
  it('memakai adapter real fetchAnalyticsMetrics domain garment', () => {
    expect(SOURCE).toContain('fetchAnalyticsMetrics');
    expect(SOURCE).toContain("const DOMAIN = 'garment'");
  });

  it('OFF → banner + link ke /settings/analytics', () => {
    expect(SOURCE).toContain('data-analytics-disabled="true"');
    expect(SOURCE).toContain('Analitik dinonaktifkan');
    expect(SOURCE).toContain('to="/settings/analytics"');
  });

  it('menampilkan pesan historis sesuai historical_data_available', () => {
    expect(SOURCE).toContain('historical_data_available');
    expect(SOURCE).toContain('Snapshot historis masih tersimpan');
    expect(SOURCE).toContain('Belum ada data historis tersimpan');
  });

  it('tabel memakai DenseTable (bukan tabel paralel)', () => {
    expect(SOURCE).toContain('DenseTable');
    expect(SOURCE).not.toContain('<table');
  });

  it('Muat Ulang memakai _nocache', () => {
    expect(SOURCE).toContain('setNocache(true)');
    expect(SOURCE).toContain('{ nocache }');
  });

  it('setiap baris punya tautan Lihat Detail ke /analytics/metrics/', () => {
    expect(SOURCE).toContain('Lihat Detail');
    expect(SOURCE).toContain('/analytics/metrics/');
  });

  it('read-only: tidak memakai useMutation', () => {
    expect(SOURCE).not.toContain('useMutation');
  });
});
