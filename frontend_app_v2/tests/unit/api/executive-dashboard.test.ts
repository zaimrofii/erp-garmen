import { describe, expect, it } from 'vitest';
import {
  buildExecutiveDashboardPath,
  fetchExecutiveDashboard,
  readExecutiveDashboard,
  EXECUTIVE_DASHBOARD_PATH,
} from '@/api/dashboard';
import { MODE } from '@/api/_adapter';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';

/** H4.7 - executiveDashboard (GET /dashboard/executive/) REAL: parsing + query + error. */

const BODY = {
  period: { from: '2026-10-01T00:00:00+07:00', to: '2026-10-31T23:59:59.999999+07:00' },
  filters: {
    period: '2026-10',
    date_from: null,
    date_to: null,
    from: null,
    to: null,
    nocache: false,
    resolved_from: '2026-10-01T00:00:00+07:00',
    resolved_to: '2026-10-31T23:59:59.999999+07:00',
  },
  sales: { total_amount: 1000, count_orders: 1, count_lines: 2 },
  purchases: { total_amount: 100000, count_purchases: 1, count_lines: 1 },
  stock: { total_qty: 5, product_count: 1, location_count: 1, unmapped_product_count: 0 },
  cogs: { total_cogs: 400, gross_profit: 600, gross_margin_pct: 60, rows_with_missing_cost: 0 },
  pnl: {
    revenue: 1000,
    cogs: 400,
    gross_profit: 600,
    gross_margin_pct: 60,
    opex: 150,
    net_profit: 450,
    net_margin_pct: 45,
    opex_source: 'journal_entry',
    opex_account_types: ['expense'],
    opex_states: ['SENT'],
  },
  production: {
    output_pcs: 8,
    scrap_pcs: 2,
    scrap_pct: 20,
    rework_pcs: 1,
    end_loss_pcs: 1,
    avg_efficiency_pct: 12.5,
    otd_pct: 100,
    total_bundles: 1,
    total_work_orders: 1,
  },
  alerts: ['Stok tidak terbaca dari Odoo'],
  generated_at: '2026-10-14T07:00:00+07:00',
  cached: false,
};

function stubClient(data: unknown): { client: ApiClient; paths: string[] } {
  const paths: string[] = [];
  const client = {
    get: async <T,>(path: string): Promise<ApiResponse<T>> => {
      paths.push(path);
      return { ok: true, status: 200, data: data as T };
    },
  } as unknown as ApiClient;

  return { client, paths };
}

function errorClient(status: number, message: string): ApiClient {
  return {
    get: async <T,>(): Promise<ApiResponse<T>> => ({
      ok: false,
      status,
      error: { kind: 'http', message },
    }),
  } as unknown as ApiClient;
}

describe('H4.7 - executiveDashboard (konstanta & MODE)', () => {
  it('MODE executiveDashboard = real; path endpoint + key baru (bukan `dashboard`)', () => {
    expect(MODE['executiveDashboard']).toBe('real');
    expect(MODE['dashboard']).toBe('real');
    expect(EXECUTIVE_DASHBOARD_PATH).toBe('/dashboard/executive/');
  });
});

describe('H4.7 - buildExecutiveDashboardPath', () => {
  it('path polos tanpa filter; period & _nocache hanya saat diminta', () => {
    expect(buildExecutiveDashboardPath()).toBe('/dashboard/executive/');
    expect(buildExecutiveDashboardPath({ period: null, nocache: false })).toBe(
      '/dashboard/executive/',
    );
    expect(buildExecutiveDashboardPath({ period: '2026-10' })).toBe(
      '/dashboard/executive/?period=2026-10',
    );
    expect(buildExecutiveDashboardPath({ nocache: true })).toBe(
      '/dashboard/executive/?_nocache=1',
    );
  });

  it('alias rentang from/to + dateFrom/dateTo ikut dikirim (backend `_sales_range`)', () => {
    expect(buildExecutiveDashboardPath({ from: '2026-10-01', to: '2026-10-31' })).toBe(
      '/dashboard/executive/?from=2026-10-01&to=2026-10-31',
    );
    expect(buildExecutiveDashboardPath({ dateFrom: '2026-10-01', dateTo: '2026-10-31' })).toBe(
      '/dashboard/executive/?date_from=2026-10-01&date_to=2026-10-31',
    );
  });
});

