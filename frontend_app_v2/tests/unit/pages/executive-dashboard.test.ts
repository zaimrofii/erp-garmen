import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * H4.7 - halaman dashboard eksekutif (`/dashboard/executive`).
 *
 * Rendering penuh butuh Router + QueryClient (di luar gaya tes tanpa DOM), jadi tes ini
 * memaku wiring sumber: route ber-guard SUPERVISOR_ROLES (paralel B2 `/dashboard`), menu
 * `Executive` di app `reports` + alias path (app `dashboard` tetap `/`), filter server
 * (period + `?_nocache=1`), KPI semua section, panel peringatan, handling `null`
 * (stok tak terbaca / opex unavailable), dan Export disabled sampai H4.8.
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function read(relative: string): string {
  return readFileSync(path.join(ROOT, relative), 'utf8');
}

const PAGE = 'src/pages/dashboard/ExecutiveDashboardPage.tsx';

describe('H4.7 - route & nav', () => {
  const app = read('src/App.tsx');
  const nav = read('src/app/nav-config.ts');

  it('route /dashboard/executive + guard SUPERVISOR_ROLES (B2 tetap utuh)', () => {
    expect(app).toContain('path="/dashboard/executive"');
    expect(app).toContain('<ExecutiveDashboardPage />');
    expect(app).toContain("import('@/pages/dashboard/ExecutiveDashboardPage')");
    expect(app).toContain('roles={SUPERVISOR_ROLES}');
    expect(app).toContain('path="/dashboard"');
    expect(app).toContain('<SupervisorDashboardPage />');
  });

  it('menu Executive di app Reports + alias path (app `dashboard` tetap `/`)', () => {
    expect(nav).toContain("{ label: 'Executive', path: '/dashboard/executive' }");
    expect(nav).toContain("{ prefix: '/dashboard/executive', appId: 'reports' }");
    expect(nav).toContain("{ prefix: '/dashboard', appId: 'dashboard' }");
  });
});

describe('H4.7 - halaman', () => {
  const page = read(PAGE);

  it('query memakai adapter fetchExecutiveDashboard + filter period + nocache', () => {
    expect(page).toContain('fetchExecutiveDashboard(client, {');
    expect(page).toContain("from '@/api/dashboard'");
    expect(page).toContain("'dashboard-executive',");
    expect(page).toContain('period: period === ');
    expect(page).toContain('nocache: forceRefresh > 0');
    expect(page).toContain('setForceRefresh((value) => value + 1)');
    expect(page).toContain('type="month"');
  });

  it('KPI semua section: penjualan/pembelian/stok/HPP/PnL/produksi', () => {
    expect(page).toContain("from '@/components/molecules/KpiCard'");
    expect(page).toContain('<KpiCard');
    expect(page).toContain('data?.sales.total_amount');
    expect(page).toContain('data?.purchases.total_amount');
    expect(page).toContain('stock?.total_qty');
    expect(page).toContain('unmapped_product_count');
    expect(page).toContain('data?.cogs.total_cogs');
    expect(page).toContain('data?.cogs.gross_profit');
    expect(page).toContain('data?.pnl.net_profit');
    expect(page).toContain('data?.pnl.net_margin_pct');
    expect(page).toContain('data?.production.output_pcs');
    expect(page).toContain('data?.production.scrap_pct');
    expect(page).toContain('data?.production.avg_efficiency_pct');
    expect(page).toContain('data?.production.otd_pct');
    expect(page).not.toContain('<table');
  });

  it('panel peringatan + `null` ditampilkan apa adanya (bukan 0)', () => {
    expect(page).toContain('alerts.map');
    expect(page).toContain('Peringatan');
    expect(page).toContain('formatOpex');
    expect(page).toContain("'n/a'");
    expect(page).toContain('formatStockQty');
    expect(page).toContain('stock === null');
    expect(page).toContain('opexUnavailable');
    expect(page).toContain("opex_source === 'unavailable'");
    expect(page).toContain('dari cache backend');
  });

  it('Export AKTIF (H4.8: ExportButton -> POST /export/executive/) + read-only', () => {
    expect(page).toContain("from '@/components/molecules/ExportButton'");
    expect(page).toContain('<ExportButton');
    expect(page).toContain('report="executive"');
    expect(page).toContain('filters={');
    expect(page).toContain('H4.8');
    expect(page).not.toContain('client.post');
    expect(page).not.toContain('client.request');
    expect(page).not.toMatch(/\bmethod: 'POST'/);
  });
});
