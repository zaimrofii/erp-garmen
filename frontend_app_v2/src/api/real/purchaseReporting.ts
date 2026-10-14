// REAL - agregat pembelian (F2C.2). Endpoint: GET /api/v1/purchase/reporting/
//
// Backend `monitoring.PurchaseReportingView` (B11 + G5b). Non-ListPage.
import type { ApiClient } from '@/integrations/api-client';
import { unwrap } from '../client';

/** Path relatif terhadap `VITE_API_BASE_URL`. */
export const PURCHASE_REPORTING_PATH = '/purchase/reporting/';

export interface MonthlySeriesPoint {
  month: string;
  po_count: number;
  amount_total: number;
  vendor_bill_count: number;
}

export interface TopVendor {
  partner_name: string | null;
  total_amount: number;
  po_count: number;
  vendor_name: string | null;
  vendor_code: string | null;
  amount_total: number;
}

export interface VendorBillSummary {
  total: number;
  total_amount: number;
  by_state: Record<string, number>;
}

export interface PurchaseReporting {
  total_po: number;
  total_amount: number;
  by_state: Record<string, number>;
  top_vendors: TopVendor[];
  monthly_series: MonthlySeriesPoint[];
  vendor_bills: VendorBillSummary;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readNum(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function readNullableStr(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}

function readNumberMap(value: unknown): Record<string, number> {
  if (!isRecord(value)) return {};
  const out: Record<string, number> = {};
  for (const [key, raw] of Object.entries(value)) out[key] = readNum(raw);
  return out;
}

/** PURE — respons mentah → `PurchaseReporting`. */
export function readPurchaseReporting(raw: unknown): PurchaseReporting | null {
  if (!isRecord(raw)) return null;

  const topVendorsRaw = Array.isArray(raw['top_vendors']) ? raw['top_vendors'] : [];
  const monthlyRaw = Array.isArray(raw['monthly_series']) ? raw['monthly_series'] : [];
  const bills = isRecord(raw['vendor_bills']) ? raw['vendor_bills'] : {};

  return {
    total_po: readNum(raw['total_po']),
    total_amount: readNum(raw['total_amount']),
    by_state: readNumberMap(raw['by_state']),
    top_vendors: topVendorsRaw.filter(isRecord).map((row) => ({
      partner_name: readNullableStr(row['partner_name']),
      total_amount: readNum(row['total_amount']),
      po_count: readNum(row['po_count']),
      vendor_name: readNullableStr(row['vendor_name']),
      vendor_code: readNullableStr(row['vendor_code']),
      amount_total: readNum(row['amount_total']),
    })),
    monthly_series: monthlyRaw.filter(isRecord).map((row) => ({
      month: readNullableStr(row['month']) ?? '',
      po_count: readNum(row['po_count']),
      amount_total: readNum(row['amount_total']),
      vendor_bill_count: readNum(row['vendor_bill_count']),
    })),
    vendor_bills: {
      total: readNum(bills['total']),
      total_amount: readNum(bills['total_amount']),
      by_state: readNumberMap(bills['by_state']),
    },
  };
}

/** Baca laporan pembelian. Gagal HTTP → melempar (`unwrap`). */
export async function fetchPurchaseReporting(client: ApiClient): Promise<PurchaseReporting> {
  const res = await client.get<unknown>(PURCHASE_REPORTING_PATH);
  const parsed = readPurchaseReporting(unwrap(res));

  if (parsed === null) {
    throw new Error('Bentuk respons laporan pembelian tidak dikenali.');
  }

  return parsed;
}
