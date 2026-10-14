// REAL - export laporan H4 (H4.8). Endpoint: POST /api/v1/export/<report>/
//
// Backend `erp_sync/export.py:ExportReportView` — respons = BERKAS binary
// (dikirim lewat `client.requestBlob`, satu-satunya pintu HTTP). Body JSON
// memakai param yang SAMA dengan endpoint laporan H4.x (parse + validasi
// di-reuse backend lewat shim request), jadi angka di berkas = angka halaman.
import type { ApiClient } from '@/integrations/api-client';
import type { ExportFilters, ExportFile, ExportFormat, ExportReport } from '@/types/export';

/** Prefix path relatif terhadap `VITE_API_BASE_URL` (`.../api/v1`). */
export const EXPORT_PATH_PREFIX = '/export/';

/** Format berkas yang didukung backend (lain dari ini → 400). */
export const EXPORT_FORMAT_VALUES: ExportFormat[] = ['xlsx', 'pdf'];

/** Default format (backend juga default `xlsx`). */
export const EXPORT_FORMAT_DEFAULT: ExportFormat = 'xlsx';

/** Label UI per format (dropdown di modal export). */
export const EXPORT_FORMAT_LABELS: Record<ExportFormat, string> = {
  xlsx: 'Excel (.xlsx)',
  pdf: 'PDF (.pdf)',
};

/** Label UI per laporan (judul modal + aria-label tombol). */
export const EXPORT_REPORT_LABELS: Record<ExportReport, string> = {
  sales: 'Laporan Penjualan',
  purchases: 'Laporan Pembelian',
  stock: 'Laporan Stok',
  cogs: 'Laporan HPP',
  pnl: 'Laporan Laba-Rugi',
  production: 'Laporan Produksi',
  executive: 'Dashboard Eksekutif',
};

/** PURE — path export satu laporan (`DELETE`-aman: tanpa query string). */
export function buildExportPath(report: ExportReport): string {
  return `${EXPORT_PATH_PREFIX}${report}/`;
}

/**
 * PURE — body JSON export: `format` + filter TERISI (camelCase UI → param
 * snake_case H4.x). Nilai `null`/`undefined`/`''` dilewati; boolean → `1`/`0`
 * supaya dipahami parser H4.x apa adanya.
 */
export function buildExportBody(
  format: ExportFormat,
  filters: ExportFilters = {},
): Record<string, unknown> {
  const body: Record<string, unknown> = {
    format: format === 'pdf' ? 'pdf' : 'xlsx',
  };

  const mapping: Array<[keyof ExportFilters, string]> = [
    ['period', 'period'],
    ['dateFrom', 'date_from'],
    ['dateTo', 'date_to'],
    ['from', 'from'],
    ['to', 'to'],
    ['groupBy', 'group_by'],
    ['customerId', 'customer_id'],
    ['vendorId', 'vendor_id'],
    ['productId', 'product_id'],
    ['orderType', 'order_type'],
    ['status', 'status'],
    ['locationId', 'location_id'],
    ['search', 'search'],
    ['onlyNonzero', 'only_nonzero'],
    ['workCenterId', 'work_center_id'],
    ['lineId', 'line_id'],
  ];

  for (const [key, param] of mapping) {
    const value = filters[key];
    if (value === null || value === undefined || value === '') continue;
    body[param] = value === true ? 1 : value === false ? 0 : value;
  }

  return body;
}

/** Unduh satu laporan sebagai berkas (blob + nama). Gagal → melempar `Error`. */
export async function exportReport(
  client: ApiClient,
  report: ExportReport,
  format: ExportFormat = EXPORT_FORMAT_DEFAULT,
  filters: ExportFilters = {},
): Promise<ExportFile> {
  const res = await client.requestBlob(
    buildExportPath(report),
    buildExportBody(format, filters),
  );

  if (!res.ok || res.blob === undefined) {
    throw new Error(res.error?.message ?? `Export gagal (status ${res.status}).`);
  }

  return {
    blob: res.blob,
    filename: res.filename ?? `${report}.${format}`,
    contentType: res.contentType ?? '',
  };
}
