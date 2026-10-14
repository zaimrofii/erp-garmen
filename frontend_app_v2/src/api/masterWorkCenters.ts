// ADAPTER - satu-satunya pintu data master work center (H1.7, TANPA logic domain).
//
// H1.7: endpoint `/api/v1/master/work-centers/` SUDAH ADA di backend (MES = source
// of truth) → MODE.masterWorkCenters = 'real' (`_adapter.ts`), tanpa implementasi dummy.
// Catatan: Work Center **MES-only** (tidak push/pull Odoo) — bentuk API tetap sama
// dengan master lain, hanya tanpa `odoo_id`.
import { pickAdapter } from './_adapter';
import * as real from './real/masterWorkCenters';

/** Daftar work center + filter (`GET /master/work-centers/`) — REAL (H1.7). */
export const fetchWorkCenters = pickAdapter(
  'masterWorkCenters',
  real.fetchWorkCenters,
  real.fetchWorkCenters,
);

/** Detail work center + `active_bundles_count` (`GET /master/work-centers/<id>/`). */
export const fetchWorkCenter = pickAdapter(
  'masterWorkCenters',
  real.fetchWorkCenter,
  real.fetchWorkCenter,
);

/** Buat work center (`POST /master/work-centers/`) — REAL (H1.7; izin admin/owner). */
export const createWorkCenter = pickAdapter(
  'masterWorkCenters',
  real.createWorkCenter,
  real.createWorkCenter,
);

/** Ubah work center (`PUT /master/work-centers/<id>/`) — REAL (H1.7). */
export const updateWorkCenter = pickAdapter(
  'masterWorkCenters',
  real.updateWorkCenter,
  real.updateWorkCenter,
);

/** Nonaktifkan work center (`DELETE` = soft delete) — REAL (H1.7). */
export const deleteWorkCenter = pickAdapter(
  'masterWorkCenters',
  real.deleteWorkCenter,
  real.deleteWorkCenter,
);

export {
  buildMasterWorkCentersPath,
  MASTER_WORK_CENTERS_PATH,
  readMasterWorkCenterDetail,
  readMasterWorkCenterPage,
  readMasterWorkCenterRow,
  readMasterWorkCenterSaved,
  toMasterWorkCenterBody,
  WORK_CENTERS_LIMIT_DEFAULT,
  WORK_CENTERS_LIMIT_MAX,
} from './real/masterWorkCenters';
export type { MasterWorkCenterPage, MasterWorkCentersParams } from './real/masterWorkCenters';
export type {
  MasterWorkCenterDetail,
  MasterWorkCenterInput,
  MasterWorkCenterLine,
  MasterWorkCenterRow,
  MasterWorkCenterSaved,
} from '@/types/master-work-center';
