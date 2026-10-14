import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * H4.2 - halaman laporan pembelian (`/reports/purchases`).
 *
 * Rendering penuh butuh Router + QueryClient + provider runtime (di luar gaya tes tanpa DOM),
 * jadi tes ini memaku wiring sumber: route ber-guard REPORTS_ROLES, item nav baru, filter
 * server, reuse `DenseTable`/`KpiCard`, escape hatch `?_nocache=1`, dan tombol Export disabled.
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function read(relative: string): string {
  return readFileSync(path.join(ROOT, relative), 'utf8');
}

const PAGE = 'src/pages/reports/PurchasesReportPage.tsx';

describe('H4.2 - route & nav', () => {
  const app = read('src/App.tsx');
  const nav = read('src/app/nav-config.ts');

  it('route /reports/purchases + guard role REPORTS', () => {
    expect(app).toContain('path="/reports/purchases"');
    expect(app).toContain('<PurchasesReportPage />');
    expect(app).toContain("import('@/pages/reports/PurchasesReportPage')");
    expect(app).toContain('roles={REPORTS_ROLES}');
  });

  it('topbar Reports menambah item Purchases', () => {
    expect(nav).toContain("{ label: 'Purchases', path: '/reports/purchases' }");
  });
});

describe('H4.2 - halaman', () => {
  const page = read(PAGE);

  it('query memakai adapter fetchPurchasesReport + filter server', () => {
    expect(page).toContain('fetchPurchasesReport(client, {');
    expect(page).toContain("from '@/api/reports'");
    expect(page).toContain("'reports-purchases',");
    expect(page).toContain('period: period ===');
    expect(page).toContain('vendorId: vendorId === ');
    expect(page).toContain('productId: productId === ');
    expect(page).toContain('status: status === ');
    expect(page).toContain('PURCHASES_STATUS_VALUES');
    expect(page).toContain('PURCHASES_GROUP_BY_VALUES');
  });

  it('group_by dari kontrak backend + dropdown master MES (vendor)', () => {
    expect(page).toContain("useState<PurchasesGroupBy>('period')");
    expect(page).toContain('fetchPartners(client, { limit: 200, is_vendor: true })');
    expect(page).toContain('fetchProducts(client, { limit: 200, active: true })');
    expect(page).toContain("label: `${row.code} - ${row.name}`");
  });

  it('escape hatch _nocache=1 lewat tombol Muat Ulang', () => {
    expect(page).toContain('nocache: forceRefresh > 0');
    expect(page).toContain('setForceRefresh((value) => value + 1)');
  });

  it('KPI + DenseTable (bukan tabel paralel) + format IDR', () => {
    expect(page).toContain("from '@/components/molecules/KpiCard'");
    expect(page).toContain('<KpiCard');
    expect(page).toContain("from '@/components/molecules/DenseTable'");
    expect(page).toContain('<DenseTable');
    expect(page).not.toContain('<table');
    expect(page).toContain('Rp${value.toLocaleString');
    expect(page).toContain("label: 'Nilai (IDR)'");
  });

  it('Export AKTIF (H4.8: ExportButton -> POST /export/purchases/) + read-only', () => {
    expect(page).toContain("from '@/components/molecules/ExportButton'");
    expect(page).toContain('<ExportButton');
    expect(page).toContain('report="purchases"');
    expect(page).toContain('filters={');
    expect(page).toContain('H4.8');
    expect(page).not.toContain('client.post');
    expect(page).not.toContain('client.request');
    expect(page).not.toMatch(/\bmethod: 'POST'/);
  });

  it('halaman read-only: tidak ada mutasi (post/put/delete/request)', () => {
    expect(page).not.toContain('client.post');
    expect(page).not.toContain('client.request');
    expect(page).not.toMatch(/\bmethod: 'POST'/);
  });
});
