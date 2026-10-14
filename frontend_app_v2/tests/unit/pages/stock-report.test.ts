import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * H4.3 - halaman laporan stok (`/reports/stock`).
 *
 * Rendering penuh butuh Router + QueryClient + provider runtime (di luar gaya tes tanpa DOM),
 * jadi tes ini memaku wiring sumber: route ber-guard REPORTS_ROLES, item nav baru, filter
 * server (location/produk/search/group_by/only_nonzero), reuse `DenseTable`/`KpiCard`/`Checkbox`,
 * escape hatch `?_nocache=1`, dan tombol Export disabled.
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function read(relative: string): string {
  return readFileSync(path.join(ROOT, relative), 'utf8');
}

const PAGE = 'src/pages/reports/StockReportPage.tsx';

describe('H4.3 - route & nav', () => {
  const app = read('src/App.tsx');
  const nav = read('src/app/nav-config.ts');

  it('route /reports/stock + guard role REPORTS', () => {
    expect(app).toContain('path="/reports/stock"');
    expect(app).toContain('<StockReportPage />');
    expect(app).toContain("import('@/pages/reports/StockReportPage')");
    expect(app).toContain('roles={REPORTS_ROLES}');
  });

  it('topbar Reports menambah item Stock', () => {
    expect(nav).toContain("{ label: 'Stock', path: '/reports/stock' }");
  });
});

describe('H4.3 - halaman', () => {
  const page = read(PAGE);

  it('query memakai adapter fetchStockReport + filter server', () => {
    expect(page).toContain('fetchStockReport(client, {');
    expect(page).toContain("from '@/api/reports'");
    expect(page).toContain("'reports-stock',");
    expect(page).toContain('locationId: locationId === ');
    expect(page).toContain('productId: productId === ');
    expect(page).toContain('search: search === ');
    expect(page).toContain('STOCK_GROUP_BY_VALUES');
  });

  it('group_by dari kontrak backend + dropdown master MES', () => {
    expect(page).toContain("useState<StockGroupBy>('product')");
    expect(page).toContain("fetchLocations(client, { limit: 200, usage: 'internal' })");
    expect(page).toContain('fetchProducts(client, { limit: 200, active: true })');
    expect(page).toContain("label: `${row.code} - ${row.name}`");
  });

  it('filter only_nonzero lewat Checkbox + escape hatch _nocache=1', () => {
    expect(page).toContain('onCheckedChange={setOnlyNonzero}');
    expect(page).toContain('nocache: forceRefresh > 0');
    expect(page).toContain('setForceRefresh((value) => value + 1)');
  });

  it('KPI + DenseTable (kolom menyesuaikan group_by) + qty reserved/available', () => {
    expect(page).toContain("from '@/components/molecules/KpiCard'");
    expect(page).toContain('<KpiCard');
    expect(page).toContain("from '@/components/molecules/DenseTable'");
    expect(page).toContain('<DenseTable');
    expect(page).not.toContain('<table');
    expect(page).toContain("label: 'Reserved'");
    expect(page).toContain("label: 'Available'");
    expect(page).toContain('buildColumns(');
  });

  it('Export AKTIF (H4.8: ExportButton -> POST /export/stock/) + read-only', () => {
    expect(page).toContain("from '@/components/molecules/ExportButton'");
    expect(page).toContain('<ExportButton');
    expect(page).toContain('report="stock"');
    expect(page).toContain('filters={');
    expect(page).toContain('H4.8');
    expect(page).not.toContain('client.post');
    expect(page).not.toContain('client.request');
    expect(page).not.toMatch(/\bmethod: 'POST'/);
  });

  it('halaman read-only: tidak ada mutasi (post/put/delete/request)', () => {
    expect(page).not.toContain('client.post');
    expect(page).not.toContain('client.request');
    expect(page).not.toMatch(/\\bmethod: 'POST'/);
  });
});
