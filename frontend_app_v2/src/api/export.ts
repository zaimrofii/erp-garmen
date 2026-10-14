// ADAPTER - satu-satunya pintu data Export laporan H4 (TANPA logic domain).
//
// H4.8: MODE `export` === 'real' (`POST /api/v1/export/<report>/`, berkas binary).
import { pickAdapter } from './_adapter';
import * as real from './real/export';

/** Unduh laporan H4 sebagai Excel/PDF (Executive + 6 laporan) — REAL (H4.8). */
export const exportReport = pickAdapter('export', real.exportReport, real.exportReport);

export {
  buildExportBody,
  buildExportPath,
  EXPORT_FORMAT_DEFAULT,
  EXPORT_FORMAT_LABELS,
  EXPORT_FORMAT_VALUES,
  EXPORT_PATH_PREFIX,
  EXPORT_REPORT_LABELS,
} from './real/export';
export type { ExportFilters, ExportFile, ExportFormat, ExportReport } from '@/types/export';
