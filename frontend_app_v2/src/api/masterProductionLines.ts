// ADAPTER - satu-satunya pintu data master production line (H1.8, TANPA logic domain).
//
// H1.8: endpoint `/api/v1/master/production-lines/` SUDAH ADA di backend (MES =
// source of truth) → MODE.masterProductionLines = 'real' (`_adapter.ts`), tanpa dummy.
// Catatan: Production Line **MES-only** (tidak push/pull Odoo — Odoo 17 tidak punya
// wadah lini); bentuk API tetap sama dengan master lain, hanya tanpa `odoo_id`.
import { pickAdapter } from './_adapter';
import * as real from './real/masterProductionLines';

/** Daftar production line + filter (`GET /master/production-lines/`) — REAL (H1.8). */
export const fetchProductionLines = pickAdapter(
  'masterProductionLines',
  real.fetchProductionLines,
  real.fetchProductionLines,
);

/** Detail lini + `work_centers[]` (`GET /master/production-lines/<id>/`) — REAL. */
export const fetchProductionLine = pickAdapter(
  'masterProductionLines',
  real.fetchProductionLine,
  real.fetchProductionLine,
);

/** Buat lini (`POST /master/production-lines/`) — REAL (H1.8; izin admin/owner). */
export const createProductionLine = pickAdapter(
  'masterProductionLines',
  real.createProductionLine,
  real.createProductionLine,
);

/** Ubah lini (`PUT /master/production-lines/<id>/`) — REAL (H1.8). */
export const updateProductionLine = pickAdapter(
  'masterProductionLines',
  real.updateProductionLine,
  real.updateProductionLine,
);

/** Nonaktifkan lini (`DELETE` = soft delete) — REAL (H1.8). */
export const deleteProductionLine = pickAdapter(
  'masterProductionLines',
  real.deleteProductionLine,
  real.deleteProductionLine,
);

export {
  buildMasterProductionLinesPath,
  MASTER_PRODUCTION_LINES_PATH,
  PRODUCTION_LINES_LIMIT_DEFAULT,
  PRODUCTION_LINES_LIMIT_MAX,
  readMasterProductionLineDetail,
  readMasterProductionLinePage,
  readMasterProductionLineRow,
  readMasterProductionLineSaved,
  toMasterProductionLineBody,
} from './real/masterProductionLines';
export type {
  MasterProductionLinePage,
  MasterProductionLinesParams,
} from './real/masterProductionLines';
export type {
  MasterProductionLineDetail,
  MasterProductionLineInput,
  MasterProductionLineRow,
  MasterProductionLineSaved,
  MasterProductionLineWorkCenter,
} from '@/types/master-production-line';
