/**
 * export.ts - kontrak export laporan H4 (H4.8).
 *
 * Endpoint: `POST /api/v1/export/<report>/` (`integrations/erp_sync/export.py:ExportReportView`).
 * Read-only: respons = **berkas binary** (xlsx/pdf) dengan
 * `Content-Disposition: attachment; filename="<report>-<periode>.<ext>"`.
 *
 * Body JSON memakai **param yang sama** dengan endpoint laporan H4.x (parse &
 * validasi di-reuse backend lewat *shim request*), sehingga angka di berkas =
 * angka di halaman laporan (Aturan Mutlak #5: UI tidak menghitung ulang).
 */

/** Laporan yang bisa diexport (7 modul H4). */
export type ExportReport =
  | 'sales'
  | 'purchases'
  | 'stock'
  | 'cogs'
  | 'pnl'
  | 'production'
  | 'executive';

/** Format berkas yang didukung backend (`format` di body/query; invalid -> 400). */
export type ExportFormat = 'xlsx' | 'pdf';

/**
 * Filter export — **subset** param endpoint laporan H4.x; hanya key terisi yang
 * dikirim (nilai `null`/`''` dilewati). `groupBy` dipetakan ke `group_by`.
 */
export interface ExportFilters {
  period?: string | null;
  dateFrom?: string | null;
  dateTo?: string | null;
  from?: string | null;
  to?: string | null;
  groupBy?: string | null;
  customerId?: number | null;
  vendorId?: number | null;
  productId?: number | null;
  orderType?: string | null;
  status?: string | null;
  locationId?: number | null;
  search?: string | null;
  onlyNonzero?: boolean | null;
  workCenterId?: number | null;
  lineId?: number | null;
}

/** Berkas hasil export (blob + nama dari `Content-Disposition`). */
export interface ExportFile {
  blob: Blob;
  filename: string;
  contentType: string;
}
