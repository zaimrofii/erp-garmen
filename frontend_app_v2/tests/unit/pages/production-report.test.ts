import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * H4.6 - halaman laporan produksi (`/reports/production`).
 *
 * Rendering penuh butuh Router + QueryClient + provider runtime (di luar gaya tes tanpa DOM),
 * jadi tes ini memaku wiring sumber: route ber-guard REPORTS_ROLES, item nav baru, filter
 * server (period/group_by/work_center/line), KPI (output/scrap/eff/OTD/rework), reuse
 * `DenseTable`/`KpiCard`, catatan basis waktu, escape hatch `?_nocache=1`, Export disabled.
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function read(relative: string): string {
  return readFileSync(path.join(ROOT, relative), 'utf8');
}

const PAGE = 'src/pages/reports/ProductionReportPage.tsx';

describe('H4.6 - route & nav', () => {
  const app = read('src/App.tsx');
  const nav = read('src/app/nav-config.ts');

  it('route /reports/production + guard role REPORTS', () => {
    expect(app).toContain('path="/reports/production"');
    expect(app).toContain('<ProductionReportPage />');
    expect(app).toContain("import('@/pages/reports/ProductionReportPage')");
    expect(app).toContain('roles={REPORTS_ROLES}');
  });

  it('topbar Reports menambah item Produksi', () => {
    expect(nav).toContain("{ label: 'Produksi', path: '/reports/production' }");
  });
});

describe('H4.6 - halaman', () => {
  const page = read(PAGE);

  it('query memakai adapter fetchProductionReport + filter server', () => {
    expect(page).toContain('fetchProductionReport(client, {');
    expect(page).toContain("from '@/api/reports'");
    expect(page).toContain("'reports-production',");
    expect(page).toContain('period: period ===');
    expect(page).toContain('groupBy,');
    expect(page).toContain('workCenterId: workCenterId === ');
    expect(page).toContain('lineId: lineId === ');
    expect(page).toContain('nocache: forceRefresh > 0');
    expect(page).toContain('setForceRefresh((value) => value + 1)');
  });

  it('group_by dari kontrak backend + dropdown master MES (WC & line)', () => {
    expect(page).toContain("useState<ProductionGroupBy>('period')");
    expect(page).toContain('PRODUCTION_GROUP_BY_VALUES');
    expect(page).toContain('fetchWorkCenters(client, { limit: 200, active: true })');
    expect(page).toContain('fetchProductionLines(client, { limit: 200, active: true })');
    expect(page).toContain("label: `${row.code} - ${row.name}`");
  });

  it('KPI + DenseTable (bukan tabel paralel) + kolom output/scrap/efisiensi/OTD', () => {
    expect(page).toContain("from '@/components/molecules/KpiCard'");
    expect(page).toContain('<KpiCard');
    expect(page).toContain("from '@/components/molecules/DenseTable'");
    expect(page).toContain('<DenseTable');
    expect(page).not.toContain('<table');
    expect(page).toContain("label: 'Output (pcs)'");
    expect(page).toContain("label: 'Efisiensi %'");
    expect(page).toContain("label: 'OTD (order-level)'");
    expect(page).toContain('total_rework_pcs');
    expect(page).toContain('total_end_loss_pcs');
    expect(page).toContain('formatOtd(');
    expect(page).toContain("'-'");
  });

  it('catatan basis waktu per metrik tampil (transparansi H4.6)', () => {
    expect(page).toContain('basis?.output');
    expect(page).toContain('basis?.scrap');
    expect(page).toContain('dari cache backend');
  });

  it('Export AKTIF (H4.8: ExportButton -> POST /export/production/) + read-only', () => {
    expect(page).toContain("from '@/components/molecules/ExportButton'");
    expect(page).toContain('<ExportButton');
    expect(page).toContain('report="production"');
    expect(page).toContain('filters={');
    expect(page).toContain('H4.8');
    expect(page).not.toContain('client.post');
    expect(page).not.toContain('client.request');
    expect(page).not.toMatch(/\bmethod: 'POST'/);
  });
});
