import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

/** Sprint C.3 — AnalyticsMetricDetailPage: metadata, filter, banner OFF, export disabled. */

const ROOT = path.resolve(import.meta.dirname, '../../..');
const SOURCE = readFileSync(
  path.join(ROOT, 'src/pages/analytics/AnalyticsMetricDetailPage.tsx'),
  'utf8',
);

describe('AnalyticsMetricDetailPage (C.3)', () => {
  it('memakai fetchAnalyticsMetric dengan metricId route', () => {
    expect(SOURCE).toContain('fetchAnalyticsMetric(client, metricId');
    expect(SOURCE).toContain('useParams');
  });

  it('header menampilkan granularity + formula_version', () => {
    expect(SOURCE).toContain('metadata.granularity');
    expect(SOURCE).toContain('metadata.formula_version');
  });

  it('OFF → banner yang sama + tautan settings', () => {
    expect(SOURCE).toContain('data-analytics-disabled="true"');
    expect(SOURCE).toContain('to="/settings/analytics"');
  });

  it('filter period & group_by dikirim ke API', () => {
    expect(SOURCE).toContain('period: period || null');
    expect(SOURCE).toContain('groupBy,');
    expect(SOURCE).toContain("value: 'work_center'");
  });

  it('tombol Export DISABLED dengan alasan sprint berikutnya', () => {
    expect(SOURCE).toContain('disabled');
    expect(SOURCE).toContain('Akan tersedia di sprint berikutnya');
  });

  it('OFF + historis menampilkan catatan endpoint snapshot menyusul', () => {
    expect(SOURCE).toContain('Tab Data Historis');
    expect(SOURCE).toContain('backlog Sprint C/D');
  });

  it('tabel memakai DenseTable', () => {
    expect(SOURCE).toContain('DenseTable');
    expect(SOURCE).not.toContain('<table');
  });
});