describe('H4.7 - readExecutiveDashboard', () => {
  it('parsing semua section + alerts list[str] (nested per laporan)', () => {
    const parsed = readExecutiveDashboard(BODY);

    expect(parsed).not.toBeNull();
    expect(parsed?.period.from).toBe('2026-10-01T00:00:00+07:00');
    expect(parsed?.filters.period).toBe('2026-10');
    expect(parsed?.filters.nocache).toBe(false);
    expect(parsed?.sales).toEqual({ total_amount: 1000, count_orders: 1, count_lines: 2 });
    expect(parsed?.purchases.total_amount).toBe(100000);
    expect(parsed?.stock?.unmapped_product_count).toBe(0);
    expect(parsed?.cogs.gross_margin_pct).toBe(60);
    expect(parsed?.pnl.opex).toBe(150);
    expect(parsed?.pnl.opex_source).toBe('journal_entry');
    expect(parsed?.pnl.opex_states).toEqual(['SENT']);
    expect(parsed?.production.scrap_pct).toBe(20);
    expect(parsed?.production.otd_pct).toBe(100);
    expect(parsed?.alerts).toEqual(['Stok tidak terbaca dari Odoo']);
    expect(parsed?.cached).toBe(false);
  });

  it('stock null (fail-safe partial Odoo) -> null, BUKAN nol', () => {
    const parsed = readExecutiveDashboard({ ...BODY, stock: null });

    expect(parsed?.stock).toBeNull();
    expect(parsed?.sales.total_amount).toBe(1000);
  });

  it('pnl.opex null + opex_source unavailable -> tetap null (angka tidak dikarang)', () => {
    const parsed = readExecutiveDashboard({
      ...BODY,
      pnl: { ...BODY.pnl, opex: null, opex_source: 'unavailable', net_profit: 600 },
    });

    expect(parsed?.pnl.opex).toBeNull();
    expect(parsed?.pnl.opex_source).toBe('unavailable');
    expect(parsed?.pnl.net_profit).toBe(600);
  });

  it('alerts hanya string; bentuk inti rusak / bukan objek -> null', () => {
    const parsed = readExecutiveDashboard({ ...BODY, alerts: ['ok', 7, null] });

    expect(parsed?.alerts).toEqual(['ok']);
    expect(readExecutiveDashboard(null)).toBeNull();
    expect(readExecutiveDashboard({ period: BODY.period })).toBeNull();
    expect(readExecutiveDashboard({ period: [], sales: BODY.sales, pnl: BODY.pnl })).toBeNull();
  });
});

describe('H4.7 - fetchExecutiveDashboard', () => {
  it('GET path + query dan mengembalikan respons terparse', async () => {
    const { client, paths } = stubClient(BODY);

    const data = await fetchExecutiveDashboard(client, { period: '2026-10', nocache: true });

    expect(paths).toEqual(['/dashboard/executive/?period=2026-10&_nocache=1']);
    expect(data.sales.total_amount).toBe(1000);
  });

  it('error HTTP -> melempar (unwrap di getParsed)', async () => {
    await expect(fetchExecutiveDashboard(errorClient(403, 'Forbidden'))).rejects.toThrow(
      'Forbidden',
    );
  });

  it('bentuk respons tak dikenali -> melempar', async () => {
    const { client } = stubClient({ bukan: 'dashboard' });

    await expect(fetchExecutiveDashboard(client)).rejects.toThrow(
      'Bentuk respons dashboard eksekutif tidak dikenali.',
    );
  });
});

