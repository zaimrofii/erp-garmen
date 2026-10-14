import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * H4.5 - halaman laporan laba-rugi (`/reports/pnl`).
 *
 * Rendering penuh butuh Router + QueryClient + provider runtime (di luar gaya tes tanpa DOM),
 * jadi tes ini memaku wiring sumber: route ber-guard REPORTS_ROLES, item nav baru, filter
 * server (period/group_by), KPI (revenue/HPP/laba kotor/margin/opex/laba bersih/margin),
 * warning `opex_source = unavailable` + `rows_with_missing_cost`, escape hatch `?_nocache=1`,
 * dan tombol Export disabled.
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function read(relative: string): string {
  return readFileSync(path.join(ROOT, relative), 'utf8');
}

const PAGE = 'src/pages/reports/PnlReportPage.tsx';

describe('H4.5 - route & nav', () => {
  const app = read('src/App.tsx');
  const nav = read('src/app/nav-config.ts');

  it('route /reports/pnl + guard role REPORTS', () => {
    expect(app).toContain('path="/reports/pnl"');
    expect(app).toContain('<PnlReportPage />');
    expect(app).toContain("import('@/pages/reports/PnlReportPage')");
    expect(app).toContain('roles={REPORTS_ROLES}');
  });

  it('topbar Reports menambah item Laba-Rugi', () => {
    expect(nav).toContain("{ label: 'Laba-Rugi', path: '/reports/pnl' }");
  });
});

describe('H4.5 - halaman', () => {
  const page = read(PAGE);

  it('query memakai adapter fetchPnlReport + filter server', () => {
    expect(page).toContain('fetchPnlReport(client, {');
    expect(page).toContain("from '@/api/reports'");
    expect(page).toContain("'reports-pnl',");
    expect(page).toContain('period: period ===');
    expect(page).toContain('groupBy,');
    expect(page).toContain('nocache: forceRefresh > 0');
    expect(page).toContain('setForceRefresh((value) => value + 1)');
  });

  it('group_by dari kontrak backend (period/quarter)', () => {
    expect(page).toContain("useState<PnlGroupBy>('period')");
    expect(page).toContain('PNL_GROUP_BY_VALUES');
    expect(page).toContain("quarter: 'Kuartal'");
  });

  it('KPI + DenseTable (bukan tabel paralel) + kolom laba-rugi', () => {
    expect(page).toContain("from '@/components/molecules/KpiCard'");
    expect(page).toContain('<KpiCard');
    expect(page).toContain("from '@/components/molecules/DenseTable'");
    expect(page).toContain('<DenseTable');
    expect(page).not.toContain('<table');
    expect(page).toContain("label: 'Revenue (IDR)'");
    expect(page).toContain("label: 'Laba Bersih'");
    expect(page).toContain('formatOpex(');
    expect(page).toContain("'n/a'");
  });

  it('warning opex unavailable + rows_with_missing_cost tampil', () => {
    expect(page).toContain("opex_source === 'unavailable'");
    expect(page).toContain('rows_with_missing_cost');
    expect(page).toContain('missing_cost_reason');
    expect(page).toContain("'(produk belum sinkron)'");
  });

  it('Export AKTIF (H4.8: ExportButton -> POST /export/pnl/) + read-only', () => {
    expect(page).toContain("from '@/components/molecules/ExportButton'");
    expect(page).toContain('<ExportButton');
    expect(page).toContain('report="pnl"');
    expect(page).toContain('filters={');
    expect(page).toContain('H4.8');
    expect(page).not.toContain('client.post');
    expect(page).not.toContain('client.request');
    expect(page).not.toMatch(/\bmethod: 'POST'/);
  });
});
