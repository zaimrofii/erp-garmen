import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * H4.4 - halaman laporan HPP/laba kotor (`/reports/cogs`).
 *
 * Rendering penuh butuh Router + QueryClient + provider runtime (di luar gaya tes tanpa DOM),
 * jadi tes ini memaku wiring sumber: route ber-guard REPORTS_ROLES, item nav baru, filter
 * server (period/customer/produk/order_type/group_by), reuse `DenseTable`/`KpiCard`,
 * warning `rows_with_missing_cost` + reason, escape hatch `?_nocache=1`, Export disabled.
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function read(relative: string): string {
  return readFileSync(path.join(ROOT, relative), 'utf8');
}

const PAGE = 'src/pages/reports/CogsReportPage.tsx';

describe('H4.4 - route & nav', () => {
  const app = read('src/App.tsx');
  const nav = read('src/app/nav-config.ts');

  it('route /reports/cogs + guard role REPORTS', () => {
    expect(app).toContain('path="/reports/cogs"');
    expect(app).toContain('<CogsReportPage />');
    expect(app).toContain("import('@/pages/reports/CogsReportPage')");
    expect(app).toContain('roles={REPORTS_ROLES}');
  });

  it('topbar Reports menambah item HPP (COGS)', () => {
    expect(nav).toContain("{ label: 'HPP (COGS)', path: '/reports/cogs' }");
  });
});

describe('H4.4 - halaman', () => {
  const page = read(PAGE);

  it('query memakai adapter fetchCogsReport + filter server', () => {
    expect(page).toContain('fetchCogsReport(client, {');
    expect(page).toContain("from '@/api/reports'");
    expect(page).toContain("'reports-cogs',");
    expect(page).toContain('period: period ===');
    expect(page).toContain('customerId: customerId === ');
    expect(page).toContain('productId: productId === ');
    expect(page).toContain('orderType: orderType === ');
    expect(page).toContain('COGS_ORDER_TYPES');
    expect(page).toContain('COGS_GROUP_BY_VALUES');
  });

  it('group_by dari kontrak backend + dropdown master MES', () => {
    expect(page).toContain("useState<CogsGroupBy>('period')");
    expect(page).toContain('fetchPartners(client, { limit: 200, is_customer: true })');
    expect(page).toContain('fetchProducts(client, { limit: 200, active: true })');
    expect(page).toContain("label: `${row.code} - ${row.name}`");
  });

  it('escape hatch `?_nocache=1` lewat tombol Muat Ulang', () => {
    expect(page).toContain('nocache: forceRefresh > 0');
    expect(page).toContain('setForceRefresh((value) => value + 1)');
  });

  it('KPI + DenseTable (bukan tabel paralel) + kolom omzet/HPP/margin', () => {
    expect(page).toContain("from '@/components/molecules/KpiCard'");
    expect(page).toContain('<KpiCard');
    expect(page).toContain("from '@/components/molecules/DenseTable'");
    expect(page).toContain('<DenseTable');
    expect(page).not.toContain('<table');
    expect(page).toContain("label: 'Omzet (IDR)'");
    expect(page).toContain("label: 'HPP (IDR)'");
    expect(page).toContain("label: 'Margin'");
    expect(page).toContain('formatPct(');
  });

  it('warning rows_with_missing_cost + reason (COGS tidak dikarang)', () => {
    expect(page).toContain('rows_with_missing_cost');
    expect(page).toContain('missing_cost_reason');
    expect(page).toContain("'(produk belum sinkron)'");
    expect(page).toContain("'(HPP belum diisi)'");
  });

  it('Export AKTIF (H4.8: ExportButton -> POST /export/cogs/) + read-only', () => {
    expect(page).toContain("from '@/components/molecules/ExportButton'");
    expect(page).toContain('<ExportButton');
    expect(page).toContain('report="cogs"');
    expect(page).toContain('filters={');
    expect(page).toContain('H4.8');
    expect(page).not.toContain('client.post');
    expect(page).not.toContain('client.request');
    expect(page).not.toMatch(/\bmethod: 'POST'/);
  });
});
