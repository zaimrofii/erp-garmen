// REAL - dashboard summary (F2C.2). Endpoint: GET /api/v1/dashboard/summary/
//
// Backend `monitoring.DashboardSummaryView` (B1 + G1). Non-ListPage response.
import type { ApiClient } from '@/integrations/api-client';
import { unwrap } from '../client';

/** Path relatif terhadap `VITE_API_BASE_URL`. */
export const DASHBOARD_SUMMARY_PATH = '/dashboard/summary/';

export interface DashboardBundleCounts {
  draft: number;
  cutting: number;
  sewing: number;
  qc: number;
  done: number;
}

export interface DashboardOrderCounts {
  open: number;
  overdue: number;
}

export interface DashboardAlert {
  code: string;
  message: string;
  severity: string;
}

export interface DashboardLineEfficiency {
  pct: number;
  delta: number;
}

export interface DashboardTrendPoint {
  date: string;
  wip: number;
  fg: number;
}

export interface DashboardSummary {
  bundles: DashboardBundleCounts;
  wip_qty: number;
  fg_qty: number;
  orders: DashboardOrderCounts;
  scrap_qty_today: number;
  alerts: DashboardAlert[];
  line_efficiency: DashboardLineEfficiency;
  trend: DashboardTrendPoint[];
  generated_at: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readNum(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function readStr(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function readBundleCounts(value: unknown): DashboardBundleCounts {
  const raw = isRecord(value) ? value : {};
  return {
    draft: readNum(raw['draft']),
    cutting: readNum(raw['cutting']),
    sewing: readNum(raw['sewing']),
    qc: readNum(raw['qc']),
    done: readNum(raw['done']),
  };
}

function readAlerts(value: unknown): DashboardAlert[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter(isRecord)
    .map((row) => ({
      code: readStr(row['code']),
      message: readStr(row['message']),
      severity: readStr(row['severity']),
    }));
}

function readTrend(value: unknown): DashboardTrendPoint[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter(isRecord)
    .map((row) => ({
      date: readStr(row['date']),
      wip: readNum(row['wip']),
      fg: readNum(row['fg']),
    }));
}

/** PURE — respons mentah → `DashboardSummary`; `null` kalau bukan objek. */
export function readDashboardSummary(raw: unknown): DashboardSummary | null {
  if (!isRecord(raw)) return null;

  const orders = isRecord(raw['orders']) ? raw['orders'] : {};
  const lineEfficiency = isRecord(raw['line_efficiency']) ? raw['line_efficiency'] : {};

  return {
    bundles: readBundleCounts(raw['bundles']),
    wip_qty: readNum(raw['wip_qty']),
    fg_qty: readNum(raw['fg_qty']),
    orders: { open: readNum(orders['open']), overdue: readNum(orders['overdue']) },
    scrap_qty_today: readNum(raw['scrap_qty_today']),
    alerts: readAlerts(raw['alerts']),
    line_efficiency: {
      pct: readNum(lineEfficiency['pct']),
      delta: readNum(lineEfficiency['delta']),
    },
    trend: readTrend(raw['trend']),
    generated_at: readStr(raw['generated_at']),
  };
}

/** Baca ringkasan dashboard. Gagal HTTP → melempar (`unwrap`). */
export async function fetchDashboardSummary(client: ApiClient): Promise<DashboardSummary> {
  const res = await client.get<unknown>(DASHBOARD_SUMMARY_PATH);
  const parsed = readDashboardSummary(unwrap(res));

  if (parsed === null) {
    throw new Error('Bentuk respons ringkasan dashboard tidak dikenali.');
  }

  return parsed;
}
