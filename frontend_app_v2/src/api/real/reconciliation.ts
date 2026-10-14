// REAL - wrap integration engine v1 (api-client). Endpoint: GET /reconciliation/report/ (§6.2)
//
// F9/9.0 - adapter BARU. Backend `ReconciliationReportView` (integrations/erp_sync/api.py)
// memakai permission `IsAuthenticated` → anonim 403, `days` di luar 1..90 → **400**
// (service TIDAK dipanggil). Read-only: endpoint ini tidak menyentuh Odoo
// (trigger rekonsiliasi = Celery beat mingguan).
//
// Bentuk respons NYATA (backend, sumber kebenaran):
//   `{days, count, entries: [{run_at, product_code, product_odoo_id, mes_qty,
//     odoo_qty, diff, is_alert, notes}]}`
// docs §6.2 menulis `rows` (bukan `entries`) → reader menerima KEDUANYA, `entries` diprioritaskan.
import type { ApiClient } from '@/integrations/api-client';
import { unwrap } from '../client';

/** Path relatif terhadap `VITE_API_BASE_URL` — kontrak §6.2. */
export const RECONCILIATION_REPORT_PATH = '/reconciliation/report/';

/** Batas `days` di backend (`ReconciliationReportView.MIN_DAYS`/`MAX_DAYS`). */
export const RECONCILIATION_DAYS_MIN = 1;
export const RECONCILIATION_DAYS_MAX = 90;
/** Nilai `days` kalau parameter tidak dikirim (`DEFAULT_DAYS`). */
export const RECONCILIATION_DAYS_DEFAULT = 7;

/** Satu baris riwayat rekonsiliasi (dict literal dari `ReconciliationService.report`). */
export interface ReconciliationEntry {
  run_at: string | null;
  product_code: string | null;
  product_odoo_id: number | null;
  mes_qty: number | null;
  odoo_qty: number | null;
  diff: number | null;
  /** Selisih melewati toleransi (`|diff| > max(units, pct × |mes_qty|)`). */
  is_alert: boolean;
  notes: string | null;
}

/** Respons 200 `GET /reconciliation/report/?days=N` (§6.2). */
export interface ReconciliationReport {
  days: number;
  count: number;
  entries: ReconciliationEntry[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readNullableNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function readNullableString(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}

/** PURE — string input user → `days` valid, atau `null` kalau di luar 1..90/bukan angka. */
export function parseReconciliationDays(value: unknown): number | null {
  if (typeof value === 'number') {
    return Number.isInteger(value) &&
      value >= RECONCILIATION_DAYS_MIN &&
      value <= RECONCILIATION_DAYS_MAX
      ? value
      : null;
  }

  if (typeof value !== 'string') return null;

  const trimmed = value.trim();
  if (!/^\d+$/.test(trimmed)) return null;

  const parsed = Number(trimmed);

  return parsed >= RECONCILIATION_DAYS_MIN && parsed <= RECONCILIATION_DAYS_MAX ? parsed : null;
}

/** PURE — path `GET /reconciliation/report/?days=N` (query selalu eksplisit). */
export function buildReconciliationReportPath(days: number): string {
  return `${RECONCILIATION_REPORT_PATH}?days=${days}`;
}

/** PURE — satu baris mentah → `ReconciliationEntry`; `null` kalau baris bukan objek. */
export function readReconciliationEntry(raw: unknown): ReconciliationEntry | null {
  if (!isRecord(raw)) return null;

  return {
    run_at: readNullableString(raw['run_at']),
    product_code: readNullableString(raw['product_code']),
    product_odoo_id: readNullableNumber(raw['product_odoo_id']),
    mes_qty: readNullableNumber(raw['mes_qty']),
    odoo_qty: readNullableNumber(raw['odoo_qty']),
    diff: readNullableNumber(raw['diff']),
    is_alert: raw['is_alert'] === true,
    notes: readNullableString(raw['notes']),
  };
}

/**
 * PURE — respons mentah → `ReconciliationReport`; `null` kalau envelope tidak dikenali
 * (`days` bukan angka atau daftar baris bukan array). Menerima `entries` (backend) dan
 * `rows` (docs §6.2) supaya perbedaan nama kunci tidak mematikan halaman.
 */
export function readReconciliationReport(raw: unknown): ReconciliationReport | null {
  if (!isRecord(raw)) return null;

  const days = raw['days'];
  const list = raw['entries'] ?? raw['rows'];
  if (typeof days !== 'number' || !Number.isFinite(days)) return null;
  if (!Array.isArray(list)) return null;

  const entries: ReconciliationEntry[] = [];
  for (const item of list) {
    const entry = readReconciliationEntry(item);
    if (entry !== null) entries.push(entry);
  }

  const count = readNullableNumber(raw['count']);

  return { days, count: count ?? entries.length, entries };
}

/**
 * Baca riwayat rekonsiliasi `days` hari terakhir. Gagal HTTP (400 `days` di luar rentang /
 * 403 tanpa session) → melempar Error (`unwrap`); bentuk tak dikenal → melempar pesan jelas.
 */
export async function getReconciliationReport(
  client: ApiClient,
  days: number = RECONCILIATION_DAYS_DEFAULT,
): Promise<ReconciliationReport> {
  const res = await client.get<unknown>(buildReconciliationReportPath(days));
  const parsed = readReconciliationReport(unwrap(res));

  if (parsed === null) {
    throw new Error(`Bentuk respons reconciliation report (days=${String(days)}) tidak dikenali.`);
  }

  return parsed;
}
